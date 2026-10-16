"""Explicit, idempotent legacy capture; never rewrites published Elaborati."""

import json

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.projects import models
from edilcloud.modules.projects.participations import sync_member
from edilcloud.modules.projects.provenance import capture_source


class Command(BaseCommand):
    help = "Censisce fonti pregresse; senza --apply non scrive. Gli originali perduti non sono ricostruiti."

    def add_arguments(self, parser):
        parser.add_argument("--project", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--metadata-only", action="store_true")

    def handle(self, *args, **options):
        project = models.Project.objects.filter(pk=options["project"]).first()
        if not project:
            raise CommandError("Cantiere non trovato.")
        report = {
            "project": project.pk,
            "applied": options["apply"],
            "objects": 0,
            "created_sources": 0,
            "versions": 0,
            "missing_files": 0,
            "unknown_actors": 0,
        }
        # Membership observations start today; they never backdate a professional role.
        if options["apply"]:
            for member in project.members.select_related("project", "profile__workspace"):
                sync_member(member, reconstructed=True)
        for cls, lookup in (
            (models.ProjectPost, "project"),
            (models.PostComment, "post__project"),
            (models.PostAttachment, "post__project"),
            (models.CommentAttachment, "comment__post__project"),
            (models.ProjectDocument, "project"),
            (models.ProjectPhoto, "project"),
            (models.ProjectDrawingPin, "project"),
            (models.ProjectModelPin, "project"),
            (models.ProjectModel3D, "project"),
            (models.ProjectMember, "project"),
        ):
            for obj in cls.objects.filter(**{lookup: project}).iterator(chunk_size=100):
                report["objects"] += 1
                if not options["apply"]:
                    continue
                count = project.evidence_sources.count()
                source, version = capture_source(
                    obj, reconstructed=True, archive=not options["metadata_only"]
                )
                report["created_sources"] += project.evidence_sources.count() - count
                report["versions"] += 1
                report["missing_files"] += version.original_state == "missing"
                report["unknown_actors"] += source.identity_state == "unavailable"
        self.stdout.write(json.dumps(report, ensure_ascii=False))
