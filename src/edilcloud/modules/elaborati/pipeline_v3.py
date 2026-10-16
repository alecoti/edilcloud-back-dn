"""Adaptive document intelligence orchestrated by application code."""

from concurrent.futures import ThreadPoolExecutor

from django.db import connection
from django.utils import timezone

from .checkpoints import run_step, threaded_step
from .content import Composition, Section, Claim, digest, validate_editor
from .engine import compose_editor, prompt_bundle, prompt_template
from .intelligence_calls import specialist
from .intelligence_contracts import FastDocumentResult, StandardAnalysisResult, validate_reader, enforce_fact_policy
from .intelligence_planning import plan_document, reconcile, complete_plan
from .intelligence_readers import evidence_bundle, mark_metadata_examined, prepare_sources, read_inventory
from .intelligence_reviews import application_quality, completeness_review, factual_review
from .intelligence_writing import claim_blocks, compose_partitions, correct_sections, index_facts
from .inventory import build_inventory, inventory_counts
from .models import DocumentJob
from .policies import policy_for
from .preflight import DocumentPath, DocumentPreflight
from .source_reading import finalize_root, set_reading_state


def progress(job, stage, **data):
    from .jobs import renew_lease

    renew_lease(job)
    job.refresh_from_db(fields=("workflow_state",))
    state = {**job.workflow_state, **data, "stage": stage}
    DocumentJob.objects.filter(pk=job.pk, state="running", lease_token=job.lease_token).update(
        stage=stage, workflow_state=state, updated_at=timezone.now(),
    )
    job.workflow_state = state


def empty_document(job, policy):
    language = job.revision.elaborato.language
    labels = {
        "it": "Non risultano attività documentate per il periodo selezionato. I dati non disponibili restano da completare; l'assenza di registrazioni non dimostra che il cantiere fosse chiuso.",
        "en": "No activities are documented for the selected period. Missing information remains to be completed; an absence of records does not establish that the site was closed.",
        "fr": "Aucune activité n'est documentée pour la période sélectionnée. Les informations manquantes restent à compléter ; l'absence de relevés ne prouve pas la fermeture du chantier.",
        "ro": "Nu sunt documentate activități pentru perioada selectată. Datele lipsă rămân de completat; lipsa înregistrărilor nu dovedește că șantierul era închis.",
        "ru": "За выбранный период нет документированных работ. Отсутствующие данные необходимо заполнить; отсутствие записей не доказывает, что стройплощадка была закрыта.",
        "ar": "لا توجد أعمال موثقة للفترة المحددة. تبقى البيانات الناقصة للاستكمال؛ وعدم وجود سجلات لا يثبت أن الموقع كان مغلقاً.",
    }
    note = labels.get(language, labels["en"])
    template = job.revision.template_snapshot
    sections = []
    for index, section in enumerate(template["sections"]):
        if index == 0:
            claim = Claim(text=note, nature="unverified", source_ids=[])
        else:
            from .fields import EditableField

            field = EditableField(key=f"complete_{section['key']}", label=section["label"], kind="text")
            claim = Claim(text="{{" + field.key + "}}", fields=[field], nature="unverified", source_ids=[])
        sections.append(Section(key=section["key"], paragraphs=[claim]))
    mark_metadata_examined(job)
    bundle = evidence_bundle(job)
    editor = compose_editor(job, Composition(title=job.revision.elaborato.title, sections=sections, photographs=[]))
    from .fields import ensure_signature_slot

    ensure_signature_slot(editor, template, language)
    return {"editor_doc": editor, "evidence": bundle,
            "reasoning": {"facts": [], "path": "FAST_0", "policy": policy.snapshot(template["sections"])},
            "quality": {"passed": False, "issues": [], "missing_data": list(policy.required_fields),
                        "content_hash": digest(editor), "evidence_hash": bundle["bundle_hash"],
                        "path": "FAST_0", "ai_used": False, "requires_completion": True}}


