"""Prepare synthetic data or run one real, non-AI preview job for UI QA.

Use only with tests.elaborati_runtime_settings. The provider replacement is
confined to seeding: HTTP servers and preview workers execute real app code.
"""
import argparse
import json
import os
from pathlib import Path
import re
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "preview", "inspect"))
    parser.add_argument("--job", type=uuid.UUID)
    args = parser.parse_args()
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "tests.elaborati_runtime_settings":
        raise SystemExit("Only the dedicated local integration settings are permitted.")
    database = os.environ.get("ELABORATI_RUNTIME_DATABASE", "")
    if not re.fullmatch(r"edilcloud_elaborati_qa_[0-9a-f]{12}", database):
        raise SystemExit("Invalid disposable database name.")

    import django
    django.setup()
    from django.conf import settings
    from django.db import connection
    from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentJob, ElaboratoRevision

    runtime = Path(settings.PRIVATE_STORAGE_ROOT).parent
    runtime.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime / "context.json"
    if args.command == "setup":
        # Never flush, replace or populate an existing dataset.
        from edilcloud.modules.workspaces.models import Workspace
        if Workspace.objects.exists() or manifest_path.exists():
            raise SystemExit("Seed requires a new empty database and no existing QA manifest.")
        import pytest
        from tests import test_elaborati as fixture
        with pytest.MonkeyPatch.context() as patch:
            calls = fixture.provider.__wrapped__(patch)
            site = fixture.site.__wrapped__(settings, runtime)
            project, owner, *_ = site
            user = owner.user
            user.email = "elaborati.qa@example.com"
            user.username = "elaborati.qa"
            user.set_password("local-qa-elaborati")
            user.save(update_fields=("email", "username", "password"))
            owner.email = user.email
            owner.save(update_fields=("email",))
            revisions = {}
            for client in ("web", "flutter"):
                for backend in ("django", "rust"):
                    revision = fixture.generate(site)
                    if revision.jobs.exclude(state="completed").exists() or not revision.editor_doc:
                        raise RuntimeError("Synthetic draft seed did not complete.")
                    revision.elaborato.title = f"QA {client} {backend} - rapporto sintetico"
                    revision.elaborato.save(update_fields=("title",))
                    revisions[f"{client}_{backend}"] = str(revision.pk)
            manifest = {
                "database": database,
                "synthetic_only": True,
                "project_id": project.pk,
                "profile_id": owner.pk,
                "user_id": user.pk,
                "revisions": revisions,
                "seed_simulated_stages": len(calls),
                "seed_usage_rows": DocumentAIUsage.objects.count(),
                "external_ai_requests": 0,
            }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest))
    elif args.command == "preview":
        if args.job is None:
            raise SystemExit("--job UUID is required.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["database"] != database or manifest.get("synthetic_only") is not True:
            raise SystemExit("Database is not owned by this QA run.")
        job = DocumentJob.objects.get(pk=args.job)
        if job.action != "preview" or str(job.revision_id) not in manifest["revisions"].values():
            raise SystemExit("Only a preview of a seeded synthetic draft is permitted.")
        from edilcloud.modules.elaborati.jobs import process_job
        processed = process_job(job.pk)
        job.refresh_from_db()
        print(json.dumps({"job": str(job.pk), "processed": processed, "state": job.state,
                          "error": job.error_message, "result": job.result}))
        if job.state != "completed":
            raise SystemExit(1)
    else:
        print(json.dumps({"database": connection.settings_dict["NAME"],
                          "revisions": ElaboratoRevision.objects.count(),
                          "jobs": list(DocumentJob.objects.values("action", "state")),
                          "ai_usage_rows": DocumentAIUsage.objects.count()}))


if __name__ == "__main__":
    main()
