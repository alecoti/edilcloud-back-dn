"""Reconcile and allocate facts without allowing silent loss or waiver."""

from collections import defaultdict
from copy import deepcopy

from .content import digest
from .intelligence_calls import specialist
from .intelligence_contracts import DocumentPlan, ReconciliationResult
from .intelligence_readers import bounded_batches, parallel_map


def requirements(policy, template):
    return [
        *[{"id": f"field:{key}", "kind": "field", "name": key} for key in policy.required_fields],
        *[{"id": f"section:{section['key']}", "kind": "section", "name": section["label"]}
          for section in template["sections"] if section.get("required")],
        *[{"id": f"rule:{key}", "kind": "completion_rule", "name": key} for key in policy.completion_rules],
    ]


def complete_plan(plan, facts, policy, template, *, reconciliation=None, job=None):
    """Complete structural destinations, never invent facts or satisfied fields."""
    from .intelligence_contracts import FactAllocation, RequirementDisposition

    sections = {s["key"] for s in template["sections"]}
    mappings = {
        "daily_report": {"activity": 2, "person": 2, "decision": 3, "condition": 3, "outcome": 3, "weather": 4},
        "inspection": {"person": 2, "finding": 3, "decision": 4, "proposal": 4, "condition": 5, "outcome": 5},
        "coordination": {"person": 2, "finding": 3, "decision": 4, "proposal": 3, "condition": 5, "outcome": 5},
        "periodic_report": {"activity": 2, "finding": 3, "condition": 3, "interruption": 3, "decision": 4, "outcome": 6},
        "photo_report": {"person": 2, "date": 2, "finding": 3, "visual_limitation": 3, "condition": 3},
        "issue_report": {"activity": 2, "finding": 2, "decision": 2, "condition": 4, "outcome": 4, "reopening": 4, "person": 3},
    }
    known = {f.id: f for f in facts}
    proposed = {}
    for row in plan.allocations:
        if row.fact_id in known and row.fact_id not in proposed:
            proposed[row.fact_id] = row.model_copy(deep=True)
    repaired = []
    allocations = []
    for fact in facts:
        row = proposed.get(fact.id)
        fallback = f"section_{mappings.get(policy.storage_key, {}).get(fact.category, 1)}"
        if fallback not in sections:
            fallback = template["sections"][0]["key"]
        if not row or not row.reason.strip() or (row.included and row.section_key not in sections):
            row = FactAllocation(fact_id=fact.id, section_key=fallback,
                included=fact.relevant or fact.critical,
                reason="Destinazione applicativa per categoria; nessun fatto pertinente viene omesso." if fact.relevant or fact.critical
                else fact.relevance_reason)
            repaired.append(fact.id)
        if not row.included and (fact.relevant or fact.critical):
            target = row.reason.removeprefix("duplicate:") if row.reason.startswith("duplicate:") else ""
            canonical = known.get(target)
            approved = reconciliation and reconciliation.get("facts", {}).get(fact.id, {}).get("canonical_fact_id") == target
            exact = canonical and " ".join(canonical.text.casefold().split()) == " ".join(fact.text.casefold().split())
            equivalent = canonical and canonical.nature == fact.nature and canonical.event_date == fact.event_date and canonical.category == fact.category
            if target == fact.id or not equivalent or not (approved or exact) or not proposed.get(target) or not proposed[target].included:
                row.included, row.section_key = True, fallback
                row.reason = "Fatto pertinente conservato: nessuna deduplicazione equivalente verificata."
                repaired.append(fact.id)
        allocations.append(row)
    required = {row.requirement_id: row for row in plan.requirements}
    completed = []
    for definition in requirements(policy, template):
        row = required.get(definition["id"])
        if row is None or set(row.fact_ids) - set(known) or not row.reason.strip():
            row = RequirementDisposition(requirement_id=definition["id"], status="requires_confirmation", fact_ids=[],
                                         reason="Requisito da completare o confermare; nessun dato dedotto.")
            repaired.append(definition["id"])
        completed.append(row)
    result = DocumentPlan(allocations=allocations, requirements=completed)
    validate_plan(result, facts, policy, template)
    if repaired and job:
        from .models import DocumentAudit

        DocumentAudit.objects.create(revision=job.revision, actor=job.requested_by, action="plan.completed_by_application",
                                     detail={"items": list(dict.fromkeys(repaired))})
    return result