def fast_document(job, policy):
    rows = list(job.evidence_items.filter(kind="source_part").order_by("source_id"))
    parts = [row.payload for row in rows]
    bundle = evidence_bundle(job)
    from .intelligence_planning import requirements
    from .editorial import editorial_contract

    result = specialist(
        job=job, key="fast_document", stage="document_fast", schema=FastDocumentResult, effort="medium",
        data={"parts": parts, "policy": policy.snapshot(job.revision.template_snapshot["sections"]),
              "requirements": requirements(policy, job.revision.template_snapshot),
              "evidence": prompt_bundle(bundle), "template": prompt_template(job.revision.template_snapshot),
              "language": job.revision.elaborato.language, "editorial_contract": editorial_contract(job.revision)},
        instructions=("Produci il documento piccolo in un'unica risposta. reading esamina ogni part_id, "
                      "facts usa id unici e quote letterali delle parti; plan assegna ogni fatto a una sezione "
                      "e rende conto di ogni requisito. composition contiene tutte le sezioni e registri del "
                      "template, campi editabili specifici per i valori mancanti e firme vuote. "
                      "Usa i parts strutturati per testo e campi; il backend costruisce i placeholder. "
                      "Per ogni Claim fattuale indica fact_ids dei fatti realmente espressi in quel blocco, "
                      "usando gli id della tua reading. I campi vuoti hanno fact_ids=[]. "
                      "Non estrarre come fatti operativi la richiesta di generare il documento o la configurazione della lingua. "
                      "Non trasformare chiavi JSON vuote, weather_recorded={} o presence=unknown "
                      "in fatti critici: sono dati mancanti gestiti dai requisiti e dai campi editabili. "
                      "Non inventare dati per completare il testo. "
                      "Nessun fatto rilevante può essere escluso. L'assenza di dati non dimostra che non sia accaduto nulla."),
    )
    validate_reader(result.reading, parts)
    enforce_fact_policy(result.reading.facts, parts, policy)
    result.plan = complete_plan(result.plan, result.reading.facts, policy, job.revision.template_snapshot, job=job)
    bundle = index_facts(bundle, result.reading.facts)
    editor = compose_editor(job, result.composition)
    from .fields import ensure_signature_slot

    ensure_signature_slot(editor, job.revision.template_snapshot, job.revision.elaborato.language)
    validate_editor(editor, bundle, job.revision.template_snapshot)
    for disposition in result.reading.sources:
        row = next(row for row in rows if row.source_id == disposition.part_id)
        set_reading_state(row, disposition.status, disposition.reason)
    for root in job.evidence_items.filter(parent_source_id=""):
        finalize_root(root)
    bundle = evidence_bundle(job)
    bundle = index_facts(bundle, result.reading.facts)
    from .content import local_quality

    quality = {"passed": False, "needs_verification": False,
               "issues": local_quality(editor, bundle, job.revision.template_snapshot),
               "missing_data": [r.requirement_id for r in result.plan.requirements if r.status != "satisfied"],
               "content_hash": digest(editor), "evidence_hash": bundle["bundle_hash"],
               "verification_scope": "single_call_with_application_validation",
               "plan": result.plan.model_dump(), "facts": [f.model_dump() for f in result.reading.facts]}
    # FAST_1 does not pretend an independent AI review occurred. Each relevant
    # extracted fact must at least retain a corresponding cited block; semantic
    # quality is measured by the acceptance dataset before rollout.
    blocks = claim_blocks(editor)
    missing = [fact for fact in result.reading.facts if (fact.relevant or fact.critical) and not any(
        fact.id in b.get("fact_ids", [])
        and set(b["source_ids"]) & {r.source_id for r in fact.references} for b in blocks)]
    for fact in missing:
        quality["issues"].append({"section_key": "", "text": fact.text, "severity": "blocking",
                                  "explanation": "Fatto rilevante privo di un blocco citato nel documento."})
    quality["passed"] = not any(i["severity"] == "blocking" for i in quality["issues"])
    return {"editor_doc": editor, "evidence": bundle,
            "reasoning": {"facts": [f.model_dump() for f in result.reading.facts], "path": "FAST_1"}, "quality": quality}


def reviews(job, editor, facts, policy, plan, bundle):
    validate_editor(editor, bundle, job.revision.template_snapshot)
    def factual():
        return factual_review(job, editor, facts)

    def complete():
        return completeness_review(job, editor, facts, policy, plan)

    if connection.vendor == "sqlite":
        factual_result, complete_result = factual(), complete()
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(threaded_step, factual)
            b = pool.submit(threaded_step, complete)
            factual_result, complete_result = a.result(), b.result()
    progress(job, "reviews", reviews_completed=job.steps.filter(
        state="completed", kind__in=("document_factual", "document_complete")).count())
    return application_quality(editor, bundle, facts, plan, factual_result, complete_result,
                               policy, job.revision.template_snapshot)


