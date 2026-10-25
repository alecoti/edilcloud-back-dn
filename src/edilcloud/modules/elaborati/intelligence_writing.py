"""Section/partition writers; preserve existing renderer/editor structures."""

from copy import deepcopy
import json

from .content import BlockPlacement, Composition, Section, digest, composition_claims, editor_claims
from .engine import check_source_ids, compose_editor, prompt_bundle, prompt_template
from .editorial import editorial_contract
from .intelligence_calls import specialist
from .intelligence_planning import section_template
from .intelligence_readers import bounded_batches, parallel_map
from .checkpoints import run_step
from .errors import IncompleteDocumentOutput

# Bounds apply to an assignment, not to the final document. Every fact remains
# in the ledger and gets a destination; larger documents create more units.
WRITER_MAX_FACTS = 8
WRITER_MAX_CHARACTERS = 12000


def subset_evidence(bundle, source_ids):
    return {**bundle, "sources": [s for s in bundle["sources"] if s["id"] in source_ids]}


def index_facts(bundle, facts):
    value = {**bundle, "fact_ids": [f.id for f in facts]}
    value["bundle_hash"] = digest({k: v for k, v in value.items() if k != "bundle_hash"})
    return value


def write_partition(job, *, key, section, facts, template, bundle, correction=None, subsection_path=()):
    wanted = {ref.source_id for fact in facts for ref in fact.references}
    # The model gets the exact primary passages, not an arbitrary three chunks
    # from each document, and the small metadata context.
    source_map = {s["id"]: s for s in bundle["sources"]}
    trimmed = []
    for source_id in wanted:
        value = deepcopy(source_map[source_id])
        references = [r for fact in facts for r in fact.references if r.source_id == source_id]
        value["data"] = {
            key: content for key, content in value["data"].items()
            if key in {"title", "filename", "author", "media_kind", "event_date_from_parent", "visual_analysis",
                       "source_actor", "company", "qualification", "professional_roles", "professional_role_labels"}
        }
        value["data"]["excerpts"] = [
            {"text": r.quote, "page": r.page, "part_id": r.part_id} for r in references
        ]
        trimmed.append(value)
    # Declarations and descriptions may be arbitrarily long. Primary passages
    # above carry their full relevant text; do not reattach every declaration.
    trimmed.extend({**s, "data": {k: v for k, v in s["data"].items() if k in {
        "name", "address", "period_start", "period_end", "document_type", "language",
    }}} for s in bundle["sources"] if s["kind"] in {"project", "request"} and s["id"] not in wanted)
    selected_bundle = index_facts({**bundle, "sources": list({s["id"]: s for s in trimmed}.values())}, facts)
    partial_template = section_template(template, section)
    data = {"facts": [f.model_dump() for f in facts], "template": prompt_template(partial_template),
            "evidence": prompt_bundle(selected_bundle), "language": job.revision.elaborato.language,
            "editorial_contract": editorial_contract(job.revision, section_keys={section}),
            "partition_key": key, "subsection_path": list(subsection_path)}
    if correction:
        data["correction"] = correction
    result = specialist(
        job=job, key=key, stage="document_section", schema=Composition, effort="medium", data=data,
        instructions=(
            "Redigi soltanto la sezione/porzione assegnata, preservando tutti i fatti pertinenti e critici. "
            "subsection_path identifica l'argomento della porzione: non redigere le altre discipline o aree. "
            "Se subsection_path è vuoto e i fatti sono pochi, usa paragrafi e registri senza microtitoli "
            "ridondanti; non ripetere la zona prima di ogni riga. "
            "Usa il formato Composition; il backend assemblerà il documento. Non ripetere le altre sezioni. "
            "Il titolo deve identificare il documento complessivo, senza aggiungere il nome tecnico della porzione. "
            "Mantieni registri, tabelle, fotografie pertinenti e campi specifici per i valori mancanti. "
            "Non riempire ore/presenze/nomi con inferenze. Non inventare visita o riunione. "
            "Alla prima menzione di una persona includi azienda, qualifica e incarichi attestati "
            "in actor/source_actor; non sostituirli con ruoli applicativi o incarichi correnti "
            "non documentati nel periodo. Alle menzioni successive è sufficiente il nome. "
            "Le firme sono campi vuoti. Non trasformare dati estratti dalla fonte in attestazioni del redattore. "
            "Ogni affermazione fattuale cita le fonti primarie e conserva decisioni, esiti e condizioni. "
            "Ogni Claim fattuale include fact_ids dei fatti effettivamente espressi nel blocco; "
            "i campi mancanti e le firme vuote hanno fact_ids=[]. Non associare un fatto al solo titolo di una colonna. "
            "Non produrre HTML o CSS. Se ci sono rilievi di correzione, correggi i blocchi interessati mantenendo "
            "tutti gli altri fatti, campi e foto pertinenti. Non eliminare fatti per aggirare un controllo."
        ),
    )
    check_source_ids(list(composition_claims(result)), selected_bundle)
    return result


