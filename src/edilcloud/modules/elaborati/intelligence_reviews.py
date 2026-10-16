"""Different review questions: is it supported, and what was left out?"""

from collections import defaultdict

from .content import digest, local_quality, validate_editor
from .intelligence_calls import specialist
from .intelligence_contracts import CompletenessReview, FactualReview
from .intelligence_planning import requirements
from .intelligence_readers import bounded_batches, parallel_map
from .intelligence_writing import claim_blocks
from .models import DocumentEvidenceItem


def validate_factual_review(review, claims, facts):
    expected = {c["claim_id"]: c for c in claims}
    actual = {r.claim_id: r for r in review.claims}
    known = {f.id: f for f in facts}
    if len(actual) != len(review.claims) or set(actual) != set(expected):
        raise ValueError("La verifica fattuale non esamina tutte le affermazioni assegnate.")
    for row in review.claims:
        if set(row.represented_fact_ids) - set(known) or not row.explanation.strip():
            raise ValueError("Verifica fattuale con riferimenti o motivazioni non validi.")
        claim = expected[row.claim_id]
        for fact_id in row.represented_fact_ids:
            if not set(claim["source_ids"]) & {r.source_id for r in known[fact_id].references}:
                raise ValueError("Il fatto rappresentato non corrisponde alle fonti citate nel blocco.")
    return review


def factual_review(job, editor, facts):
    claims = claim_blocks(editor)
    def review(batch):
        source_ids = {sid for claim in batch for sid in claim["source_ids"]}
        parts = job.evidence_items.filter(parent_source_id__in=source_ids, kind="source_part")
        originals = [row.payload for row in parts.iterator(chunk_size=50)]
        # Per-claim evidence can itself be a long document. Review in bounded
        # source windows, then aggregate adverse verdicts conservatively.
        evidence_windows = list(bounded_batches(originals, max_characters=36000, max_items=16)) or [[]]
        results = []
        for window_index, window in enumerate(evidence_windows):
            relevant_facts = [f for f in facts if any(r.source_id in source_ids for r in f.references)]
            result = specialist(
                job=job, key=f"factual:{digest(batch)[:24]}:{window_index}:{digest(window)[:12]}",
                stage="document_factual", schema=FactualReview, effort="high",
                data={"claims": batch, "original_sources": window,
                      "facts": [f.model_dump() for f in relevant_facts]},
                instructions=("Verifica ogni claim_id rispetto alle fonti originali in questa finestra e ai "
                              "riferimenti puntuali dei fatti. Restituisci ogni claim una volta: supported, "
                              "partially_supported, contradicted o not_verifiable. Non basta una citazione. "
                              "Elenca represented_fact_ids solo se il fatto compare davvero nel blocco. "
                              "Se il supporto è fuori dalla finestra usa not_verifiable e spiegalo; "
                              "non confondere placeholder e titoli di colonne con fatti inventati. "
                              "Controlla date, attribuzioni, condizioni, proposta/esecuzione/verifica e dati numerici."),
            )
            validate_factual_review(result, batch, relevant_facts)
            results.append(result)
        return results
    grouped = defaultdict(list)
    for results in parallel_map(review, bounded_batches(claims, max_characters=16000, max_items=12)):
        for result in results:
            for row in result.claims:
                grouped[row.claim_id].append(row)
    verdicts = []
    for claim in claims:
        candidates = grouped[claim["claim_id"]]
        status = (
            "contradicted" if any(r.status == "contradicted" for r in candidates)
            else "supported" if any(r.status == "supported" for r in candidates)
            else "partially_supported" if any(r.status == "partially_supported" for r in candidates)
            else "not_verifiable"
        )
        verdicts.append({"claim_id": claim["claim_id"], "status": status,
                         "represented_fact_ids": sorted({f for r in candidates if r.status == "supported" for f in r.represented_fact_ids}),
                         "explanation": "; ".join(dict.fromkeys(r.explanation for r in candidates))})
    return {"claims": verdicts}


