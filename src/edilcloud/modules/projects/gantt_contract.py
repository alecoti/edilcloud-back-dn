"""Microsoft Project metadata shared by imports, planning and the isolated JVM worker."""

from __future__ import annotations

from datetime import datetime
import math
import re
from xml.etree import ElementTree as ET


CONSTRAINT_CODES = {0: "asap", 1: "alap", 2: "mso", 3: "mfo", 4: "snet", 5: "snlt", 6: "fnet", 7: "fnlt"}
CONSTRAINT_LABELS = {
    "asap": "Appena possibile", "alap": "Più tardi possibile",
    "snet": "Inizia non prima del", "snlt": "Inizia non oltre il",
    "fnet": "Finisce non prima del", "fnlt": "Finisce non oltre il",
    "mso": "Deve iniziare il", "mfo": "Deve finire il",
}
LINK_CODES = {0: "e2e", 1: "e2s", 2: "s2e", 3: "s2s"}
LAG_UNITS = {3: "minutes", 4: "elapsed_minutes", 5: "hours", 6: "elapsed_hours",
             7: "days", 8: "elapsed_days", 9: "weeks", 10: "elapsed_weeks",
             11: "months", 12: "elapsed_months", 19: "percent", 20: "elapsed_percent"}


def xml_text(node, name: str, default: str = "") -> str:
    child = next((item for item in node if item.tag.rsplit("}", 1)[-1] == name), None)
    return (child.text or "").strip() if child is not None else default


def xml_children(node, name: str):
    return [item for item in node if item.tag.rsplit("}", 1)[-1] == name]


def preserve_task_uids(source_xml: str, uid_by_id: dict[str, str]) -> str:
    """MPXJ's MSPDI writer maps UIDs. Restore stable IDs and every task reference."""
    root = ET.fromstring(source_xml)
    containers = xml_children(root, "Tasks")
    replacements = {}
    for task in xml_children(containers[0], "Task") if containers else []:
        current = xml_text(task, "UID")
        stable = uid_by_id.get(xml_text(task, "ID"))
        if stable is not None:
            replacements[current] = stable
    if len(set(replacements.values())) != len(replacements):
        raise ValueError("Task identifiers are not unique")
    for task in xml_children(containers[0], "Task") if containers else []:
        for item in xml_children(task, "UID"):
            item.text = replacements.get(item.text, item.text)
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] in {"PredecessorUID", "TaskUID"}:
            item.text = replacements.get(item.text, item.text)
    return ET.tostring(root, encoding="unicode")


