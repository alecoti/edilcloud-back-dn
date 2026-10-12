"""Backfill image previews without modifying originals or model references."""
from pathlib import Path
import json
import shutil
import time

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.files.image_storage import IMAGE_SUFFIXES, PREVIEW_ROOT


class Command(BaseCommand):
    help = "Audit existing images, or generate previews with --apply; originals are retained."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--backup-dir", type=Path)
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        storage = default_storage
        if not callable(getattr(storage, "prepare_image_previews", None)):
            raise CommandError("Image preview storage is not configured.")
        root = Path(storage.location).resolve()
        backup = options["backup_dir"]
        if backup:
            backup = backup.resolve()
            if backup == root or root in backup.parents:
                raise CommandError("Backup directory must be outside MEDIA_ROOT.")
        report = {"apply": options["apply"], "images": 0, "generated": 0,
                  "already_ready": 0, "skipped": 0, "failed": 0, "source_bytes": 0,
                  "preview_bytes": 0, "samples": []}
        started = time.monotonic()
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            name = path.relative_to(root).as_posix()
            if name.startswith(PREVIEW_ROOT + "/"):
                continue
            if options["limit"] and report["images"] >= options["limit"]:
                break
            report["images"] += 1
            report["source_bytes"] += path.stat().st_size
            try:
                existing = storage.image_metadata(name)
                if existing:
                    report["already_ready"] += 1
                    metadata = existing
                elif options["apply"]:
                    if backup:
                        target = backup / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            shutil.copy2(path, target)
                    metadata = storage.prepare_image_previews(name)
                    report["generated" if metadata.get("variants") else "skipped"] += 1
                else:
                    continue
                variants = metadata.get("variants", [])
                report["preview_bytes"] += sum(v["size"] for v in variants)
                if variants and len(report["samples"]) < 20:
                    report["samples"].append({"source_bytes": path.stat().st_size,
                                              "variants": [{k: v[k] for k in ("width", "height", "size")} for v in variants]})
            except Exception as exc:
                report["failed"] += 1
                self.stderr.write(f"Image preview failed ({type(exc).__name__}); original retained.")
            if report["images"] % 100 == 0:
                self.stdout.write(json.dumps({"processed": report["images"], "generated": report["generated"]}))
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report))