def writing_tasks(facts, plan, template, corrections=None):
    """Planner headings plus application-enforced, bounded leaf assignments."""
    known = {f.id: f for f in facts}
    assignments = {section["key"]: {} for section in template["sections"]}
    section_facts = {}
    for allocation in plan.allocations:
        if allocation.included and allocation.section_key in assignments:
            section_facts.setdefault(allocation.section_key, []).append(known[allocation.fact_id])
    articulated = {key for key, values in section_facts.items() if len(values) > WRITER_MAX_FACTS
                   or len(json.dumps([f.model_dump() for f in values], ensure_ascii=False)) > WRITER_MAX_CHARACTERS}
    for allocation in plan.allocations:
        if allocation.included and allocation.section_key in assignments:
            path = tuple(label.strip() for label in allocation.subsection_path if label.strip()) if allocation.section_key in articulated else ()
            if any(len(label) > 150 for label in path) or len(path) > 8:
                raise ValueError("Il percorso della sotto-sezione non è valido.")
            assignments[allocation.section_key].setdefault(path, []).append(known[allocation.fact_id])
    tasks = []
    for section in template["sections"]:
        groups = assignments[section["key"]] or {(): []}
        for path, values in groups.items():
            for batch in list(bounded_batches([f.model_dump() for f in values],
                    max_items=WRITER_MAX_FACTS, max_characters=WRITER_MAX_CHARACTERS)) or [[]]:
                # An atomic fact requiring more than a leaf budget must be
                # decomposed at extraction, never silently truncated here.
                if len(batch) == 1 and len(json.dumps(batch[0], ensure_ascii=False)) > WRITER_MAX_CHARACTERS:
                    raise ValueError("Un fatto documentale richiede una lettura più granulare prima della redazione.")
                key = f"write:{section['key']}:{digest([path, batch])[:24]}"
                correction = (corrections or {}).get(section["key"])
                if correction:
                    key += f":correct:{digest(correction)[:12]}"
                tasks.append({"key": key, "section": section["key"], "subsection_path": list(path),
                              "fact_ids": [f["id"] for f in batch], "correction": correction})
    return tasks


def write_task(job, *, task, known, template, bundle, depth=0):
    """Keep incomplete attempts, checkpoint a split, and purchase child units."""
    facts = [known[key] for key in task["fact_ids"]]
    try:
        value = write_partition(job, key=task["key"], section=task["section"], facts=facts,
                                template=template, bundle=bundle, correction=task["correction"],
                                subsection_path=task["subsection_path"])
        return [(value, task)]
    except IncompleteDocumentOutput:
        if len(facts) < 2 or depth >= 8:
            raise IncompleteDocumentOutput(
                "La sotto-sezione minima ha prodotto output incompleto. I risultati riusciti sono conservati; "
                "è necessaria una revisione dell'incarico prima di proseguire."
            ) from None
        middle = len(facts) // 2
        children = [
            {**task, "key": f"write:split:{digest([task['key'], index, [f.id for f in group]])[:40]}",
             "fact_ids": [f.id for f in group]}
            for index, group in enumerate((facts[:middle], facts[middle:]))
        ]
        children = run_step(job=job, key=f"partition:{digest(task['key'])[:40]}", kind="document_partition",
                            data={"parent": task, "depth": depth, "strategy": "bisect_facts_v1"},
                            execute=lambda _step: children, contract_version="v3.2")
        outputs = []
        for child in children:
            outputs.extend(write_task(job, task=child, known=known, template=template, bundle=bundle, depth=depth + 1))
        return outputs


