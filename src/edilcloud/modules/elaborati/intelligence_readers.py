"""Bounded readers over the complete, materialized inventory."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from .checkpoints import threaded_step
from .content import digest
from .errors import UnusableDocumentResult
from .intelligence_calls import specialist
from .intelligence_contracts import QuoteRepairResult, ReaderResult, validate_reader, enforce_fact_policy
from .models import DocumentEvidenceItem
from .source_reading import finalize_root, set_reading_state


def evidence_records(rows, *, page_size=50, order=("source_id",)):
    """Materialize one keyset page before yielding work that may call AI.

    A QuerySet.iterator cursor spans the provider call and progress/lease
    writes. On SQLite that can deadlock even in WAL mode; on PostgreSQL it
    unnecessarily holds a server cursor across slow network requests. Keep
    the original stable source ordering, without loading the whole inventory.
    """
    last = None
    while True:
        selected = rows.order_by(*order)
        if last is not None:
            after = Q()
            for index, field in enumerate(order):
                prefix = {name: last[position] for position, name in enumerate(order[:index])}
                after |= Q(**prefix, **{field + "__gt": last[index]})
            selected = selected.filter(after)
        page = list(selected[:page_size])
        if not page:
            return
        last = tuple(getattr(page[-1], field) for field in order)
        yield from page


def bounded_batches(values, *, max_characters=26000, max_items=12):
    batch, size = [], 0
    for value in values:
        value_size = len(json.dumps(value, ensure_ascii=False, default=str))
        if batch and (size + value_size > max_characters or len(batch) >= max_items):
            yield batch
            batch, size = [], 0
        batch.append(value)
        size += value_size
    if batch:
        yield batch


def parallel_map(callback, values, *, workers=None):
    # SQLite cannot provide production concurrent write semantics. PostgreSQL
    # runtime uses separate thread connections; tests can request workers=1.
    limit = workers or int(getattr(settings, "ELABORATI_V3_CONCURRENCY", 2))
    if connection.vendor == "sqlite" or limit <= 1:
        for value in values:
            yield callback(value)
        return
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="document-specialist") as executor:
        pending = []
        for value in values:
            pending.append(executor.submit(threaded_step, lambda value=value: callback(value)))
            if len(pending) >= limit:
                yield pending.pop(0).result()
        for result in pending:
            yield result.result()


def prepare_sources(job):
    from .intelligence_media import prepare_source

    roots = DocumentEvidenceItem.objects.filter(job=job, parent_source_id="").order_by("source_id")
    # Lanes share no mutable source rows. A provider checkpoint is per image or
    # audio segment, not the parent document job.
    def prepare(item):
        prepare_source(job, item)
        return item.pk

    for _ in parallel_map(prepare, evidence_records(roots)):
        pass
    return roots.count()


def part_batches(job):
    rows = DocumentEvidenceItem.objects.filter(job=job, kind="source_part").order_by("parent_source_id", "source_id")
    for batch in bounded_batches(row.payload for row in evidence_records(rows, order=("parent_source_id", "source_id"))):
        yield batch


def validate_reader_with_quote_repair(job, result, parts, identifier):
    """One bounded passage selection, without re-reading/rebuying the batch.

    Facts, attribution, nature and source identity remain unchanged. Selecting
    a genuine passage is not a verdict that the fact is true: both independent
    reviewers still compare those facts against the original evidence.
    """
    try:
        return validate_reader(result, parts)
    except ValueError as exc:
        if str(exc) != "Il passaggio citato non è presente nella fonte originale.":
            raise
    originals = {p["part_id"]: p for p in parts}
    invalid = []
    def normalize(value):
        return " ".join(value.split())
    for fact in result.facts:
        for index, ref in enumerate(fact.references):
            part = originals.get(ref.part_id)
            if not part or ref.source_id != part["source_id"] or ref.page != part.get("page"):
                raise ValueError("Il riferimento non corrisponde alla fonte esaminata.")
            if normalize(ref.quote) not in normalize(part["text"]):
                invalid.append({"reference_key": f"{fact.id}:{index}", "fact": fact.text,
                                "part_id": ref.part_id, "invalid_quote": ref.quote})
    if not invalid:
        raise ValueError("Il passaggio citato non è presente nella fonte originale.")
    selection = specialist(job=job, key=f"reader_quotes:{identifier}", stage="document_quote_selection",
        schema=QuoteRepairResult, effort="medium", data={"references": invalid,
            "original_sources": [originals[key] for key in dict.fromkeys(row["part_id"] for row in invalid)]},
        instructions=("Seleziona soltanto passaggi letterali CONTIGUI dal testo della fonte originale con lo stesso part_id per ciascun "
                      "reference_key. Non riscrivere il fatto, non correggere o inventare valori della fonte. "
                      "Puoi scegliere più passaggi distinti quando i campi sono separati. Ogni stringa di quotes "
                      "deve comparire letteralmente nella fonte. Se non esiste alcun passaggio pertinente, "
                      "restituisci quotes=[] per quel riferimento. Non includere commenti o nuovi fatti."))
    mapping = {row.reference_key: row.quotes for row in selection.references}
    expected = {row["reference_key"] for row in invalid}
    if len(mapping) != len(selection.references) or set(mapping) != expected:
        raise UnusableDocumentResult("La selezione dei passaggi non corrisponde ai riferimenti assegnati.")
    for fact in result.facts:
        references = []
        for index, ref in enumerate(fact.references):
            key = f"{fact.id}:{index}"
            if key not in mapping:
                references.append(ref)
                continue
            quotes = mapping[key]
            if not quotes or any(not q.strip() or normalize(q) not in normalize(originals[ref.part_id]["text"]) for q in quotes):
                raise UnusableDocumentResult("Citazione non verificabile dopo la selezione: nessun ulteriore tentativo automatico.")
            references.extend(ref.model_copy(update={"quote": quote}) for quote in quotes)
        fact.references = references
    return validate_reader(result, parts)


def read_batch(job, parts, *, policy, request):
    identifier = digest([p["part_id"] for p in parts])
    result = specialist(
        job=job, key=f"reader:{identifier}", stage="document_reading", schema=ReaderResult,
        data={"parts": parts, "policy": policy, "request": request},
        instructions=(
            "Sei il lettore documentale. Esamina ogni parte originale e restituisci un esito per ciascun part_id. "
            "Estrai tutti i fatti pertinenti, decisioni, proposte, richieste, esiti, persone e date. "
            "Preserva condizioni di approvazione, negazioni e riscontri finali. Ogni fatto ha un id locale unico "
            "e riferimenti source_id/part_id/page con quote letterale CONTIGUA presente nella parte. "
            "Non scambiare la data di pubblicazione con quella del fatto. Una visita o riunione è un fatto "
            "solo se una fonte ne dichiara l'avvenimento; la richiesta di creare un verbale non ne è prova. "
            "nature=executed soltanto per esecuzione dichiarata; verified solo per verifica esplicita; "
            "declared è una dichiarazione attribuita; una proposta/condizione resta tale. "
            "Segna critical i fatti della policy, inclusi esiti/decisioni/condizioni; motivane la rilevanza. "
            "I metadati e il programma non attestano esecuzione, presenza o verifiche. Un'esclusione deve essere motivata."
            "Le chiavi JSON vuote e presence=unknown non sono eventi operativi o criticità: "
            "indicano campi mancanti da gestire nei requisiti, non fatti critici autonomi. "
            "Richiesta del documento e lingua sono contesto amministrativo, non fatti da rendicontare."
        ),
    )
    validate_reader_with_quote_repair(job, result, parts, identifier)
    from .policies import policy_for

    enforce_fact_policy(result.facts, parts, policy_for(job.revision.elaborato.document_type))
    # Model-generated IDs are local to this batch. Server namespacing prevents
    # collisions between readers without altering or losing their facts.
    facts = []
    for fact in result.facts:
        stable_id = "fact:" + hashlib.sha256(f"{identifier}:{fact.id}".encode()).hexdigest()[:32]
        facts.append(fact.model_copy(update={"id": stable_id}))
    for item in result.sources:
        row = job.evidence_items.get(source_id=item.part_id)
        related = [f.model_dump() for f in facts if any(r.part_id == item.part_id for r in f.references)]
        set_reading_state(row, item.status, item.reason, {"facts": related, "reader_step": f"reader:{identifier}"})
    for source_id in {part["source_id"] for part in parts}:
        finalize_root(job.evidence_items.get(source_id=source_id))
    return facts


def read_inventory(job, *, policy, request):
    facts = []
    for batch_facts in parallel_map(lambda parts: read_batch(job, parts, policy=policy, request=request), part_batches(job)):
        facts.extend(batch_facts)
        from .pipeline_v3 import progress
        from .inventory import inventory_counts

        progress(job, "reading", facts=len(facts), inventory=inventory_counts(job))
    for item in evidence_records(DocumentEvidenceItem.objects.filter(job=job, parent_source_id="")):
        item.refresh_from_db()
        if item.state == "pending":
            finalize_root(item)
    return facts


def evidence_bundle(job):
    """Canonical source references for editor/rendering, with explicit coverage.

    Provider calls use bounded subsets. This full bundle is for persistence and
    deterministic citation/file lookup, never one unbounded provider prompt.
    """
    document = job.revision.elaborato
    sources = []
    children = defaultdict(list)
    for item in DocumentEvidenceItem.objects.filter(job=job).exclude(parent_source_id="").iterator(chunk_size=100):
        if item.kind == "source_part":
            value = item.payload
            children[item.parent_source_id].append({
                "part_id": item.source_id, "text": value["text"], "page": value.get("page"),
                "section": value.get("section"), "extraction_method": value.get("method"),
            })
    for item in DocumentEvidenceItem.objects.filter(job=job, parent_source_id="").iterator(chunk_size=100):
        value = dict(item.payload)
        data = dict(value["data"])
        if children.get(item.source_id) and item.payload.get("file_ref"):
            data["excerpts"] = children[item.source_id]
            data["file_content_extracted"] = True
            data["extraction_is_partial"] = item.state != "read"
        if item.reading.get("visual_analysis"):
            data["visual_analysis"] = item.reading["visual_analysis"]
        value.update(data=data, reading_state=item.state, reading_reason=item.reason)
        sources.append(value)
    complete = not job.evidence_items.filter(state__in=("pending", "failed", "unreadable")).exists()
    value = {"schema_version": 3, "project_id": document.project_id, "period_start": str(document.period_start),
             "period_end": str(document.period_end), "captured_at": job.workflow_state.get("inventory_started_at"),
             "sources": sources, "truncated": False, "coverage_complete": complete}
    value["census"] = {"total": len(sources), "selected": len(sources), "complete": True,
                        "excluded_from_selection": 0}
    value["bundle_hash"] = digest(value)
    return value


def mark_metadata_examined(job):
    # Used by FAST_0 only: no substantive content was selected by preflight.
    rows = DocumentEvidenceItem.objects.filter(job=job, parent_source_id="", state="pending")
    for item in evidence_records(rows, page_size=100):
        if item.kind in {"project", "request", "member", "task", "activity", "event"}:
            set_reading_state(item, "excluded", "metadata_does_not_document_performed_work")
        elif item.kind in {"post", "comment", "declaration"} and not item.payload.get("data", {}).get("text", "").strip():
            set_reading_state(item, "excluded", "empty_communication")
    DocumentEvidenceItem.objects.filter(job=job, state="read", read_at__isnull=True).update(read_at=timezone.now())
