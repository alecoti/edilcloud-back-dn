"""Non-destructive extension of existing media with a shared 640px preview."""
import hashlib
import json
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.files.image_storage import IMAGE_SUFFIXES, PREVIEW_ROOT


class Command(BaseCommand):
    help = "Add intermediate previews, preserving originals and legacy variants. Dry run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        storage = default_storage
        if not callable(getattr(storage, "extend_image_previews", None)):
            raise CommandError("Storage does not support intermediate previews.")
        root = Path(storage.location)
        result = {"apply": options["apply"], "examined": 0, "eligible": 0, "extended": 0, "unchanged": 0,
                  "errors": 0, "original_bytes_changed": 0, "previous_display_bytes": 0, "intermediate_display_bytes": 0}
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            name = path.relative_to(root).as_posix()
            if name.startswith(PREVIEW_ROOT + "/"):
                continue
            if options["limit"] and result["examined"] >= options["limit"]:
                break
            result["examined"] += 1
            metadata = storage.image_metadata(name)
            variants = metadata.get("variants", [])
            if metadata.get("extra_variants") or not variants or max(max(v["width"], v["height"]) for v in variants) <= 640:
                result["unchanged"] += 1
                continue
            result["eligible"] += 1
            if not options["apply"]:
                continue
            with path.open("rb") as handle:
                before = hashlib.file_digest(handle, "sha256").hexdigest()
            try:
                updated = storage.extend_image_previews(name)
                with path.open("rb") as handle:
                    after = hashlib.file_digest(handle, "sha256").hexdigest()
                if before != after:
                    result["original_bytes_changed"] += 1
                    raise CommandError("Original hash changed; stop and inspect the backup.")
                if updated.get("extra_variants"):
                    result["extended"] += 1
                    larger = min((v for v in variants if max(v["width"], v["height"]) > 640), key=lambda v: v["size"])
                    result["previous_display_bytes"] += larger["size"]
                    result["intermediate_display_bytes"] += updated["extra_variants"][0]["size"]
                else:
                    result["unchanged"] += 1
            except CommandError:
                raise
            except Exception:
                result["errors"] += 1
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result["errors"]:
            raise CommandError("Some previews could not be extended; originals retained.")