def compose_partitions(job, *, facts, plan, bundle, template, corrections=None, partial=False):
    known = {f.id: f for f in facts}
    proposed = writing_tasks(facts, plan, template, corrections)
    tasks = run_step(job=job, key=f"writing_plan:{digest(proposed)[:32]}", kind="document_writing_plan",
                     data={"tasks": proposed}, execute=lambda _step: proposed, contract_version="v3.2")
    from .pipeline_v3 import progress

    phase = "correction" if corrections else "sections"
    prefix = "correction_" if corrections else ""
    progress(job, phase, **{f"{prefix}sections_total": len(template["sections"]), f"{prefix}sections_completed": 0,
                           f"{prefix}partitions_total": len(tasks), f"{prefix}partitions_completed": 0})
    outputs, completed_tasks = [], []
    for index, leaves in enumerate(parallel_map(
            lambda task: write_task(job, task=task, known=known, template=template, bundle=bundle), tasks)):
        outputs.extend(value for value, _task in leaves)
        completed_tasks.extend(task for _value, task in leaves)
        pending_sections = {task["section"] for task in tasks[index + 1:]}
        progress(job, phase, **{f"{prefix}sections_completed": len(template["sections"]) - len(pending_sections),
                 f"{prefix}partitions_completed": len(outputs), f"{prefix}partitions_total": len(outputs) + len(tasks) - index - 1})
    composition = assemble_partitions(outputs, completed_tasks, template, title=job.revision.elaborato.title)
    editor = compose_editor(job, composition)
    from .fields import ensure_signature_slot, preserve_completed_fields

    if not partial:
        ensure_signature_slot(editor, template, job.revision.elaborato.language)
        preserve_completed_fields(job.revision.editor_doc, editor)
    return editor


def section_blocks(editor):
    groups, key = {}, None
    for node in editor.get("content", []):
        if node["type"] == "heading" and node.get("attrs", {}).get("level") == 2:
            key = node.get("attrs", {}).get("sectionKey")
        if key:
            groups.setdefault(key, []).append(deepcopy(node))
    return groups


def replace_sections(editor, replacement, template, selected):
    from .fields import fields_in, preserve_completed_fields

    previous = section_blocks(editor)
    following = section_blocks(replacement)
    if set(selected) - set(following):
        raise ValueError("La correzione non contiene tutte le sezioni richieste.")
    reserved = {f["fieldId"] for key, nodes in previous.items() if key not in selected
                for node in nodes for f in fields_in(node)}
    for key in selected:
        for node in following[key]:
            for field in fields_in(node):
                identifier = field["fieldId"]
                if identifier in reserved:
                    field["fieldId"] = f"{identifier[:74]}.c{digest([key, identifier, len(reserved)])[:16]}"
                reserved.add(field["fieldId"])
    result = deepcopy(editor)
    result["content"] = [node for section in template["sections"]
                         for node in (following if section["key"] in selected else previous).get(section["key"], [])]
    preserve_completed_fields(editor, result)
    return result


def correct_sections(job, *, editor, facts, plan, bundle, template, corrections):
    from copy import copy

    partial_template = {**template, "sections": [s for s in template["sections"] if s["key"] in corrections]}
    partial_job = copy(job)
    partial_job.revision = copy(job.revision)
    partial_job.revision.template_snapshot = partial_template
    partial_job.revision.editor_doc = {**editor, "content": [node for key, nodes in section_blocks(editor).items()
                                                           if key in corrections for node in nodes]}
    replacement = compose_partitions(partial_job, facts=facts, plan=plan, bundle=bundle,
                                    template=partial_template, corrections=corrections, partial=True)
    return replace_sections(editor, replacement, template, set(corrections))


