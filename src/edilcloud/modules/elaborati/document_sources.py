"""Reuse current, permission-scoped extracted chunks without invoking the indexer.

Only chunks matching the live document timestamp are eligible. A pending or old
index must never make a replaced/deleted file appear verified in a new report.
"""

from collections import defaultdict

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
    return result
