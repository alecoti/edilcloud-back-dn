"""Section/partition writers; preserve existing renderer/editor structures."""

from copy import deepcopy

from .content import Composition, Section, digest, composition_claims, editor_claims
from .engine import check_source_ids, compose_editor, prompt_bundle, prompt_template
from .editorial import editorial_contract
from .intelligence_calls import specialist
from .intelligence_planning import section_template
from .intelligence_readers import bounded_batches, parallel_map


def subset_evidence(bundle, source_ids):
    return {**bundle, "sources": [s for s in bundle["sources"] if s["id"] in source_ids]}


def write_partition(job, *, key, section, facts, template, bundle, correction=None):
    wanted = {ref.source_id for fact in facts for ref in fact.references}
    # The model gets the exact primary passages, not an arbitrary three chunks
    # from each document, and the small metadata context.
    source_map = {s["id"]: s for s in bundle["sources"]}
    trimmed = []
    for source_id in wanted:
        value = deepcopy(source_map[source_id])
        references = [r for fact in facts for r in fact.references if r.source_id == source_id]
        if value.get("file_ref"):
            value["data"]["excerpts"] = [
                {"text": r.quote, "page": r.page, "part_id": r.part_id} for r in references
            ]
        trimmed.append(value)
    trimmed.extend(s for s in bundle["sources"] if s["kind"] in {"project", "request", "declaration"})
    selected_bundle = {**bundle, "sources": list({s["id"]: s for s in trimmed}.values())}
    partial_template = section_template(template, section)
    data = {"facts": [f.model_dump() for f in facts], "template": prompt_template(partial_template),
            "evidence": prompt_bundle(selected_bundle), "language": job.revision.elaborato.language,
            "editorial_contract": editorial_contract(job.revision), "partition_key": key}
    if correction:
        data["correction"] = correction
    result = specialist(
        job=job, key=key, stage="document_section", schema=Composition, effort="medium", data=data,
        instructions=(
            "Redigi soltanto la sezione/porzione assegnata, preservando tutti i fatti pertinenti e critici. "
            "Usa il formato Composition; il backend assemblerà il documento. Non ripetere le altre sezioni. "
            "Il titolo deve identificare il documento complessivo, senza aggiungere il nome tecnico della porzione. "
            "Mantieni registri, tabelle, fotografie pertinenti e campi specifici per i valori mancanti. "
            "Non riempire ore/presenze/nomi con inferenze. Non inventare visita o riunione. "
            "Le firme sono campi vuoti. Non trasformare dati estratti dalla fonte in attestazioni del redattore. "
            "Ogni affermazione fattuale cita le fonti primarie e conserva decisioni, esiti e condizioni. "
            "Non produrre HTML o CSS. Se ci sono rilievi di correzione, correggi i blocchi interessati mantenendo "
            "tutti gli altri fatti, campi e foto pertinenti. Non eliminare fatti per aggirare un controllo."
        ),
    )
    check_source_ids(list(composition_claims(result)), selected_bundle)
    return result


def compose_partitions(job, *, facts, plan, bundle, template, corrections=None):
    known = {f.id: f for f in facts}
    assignments = {section["key"]: [] for section in template["sections"]}
    for allocation in plan.allocations:
        if allocation.included:
            assignments[allocation.section_key].append(known[allocation.fact_id])
    tasks = []
    for section in template["sections"]:
        values = assignments[section["key"]]
        batches = list(bounded_batches([f.model_dump() for f in values], max_items=24, max_characters=28000)) or [[]]
        for index, batch in enumerate(batches):
            key = f"write:{section['key']}:{index}:{digest(batch)[:16]}"
            correction = (corrections or {}).get(section["key"])
            if correction:
                key += f":correct:{digest(correction)[:12]}"
            tasks.append({"key": key, "section": section["key"],
                          "facts": [known[f["id"]] for f in batch], "correction": correction})
    outputs = list(parallel_map(lambda task: write_partition(job, template=template, bundle=bundle, **task), tasks))
    sections = []
    photos = []
    photo_ids = set()
    for definition in template["sections"]:
        pieces = [value.sections[0] for value, task in zip(outputs, tasks, strict=True) if task["section"] == definition["key"]]
        paragraphs, lists, tables = [], [], []
        for piece in pieces:
            paragraphs.extend(piece.paragraphs)
            lists.extend(piece.lists)
            tables.extend(piece.tables)
        # Complete structured blocks, with deterministic order. All layout
        # hints are intentionally recomputed after partition assembly.
        sections.append(Section(key=definition["key"], paragraphs=paragraphs, lists=lists, tables=tables))
    for value in outputs:
        for photo in value.photographs:
            if photo.source_id not in photo_ids:
                photos.append(photo)
                photo_ids.add(photo.source_id)
    composition = Composition(title=job.revision.elaborato.title, sections=sections, photographs=photos)
    editor = compose_editor(job, composition)
    from .fields import ensure_signature_slot, preserve_completed_fields

    ensure_signature_slot(editor, template, job.revision.elaborato.language)
    preserve_completed_fields(job.revision.editor_doc, editor)
    return editor


def claim_blocks(editor):
    # Stable addresses independent of renderer HTML and unsupported editor attrs.
    return [
        {**claim, "claim_id": f"claim:{index}:{digest(claim)[:20]}"}
        for index, claim in enumerate(editor_claims(editor))
    ]