def assemble_partitions(outputs, tasks, template, *, title):
    """Rebase local block addresses without flattening the authored structure."""
    outputs = deepcopy(outputs)
    seen_fields = set()
    photos, photo_index, local_photos = [], {}, {}
    for number, (value, task) in enumerate(zip(outputs, tasks, strict=True)):
        if len(value.sections) != 1 or value.sections[0].key != task["section"]:
            raise ValueError("La porzione non corrisponde alla sezione assegnata.")
        for claim in composition_claims(value):
            for index, field in enumerate(claim.fields):
                key = field.key
                if key in seen_fields:
                    replacement = f"{key[:74]}.p{digest([task['key'], index, len(seen_fields)])[:16]}"
                    claim.text = claim.text.replace("{{" + key + "}}", "{{" + replacement + "}}")
                    claim.fields[index] = field.model_copy(update={"key": replacement})
                    key = replacement
                seen_fields.add(key)
        for index, photo in enumerate(value.photographs):
            if photo.section_key and photo.section_key != task["section"]:
                raise ValueError("Una fotografia è stata assegnata a una sezione fuori dalla porzione.")
            photo.section_key = task["section"]
            existing = photo_index.get(photo.source_id)
            if existing is None:
                photo_index[photo.source_id] = len(photos)
                local_photos[number, index] = len(photos)
                photos.append(photo)
            else:
                primary = photos[existing]
                if photo.caption.text != primary.caption.text:
                    primary.caption.text += "\n" + photo.caption.text
                primary.caption.source_ids = list(dict.fromkeys([*primary.caption.source_ids, *photo.caption.source_ids]))
                primary.caption.fact_ids = list(dict.fromkeys([*primary.caption.fact_ids, *photo.caption.fact_ids]))
                local_photos[number, index] = existing
    sections = []
    for definition in template["sections"]:
        paragraphs, lists, tables, layout = [], [], [], []
        used = set()
        previous_path = None
        section_photos = [i for i, photo in enumerate(photos) if photo.section_key == definition["key"]]
        for number, (value, task) in enumerate(zip(outputs, tasks, strict=True)):
            if task["section"] != definition["key"]:
                continue
            piece = value.sections[0]
            path = tuple(task.get("subsection_path", ()))
            if path and path != previous_path:
                for depth, label in enumerate(path):
                    if previous_path and previous_path[:depth + 1] == path[:depth + 1]:
                        continue
                    layout.append(BlockPlacement(kind="heading", label=label, heading_level=min(3 + depth, 6)))
            previous_path = path
            offsets = {"paragraph": len(paragraphs), "list": len(lists), "table": len(tables)}
            sizes = {"paragraph": len(piece.paragraphs), "list": len(piece.lists),
                     "table": len(piece.tables), "photo": len(value.photographs)}
            hints = list(piece.layout)
            referenced = {(p.kind, p.index) for p in hints if p.kind != "heading"}
            hints.extend(BlockPlacement(kind=kind, index=index)
                         for kind, size in sizes.items() for index in range(size) if (kind, index) not in referenced)
            for hint in hints:
                if hint.kind == "heading":
                    if hint.label.strip():
                        layout.append(hint)
                    continue
                if hint.index >= sizes[hint.kind]:
                    continue
                if hint.kind == "photo":
                    global_index = local_photos[number, hint.index]
                    if global_index not in section_photos:
                        continue  # The same source is already placed in another section.
                    index = section_photos.index(global_index)
                else:
                    index = offsets[hint.kind] + hint.index
                address = (hint.kind, index)
                if address not in used:
                    layout.append(hint.model_copy(update={"index": index}))
                    used.add(address)
            paragraphs.extend(piece.paragraphs)
            lists.extend(piece.lists)
            tables.extend(piece.tables)
        sections.append(Section(key=definition["key"], paragraphs=paragraphs, lists=lists, tables=tables, layout=layout))
    return Composition(title=next((v.title for v in outputs if v.title.strip()), title),
                       subtitle=next((v.subtitle for v in outputs if v.subtitle), ""),
                       sections=sections, photographs=photos)


def claim_blocks(editor):
    # Stable addresses independent of renderer HTML and unsupported editor attrs.
    return [
        {**claim, "claim_id": f"claim:{index}:{digest(claim)[:20]}"}
        for index, claim in enumerate(editor_claims(editor, include_context=True))
    ]
