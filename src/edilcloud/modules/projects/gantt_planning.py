"""Versioned planning contract; no JVM, provider calls or plan writes on reads."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from edilcloud.modules.projects.gantt_contract import CONSTRAINT_LABELS, validate_schedule_rule
from edilcloud.modules.projects.models import (
    Project, ProjectActivity, ProjectScheduleLink, ProjectSchedulePlan,
    ProjectScheduleVersion, ProjectTask,
)


def local_iso(value):
    if isinstance(value, datetime) and timezone.is_aware(value):
        value = timezone.localtime(value).replace(tzinfo=None)
    return value.isoformat() if value is not None else None


def schedule_snapshot(project) -> dict:
    tasks = list(project.tasks.prefetch_related("activities").order_by("id"))
    entities = []
    for task in tasks:
        entities.append({"ref": f"task-{task.id}", "kind": "task", "id": task.id,
                         "name": task.name, "start": local_iso(task.date_start), "end": local_iso(task.date_end),
                         "progress": task.progress, "metadata": task.schedule_metadata})
        entities.extend({"ref": f"activity-{item.id}", "kind": "activity", "id": item.id,
                         "task_id": task.id, "name": item.title,
                         "start": local_iso(item.datetime_start), "end": local_iso(item.datetime_end),
                         "progress": item.progress, "metadata": item.schedule_metadata}
                        for item in task.activities.all())
    links = [{"id": link.id,
              "source": f"activity-{link.source_activity_id}" if link.source_activity_id else f"task-{link.source_task_id}",
              "target": f"activity-{link.target_activity_id}" if link.target_activity_id else f"task-{link.target_task_id}",
              "type": link.link_type, "lag_days": link.lag_days,
              "metadata": link.schedule_metadata, "origin": link.origin}
             for link in project.schedule_links.order_by("id")]
    plan = ProjectSchedulePlan.objects.filter(project=project).first()
    return {"entities": entities, "links": links, "plan": plan.metadata if plan else {},
            "plan_present": plan is not None,
            "project_start": str(project.date_start), "project_target_end": str(project.date_end),
            "original_file": plan.original_file.name if plan else "",
            "source_sha256": plan.source_sha256 if plan else ""}


def revision_for(snapshot: dict, source_xml: str = "") -> str:
    content = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + source_xml
    return hashlib.sha256(content.encode()).hexdigest()


def capture_schedule_version(*, project, profile=None, label="Prima della modifica"):
    plan = ProjectSchedulePlan.objects.filter(project=project).first()
    return ProjectScheduleVersion.objects.create(project=project, label=label, created_by=profile,
                                                snapshot=schedule_snapshot(project),
                                                source_xml=plan.source_xml if plan else "")


def prepare_professional_date_edit(*, project, profile):
    active = ProjectSchedulePlan.objects.filter(project=project).exists()
    if active:
        Project.objects.select_for_update().get(id=project.id)
        capture_schedule_version(project=project, profile=profile, label="Prima della modifica delle date")
    return active


def validate_professional_entity_dates(entity):
    if isinstance(entity, ProjectTask):
        start, end = _entity_dates({"kind": "task", "start": str(entity.date_start), "end": str(entity.date_end), "metadata": entity.schedule_metadata})
    else:
        start, end = local_iso(entity.datetime_start), local_iso(entity.datetime_end)
    for item in planning_risks([{**entity.schedule_metadata, "ref": str(entity.id), "start": start, "end": end}], {}):
        if item["code"] in {"date-constraint-conflict", "invalid-task-range"}:
            raise ValueError("Lo spostamento non rispetta il vincolo di data. Modifica il vincolo dal pannello Piano e vincoli oppure simula un piano compatibile.")
    if entity.schedule_metadata.get("actual_start") and start != entity.schedule_metadata["actual_start"]:
        raise ValueError("L'inizio effettivo registrato non può essere spostato insieme alle date previste.")


def anchor_professional_date_edit(entity):
    """Dragging an automatic ASAP task adds SNET, matching Project's date-edit semantics."""
    if entity.schedule_metadata.get("mode", "auto") == "auto" and entity.schedule_metadata.get("constraint_type", "asap") in {"asap", "alap"}:
        start = f"{entity.date_start}T08:00:00" if isinstance(entity, ProjectTask) else local_iso(entity.datetime_start)
        entity.schedule_metadata = {**entity.schedule_metadata, "constraint_type": "snet", "constraint_date": start,
                                    "constraint_precision": "day" if isinstance(entity, ProjectTask) else "minute"}
        entity.save(update_fields=("schedule_metadata", "updated_at"))


