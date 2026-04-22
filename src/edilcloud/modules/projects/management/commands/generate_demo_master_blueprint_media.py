from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.projects.demo_master_blueprint_media import (
    DEFAULT_GEMINI_DRAWING_MODEL,
    DEFAULT_GEMINI_IMAGE_MODEL,
    DEFAULT_GEMINI_TTS_MODEL,
    EDITORIAL_BLUEPRINT_PATH,
    GENERATED_MEDIA_MANIFEST_PATH,
    BlueprintMediaError,
    build_manifest,
    collect_audio_jobs,
    collect_document_jobs,
    collect_drawing_jobs,
    collect_image_jobs,
    load_editorial_blueprint,
    materialize_audio_job,
    materialize_document_job,
    materialize_drawing_job,
    materialize_image_job,
    require_gemini_api_key,
    write_manifest,
)


class Command(BaseCommand):
    help = "Generate demo master document/drawing/image/audio assets from the editorial blueprint."

    def add_arguments(self, parser):
        parser.add_argument("--blueprint-path", default=str(EDITORIAL_BLUEPRINT_PATH))
        parser.add_argument("--manifest-path", default=str(GENERATED_MEDIA_MANIFEST_PATH))
        parser.add_argument("--document-ref", action="append", dest="document_refs")
        parser.add_argument("--drawing-model", default=DEFAULT_GEMINI_DRAWING_MODEL)
        parser.add_argument("--image-model", default=DEFAULT_GEMINI_IMAGE_MODEL)
        parser.add_argument("--tts-model", default=DEFAULT_GEMINI_TTS_MODEL)
        parser.add_argument("--drawing-code", action="append", dest="drawing_codes")
        parser.add_argument("--asset-stem", action="append", dest="asset_stems")
        parser.add_argument("--audio-ref", action="append", dest="audio_refs")
        parser.add_argument("--limit-documents", type=int)
        parser.add_argument("--limit-drawings", type=int)
        parser.add_argument("--limit-images", type=int)
        parser.add_argument("--limit-audio", type=int)
        parser.add_argument("--skip-documents", action="store_true")
        parser.add_argument("--skip-drawings", action="store_true")
        parser.add_argument("--skip-images", action="store_true")
        parser.add_argument("--skip-audio", action="store_true")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        blueprint_path = Path(options["blueprint_path"]).resolve()
        manifest_path = Path(options["manifest_path"]).resolve()
        try:
            blueprint = load_editorial_blueprint(blueprint_path)
            document_jobs = [] if options["skip_documents"] else collect_document_jobs(blueprint)
            drawing_jobs = [] if options["skip_drawings"] else collect_drawing_jobs(blueprint)
            image_jobs = [] if options["skip_images"] else collect_image_jobs(blueprint)
            audio_jobs = [] if options["skip_audio"] else collect_audio_jobs(blueprint)
        except BlueprintMediaError as exc:
            raise CommandError(str(exc)) from exc

        if options["document_refs"]:
            allowed_document_refs = set(options["document_refs"])
            document_jobs = [job for job in document_jobs if job.document_ref in allowed_document_refs]
        if options["drawing_codes"]:
            allowed_codes = set(options["drawing_codes"])
            drawing_jobs = [job for job in drawing_jobs if job.drawing_code in allowed_codes]
        if options["asset_stems"]:
            allowed_stems = set(options["asset_stems"])
            image_jobs = [job for job in image_jobs if job.asset_stem in allowed_stems]
        if options["audio_refs"]:
            allowed_audio_refs = set(options["audio_refs"])
            audio_jobs = [job for job in audio_jobs if job.audio_ref in allowed_audio_refs]
        if options["limit_documents"] is not None:
            document_jobs = document_jobs[: max(0, options["limit_documents"])]
        if options["limit_drawings"] is not None:
            drawing_jobs = drawing_jobs[: max(0, options["limit_drawings"])]
        if options["limit_images"] is not None:
            image_jobs = image_jobs[: max(0, options["limit_images"])]
        if options["limit_audio"] is not None:
            audio_jobs = audio_jobs[: max(0, options["limit_audio"])]

        self.stdout.write(
            f"Blueprint: {blueprint_path}\n"
            f"Document jobs: {len(document_jobs)} | Drawing jobs: {len(drawing_jobs)} | Image jobs: {len(image_jobs)} | Audio jobs: {len(audio_jobs)}\n"
            f"Drawing model: {options['drawing_model']} | Image model: {options['image_model']} | TTS model: {options['tts_model']}"
        )

        if options["dry_run"]:
            manifest = build_manifest(
                blueprint_path=blueprint_path,
                document_jobs=document_jobs,
                drawing_model=options["drawing_model"],
                image_model=options["image_model"],
                tts_model=options["tts_model"],
                drawing_jobs=drawing_jobs,
                image_jobs=image_jobs,
                audio_jobs=audio_jobs,
            )
            write_manifest(manifest=manifest, manifest_path=manifest_path)
            self.stdout.write(self.style.SUCCESS(f"Dry run manifest written to {manifest_path}"))
            return

        api_key = ""
        if drawing_jobs or image_jobs or audio_jobs:
            try:
                api_key = require_gemini_api_key()
            except BlueprintMediaError as exc:
                raise CommandError(str(exc)) from exc

        for index, job in enumerate(document_jobs, start=1):
            self.stdout.write(f"[document {index}/{len(document_jobs)}] {job.document_ref}")
            try:
                materialize_document_job(
                    job=job,
                    overwrite=options["overwrite"],
                )
            except BlueprintMediaError as exc:
                job.status = "error"
                job.error = str(exc)
                self.stderr.write(self.style.ERROR(f"  failed: {exc}"))
            else:
                self.stdout.write(f"  {job.status}: {job.output_relative_path}")

        for index, job in enumerate(drawing_jobs, start=1):
            self.stdout.write(f"[drawing {index}/{len(drawing_jobs)}] {job.drawing_code}")
            try:
                materialize_drawing_job(
                    job=job,
                    api_key=api_key,
                    model=options["drawing_model"],
                    overwrite=options["overwrite"],
                )
            except BlueprintMediaError as exc:
                job.status = "error"
                job.error = str(exc)
                self.stderr.write(self.style.ERROR(f"  failed: {exc}"))
            else:
                self.stdout.write(f"  {job.status}: {job.output_relative_path}")

        for index, job in enumerate(image_jobs, start=1):
            self.stdout.write(f"[image {index}/{len(image_jobs)}] {job.asset_stem}")
            try:
                materialize_image_job(
                    job=job,
                    api_key=api_key,
                    model=options["image_model"],
                    overwrite=options["overwrite"],
                )
            except BlueprintMediaError as exc:
                job.status = "error"
                job.error = str(exc)
                self.stderr.write(self.style.ERROR(f"  failed: {exc}"))
            else:
                self.stdout.write(f"  {job.status}: {job.output_relative_path}")

        for index, job in enumerate(audio_jobs, start=1):
            self.stdout.write(f"[audio {index}/{len(audio_jobs)}] {job.audio_ref}")
            try:
                materialize_audio_job(
                    job=job,
                    api_key=api_key,
                    model=options["tts_model"],
                    overwrite=options["overwrite"],
                )
            except BlueprintMediaError as exc:
                job.status = "error"
                job.error = str(exc)
                self.stderr.write(self.style.ERROR(f"  failed: {exc}"))
            else:
                self.stdout.write(f"  {job.status}: {job.output_relative_path}")

        manifest = build_manifest(
            blueprint_path=blueprint_path,
            document_jobs=document_jobs,
            drawing_model=options["drawing_model"],
            image_model=options["image_model"],
            tts_model=options["tts_model"],
            drawing_jobs=drawing_jobs,
            image_jobs=image_jobs,
            audio_jobs=audio_jobs,
        )
        write_manifest(manifest=manifest, manifest_path=manifest_path)

        document_errors = sum(1 for job in document_jobs if job.status == "error")
        drawing_errors = sum(1 for job in drawing_jobs if job.status == "error")
        image_errors = sum(1 for job in image_jobs if job.status == "error")
        audio_errors = sum(1 for job in audio_jobs if job.status == "error")
        if document_errors or drawing_errors or image_errors or audio_errors:
            raise CommandError(
                "Media generation completed with errors. "
                f"documents={document_errors}, drawings={drawing_errors}, images={image_errors}, audio={audio_errors}, manifest={manifest_path}"
            )

        self.stdout.write(self.style.SUCCESS(f"Media manifest written to {manifest_path}"))
