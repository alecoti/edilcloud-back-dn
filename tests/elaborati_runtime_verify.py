"""Read frozen synthetic PDFs through both real APIs after signature removal.

Requires the integration launcher and its owned context. This is not a load
test. The single AI action request is rejected by the local QA proxy before
it reaches either backend; database counters prove that it queued no work.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import uuid

import psycopg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-batches", action="store_true")
    args = parser.parse_args()
    task = Path(__file__).resolve().parents[2]
    context = json.loads((task / "runtime/context.json").read_text(encoding="utf-8"))
    database = context["database"]
    if not context.get("synthetic_only") or not re.fullmatch(r"edilcloud_elaborati_qa_[0-9a-f]{12}", database):
        raise SystemExit("An owned synthetic QA context is required.")
    revisions = dict(context["revisions"])
    if args.all_batches:
        for batch, entries in context.get("qa_cases", {}).items():
            revisions.update({f"{batch}/{name}": revision for name, revision in entries.items()})
    opener = build_opener(ProxyHandler({}))

    def call(base, path, *, token=None, data=None, method="GET"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "JWT " + token
        request = Request(base + path, headers=headers, method=method,
                          data=None if data is None else json.dumps(data).encode())
        try:
            with opener.open(request, timeout=20) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as response:
            return response.code, dict(response.headers), response.read()

    url = "postgresql://edilcloud_rust_parity:local-parity-only@127.0.0.1:55432/" + database
    with psycopg.connect(url) as db:
        expected = {str(row[0]): row[1] for row in db.execute(
            "SELECT id,pdf_hash FROM elaborati_elaboratorevision").fetchall()}
        before_usage = db.execute("SELECT count(*) FROM elaborati_documentaiusage").fetchone()[0]
        before_jobs = db.execute("SELECT count(*) FROM elaborati_documentjob").fetchone()[0]
    report = {"synthetic_only": True, "after_personal_signature_removal": True, "cases": []}
    tokens = {}
    for backend, base in (("django", "http://127.0.0.1:8013"), ("rust", "http://127.0.0.1:8014")):
        status, _, raw = call(base, "/api/v1/auth/login", method="POST", data={
            "username_or_email": "elaborati.qa@example.com", "password": "local-qa-elaborati"})
        assert status == 200, (backend, status)
        token = json.loads(raw)["token"]
        tokens[backend] = token
        status, _, raw = call(base, "/api/v1/elaborati/signature", token=token)
        assert status == 200 and json.loads(raw) == {
            "enrolled": False, "strokes": [], "fingerprint": None}, (backend, status)
        for name, revision in revisions.items():
            assert expected[revision], "Every seeded revision must first be published."
            prefix = f"/api/v1/elaborati/revisions/{revision}/pdf"
            status, headers, body = call(base, prefix +
                f"?purpose=display&hash={expected[revision]}&download=true", token=token)
            bad, _, _ = call(base, prefix + "?hash=" + "0" * 64, token=token)
            purpose, _, _ = call(base, prefix + "?purpose=unknown", token=token)
            row = {"api_backend": backend, "created_by_case": name, "revision": revision,
                   "status": status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                   "stored_hash": expected[revision],
                   "cache_control": headers.get("Cache-Control", headers.get("cache-control")),
                   "wrong_hash_status": bad, "unknown_purpose_status": purpose}
            assert status == 200 and row["sha256"] == expected[revision], row
            assert bad == 409 and purpose == 400 and row["cache_control"] == "private, no-store", row
            report["cases"].append(row)
    context_status, _, active_raw = call("http://127.0.0.1:8003", "/_qa/context")
    assert context_status == 200
    active_revision = json.loads(active_raw)["revisions"]["flutter_rust"]
    status, _, _ = call("http://127.0.0.1:8003",
        f"/api/v1/elaborati/revisions/{active_revision}/actions",
        token=tokens["rust"], method="POST", data={
            "action": "verify", "idempotency_key": str(uuid.uuid4()), "version": 2})
    with psycopg.connect(url) as db:
        report["ai_guard"] = {"status": status, "usage_before": before_usage,
            "usage_after": db.execute("SELECT count(*) FROM elaborati_documentaiusage").fetchone()[0],
            "jobs_before": before_jobs,
            "jobs_after": db.execute("SELECT count(*) FROM elaborati_documentjob").fetchone()[0]}
        report["personal_signatures"] = db.execute("SELECT count(*) FROM elaborati_personalsignature").fetchone()[0]
    assert report["ai_guard"]["status"] == 403 and report["ai_guard"]["usage_after"] == before_usage == 0
    assert report["ai_guard"]["jobs_after"] == before_jobs
    filename = "display-cross-backend-frozen.json" if args.all_batches else "integration-cross-backend-frozen.json"
    output = task.parents[1] / "docs/elaborati/20261025/evidence" / filename
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frozen_cases_passed": len(report["cases"]),
                      "ai_guard": report["ai_guard"], "personal_signatures": report["personal_signatures"]}))


if __name__ == "__main__":
    main()