def reconcile(job, facts, policy):
    known = {fact.id: fact for fact in facts}
    resolved = {}
    conflicts = []
    for batch in bounded_batches([f.model_dump() for f in facts], max_characters=40000, max_items=35):
        ids = {f["id"] for f in batch}
        result = specialist(
            job=job, key=f"reconcile:{digest(sorted(ids))}", stage="document_reconcile",
            schema=ReconciliationResult, effort="high", data={"facts": batch, "policy": policy},
            instructions=("Riconcilia ogni fatto senza riscrivere o eliminare l'evidenza. Restituisci ogni fact_id "
                          "esattamente una volta. canonical_fact_id può indicare soltanto un fatto del lotto "
                          "equivalente per significato, data e natura; altrimenti usa lo stesso id. "
                          "Non unificare proposta, esecuzione, verifica o esito condizionato. "
                          "Segnala contraddizioni tramite conflicts_with. Collega gli sviluppi del medesimo "
                          "evento con related_fact_ids, senza confonderli con duplicati. Mantieni esiti e condizioni rilevanti."),
        )
        if {r.fact_id for r in result.facts} != ids or len(result.facts) != len(ids):
            raise ValueError("La riconciliazione non rende conto di tutti i fatti.")
        for row in result.facts:
            if row.canonical_fact_id not in ids or (set(row.conflicts_with) | set(row.related_fact_ids)) - ids or not row.reason.strip():
                raise ValueError("Riconciliazione con riferimenti o motivazioni non validi.")
            # A model may flag doubts; it cannot discard a critical/relevant
            # source fact solely to simplify the final document.
            original = known[row.fact_id]
            row.relevant = row.relevant or original.critical or original.relevant
            resolved[row.fact_id] = row.model_dump()
            conflicts.extend((row.fact_id, other) for other in row.conflicts_with)
    # Exact duplicates across different batches can be unified deterministically.
    exact = {}
    for fact in facts:
        key = digest({"text": " ".join(fact.text.casefold().split()), "nature": fact.nature,
                      "date": fact.event_date, "category": fact.category})
        if key in exact:
            resolved[fact.id]["canonical_fact_id"] = exact[key]
        else:
            exact[key] = fact.id
    from .intelligence_reconciliation import reconcile_global

    return reconcile_global(job, facts, {"facts": resolved, "conflicts": conflicts}, policy)


def validate_plan(plan, facts, policy, template):
    known = {f.id: f for f in facts}
    sections = {s["key"] for s in template["sections"]}
    expected = {r["id"] for r in requirements(policy, template)}
    allocations = {row.fact_id: row for row in plan.allocations}
    if len(allocations) != len(plan.allocations) or set(allocations) != set(known):
        raise ValueError("Il piano non assegna una destinazione a ogni fatto.")
    for row in allocations.values():
        if not row.reason.strip() or (row.included and row.section_key not in sections):
            raise ValueError("Destinazione o motivazione del fatto non valida.")
        if not row.included and (known[row.fact_id].critical or known[row.fact_id].relevant):
            # Relevant facts may be deduplicated into a canonical fact, but this
            # must be reconciled explicitly, never hidden by the writer.
            if not row.reason.startswith("duplicate:"):
                raise ValueError("Un fatto rilevante non può essere escluso senza riconciliazione esplicita.")
    dispositions = {r.requirement_id: r for r in plan.requirements}
    if len(dispositions) != len(plan.requirements) or set(dispositions) != expected:
        raise ValueError("Il piano non rende conto di tutti i requisiti applicativi.")
    for row in dispositions.values():
        if not row.reason.strip() or set(row.fact_ids) - set(known):
            raise ValueError("Requisito senza motivazione o con riferimenti sconosciuti.")
    return plan