def refine_document(job, editor, facts, policy, plan, bundle, quality):
    by_section = {}
    for issue in quality["issues"]:
        key = issue.get("section_key")
        if key and issue["severity"] == "blocking":
            by_section.setdefault(key, []).append(issue)
    if not by_section:
        return editor, quality
    progress(job, "correction")
    corrected = correct_sections(job, editor=editor, facts=facts, plan=plan, bundle=bundle,
                                 template=job.revision.template_snapshot, corrections=by_section)
    candidate_quality = reviews(job, corrected, facts, policy, plan, bundle)
    previous = sum(i["severity"] == "blocking" for i in quality["issues"])
    following = sum(i["severity"] == "blocking" for i in candidate_quality["issues"])
    if following < previous:
        return corrected, candidate_quality
    return editor, quality


def standard_document(job, policy):
    from .intelligence_planning import requirements
    from .editorial import editorial_contract

    parts = [row.payload for row in job.evidence_items.filter(kind="source_part").order_by("source_id")]
    template = job.revision.template_snapshot
    analysis = specialist(
        job=job, key="standard_analysis", stage="document_reasoning", schema=StandardAnalysisResult,
        data={"parts": parts, "requirements": requirements(policy, template),
              "policy": policy.snapshot(template["sections"]), "template": prompt_template(template)},
        instructions=("Esamina ogni parte e restituisci tutti i fatti pertinenti con quote letterali e "
                      "source_id/part_id/page. Ogni part_id ha un esito motivato; ogni fatto ha id unico. "
                      "Preserva decisioni/esiti/condizioni. Il piano assegna ogni fatto rilevante a una sezione "
                      "e ogni requisito a uno stato motivato, senza inferire presenze, visite o riunioni. "
                      "Una dichiarazione di visita avvenuta è distinta da una richiesta di visita futura. "
                      "Non escludere fatti rilevanti per semplificare. Non scrivere ancora il documento."),
    )
    validate_reader(analysis.reading, parts)
    enforce_fact_policy(analysis.reading.facts, parts, policy)
    analysis.plan = complete_plan(analysis.plan, analysis.reading.facts, policy, template, job=job)
    for disposition in analysis.reading.sources:
        set_reading_state(job.evidence_items.get(source_id=disposition.part_id), disposition.status, disposition.reason)
    for item in job.evidence_items.filter(parent_source_id="", state="pending"):
        finalize_root(item)
    bundle = evidence_bundle(job)
    bundle = index_facts(bundle, analysis.reading.facts)
    progress(job, "composition", facts=len(analysis.reading.facts), inventory=inventory_counts(job))
    composition = specialist(
        job=job, key="standard_composition", stage="document_composition", schema=Composition,
        effort="medium", data={"evidence": prompt_bundle(bundle), "template": prompt_template(template),
                               "analysis": analysis.model_dump(), "language": job.revision.elaborato.language,
                               "editorial_contract": editorial_contract(job.revision)},
        instructions=("Componi il documento completo con tutte le sezioni, registri, tabelle, fotografie "
                      "pertinenti e campi tipizzati previsti. Rappresenta ogni fatto rilevante e critico del piano, "
                      "conservando esiti e condizioni. Non trasformare il programma in esecuzione o il team "
                      "in partecipanti. Ogni Claim fattuale include fact_ids dei fatti effettivamente espressi "
                      "nel blocco; un campo mancante ha fact_ids=[]. Non associare fatti al solo titolo di colonne. "
                      "Non inventare valori o firme per riempire le lacune. "
                      "Il renderer controlla il layout: restituisci soltanto il contenuto strutturato."),
    )
    editor = compose_editor(job, composition)
    from .fields import ensure_signature_slot, preserve_completed_fields

    ensure_signature_slot(editor, template, job.revision.elaborato.language)
    preserve_completed_fields(job.revision.editor_doc, editor)
    progress(job, "reviews", sections_total=len(template["sections"]), sections_completed=len(template["sections"]))
    quality = reviews(job, editor, analysis.reading.facts, policy, analysis.plan, bundle)
    if not quality["passed"]:
        editor, quality = refine_document(job, editor, analysis.reading.facts, policy, analysis.plan, bundle, quality)
    return {"editor_doc": editor, "evidence": bundle,
            "reasoning": {"facts": [f.model_dump() for f in analysis.reading.facts],
                          "plan": analysis.plan.model_dump(), "path": "STANDARD"}, "quality": quality}