def _entity_dates(entity):
    metadata = entity["metadata"]
    if entity["kind"] == "activity":
        return entity["start"], entity["end"]
    values = []
    for field, hour in (("start", 8), ("end", 17)):
        day = entity[field]
        stored = metadata.get(f"scheduled_{field}") or metadata.get(field)
        values.append(stored if stored and stored[:10] == day else f"{day}T{hour:02d}:00:00")
    return values


def planning_rows(snapshot: dict):
    original_rows = snapshot["plan"].get("rows", [])
    rows_by_uid = {row["uid"]: {**row, "ref": f"source-{row['uid']}", "editable": False} for row in original_rows}
    ref_to_uid = {}
    parent_uids = {}
    child_task_ids = {entity.get("task_id") for entity in snapshot["entities"] if entity["kind"] == "activity"}
    for entity in snapshot["entities"]:
        uid = str(entity["metadata"].get("uid") or (1_000_000_000 + entity["id"] * 2 + (entity["kind"] == "activity")))
        ref_to_uid[entity["ref"]] = uid
        if entity["kind"] == "task":
            parent_uids[entity["id"]] = uid
    for entity in snapshot["entities"]:
        uid = ref_to_uid[entity["ref"]]
        start, end = _entity_dates(entity)
        row = {"constraint_type": "asap", "constraint_date": None, "deadline": None, "mode": "auto",
               "milestone": False, "summary": False, "outline_level": 1,
               **rows_by_uid.get(uid, {}), **entity["metadata"],
               "uid": uid, "ref": entity["ref"], "name": entity["name"], "start": start, "end": end,
               "progress": entity["progress"], "editable": True, "kind": entity["kind"]}
        if not entity["metadata"].get("uid"):
            row["summary"] = entity["kind"] == "task" and entity["id"] in child_task_ids
            row["parent_uid"] = parent_uids.get(entity.get("task_id"))
            row["outline_level"] = 2 if row["parent_uid"] else 1
            row["duration_inferred"] = True
        row["constraint_label"] = CONSTRAINT_LABELS.get(row["constraint_type"], "Vincolo non riconosciuto")
        rows_by_uid[uid] = row
    live_refs = set(ref_to_uid)
    for uid, ref in snapshot["plan"].get("entity_map", {}).items():
        if ref not in live_refs and uid in rows_by_uid:
            rows_by_uid[uid]["operational_entity_removed"] = True
    editable_uids = set(ref_to_uid.values())
    for row in rows_by_uid.values():
        if not row.get("editable"):
            continue
        row["predecessors"] = [item for item in row.get("predecessors", []) if item["uid"] not in editable_uids]
    for link in snapshot["links"]:
        target_uid, source_uid = ref_to_uid.get(link["target"]), ref_to_uid.get(link["source"])
        if target_uid in rows_by_uid and source_uid is not None:
            rows_by_uid[target_uid].setdefault("predecessors", []).append({
                **link["metadata"], "uid": source_uid, "type": link["type"],
                **({"lag_value": link["lag_days"], "lag_minutes": link["lag_days"] * (480 if rows_by_uid[target_uid].get("duration_inferred") else snapshot["plan"].get("minutes_per_day", 480)),
                     "lag_format": 7, "lag_unit": "days", "origin": "legacy-days"} if not link["metadata"] else {})})
    # Original hierarchy order is retained; synthetic rows follow their operational phase.
    return list(rows_by_uid.values()), ref_to_uid


