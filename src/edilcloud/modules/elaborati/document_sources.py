"""Reuse current, permission-scoped extracted chunks without invoking the indexer.

Only chunks matching the live document timestamp are eligible. A pending or old
index must never make a replaced/deleted file appear verified in a new report.
"""

from collections import defaultdict
import hashlib

from edilcloud.modules.assistant.models import ProjectAssistantChunkMap


def document_excerpts(project_id, documents):
    by_id = {d.pk: d for d in documents}
    result = defaultdict(list)
    chunks = (
        ProjectAssistantChunkMap.objects.filter(
            project_id=project_id,
            document_id__in=by_id,
            source_type="document",
            chunk_source__is_indexed=True,
            extracted_char_count__gt=0,
        )
        .select_related("chunk_source")
        .defer("embedding")
        .order_by("document_id", "chunk_index")[:121]
    )
    for chunk in chunks:
        document = by_id.get(chunk.document_id)
        if (
            not document
            or not chunk.source_updated_at
            or chunk.source_updated_at < document.updated_at
        ):
            continue
        if len(result[document.pk]) >= 3:
            continue
        result[document.pk].append(
            {
                "chunk_id": chunk.pk,
                "text": chunk.content[:4000],
                "page": chunk.page_reference,
                "section": chunk.section_reference,
                "indexed_at": chunk.chunk_source.last_indexed_at.isoformat()
                if chunk.chunk_source.last_indexed_at
                else None,
                "source_updated_at": chunk.source_updated_at.isoformat(),
                "content_hash": chunk.content_hash,
            }
        )
    # Do not reduce a just-uploaded, readable PDF to its filename while waiting
    # for the search index. This bounded fallback reads the authorized current
    # storage object and never consumes a stale vector-store copy.
    import pypdfium2 as pdfium

    remaining_bytes = 30 * 1024 * 1024
    for document in documents:
        if result.get(document.pk) or not document.document or remaining_bytes <= 0:
            continue
        if not document.document.name.lower().endswith(".pdf"):
            continue
        try:
            with document.document.open("rb") as stream:
                raw = stream.read(min(5 * 1024 * 1024, remaining_bytes) + 1)
            remaining_bytes -= len(raw)
            if not raw.startswith(b"%PDF-") or len(raw) > 5 * 1024 * 1024:
                continue
            with pdfium.PdfDocument(raw) as pdf:
                for index in range(min(len(pdf), 8)):
                    page = pdf[index]
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()[:4000].strip()
                    finally:
                        textpage.close()
                        page.close()
                    if text:
                        result[document.pk].append(
                            {
                                "chunk_id": None,
                                "text": text,
                                "page": index + 1,
                                "section": "",
                                "indexed_at": None,
                                "source_updated_at": document.updated_at.isoformat(),
                                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                                "extraction_method": "current_pdf_text",
                                "file_sha256": hashlib.sha256(raw).hexdigest(),
                            }
                        )
        except (OSError, ValueError, pdfium.PdfiumError):
            continue
    return result
