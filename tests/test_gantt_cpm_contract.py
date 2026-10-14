"""Scheduling outcomes, including cases silently misinterpreted by MPXJ alone."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


def row(uid, **changes):
    return {"uid": str(uid), "ref": f"activity-{uid}", "name": f"Task {uid}",
            "start": "2026-10-12T08:00:00", "end": "2026-10-12T17:00:00",
            "constraint_type": "asap", "constraint_date": None, "deadline": None,
            "mode": "auto", "editable": True, "summary": False, "progress": 0,
            "duration_inferred": True, "predecessors": [], **changes}


def run(rows, source_xml=""):
    worker = Path(__file__).parents[1] / "src/edilcloud/modules/projects/gantt_cpm_worker.py"
    response = subprocess.run([sys.executable, "-X", "utf8", str(worker)],
                              input=json.dumps({"start": "2026-10-12", "rows": rows, "links": [], "source_xml": source_xml}),
                              capture_output=True, text=True, encoding="utf-8", timeout=40)
    if response.returncode:
        raise ValueError(response.stderr)
    result = json.loads(response.stdout.strip().splitlines()[-1])
    return {item["uid"]: item for item in result["rows"]}, result


@pytest.mark.parametrize("kind, expected_start, expected_end", [
    ("e2s", "2026-10-13T08:00:00", "2026-10-13T17:00:00"),
    ("s2s", "2026-10-12T08:00:00", "2026-10-12T17:00:00"),
    ("e2e", "2026-10-12T08:00:00", "2026-10-12T17:00:00"),
    # SF can place the predecessor-completing shift before the project start.
    # At a non-working boundary, 17:00 and the next 08:00 are the same working instant.
    ("s2e", "2026-10-11T08:00:00", "2026-10-11T17:00:00"),
])
def test_four_dependency_types_are_verified_after_cpm(kind, expected_start, expected_end):
    rows, result = run([row(1), row(2, predecessors=[{"uid": "1", "type": kind, "lag_minutes": 0}])])
    assert rows["2"]["start"] == expected_start
    assert rows["2"]["end"] == expected_end
    if kind == "s2e":
        # MPXJ's zero-lag SF result can violate the actual timestamp inequality.
        # Keep the independent audit: the application must refuse this result.
        assert any(item["code"] == "dependency-conflict" for item in result["risks"])
    else:
        assert not result["risks"]


@pytest.mark.parametrize("kind, bound, expected_start, expected_end", [
    ("asap", None, "2026-10-12T08:00:00", "2026-10-12T17:00:00"),
    ("alap", None, "2026-10-14T08:00:00", "2026-10-14T17:00:00"),
    ("mso", "2026-10-14T08:00:00", "2026-10-14T08:00:00", "2026-10-14T17:00:00"),
    ("mfo", "2026-10-14T17:00:00", "2026-10-14T08:00:00", "2026-10-14T17:00:00"),
    ("snet", "2026-10-14T08:00:00", "2026-10-14T08:00:00", "2026-10-14T17:00:00"),
    ("snlt", "2026-10-14T08:00:00", "2026-10-12T08:00:00", "2026-10-12T17:00:00"),
    ("fnet", "2026-10-14T17:00:00", "2026-10-14T08:00:00", "2026-10-14T17:00:00"),
    ("fnlt", "2026-10-14T17:00:00", "2026-10-12T08:00:00", "2026-10-12T17:00:00"),
])
def test_eight_constraint_types_have_expected_scheduling_outcomes(kind, bound, expected_start, expected_end):
    # A separate fixed task sets the project finish so ALAP can be distinguished from ASAP.
    rows, result = run([row(1, constraint_type=kind, constraint_date=bound),
                        row(2, constraint_type="mso", constraint_date="2026-10-14T08:00:00")])
    assert rows["1"]["start"] == expected_start
    assert rows["1"]["end"] == expected_end
    assert not result["risks"]


@pytest.mark.parametrize("unit, value, expected", [
    ("hours", 0.5, "2026-10-13T08:30:00"),
    ("hours", -0.5, "2026-10-12T16:30:00"),
    ("percent", 50, "2026-10-13T13:00:00"),
    ("elapsed_percent", 500, "2026-10-14T09:00:00"),
    ("elapsed_hours", 16.5, "2026-10-13T09:30:00"),
])
def test_fractional_negative_and_percent_lags_survive_repeated_calculation(unit, value, expected):
    predecessor = {"uid": "1", "type": "e2s", "origin": "manual-precise", "lag_value": value, "lag_unit": unit}
    inputs = [row(1), row(2, predecessors=[predecessor])]
    rows, result = run(inputs)
    assert rows["2"]["start"] == expected
    assert not result["risks"]
    # The source XML can round/normalise lag units. The canonical graph remains authoritative.
    repeated, second = run(inputs, result["source_xml"])
    assert repeated["2"]["start"] == expected
    assert {item["uid"] for item in second["rows"]} == {"1", "2"}
    assert not second["risks"]


def test_explicit_cycle_is_rejected_instead_of_producing_a_partial_plan():
    with pytest.raises(ValueError, match="Cyclic"):
        run([row(1, predecessors=[{"uid": "2", "type": "e2s"}]), row(2, predecessors=[{"uid": "1", "type": "e2s"}])])


def calendar_xml():
    days = ''.join(f'<WeekDay><DayType>{day}</DayType><DayWorking>{int(2 <= day <= 6)}</DayWorking>' +
                   ('<WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime><ToTime>12:00:00</ToTime></WorkingTime><WorkingTime><FromTime>13:00:00</FromTime><ToTime>17:00:00</ToTime></WorkingTime></WorkingTimes>' if 2 <= day <= 6 else '') + '</WeekDay>' for day in range(1, 8))
    tasks = ''.join(f'<Task><UID>{uid}</UID><ID>{uid}</ID><Name>Task {uid}</Name><Type>1</Type><Summary>0</Summary><OutlineLevel>1</OutlineLevel><Start>2026-10-12T08:00:00</Start><Finish>2026-10-12T17:00:00</Finish><Duration>PT8H0M0S</Duration><DurationFormat>7</DurationFormat><ConstraintType>0</ConstraintType><PercentComplete>0</PercentComplete><CalendarUID>1</CalendarUID></Task>' for uid in (1, 2))
    return ('<Project xmlns="http://schemas.microsoft.com/project"><Name>Calendar QA</Name><ScheduleFromStart>1</ScheduleFromStart><StartDate>2026-10-12T08:00:00</StartDate><CalendarUID>1</CalendarUID><MinutesPerDay>480</MinutesPerDay><MinutesPerWeek>2400</MinutesPerWeek><Calendars><Calendar><UID>1</UID><Name>Settimana e festività</Name><IsBaseCalendar>1</IsBaseCalendar><BaseCalendarUID>-1</BaseCalendarUID><WeekDays>' + days + '</WeekDays><Exceptions><Exception><Name>Chiusura cantiere</Name><EnteredByOccurrences>0</EnteredByOccurrences><TimePeriod><FromDate>2026-10-13T00:00:00</FromDate><ToDate>2026-10-13T23:59:00</ToDate></TimePeriod><DayWorking>0</DayWorking></Exception></Exceptions></Calendar></Calendars><Tasks>' + tasks + '</Tasks></Project>')


def test_imported_calendar_exception_is_used_for_working_time_dependencies():
    rows, result = run([row(1, duration_inferred=False), row(2, duration_inferred=False,
                       predecessors=[{"uid": "1", "type": "e2s", "lag_minutes": 0}])], calendar_xml())
    assert rows["2"]["start"] == "2026-10-14T08:00:00"
    assert not result["risks"]


def test_native_tasks_keep_weekend_semantics_when_added_to_imported_five_day_calendar():
    inputs = [row(1, duration_inferred=False), row(2, duration_inferred=False),
              row(3, constraint_type="snet", constraint_date="2026-10-16T08:00:00"),
              row(4, predecessors=[{"uid": "3", "type": "e2s", "lag_minutes": 0}])]
    rows, result = run(inputs, calendar_xml())
    assert rows["4"]["start"] == "2026-10-17T08:00:00"
    assert not result["risks"]