def plan_document(job, facts, policy, template, reconciliation):
    if not reconciliation.get("global_complete"):
        raise ValueError("Il piano DEEP richiede la riconciliazione globale completata.")
    required = requirements(policy, template)
    allocations = []
    groups = defaultdict(list)
    for fact in facts:
        canonical = reconciliation["facts"][fact.id]["canonical_fact_id"]
        groups[canonical].append(fact)
    batches = bounded_batches(
        [{"fact": fact.model_dump(), "reconciliation": reconciliation["facts"][fact.id]}
         for fact in facts], max_characters=36000, max_items=30,
    )

    def create(batch):
        identifier = digest([v["fact"]["id"] for v in batch])
        return specialist(
            job=job, key=f"plan:{identifier}", stage="document_plan", schema=DocumentPlan,
            data={"facts": batch, "requirements": required, "policy": policy.snapshot(template["sections"]),
                  "sections": template["sections"]},
            instructions=("Assegna ogni fatto a UNA sezione pertinente. Restituisci tutti i fact_id del lotto. "
                          "Ogni fatto rilevante o critico deve essere incluso. Un duplicato può essere escluso "
                          "solo se la riconciliazione indica un altro canonical_fact_id; in tal caso reason deve "
                          "essere esattamente duplicate:<canonical_fact_id>. Per ogni requisito restituisci "
                          "uno stato, motivazione e fact_ids del lotto che lo documentano. "
                          "Dato mancante richiede un campo o conferma, non un valore inferito dal team o dal programma. "
                          "Assegna subsection_path con titoli descrittivi per disciplina, area, piano o evento "
                          "quando la sezione è articolata, ad esempio [Impianti elettrici, Piano primo]. "
                          "Riusa lo stesso percorso per fatti dello stesso argomento. Non scrivere numeri di "
                          "sezione né titoli tecnici di batch. Il backend suddividerà ulteriormente gli incarichi grandi."),
        )

    requirement_rows = defaultdict(list)
    for result in parallel_map(create, batches):
        allocations.extend(result.allocations)
        for row in result.requirements:
            requirement_rows[row.requirement_id].append(row)
    # All required rows exist, including when no facts are extractable.
    from .intelligence_contracts import RequirementDisposition

    combined = []
    for definition in required:
        rows = requirement_rows[definition["id"]]
        references = sorted({fact_id for row in rows for fact_id in row.fact_ids})
        status = "satisfied" if any(r.status == "satisfied" and r.fact_ids for r in rows) else "requires_confirmation"
        combined.append(RequirementDisposition(
            requirement_id=definition["id"], status=status, fact_ids=references,
            reason="; ".join(dict.fromkeys(r.reason for r in rows)) or "Dato da completare o confermare nell'editor.",
        ))
    plan = DocumentPlan(allocations=allocations, requirements=combined)
    plan = complete_plan(plan, facts, policy, template, reconciliation=reconciliation, job=job)
    for allocation in plan.allocations:
        if not allocation.included and allocation.reason.startswith("duplicate:"):
            canonical = allocation.reason.removeprefix("duplicate:")
            if reconciliation["facts"][allocation.fact_id]["canonical_fact_id"] != canonical:
                raise ValueError("Esclusione per duplicato priva di riscontro nella riconciliazione.")
            target = next((a for a in plan.allocations if a.fact_id == canonical), None)
            if not target or not target.included:
                raise ValueError("Il fatto canonico escluso non è rappresentato nel piano.")
    return plan


def section_template(template, key):
    value = deepcopy(template)
    value["sections"] = [s for s in value["sections"] if s["key"] == key]
    return value