def planning_risks(rows: list[dict], plan: dict):
    risks = []
    known_uids = {row["uid"] for row in rows if row.get("uid")}
    def risk(row, code, message, severity="warning", **evidence):
        risks.append({"code": code, "severity": severity, "ref": row.get("ref"), "uid": row.get("uid"),
                      "message": message, "evidence": evidence})
    if any(row.get("duration_inferred") for row in rows):
        risk({}, "native-duration-convention", "Le durate native seguono i giorni inclusivi del Gantt EdilCloud, con 8 ore lavorative al giorno. Verificare il calendario prima di applicare il ricalcolo.", "info")
    if plan and not plan.get("schedule_from_start", True):
        risk({}, "finish-scheduling-unsupported", "Il piano parte dalla data di fine: conservato, ma questo motore CPM calcola dalla data di inizio.", "blocking")
    if plan and not plan.get("calendars"):
        risk({}, "missing-source-calendar", "Il file non contiene calendari: l'importazione resta consultabile, ma il ricalcolo non è verificabile.", "blocking")
    for row in rows:
        rule = row.get("constraint_type", "asap")
        if row.get("operational_entity_removed"):
            risk(row, "operational-entity-removed", "La lavorazione importata è stata eliminata dal cantiere. Il file originale resta disponibile: verificare e reimportare il piano prima del ricalcolo.", "blocking")
        if rule not in CONSTRAINT_LABELS:
            risk(row, "unknown-constraint", "Tipo di vincolo originale non supportato.", "blocking", constraint_type=rule)
        if rule not in {"asap", "alap"} and not row.get("constraint_date"):
            risk(row, "missing-constraint-date", "Il vincolo richiede una data, assente nel file.", "blocking")
        if row.get("summary") and rule not in {"asap", "alap"}:
            risk(row, "summary-constraint-unsupported", "Vincolo sulla fase riepilogativa conservato; il motore non garantisce questo ricalcolo.", "blocking")
        for key, label in (("split", "suddivisa"), ("recurring", "ricorrente"), ("external", "collegata a un progetto esterno")):
            if row.get(key):
                risk(row, f"{key}-unsupported", f"Attività {label}: dati conservati, ricalcolo automatico non verificabile.", "blocking")
        if row.get("mode") == "manual":
            risk(row, "manual-scheduling", "Attività pianificata manualmente: la simulazione non deve spostarla.", "info")
        if row.get("inactive"):
            risk(row, "inactive-task", "Attività inattiva conservata nel piano originale.", "info")
        if row.get("dates_inferred"):
            risk(row, "inferred-task-dates", "Date operative provvisorie: il file originale non contiene date complete.", "blocking")
        for relation in row.get("predecessors", []):
            if relation.get("cross_project") or relation.get("type") not in {"e2s", "s2s", "e2e", "s2e"}:
                risk(row, "unresolved-source-relation", "Dipendenza esterna o non riconosciuta conservata; ricalcolo non verificabile.", "blocking", relation=relation)
            if relation.get("uid") not in known_uids:
                risk(row, "missing-predecessor", "La dipendenza riferisce un'attività non presente nel piano: verificare il file originale.", "blocking", relation=relation)
        if row.get("progress", 0) > 0 and not row.get("actual_start") and not row.get("summary") and row.get("mode") != "manual":
            risk(row, "missing-actual-start", "Attività già avviata senza data effettiva: serve un dato verificato prima del ricalcolo.", "blocking")
        if row.get("progress", 0) > 0 and row.get("actual_start") and not row.get("summary") and row.get("mode") != "manual":
            if row.get("actual_duration_minutes") is None or row.get("remaining_duration_minutes") is None:
                risk(row, "missing-actual-durations", "Indicare durata effettiva e durata residua: l'avanzamento percentuale da solo non misura il lavoro svolto.", "blocking")
        if row.get("total_slack_minutes", 0) < 0:
            risk(row, "negative-slack", "Il margine è negativo: una data richiesta non è compatibile con il piano.", "warning", total_slack_minutes=row["total_slack_minutes"])
        if row.get("baseline_end") and row.get("end") and row["end"] > row["baseline_end"]:
            risk(row, "baseline-delay", "La fine prevista supera la baseline importata.", baseline_end=row["baseline_end"], planned_end=row["end"])
        try:
            start = datetime.fromisoformat(row["start"]).replace(tzinfo=None)
            end = datetime.fromisoformat(row["end"]).replace(tzinfo=None)
        except (ValueError, TypeError, KeyError):
            risk(row, "missing-task-dates", "Date non disponibili: il task originale è conservato.", "blocking")
            continue
        if end < start:
            risk(row, "invalid-task-range", "La fine precede l'inizio. Correggere le date prima del ricalcolo.", "blocking")
        if row.get("deadline"):
            deadline = datetime.fromisoformat(row["deadline"]).replace(tzinfo=None)
            if end > deadline:
                risk(row, "deadline-exceeded", "La fine prevista supera la scadenza.", deadline=row["deadline"], planned_end=row["end"], delay_minutes=(end - deadline).total_seconds() / 60)
        if row.get("constraint_date"):
            bound = datetime.fromisoformat(row["constraint_date"]).replace(tzinfo=None)
            actual = start if rule in {"mso", "snet", "snlt"} else end
            if row.get("constraint_precision") == "day":
                actual, bound = actual.date(), bound.date()
            violated = ((rule in {"mso", "mfo"} and actual != bound) or
                        (rule in {"snet", "fnet"} and actual < bound) or
                        (rule in {"snlt", "fnlt"} and actual > bound))
            if violated:
                risk(row, "date-constraint-conflict", "Le date previste non rispettano il vincolo.", "error",
                     constraint_type=rule, constraint_date=row["constraint_date"], planned_start=row["start"], planned_end=row["end"])
    if plan.get("resource_count", 0):
        risk({}, "resource-leveling-not-included", "Risorse conservate; il CPM non risolve sovrapposizioni o livellamento delle squadre.", "warning")
    return risks


