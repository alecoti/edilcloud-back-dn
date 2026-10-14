"""Bounded, isolated MPXJ CPM worker. Never imports Django or writes application data."""

from __future__ import annotations

import json
import sys


def calculate(payload: dict) -> dict:
    import mpxj  # noqa: F401
    import jpype
    import jpype.imports  # noqa: F401
    if not jpype.isJVMStarted():
        jpype.startJVM("-Xmx256m", convertStrings=True)
    from java.io import ByteArrayInputStream, ByteArrayOutputStream
    from java.lang import Integer
    from java.time import DayOfWeek, LocalDateTime
    from org.mpxj import ConstraintType, Duration, ProjectFile, ProjectCalendarDays, Relation, RelationType, TaskMode, TimeUnit
    from org.mpxj.cpm import MicrosoftScheduler
    from org.mpxj.mspdi import MSPDIReader, MSPDIWriter
    from edilcloud.modules.projects.gantt_contract import CONSTRAINT_CODES, extract_project_xml, preserve_task_uids

    def date_value(value):
        return LocalDateTime.parse(value[:19]) if value else None

    def native_calendar(project):
        name = "EdilCloud · giorni di calendario"
        existing = next((item for item in project.getCalendars() if str(item.getName()) == name), None)
        if existing is not None:
            return existing
        calendar = project.addDefaultBaseCalendar()
        if calendar.getUniqueID() is None:
            calendar.setUniqueID(Integer(max((int(item.getUniqueID()) for item in project.getCalendars() if item.getUniqueID() is not None), default=0) + 1))
        calendar.setName(name)
        calendar.setCalendarMinutesPerDay(Integer(480))
        calendar.setCalendarMinutesPerWeek(Integer(3360))
        for day in (DayOfWeek.SATURDAY, DayOfWeek.SUNDAY):
            calendar.setWorkingDay(day, True)
            hours = calendar.getCalendarHours(day)
            hours.clear()
            hours.add(ProjectCalendarDays.DEFAULT_WORKING_MORNING)
            hours.add(ProjectCalendarDays.DEFAULT_WORKING_AFTERNOON)
        return calendar

    if payload.get("source_xml"):
        stream = ByteArrayInputStream(payload["source_xml"].encode("utf-8"))
        try:
            project = MSPDIReader().read(stream)
        finally:
            stream.close()
    else:
        project = ProjectFile()
        calendar = native_calendar(project)
        project.setDefaultCalendar(calendar)

    if project.getDefaultCalendar() is None:
        raise ValueError("Missing project calendar")
    task_by_uid = {str(task.getUniqueID()): task for task in project.getTasks()}
    reverse_constraints = {value: key for key, value in CONSTRAINT_CODES.items()}
    original_dates = {}
    editable_uids = {row["uid"] for row in payload["rows"] if row.get("editable")}
    for row in payload["rows"]:
        uid = row["uid"]
        task = task_by_uid.get(uid)
        is_new = task is None
        if is_new:
            parent = task_by_uid.get(row.get("parent_uid"))
            task = parent.addTask() if parent is not None else project.addTask()
            task.setUniqueID(Integer(int(uid)))
            if task.getID() is None:
                task.setID(Integer(max((int(item.getID()) for item in project.getTasks() if item.getID() is not None), default=0) + 1))
            task_by_uid[uid] = task
        if not row.get("editable"):
            continue
        if row.get("duration_inferred"):
            task.setCalendar(native_calendar(project))
        task.setName(row["name"])
        start, end = date_value(row["start"]), date_value(row["end"])
        original_dates[uid] = (start, end)
        dates_changed = start != task.getStart() or end != task.getFinish()
        task.setStart(start)
        task.setFinish(end)
        task.setSummary(bool(row.get("summary")))
        task.setMilestone(bool(row.get("milestone")))
        task.setConstraintType(ConstraintType.getInstance(jpype.JInt(reverse_constraints[row["constraint_type"]])))
        task.setConstraintDate(date_value(row.get("constraint_date")))
        task.setDeadline(date_value(row.get("deadline")))
        task.setTaskMode(TaskMode.MANUALLY_SCHEDULED if row.get("mode") == "manual" else TaskMode.AUTO_SCHEDULED)
        task.setActualStart(date_value(row.get("actual_start")))
        task.setActualFinish(date_value(row.get("actual_end")))
        task.setPercentageComplete(float(row.get("progress", 0)))
        if not row.get("summary") and (is_new or dates_changed or task.getDuration() is None):
            if row.get("milestone"):
                duration = Duration.getInstance(0.0, TimeUnit.MINUTES)
            else:
                calendar = task.getEffectiveCalendar()
                # Native midnight dates are inclusive, as in the existing UI.
                if row.get("duration_inferred"):
                    from java.time.temporal import ChronoUnit
                    days = int(ChronoUnit.DAYS.between(start.toLocalDate(), end.toLocalDate())) + 1
                    duration = Duration.getInstance(float(max(days, 1) * 480), TimeUnit.MINUTES)
                else:
                    duration = calendar.getWork(start, end, TimeUnit.MINUTES)
            task.setDuration(duration)
        if not row.get("summary") and not row.get("actual_start") and not row.get("progress", 0):
            # MSPDI omits zero-valued actual durations. Re-establish them even
            # when dates and duration did not change on a second calculation.
            task.setActualDuration(Duration.getInstance(0.0, TimeUnit.MINUTES))
            task.setRemainingDuration(task.getDuration())
        if row.get("actual_duration_minutes") is not None:
            task.setActualDuration(Duration.getInstance(float(row["actual_duration_minutes"]), TimeUnit.MINUTES))
        if row.get("remaining_duration_minutes") is not None:
            task.setRemainingDuration(Duration.getInstance(float(row["remaining_duration_minutes"]), TimeUnit.MINUTES))

    # The canonical graph retains original summary relations and fractional lag
    # metadata which MSPDI cannot always encode without rounding.
    canonical_graph = any("predecessors" in row for row in payload["rows"])
    if canonical_graph:
        editable_uids = set(task_by_uid)
    for uid in editable_uids:
        task = task_by_uid[uid]
        for relation in list(task.getPredecessors()):
            predecessor = relation.getPredecessorTask()
            if str(predecessor.getUniqueID()) in editable_uids:
                task.removePredecessor(predecessor, relation.getType(), relation.getLag())
    relation_types = {"e2s": RelationType.FINISH_START, "s2s": RelationType.START_START,
                      "e2e": RelationType.FINISH_FINISH, "s2e": RelationType.START_FINISH}
    links = payload["links"]
    if canonical_graph:
        links = [{"source_uid": predecessor["uid"], "target_uid": row["uid"],
                  "type": predecessor["type"], "lag_days": 0, "metadata": predecessor}
                 for row in payload["rows"] for predecessor in row.get("predecessors", [])]
    for link in links:
        source, target = task_by_uid[link["source_uid"]], task_by_uid[link["target_uid"]]
        metadata = link.get("metadata", {})
        lag_format = metadata.get("lag_format", 7)
        lag_minutes = metadata.get("lag_minutes")
        if metadata.get("origin") == "legacy-days" and lag_minutes is not None:
            lag = Duration.getInstance(float(lag_minutes), TimeUnit.MINUTES)
        elif metadata.get("origin") == "manual-precise":
            units = {"days": TimeUnit.DAYS, "hours": TimeUnit.HOURS, "minutes": TimeUnit.MINUTES,
                     "elapsed_days": TimeUnit.ELAPSED_DAYS, "elapsed_hours": TimeUnit.ELAPSED_HOURS,
                     "elapsed_minutes": TimeUnit.ELAPSED_MINUTES, "percent": TimeUnit.PERCENT, "elapsed_percent": TimeUnit.ELAPSED_PERCENT}
            lag = Duration.getInstance(float(metadata["lag_value"]), units[metadata["lag_unit"]])
        elif metadata.get("lag_percent") is not None:
            lag = Duration.getInstance(float(metadata["lag_percent"]), TimeUnit.ELAPSED_PERCENT if lag_format % 2 == 0 else TimeUnit.PERCENT)
        elif lag_minutes is not None:
            lag = Duration.getInstance(float(lag_minutes), TimeUnit.ELAPSED_MINUTES if lag_format % 2 == 0 else TimeUnit.MINUTES)
        else:
            lag = Duration.getInstance(float(link["lag_days"]), TimeUnit.DAYS)
        target.addPredecessor(Relation.Builder().predecessorTask(source).type(relation_types[link["type"]]).lag(lag))

    # MicrosoftScheduler handles ordinary percentages, but elapsed percentages
    # are ignored by some MPXJ versions. Resolve both against predecessor duration
    # here; the canonical JSON graph keeps the original percentage for later runs.
    for target in task_by_uid.values():
        for relation in list(target.getPredecessors()):
            lag = relation.getLag()
            if lag.getUnits() not in {TimeUnit.PERCENT, TimeUnit.ELAPSED_PERCENT}:
                continue
            predecessor = relation.getPredecessorTask()
            duration = predecessor.getDuration()
            if duration is None:
                raise ValueError("Percentage lag requires a known predecessor duration")
            minutes = duration.convertUnits(TimeUnit.MINUTES, project.getProjectProperties()).getDuration() * lag.getDuration() / 100.0
            resolved = Duration.getInstance(minutes, TimeUnit.ELAPSED_MINUTES if lag.getUnits() == TimeUnit.ELAPSED_PERCENT else TimeUnit.MINUTES)
            target.removePredecessor(predecessor, relation.getType(), lag)
            target.addPredecessor(Relation.Builder().predecessorTask(predecessor).type(relation.getType()).lag(resolved))

    adjacency = {}
    indegree = {uid: 0 for uid in task_by_uid}
    for uid, task in task_by_uid.items():
        for relation in task.getPredecessors():
            predecessor_uid = str(relation.getPredecessorTask().getUniqueID())
            adjacency.setdefault(predecessor_uid, []).append(uid)
            indegree[uid] += 1
    from collections import deque
    queue = deque(uid for uid, degree in indegree.items() if degree == 0)
    processed = 0
    while queue:
        processed += 1
        for uid in adjacency.get(queue.popleft(), []):
            indegree[uid] -= 1
            if indegree[uid] == 0:
                queue.append(uid)
    if processed != len(indegree):
        raise ValueError("Cyclic schedule")

    start = project.getProjectProperties().getStartDate() if payload.get("source_xml") else None
    start = start or date_value(payload["start"] + "T08:00:00")
    MicrosoftScheduler().schedule(project, start)
    risks = []
    for row in payload["rows"]:
        if row.get("mode") == "manual" and row["uid"] in original_dates:
            task = task_by_uid[row["uid"]]
            if original_dates[row["uid"]] != (task.getStart(), task.getFinish()):
                risks.append({"code": "manual-task-moved", "severity": "blocking", "ref": row["ref"],
                              "message": "Il motore sposterebbe un'attività manuale. Applicazione bloccata.", "evidence": {}})
    # Verify predecessor inequalities using MPXJ calendars, rather than calendar-day approximations.
    for uid, task in task_by_uid.items():
        if task.getStart() is None or task.getFinish() is None:
            continue
        for relation in task.getPredecessors():
            source = relation.getPredecessorTask()
            kind = str(relation.getType())
            source_date = source.getFinish() if kind in {"FS", "FF"} else source.getStart()
            target_date = task.getStart() if kind in {"FS", "SS"} else task.getFinish()
            if source_date is None:
                continue
            lag = relation.getLag()
            if lag.getUnits() == TimeUnit.PERCENT:
                predecessor_duration = source.getDuration()
                lag = Duration.getInstance(predecessor_duration.getDuration() * lag.getDuration() / 100.0, predecessor_duration.getUnits())
            required = task.getEffectiveCalendar().getDate(source_date, lag)
            if target_date.isBefore(required):
                row = next((item for item in payload["rows"] if item["uid"] == uid), {})
                risks.append({"code": "dependency-conflict", "severity": "error", "ref": row.get("ref"),
                              "message": "Il risultato non rispetta una dipendenza: applicazione bloccata.",
                              "evidence": {"source_uid": str(source.getUniqueID()), "target_uid": uid,
                                           "type": kind, "required": str(required), "actual": str(target_date)}})
    output = ByteArrayOutputStream()
    writer = MSPDIWriter()
    writer.setMicrosoftProjectCompatibleOutput(False)
    writer.write(project, output)
    source_xml = preserve_task_uids(str(output.toString("UTF-8")),
                                    {str(task.getID()): str(task.getUniqueID()) for task in project.getTasks()})
    result = extract_project_xml(source_xml)
    return {"rows": result["rows"], "risks": risks, "source_xml": source_xml, "engine": "MPXJ MicrosoftScheduler"}


if __name__ == "__main__":
    try:
        print(json.dumps(calculate(json.load(sys.stdin)), ensure_ascii=False))
    except Exception as exc:  # Diagnostics stay on the server; API responses are sanitised.
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(1)
