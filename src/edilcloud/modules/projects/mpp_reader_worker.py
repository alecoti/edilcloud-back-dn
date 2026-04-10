from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_LINK_TYPE_MAP = {
    "FS": "e2s",
    "SS": "s2s",
    "FF": "e2e",
    "SF": "s2e",
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_int(value: Any) -> int | None:
    try:
        return int(float(_clean_text(value)))
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    normalized = _clean_text(value).replace("%", "").replace(",", ".")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _clamp_progress(value: float | int | None) -> int:
    try:
        numeric = int(round(float(value or 0)))
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(100, numeric))


def _to_iso_date(value: Any) -> str | None:
    normalized = _clean_text(value)
    if not normalized:
        return None
    if "T" in normalized:
        return normalized.split("T", 1)[0]
    if " " in normalized:
        return normalized.split(" ", 1)[0]
    return normalized


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        normalized = _clean_text(value)
        if normalized:
            return normalized
    return ""


def _read_task_text_fields(task) -> list[str]:
    values: list[str] = []
    for field_index in (1, 2, 3):
        try:
            values.append(_clean_text(task.getText(field_index)))
        except Exception:  # noqa: BLE001
            values.append("")
    return values


def _lag_to_days(lag_value, minutes_per_day: int) -> int:
    if lag_value is None:
        return 0
    duration = _parse_float(lag_value.getDuration())
    if duration in {None, 0}:
        return 0

    units = _clean_text(lag_value.getUnits()).lower()
    hours_per_day = max(minutes_per_day / 60, 1)
    if units in {"d", "day", "days"}:
        value = duration
    elif units in {"h", "hr", "hour", "hours"}:
        value = duration / hours_per_day
    elif units in {"m", "min", "minute", "minutes"}:
        value = duration / max(minutes_per_day, 1)
    elif units in {"w", "wk", "week", "weeks"}:
        value = duration * 5
    elif units in {"mo", "month", "months"}:
        value = duration * 20
    elif units in {"y", "yr", "year", "years"}:
        value = duration * 240
    else:
        value = duration

    if 0 < abs(value) < 0.5:
        return 1 if value > 0 else -1
    return int(round(value))


def _read_project(path: Path) -> tuple[list[dict[str, Any]], int]:
    try:
        import mpxj  # noqa: F401
        import jpype
        import jpype.imports  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Supporto MPP non disponibile sul backend.") from exc

    if not jpype.isJVMStarted():
        jpype.startJVM(convertStrings=True)

    from org.mpxj.reader import UniversalProjectReader

    project_file = UniversalProjectReader().read(str(path))
    if project_file is None:
        raise RuntimeError(
            "Impossibile leggere il file MPP. Verifica che non sia corrotto o protetto da password."
        )

    minutes_per_day = 480
    try:
        properties = project_file.getProjectProperties()
        if properties is not None:
            minutes_per_day = _parse_int(properties.getMinutesPerDay()) or 480
    except Exception:  # noqa: BLE001
        minutes_per_day = 480

    raw_tasks: list[dict[str, Any]] = []
    tasks = project_file.getTasks()
    if tasks is None:
        return raw_tasks, minutes_per_day

    for index in range(tasks.size()):
        task = tasks.get(index)
        uid = _clean_text(task.getUniqueID() or task.getID())
        name = _clean_text(task.getName())
        if not uid or uid == "0" or not name:
            continue

        predecessors: list[list[Any]] = []
        task_predecessors = task.getPredecessors()
        if task_predecessors:
            for rel_index in range(task_predecessors.size()):
                relation = task_predecessors.get(rel_index)
                predecessor_task = relation.getPredecessorTask()
                predecessor_uid = ""
                if predecessor_task is not None:
                    predecessor_uid = _clean_text(predecessor_task.getUniqueID() or predecessor_task.getID())
                if not predecessor_uid:
                    continue
                relation_type = _clean_text(relation.getType()).upper()
                link_type = PROJECT_LINK_TYPE_MAP.get(relation_type, "e2s")
                lag_days = _lag_to_days(relation.getLag(), minutes_per_day)
                predecessors.append([predecessor_uid, link_type, lag_days])

        raw_tasks.append(
            {
                "uid": uid,
                "name": name,
                "summary": _clean_text(task.getSummary()).lower() == "true",
                "outline_level": _parse_int(task.getOutlineLevel()) or 1,
                "start": _to_iso_date(task.getStart()),
                "end": _to_iso_date(task.getFinish()),
                "progress": _clamp_progress(_parse_float(task.getPercentageComplete()) or 0),
                "note": _clean_text(task.getNotes()),
                "company": _first_non_empty(_read_task_text_fields(task)),
                "predecessors": predecessors,
            }
        )

    return raw_tasks, minutes_per_day


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python -m edilcloud.modules.projects.mpp_reader_worker <path-to-mpp>", file=sys.stderr)
        return 2

    mpp_path = Path(argv[1])
    if not mpp_path.exists():
        print("File MPP non trovato.", file=sys.stderr)
        return 1

    try:
        raw_tasks, minutes_per_day = _read_project(mpp_path)
    except Exception as exc:  # noqa: BLE001
        print(_clean_text(exc) or "Errore durante lettura file MPP.", file=sys.stderr)
        return 1

    payload = {
        "minutes_per_day": minutes_per_day,
        "raw_tasks": raw_tasks,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