def _authorized_project(profile, project_id, *, edit=False):
    from edilcloud.modules.projects.services import get_project_with_team_context, can_edit_project
    project, membership, _ = get_project_with_team_context(profile=profile, project_id=project_id)
    if edit and not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare la pianificazione di questo progetto.")
    return project, can_edit_project(membership)


def get_project_planning(*, profile, project_id):
    project, can_edit = _authorized_project(profile, project_id)
    snapshot = schedule_snapshot(project)
    plan = ProjectSchedulePlan.objects.filter(project=project).first()
    rows, ref_to_uid = planning_rows(snapshot)
    links = []
    for link in snapshot["links"]:
        links.append({**link, "source_uid": ref_to_uid.get(link["source"]), "target_uid": ref_to_uid.get(link["target"])})
    risks = planning_risks(rows, snapshot["plan"])
    dated = [row["end"] for row in rows if row.get("end") and not row.get("inactive")]
    if dated and max(dated)[:10] > snapshot["project_target_end"]:
        risks.append({"code": "project-target-exceeded", "severity": "warning", "ref": None, "uid": None,
                      "message": "La fine prevista supera la data di fine della commessa.",
                      "evidence": {"target_end": snapshot["project_target_end"], "planned_end": max(dated)}})
    return {"contract_version": 3, "revision": revision_for(snapshot, plan.source_xml if plan else ""),
            "rows": rows, "links": links, "risks": risks, "can_edit": can_edit,
            "calendars": [{key: value for key, value in calendar.items() if key != "source_xml"}
                          for calendar in snapshot["plan"].get("calendars", [])],
            "source_name": Path(snapshot["original_file"]).name or None,
            "source_sha256": snapshot["source_sha256"] or None,
            "source_available": bool(plan and plan.original_file),
            "can_simulate": can_edit and not any(risk["severity"] == "blocking" for risk in risks),
            "versions": [{"id": item.id, "label": item.label, "created_at": item.created_at.isoformat()}
                         for item in project.schedule_versions.only("id", "label", "created_at")[:20]],
            "constraint_types": [{"value": key, "label": value} for key, value in CONSTRAINT_LABELS.items()],
            "analysis_provenance": "current-plan-rules; imported CPM values are historical, until a new simulation",
            "engine": "MPXJ MicrosoftScheduler; calendars and CPM; no resource leveling"}


@transaction.atomic
def update_project_schedule_rule(*, profile, project_id, entity_ref, payload, expected_revision):
    from edilcloud.modules.projects.gantt_schedule import resolve_project_schedule_entity
    project, _ = _authorized_project(profile, project_id, edit=True)
    Project.objects.select_for_update().get(id=project.id)
    current = get_project_planning(profile=profile, project_id=project_id)
    if expected_revision != current["revision"]:
        raise ValueError("Il piano è cambiato. Ricarica i vincoli prima di salvare.")
    entity = resolve_project_schedule_entity(project=project, entity_ref=entity_ref)
    if entity is None:
        raise ValueError("Lavorazione o fase non trovata nel progetto.")
    rule = validate_schedule_rule(payload)
    capture_schedule_version(project=project, profile=profile, label="Prima della modifica del vincolo")
    entity.schedule_metadata = {**entity.schedule_metadata, **rule,
                                "constraint_precision": "day" if len(payload.get("constraint_date") or "") == 10 else "minute"}
    entity.save(update_fields=("schedule_metadata", "updated_at"))
    ProjectSchedulePlan.objects.get_or_create(project=project)
    from edilcloud.modules.projects.services import emit_project_realtime_event
    emit_project_realtime_event(event_type="schedule.rule.updated", project_id=project.id, actor_profile=profile,
                                data={"category": "task", "entity_ref": entity_ref})
    return get_project_planning(profile=profile, project_id=project_id)