def int_value(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def iso_datetime(value: str | None) -> str | None:
    if not value or value == "NA":
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def duration_minutes(value: str) -> float | None:
    match = re.fullmatch(r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", value or "")
    if not match:
        return None
    days, hours, minutes, seconds = (float(item or 0) for item in match.groups())
    return days * 1440 + hours * 60 + minutes + seconds / 60


def extract_project_xml(source_xml: str) -> dict:
    root = ET.fromstring(source_xml)
    task_container = xml_children(root, "Tasks")
    rows = []
    parents: list[tuple[int, str]] = []
    for task in xml_children(task_container[0], "Task") if task_container else []:
        uid, name = xml_text(task, "UID"), xml_text(task, "Name")
        if not uid or uid == "0" or not name:
            continue
        level = int_value(xml_text(task, "OutlineLevel"), 1)
        while parents and parents[-1][0] >= level:
            parents.pop()
        constraint_code = int_value(xml_text(task, "ConstraintType"))
        baseline = next((item for item in xml_children(task, "Baseline") if xml_text(item, "Number", "0") == "0"), None)
        row = {
            "uid": uid, "name": name, "outline_level": level,
            "parent_uid": parents[-1][1] if parents else None,
            "summary": xml_text(task, "Summary") == "1",
            "start": iso_datetime(xml_text(task, "Start")), "end": iso_datetime(xml_text(task, "Finish")),
            "constraint_type": CONSTRAINT_CODES.get(constraint_code, f"unknown-{constraint_code}"),
            "constraint_date": iso_datetime(xml_text(task, "ConstraintDate")),
            "deadline": iso_datetime(xml_text(task, "Deadline")),
            "calendar_uid": xml_text(task, "CalendarUID") or None,
            "mode": "manual" if xml_text(task, "Manual") == "1" else "auto",
            "milestone": xml_text(task, "Milestone") == "1",
            "inactive": xml_text(task, "Active", "1") == "0",
            "external": xml_text(task, "ExternalTask") == "1",
            "recurring": xml_text(task, "IsRecurring") == "1" or bool(xml_children(task, "RecurringTask")),
            "split": bool(xml_children(task, "SplitParts")),
            "duration": xml_text(task, "Duration"), "duration_format": int_value(xml_text(task, "DurationFormat"), 7),
            "progress": int_value(xml_text(task, "PercentComplete")),
            "actual_start": iso_datetime(xml_text(task, "ActualStart")),
            "actual_end": iso_datetime(xml_text(task, "ActualFinish")),
            "actual_duration_minutes": duration_minutes(xml_text(task, "ActualDuration")),
            "remaining_duration_minutes": duration_minutes(xml_text(task, "RemainingDuration")),
            "baseline_start": iso_datetime(xml_text(baseline, "Start")) if baseline is not None else None,
            "baseline_end": iso_datetime(xml_text(baseline, "Finish")) if baseline is not None else None,
            "critical": xml_text(task, "Critical") == "1",
            "total_slack_minutes": int_value(xml_text(task, "TotalSlack")) / 10,
            "free_slack_minutes": int_value(xml_text(task, "FreeSlack")) / 10,
            "predecessors": [],
        }
        for predecessor in xml_children(task, "PredecessorLink"):
            lag_format = int_value(xml_text(predecessor, "LagFormat"), 7)
            raw_lag = int_value(xml_text(predecessor, "LinkLag"))
            is_percent = lag_format % 16 in {3, 4} and lag_format >= 19
            row["predecessors"].append({
                "uid": xml_text(predecessor, "PredecessorUID"),
                "type": LINK_CODES.get(int_value(xml_text(predecessor, "Type"), 1), "unknown"),
                "lag_value": raw_lag if is_percent else raw_lag / 10,
                "lag_unit": ("elapsed_percent" if lag_format % 2 == 0 else "percent") if is_percent else LAG_UNITS.get(lag_format % 16 if lag_format >= 35 else lag_format, f"format-{lag_format}"),
                "lag_minutes": None if is_percent else raw_lag / 10,
                "lag_percent": raw_lag if is_percent else None,
                "lag_format": lag_format,
                "cross_project": xml_text(predecessor, "CrossProject") == "1",
            })
        rows.append(row)
        if row["summary"]:
            parents.append((level, uid))
    calendars = []
    calendar_container = xml_children(root, "Calendars")
    for calendar in xml_children(calendar_container[0], "Calendar") if calendar_container else []:
        weekdays = []
        for container in xml_children(calendar, "WeekDays"):
            for day in xml_children(container, "WeekDay"):
                hours = []
                for times in xml_children(day, "WorkingTimes"):
                    hours += [{"from": xml_text(item, "FromTime"), "to": xml_text(item, "ToTime")}
                              for item in xml_children(times, "WorkingTime")]
                weekdays.append({"day": int_value(xml_text(day, "DayType")),
                                 "working": xml_text(day, "DayWorking") == "1", "hours": hours})
        exceptions = xml_children(calendar, "Exceptions")
        calendars.append({"uid": xml_text(calendar, "UID"), "name": xml_text(calendar, "Name"),
                          "base_uid": xml_text(calendar, "BaseCalendarUID") or None,
                          "weekdays": weekdays,
                          "exception_count": len(xml_children(exceptions[0], "Exception")) if exceptions else 0,
                          "source_xml": ET.tostring(calendar, encoding="unicode")})
    return {
        "contract_version": 3, "rows": rows, "calendars": calendars,
        "minutes_per_day": int_value(xml_text(root, "MinutesPerDay"), 480),
        "schedule_from_start": xml_text(root, "ScheduleFromStart", "1") == "1",
        "start": iso_datetime(xml_text(root, "StartDate")), "end": iso_datetime(xml_text(root, "FinishDate")),
        "calendar_uid": xml_text(root, "CalendarUID") or None,
        "resource_count": len(xml_children(xml_children(root, "Resources")[0], "Resource")) if xml_children(root, "Resources") else 0,
    }


def validate_schedule_rule(payload: dict) -> dict:
    constraint = payload.get("constraint_type", "asap")
    if constraint not in CONSTRAINT_LABELS:
        raise ValueError("Tipo di vincolo di data non valido.")
    constraint_date = iso_datetime(payload.get("constraint_date"))
    if constraint not in {"asap", "alap"} and not constraint_date:
        raise ValueError("Questo vincolo richiede una data valida.")
    deadline = iso_datetime(payload.get("deadline"))
    if payload.get("deadline") and not deadline:
        raise ValueError("Scadenza non valida.")
    mode = payload.get("mode", "auto")
    if mode not in {"auto", "manual"}:
        raise ValueError("Modalità di pianificazione non valida.")
    result = {"constraint_type": constraint,
            "constraint_date": constraint_date if constraint not in {"asap", "alap"} else None,
            "deadline": deadline, "mode": mode}
    for name in ("actual_start", "actual_end"):
        if name in payload:
            result[name] = iso_datetime(payload[name])
            if payload[name] and not result[name]:
                raise ValueError("Data effettiva non valida.")
    for name in ("actual_duration_minutes", "remaining_duration_minutes"):
        if name in payload:
            value = payload[name]
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("La durata effettiva o residua deve essere un numero di minuti non negativo.")
            result[name] = value
    if result.get("actual_start") and result.get("actual_end") and result["actual_end"] < result["actual_start"]:
        raise ValueError("La fine effettiva precede l'inizio effettivo.")
    if result.get("actual_end") and result.get("remaining_duration_minutes", 0):
        raise ValueError("Una lavorazione terminata non può avere durata residua.")
    return result


def precise_lag_metadata(value: float, unit: str) -> dict:
    if unit not in {"days", "hours", "minutes", "elapsed_days", "elapsed_hours", "elapsed_minutes", "percent", "elapsed_percent"}:
        raise ValueError("Unità dell'anticipo o ritardo non valida.")
    if not math.isfinite(value) or abs(value) > 36600:
        raise ValueError("Anticipo o ritardo fuori dall'intervallo consentito.")
    return {"lag_value": value, "lag_unit": unit, "precision": "exact", "origin": "manual-precise"}