def generate_document(job):
    saved = job.steps.filter(key="document_content", state="completed").first()
    if saved:
        return run_step(job=job, key=saved.key, kind=saved.kind, data=saved.input,
                        contract_version=saved.contract_version, execute=lambda step: None)
    policy = policy_for(job.revision.elaborato.document_type)
    progress(job, "inventory")
    build_inventory(job)
    # A resumed job retains the admitted route. Changing a classifier must not
    # turn already-paid STANDARD stages into a new DEEP generation.
    saved_preflight = job.workflow_state.get("preflight")
    preflight = DocumentPreflight(**saved_preflight) if saved_preflight else DocumentPreflight.inspect(job)
    progress(job, "preflight", preflight=preflight.as_dict(), inventory=inventory_counts(job))
    if preflight.path == DocumentPath.FAST_0:
        result = empty_document(job, policy)
    else:
        progress(job, "reading")
        prepare_sources(job)
        # Extracted files can be larger than their metadata suggested. Upgrade
        # the route before placing original text into a provider request.
        part_count = part_characters = 0
        for row in job.evidence_items.filter(kind="source_part").iterator(chunk_size=50):
            part_count += 1
            part_characters += len(row.payload.get("text", ""))
        if part_characters > 60000 or part_count > 24:
            preflight = DocumentPreflight(DocumentPath.DEEP, "extracted_content_requires_partitioning",
                                          preflight.counts, preflight.significant_sources,
                                          part_characters, preflight.days, preflight.policy_version)
            progress(job, "reading", preflight=preflight.as_dict())
        if preflight.path == DocumentPath.FAST_1:
            result = fast_document(job, policy)
            from .preflight import fast_review_reason
            from .intelligence_contracts import DocumentaryFact, DocumentPlan

            facts = [DocumentaryFact.model_validate(v) for v in result["reasoning"]["facts"]]
            reason = fast_review_reason(facts, result["quality"])
            if reason:
                # Keep the successful paid reading/composition. Promotion adds
                # the missing independent reviews, never repurchases that call.
                preflight = DocumentPreflight(DocumentPath.STANDARD, reason, preflight.counts,
                    preflight.significant_sources, preflight.text_characters, preflight.days, preflight.policy_version)
                progress(job, "reviews", preflight=preflight.as_dict(), promoted_from="FAST_1")
                plan = DocumentPlan.model_validate(result["quality"]["plan"])
                quality = reviews(job, result["editor_doc"], facts, policy, plan, result["evidence"])
                if not quality["passed"]:
                    result["editor_doc"], quality = refine_document(
                        job, result["editor_doc"], facts, policy, plan, result["evidence"], quality)
                result["quality"] = quality
                result["reasoning"].update(path="STANDARD", promoted_from="FAST_1", promotion_reason=reason)
        elif preflight.path == DocumentPath.STANDARD:
            result = standard_document(job, policy)
        else:
            request = {"project_id": job.revision.elaborato.project_id,
                       "period_start": str(job.revision.elaborato.period_start),
                       "period_end": str(job.revision.elaborato.period_end),
                       "context": job.revision.elaborato.context}
            facts = read_inventory(job, policy=policy.snapshot(job.revision.template_snapshot["sections"]), request=request)
            progress(job, "reconciliation", inventory=inventory_counts(job), facts=len(facts))
            reconciliation = reconcile(job, facts, policy.snapshot(job.revision.template_snapshot["sections"]))
            progress(job, "planning")
            plan = plan_document(job, facts, policy, job.revision.template_snapshot, reconciliation)
            bundle = evidence_bundle(job)
            bundle = index_facts(bundle, facts)
            progress(job, "sections")
            editor = compose_partitions(job, facts=facts, plan=plan, bundle=bundle, template=job.revision.template_snapshot)
            progress(job, "reviews")
            quality = reviews(job, editor, facts, policy, plan, bundle)
            if not quality["passed"]:
                editor, quality = refine_document(job, editor, facts, policy, plan, bundle, quality)
            result = {"editor_doc": editor, "evidence": bundle,
                      "reasoning": {"facts": [f.model_dump() for f in facts], "reconciliation": reconciliation,
                                    "plan": plan.model_dump(), "path": preflight.path}, "quality": quality}
    progress(job, "document_ready", inventory=inventory_counts(job), path=preflight.path,
             facts=len(result["reasoning"].get("facts", [])),
             sections_total=len(job.revision.template_snapshot["sections"]),
             sections_completed=len(job.revision.template_snapshot["sections"]))
    # A full content checkpoint precedes the separate local rendering stage.
    run_step(job=job, key="document_content", kind="document_content", data={"result_hash": digest(result)},
             execute=lambda step: result)
    return result