def simulate_project_schedule(*, profile, project_id, expected_revision):
    current = get_project_planning(profile=profile, project_id=project_id)
    if not current["can_edit"]:
        raise ValueError("Non hai permessi per simulare questo piano.")
    if current["revision"] != expected_revision:
        raise ValueError("Il piano è cambiato. Ricarica prima di simulare.")
    if not current["can_simulate"]:
        raise ValueError("Il piano contiene limiti o dati mancanti: controlla le segnalazioni prima di simulare.")
    project, _ = _authorized_project(profile, project_id, edit=True)
    plan = ProjectSchedulePlan.objects.filter(project=project).first()
    payload = {"source_xml": plan.source_xml if plan else "", "rows": current["rows"],
               "links": current["links"], "start": str(project.date_start)}
    worker = Path(__file__).with_name("gantt_cpm_worker.py")
    try:
        result = subprocess.run([sys.executable, "-X", "utf8", str(worker)], input=json.dumps(payload),
                                capture_output=True, text=True, encoding="utf-8", timeout=40, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("La simulazione ha superato il tempo disponibile. Il piano non è stato modificato.") from exc
    if result.returncode != 0:
        # Java diagnostics may contain paths or private task data. Do not expose them to clients.
        raise ValueError("Il motore non riesce a verificare questo piano. Nessuna data è stata modificata.")
    try:
        calculated = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.startswith("{")))
    except (ValueError, StopIteration) as exc:
        raise ValueError("Risposta del motore di pianificazione non valida.") from exc
    by_uid = {row["uid"]: row for row in calculated["rows"]}
    proposals = [{"ref": row["ref"], "name": row["name"], "before_start": row["start"], "before_end": row["end"],
                  "start": by_uid[row["uid"]]["start"], "end": by_uid[row["uid"]]["end"],
                  "critical": by_uid[row["uid"]]["critical"], "total_slack_minutes": by_uid[row["uid"]]["total_slack_minutes"]}
                 for row in current["rows"] if row.get("editable") and row["uid"] in by_uid]
    evaluated = [{**row, **by_uid.get(row["uid"], {}), "predecessors": row.get("predecessors", [])} for row in current["rows"]]
    risks = planning_risks(evaluated, schedule_snapshot(project)["plan"])
    ends = [row["end"] for row in evaluated if row.get("end") and not row.get("inactive")]
    if ends and max(ends)[:10] > str(project.date_end):
        risks.append({"code": "project-target-exceeded", "severity": "warning", "ref": None, "uid": None,
                      "message": "La fine simulata supera la data di fine della commessa.",
                      "evidence": {"target_end": str(project.date_end), "planned_end": max(ends)}})
    risks.extend(calculated.get("risks", []))
    return {"revision": current["revision"], "proposals": proposals, "risks": risks,
            "can_apply": not any(item["severity"] in {"blocking", "error"} for item in risks),
            "engine": calculated.get("engine", "MPXJ MicrosoftScheduler"),
            "rows": evaluated, "source_xml": calculated["source_xml"]}


