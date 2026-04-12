from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.projects.demo_master_assets import (
    AVATAR_SOURCE_EXTENSIONS,
    DEMO_ASSET_SOURCE_ROOT,
    DOCUMENT_SOURCE_EXTENSIONS,
    IMAGE_SOURCE_EXTENSIONS,
    LOGO_SOURCE_EXTENSIONS,
    asset_code_for_filename,
    expected_source_pattern,
    find_demo_source_file,
    visual_source_dir_for_filename,
)
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import COMPANIES, PROJECT_BLUEPRINT
from edilcloud.modules.projects.models import CommentAttachment, PostAttachment, Project
from edilcloud.modules.workspaces.models import Profile, Workspace
from edilcloud.modules.workspaces.services import file_url


IMAGE_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


def company_code_by_name() -> dict[str, str]:
    return {company["name"]: company["code"] for company in COMPANIES}


def person_code_by_email() -> dict[str, str]:
    rows: dict[str, str] = {}
    for company in COMPANIES:
        for code, _first_name, _last_name, email, *_rest in company["people"]:
            rows[email.lower()] = code
    return rows


def normalize_path(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("\\", "/")


def is_image_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def build_row(
    *,
    category: str,
    code: str,
    title: str,
    current_relative_path: str | None,
    current_url: str | None,
    expected_source: str,
    source_exists: bool,
) -> dict[str, str | bool | None]:
    return {
        "category": category,
        "code": code,
        "title": title,
        "current_relative_path": normalize_path(current_relative_path),
        "current_url": current_url,
        "expected_source": expected_source,
        "source_exists": source_exists,
        "replace_rule": "Sostituisci il file sorgente e rilancia il seed demo.",
    }


class Command(BaseCommand):
    help = "Report all demo master assets with current backend paths and stable source locations."

    def add_arguments(self, parser):
        parser.add_argument("--project-name", default=PROJECT_BLUEPRINT["name"])
        parser.add_argument("--format", choices=("table", "json"), default="table")

    def handle(self, *args, **options):
        project = Project.objects.filter(name=options["project_name"]).first()
        if project is None:
            raise CommandError(
                f'Progetto demo "{options["project_name"]}" non trovato. Esegui prima il seed del Demo Master.'
            )

        rows: list[dict[str, str | bool | None]] = []
        company_codes = company_code_by_name()
        person_codes = person_code_by_email()

        member_profiles = (
            Profile.objects.select_related("workspace")
            .filter(project_memberships__project=project)
            .distinct()
            .order_by("workspace__name", "first_name", "last_name", "id")
        )
        workspace_ids = {profile.workspace_id for profile in member_profiles}

        for workspace in Workspace.objects.filter(id__in=workspace_ids).order_by("name", "id"):
            company_code = company_codes.get(workspace.name)
            if not company_code:
                continue
            source_pattern = expected_source_pattern(f"companies/{company_code}", "logo.svg")
            source_file = find_demo_source_file(
                relative_dir=f"companies/{company_code}",
                preferred_filename="logo.svg",
                extensions=LOGO_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="workspace-logo",
                    code=f"logo-{company_code}",
                    title=workspace.name,
                    current_relative_path=getattr(workspace.logo, "name", None),
                    current_url=file_url(workspace.logo),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        for profile in member_profiles:
            person_code = person_codes.get((profile.email or "").lower())
            if not person_code:
                continue
            source_pattern = expected_source_pattern("avatars", f"{person_code}.jpg")
            source_file = find_demo_source_file(
                relative_dir="avatars",
                preferred_filename=f"{person_code}.jpg",
                extensions=AVATAR_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="profile-avatar",
                    code=f"avatar-{person_code}",
                    title=f"{profile.member_name} ({profile.workspace.name})",
                    current_relative_path=getattr(profile.photo, "name", None),
                    current_url=file_url(profile.photo),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        for document in project.documents.select_related("folder").order_by("title", "id"):
            filename = Path(document.document.name).name if document.document else f"document-{document.id}.pdf"
            source_pattern = expected_source_pattern("documents", filename)
            source_file = find_demo_source_file(
                relative_dir="documents",
                preferred_filename=filename,
                extensions=DOCUMENT_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="project-document",
                    code=asset_code_for_filename(filename, category="document"),
                    title=document.title or filename,
                    current_relative_path=getattr(document.document, "name", None),
                    current_url=file_url(document.document),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        for photo in project.photos.order_by("title", "id"):
            filename = Path(photo.photo.name).name if photo.photo else f"photo-{photo.id}.svg"
            source_dir = visual_source_dir_for_filename(filename)
            source_pattern = expected_source_pattern(source_dir, filename)
            source_file = find_demo_source_file(
                relative_dir=source_dir,
                preferred_filename=filename,
                extensions=IMAGE_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="project-photo",
                    code=asset_code_for_filename(filename),
                    title=photo.title or filename,
                    current_relative_path=getattr(photo.photo, "name", None),
                    current_url=file_url(photo.photo),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        for attachment in PostAttachment.objects.select_related("post").filter(post__project=project).order_by("id"):
            filename = Path(attachment.file.name).name if attachment.file else f"post-attachment-{attachment.id}"
            source_dir = "attachments" if is_image_filename(filename) else "documents"
            source_pattern = expected_source_pattern(
                source_dir,
                filename,
            )
            source_file = find_demo_source_file(
                relative_dir=source_dir,
                preferred_filename=filename,
                extensions=IMAGE_SOURCE_EXTENSIONS if is_image_filename(filename) else DOCUMENT_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="post-attachment",
                    code=asset_code_for_filename(filename, category="attachment"),
                    title=f"Post #{attachment.post_id}",
                    current_relative_path=getattr(attachment.file, "name", None),
                    current_url=file_url(attachment.file),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        for attachment in CommentAttachment.objects.select_related("comment").filter(comment__post__project=project).order_by("id"):
            filename = Path(attachment.file.name).name if attachment.file else f"comment-attachment-{attachment.id}"
            source_dir = "attachments" if is_image_filename(filename) else "documents"
            source_pattern = expected_source_pattern(source_dir, filename)
            source_file = find_demo_source_file(
                relative_dir=source_dir,
                preferred_filename=filename,
                extensions=IMAGE_SOURCE_EXTENSIONS if is_image_filename(filename) else DOCUMENT_SOURCE_EXTENSIONS,
            )
            rows.append(
                build_row(
                    category="comment-attachment",
                    code=asset_code_for_filename(filename, category="attachment"),
                    title=f"Comment #{attachment.comment_id}",
                    current_relative_path=getattr(attachment.file, "name", None),
                    current_url=file_url(attachment.file),
                    expected_source=source_pattern,
                    source_exists=source_file is not None,
                )
            )

        payload = {
            "project": {
                "id": project.id,
                "name": project.name,
            },
            "source_root": normalize_path(str(DEMO_ASSET_SOURCE_ROOT)),
            "assets": rows,
        }

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
            return

        self.stdout.write(f'Project: {project.name} (#{project.id})')
        self.stdout.write(f"Source root: {normalize_path(str(DEMO_ASSET_SOURCE_ROOT))}")
        self.stdout.write("Category | Code | Source Exists | Expected Source | Current Relative Path")
        self.stdout.write("-" * 140)
        for row in rows:
            self.stdout.write(
                f'{row["category"]} | {row["code"]} | {"yes" if row["source_exists"] else "no"} | '
                f'{row["expected_source"]} | {row["current_relative_path"] or "-"}'
            )