def completeness_review(job, editor, facts, policy, plan):
    blocks = claim_blocks(editor)
    dispositions = {a.fact_id: a.model_dump() for a in plan.allocations}
    all_requirements = requirements(policy, job.revision.template_snapshot)
    issues = []
    read_ids = set()
    roots = DocumentEvidenceItem.objects.filter(job=job, parent_source_id="")
    # Review the original material independently of the readers' summaries.
    originals = DocumentEvidenceItem.objects.filter(job=job, kind="source_part")
    def review(window):
        source_ids = {v["source_id"] for v in window}
        local_facts = [f for f in facts if any(r.source_id in source_ids for r in f.references)]
        referenced_blocks = [b for b in blocks if set(b["source_ids"]) & source_ids]
        result = specialist(
            job=job, key=f"complete:{digest(window)[:24]}:{digest(editor)[:12]}",
            stage="document_complete", schema=CompletenessReview, effort="high",
            data={"inventory": [{"id": value["source_id"], "part_id": value["part_id"]} for value in window],
                  "original_sources": window, "facts": [f.model_dump() for f in local_facts],
                  "allocations": [dispositions[f.id] for f in local_facts],
                  "requirements": all_requirements, "document_blocks": referenced_blocks,
                  "policy": policy.snapshot(job.revision.template_snapshot["sections"])},
            instructions=("Sei il revisore indipendente della COMPLETEZZA. Leggi le fonti originali, non solo "
                          "i fatti selezionati. Cerca cosa è rimasto fuori: unrepresented_fact, missing_requirement, "
                          "unread_source, missing_outcome, questionable_exclusion. Controlla soprattutto esiti, "
                          "decisioni e condizioni. Esamina ogni part_id e restituiscilo in reviewed_source_ids. "
                          "I document_blocks sono quelli con citazioni di queste fonti: un fatto non rappresentato "
                          "non è coperto dal fatto che una fonte sia citata altrove. Non attribuire valore assoluto "
                          "a un requisito non documentato: indica campo/conferma necessari. subject_id deve riferirsi "
                          "a fact_id, part_id, source_id o requirement_id presenti nell'ingresso."),
        )
        expected = {v["part_id"] for v in window}
        if len(result.reviewed_source_ids) != len(expected) or set(result.reviewed_source_ids) != expected:
            raise ValueError("Il revisore della completezza non ha esaminato tutte le fonti assegnate.")
        allowed = expected | source_ids | {f.id for f in local_facts} | {r["id"] for r in all_requirements}
        if any(issue.subject_id not in allowed or not issue.explanation.strip() for issue in result.issues):
            raise ValueError("Rilievo di completezza con riferimento sconosciuto.")
        return result
    for result in parallel_map(review, bounded_batches((row.payload for row in originals.iterator(chunk_size=50)),
                                                       max_characters=26000, max_items=12)):
        issues.extend(row.model_dump() for row in result.issues)
        read_ids.update(result.reviewed_source_ids)
    for row in roots.exclude(state="read"):
        if row.state != "excluded" or not row.reason:
            issues.append({"kind": "unread_source", "subject_id": row.source_id, "critical": True,
                           "explanation": f"Fonte non completamente esaminata: {row.reason or row.state}."})
    return {"reviewed_source_ids": sorted(read_ids), "issues": issues}


def application_quality(editor, bundle, facts, plan, factual, completeness, policy, template):
    validate_editor(editor, bundle, template)
    issues = local_quality(editor, bundle, template)
    blocks = {v["claim_id"]: v for v in claim_blocks(editor)}
    represented = set()
    for row in factual["claims"]:
        block = blocks[row["claim_id"]]
        represented.update(row["represented_fact_ids"] if row["status"] == "supported" else [])
        if row["status"] != "supported" and block["nature"] != "unverified":
            issues.append({"section_key": block["section_key"], "text": block["text"],
                           "severity": "blocking", "explanation": row["explanation"]})
    allocations = {a.fact_id: a for a in plan.allocations}
    for fact in facts:
        allocation = allocations[fact.id]
        canonical = allocation.reason.removeprefix("duplicate:") if not allocation.included else fact.id
        if (fact.relevant or fact.critical) and canonical not in represented:
            issues.append({"section_key": allocation.section_key, "text": fact.text, "severity": "blocking",
                           "explanation": "Fatto rilevante non rappresentato e verificato nel documento."})
    if policy.required_event:
        declared = any(f.category == policy.required_event and f.nature in {"observed", "declared", "executed", "verified"}
                       and any(not r.source_id.startswith(("request:", "member:", "project:")) for r in f.references)
                       for f in facts)
        if not declared:
            issues.append({"section_key": "", "text": "", "severity": "blocking",
                           "explanation": "La visita o riunione deve essere dichiarata da una fonte pertinente; non può essere inferita dalla richiesta."})
    if policy.storage_key == "photo_report" and not any(n["type"] == "evidencePhoto" for n in editor.get("content", [])):
        issues.append({"section_key": "", "text": "", "severity": "blocking", "explanation": "Mancano fotografie effettive nella relazione fotografica."})
    for row in completeness["issues"]:
        issues.append({"section_key": "", "text": "", "severity": "blocking" if row["critical"] else "warning",
                       "explanation": row["explanation"], "category": row["kind"], "subject_id": row["subject_id"]})
    return {"passed": not any(i["severity"] == "blocking" for i in issues), "issues": issues,
            "missing_data": [r.requirement_id for r in plan.requirements if r.status != "satisfied"],
            "content_hash": digest(editor), "evidence_hash": bundle["bundle_hash"],
            "policy_version": policy.version, "coverage": {"facts": len(facts), "represented_facts": len(represented),
                                                            "sources": len(bundle["sources"]), "complete_reading": bundle["coverage_complete"]},
            "provenance": {"plan": plan.model_dump(), "factual": factual, "completeness": completeness}}
