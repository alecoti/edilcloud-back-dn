"""Read-only service benchmark. Pipe into manage.py shell on the target instance."""

import json
import os
import time

from django.db import connection
from django.test.utils import CaptureQueriesContext

from edilcloud.modules.projects import services
from edilcloud.modules.workspaces.models import Profile

profile = Profile.objects.get(id=int(os.environ.get("PERF_PROFILE_ID", "53")))
project_id = int(os.environ.get("PERF_PROJECT_ID", "20"))
cases = {
    "tasks": lambda: services.list_project_tasks(profile=profile, project_id=project_id, compact=True),
    "overview": lambda: services.get_project_overview(profile=profile, project_id=project_id, compact=True),
    "gantt": lambda: services.list_project_gantt(profile=profile, project_id=project_id, compact=True),
    "feed": lambda: services.list_project_feed(profile=profile, project_id=project_id, limit=12, lightweight=True),
}
for name, run in cases.items():
    for iteration in range(3):
        started = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            data = run()
        print(json.dumps({
            "name": name, "iteration": iteration,
            "ms": round((time.perf_counter() - started) * 1000),
            "queries": len(queries),
            "sql_ms": round(sum(float(q["time"]) for q in queries) * 1000),
            "json_bytes": len(json.dumps(data, default=str).encode()),
        }))