@transaction.atomic
def apply_project_schedule_simulation(*, profile, project_id, expected_revision):
    project, _ = _authorized_project(profile, project_id, edit=True)
    # Recompute server-side; clients cannot submit arbitrary dates or forged simulation results.
    calculated = simulate_project_schedule(profile=profile, project_id=project_id, expected_revision=expected_revision)
    Project.objects.select_for_update().get(id=project.id)
    current = get_project_planning(profile=profile, project_id=project_id)
    if current["revision"] != calculated["revision"]:
        raise ValueError("Il piano è cambiato durante la simulazione. Ripeti la verifica.")
    if not calculated["can_apply"]:
        raise ValueError("La simulazione contiene conflitti: nessuna data è stata modificata.")
    capture_schedule_version(project=project, profile=profile, label="Prima del ricalcolo CPM")
    for proposal in calculated["proposals"]:
        kind, raw_id = proposal["ref"].split("-", 1)
        start = datetime.fromisoformat(proposal["start"])
        end = datetime.fromisoformat(proposal["end"])
        if kind == "task":
            entity = ProjectTask.objects.get(project=project, id=int(raw_id))
            entity.date_start, entity.date_end = start.date(), end.date()
        else:
            entity = ProjectActivity.objects.get(task__project=project, id=int(raw_id))
            entity.datetime_start = timezone.make_aware(start) if timezone.is_naive(start) else start
            entity.datetime_end = timezone.make_aware(end) if timezone.is_naive(end) else end
        entity.schedule_metadata = {**entity.schedule_metadata, "scheduled_start": proposal["start"], "scheduled_end": proposal["end"]}
        entity.save()
    plan, _ = ProjectSchedulePlan.objects.get_or_create(project=project)
    plan.source_xml = calculated["source_xml"]
    from edilcloud.modules.projects.gantt_contract import extract_project_xml
    plan.metadata = extract_project_xml(plan.source_xml)
    calculated_by_uid = {row["uid"]: row for row in calculated["rows"]}
    for row in plan.metadata["rows"]:
        previous = calculated_by_uid.get(row["uid"], {})
        for key in ("predecessors", "split", "recurring", "external", "dates_inferred"):
            if key in previous:
                row[key] = previous[key]
    plan.metadata["entity_map"] = {row["uid"]: row["ref"] for row in calculated["rows"] if row.get("editable")}
    plan.save()
    from edilcloud.modules.projects.services import emit_project_realtime_event
    emit_project_realtime_event(event_type="schedule.plan.recalculated", project_id=project.id, actor_profile=profile,
                                data={"category": "task", "entity_count": len(calculated["proposals"])})
    return get_project_planning(profile=profile, project_id=project_id)


@transaction.atomic
def restore_project_schedule_version(*, profile, project_id, version_id, expected_revision):
    project, _ = _authorized_project(profile, project_id, edit=True)
    Project.objects.select_for_update().get(id=project.id)
    current = get_project_planning(profile=profile, project_id=project_id)
    if current["revision"] != expected_revision:
        raise ValueError("Il piano è cambiato. Ricarica prima di ripristinare.")
    version = project.schedule_versions.filter(id=version_id).first()
    if version is None:
        raise ValueError("Versione non trovata nel progetto.")
    snapshot = schedule_snapshot(project)
    if {row["ref"] for row in snapshot["entities"]} != {row["ref"] for row in version.snapshot["entities"]}:
        raise ValueError("Sono cambiate le lavorazioni del piano: il backup resta disponibile, ma non è sicuro ripristinare automaticamente.")
    capture_schedule_version(project=project, profile=profile, label="Prima del ripristino della pianificazione")
    for row in version.snapshot["entities"]:
        if row["kind"] == "task":
            entity = ProjectTask.objects.get(project=project, id=row["id"])
            entity.date_start, entity.date_end = row["start"], row["end"]
        else:
            entity = ProjectActivity.objects.get(task__project=project, id=row["id"])
            entity.datetime_start = timezone.make_aware(datetime.fromisoformat(row["start"]))
            entity.datetime_end = timezone.make_aware(datetime.fromisoformat(row["end"]))
        entity.schedule_metadata = row["metadata"]
        entity.save()
    project.schedule_links.all().delete()
    for link in version.snapshot["links"]:
        endpoints = {}
        for side in ("source", "target"):
            kind, raw_id = link[side].split("-")
            endpoints[f"{side}_{kind}_id"] = int(raw_id)
        ProjectScheduleLink.objects.create(project=project, **endpoints, link_type=link["type"], lag_days=link["lag_days"],
                                           origin=link["origin"], schedule_metadata=link["metadata"])
    plan, _ = ProjectSchedulePlan.objects.get_or_create(project=project)
    plan.source_xml = version.source_xml
    plan.metadata = version.snapshot["plan"]
    plan.original_file.name = version.snapshot.get("original_file", "")
    plan.source_sha256 = version.snapshot.get("source_sha256", "")
    plan.save()
    if not version.snapshot.get("plan_present", bool(version.source_xml)):
        plan.delete()
    from edilcloud.modules.projects.services import emit_project_realtime_event
    emit_project_realtime_event(event_type="schedule.plan.restored", project_id=project.id, actor_profile=profile,
                                data={"category": "task", "version_id": version_id})
    return get_project_planning(profile=profile, project_id=project_id)
