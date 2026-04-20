"""Project domain services for list/detail read models and operational mutations."""

from __future__ import annotations

import colorsys
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote
import uuid

import httpx
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Avg, Case, Count, DateTimeField, F, Max, Prefetch, Q, When
from django.http import FileResponse
from django.utils import timezone

from edilcloud.modules.files.media_optimizer import optimize_media_for_storage
from edilcloud.modules.notifications.catalog import (
    NotificationBlueprint,
    build_project_activity_notification,
    build_project_document_notification,
    build_project_folder_notification,
    build_project_invite_notification,
    build_project_member_added_notification,
    build_project_task_notification,
    build_project_thread_notification,
)
from edilcloud.modules.projects.archive import (
    mark_project_archived_if_due,
    sync_project_archive_schedule,
)
from edilcloud.modules.projects.emails import send_project_invite_code_email
from edilcloud.modules.projects.gantt_import import (
    ImportWarning,
    ImportedLink,
    ImportedPhase,
    ImportedPlan,
    parse_gantt_import_file,
)
from edilcloud.modules.projects.gantt_schedule import (
    create_project_schedule_link_record,
    delete_project_schedule_link_record,
    propagate_project_schedule_delays,
    shift_task_activities_only,
    sync_task_bounds_to_activities,
    update_project_schedule_link_record,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostComment,
    PostCommentTranslation,
    PostKind,
    Project,
    ProjectActivity,
    ProjectClientMutation,
    ProjectCompanyColor,
    ProjectDocument,
    ProjectDrawingPin,
    ProjectFolder,
    ProjectInviteCode,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectPostTranslation,
    ProjectPostSeenState,
    ProjectScheduleLink,
    ProjectScheduleLinkType,
    ProjectStatus,
    ProjectTask,
    TaskActivityStatus,
)
from edilcloud.modules.projects.operational_history import persist_project_operational_event
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole
from edilcloud.modules.workspaces.services import (
    file_url,
    get_role_priority,
    get_user_profile,
    normalize_role,
    resolve_existing_profile_for_email,
    select_default_profile,
)
from edilcloud.platform.geocoding import geocode_address
from edilcloud.platform.realtime.services import publish_notification_event, publish_project_event


PROJECT_EDIT_ROLES = {
    WorkspaceRole.OWNER,
    WorkspaceRole.DELEGATE,
    WorkspaceRole.MANAGER,
}
PROJECT_MANAGE_ROLES = {
    WorkspaceRole.OWNER,
    WorkspaceRole.DELEGATE,
}
PROJECT_ROLE_LABELS = {
    WorkspaceRole.OWNER: "Owner",
    WorkspaceRole.DELEGATE: "Delegate",
    WorkspaceRole.MANAGER: "Manager",
    WorkspaceRole.WORKER: "Operativo",
}
PROJECT_ASSIGNMENT_ROLE_LABELS = {
    "committente": "Committente",
    "responsabile_lavori": "Responsabile dei lavori",
    "csp": "CSP",
    "cse": "CSE",
    "datore_lavoro": "Datore di lavoro",
    "dirigente": "Dirigente",
    "preposto": "Preposto",
    "rspp": "RSPP",
    "medico_competente": "Medico competente",
    "rls": "RLS",
    "rlst": "RLST",
    "rls_sito": "RLS di sito",
    "addetto_primo_soccorso": "Addetto primo soccorso",
    "addetto_antincendio_emergenza": "Addetto antincendio / evacuazione / emergenza",
    "lavoratore": "Lavoratore",
}
PROJECT_ASSIGNMENT_COORDINATOR_ROLE_CODES = ["csp", "cse"]
PROJECT_ASSIGNMENT_EMERGENCY_ROLE_CODES = [
    "addetto_primo_soccorso",
    "addetto_antincendio_emergenza",
]
PROJECT_COMPANY_COLOR_PROJECT_VARIATION_WINDOW = 10
PROJECT_COMPANY_COLOR_GOOGLE_CANDIDATES = [
    ("red", "500", "#F44336"),
    ("pink", "500", "#E91E63"),
    ("purple", "500", "#9C27B0"),
    ("deep-purple", "500", "#673AB7"),
    ("indigo", "500", "#3F51B5"),
    ("blue", "500", "#2196F3"),
    ("light-blue", "700", "#0288D1"),
    ("cyan", "700", "#0097A7"),
    ("teal", "500", "#009688"),
    ("green", "500", "#4CAF50"),
    ("light-green", "700", "#689F38"),
    ("lime", "800", "#9E9D24"),
    ("yellow", "800", "#F9A825"),
    ("amber", "700", "#FFA000"),
    ("orange", "500", "#FF9800"),
    ("deep-orange", "500", "#FF5722"),
    ("brown", "500", "#795548"),
    ("blue-grey", "500", "#607D8B"),
    ("grey", "700", "#616161"),
    ("red", "A700", "#D50000"),
    ("pink", "A400", "#F50057"),
    ("purple", "A700", "#AA00FF"),
    ("deep-purple", "A400", "#651FFF"),
    ("indigo", "A700", "#304FFE"),
    ("blue", "A700", "#2962FF"),
    ("light-blue", "A700", "#0091EA"),
    ("cyan", "A700", "#00B8D4"),
    ("teal", "A700", "#00BFA5"),
    ("green", "A700", "#00C853"),
    ("light-green", "A700", "#64DD17"),
    ("lime", "A700", "#AEEA00"),
    ("yellow", "A700", "#FFD600"),
    ("amber", "A700", "#FFAB00"),
    ("orange", "A700", "#FF6D00"),
    ("deep-orange", "A700", "#DD2C00"),
    ("red", "700", "#D32F2F"),
    ("pink", "700", "#C2185B"),
    ("purple", "700", "#7B1FA2"),
    ("deep-purple", "700", "#512DA8"),
    ("indigo", "700", "#303F9F"),
    ("blue", "700", "#1976D2"),
    ("light-blue", "500", "#03A9F4"),
    ("cyan", "500", "#00BCD4"),
    ("teal", "700", "#00796B"),
    ("green", "700", "#388E3C"),
    ("light-green", "500", "#8BC34A"),
    ("lime", "700", "#AFB42B"),
    ("yellow", "700", "#FBC02D"),
    ("amber", "500", "#FFC107"),
    ("orange", "700", "#F57C00"),
    ("deep-orange", "700", "#E64A19"),
    ("brown", "700", "#5D4037"),
    ("blue-grey", "700", "#455A64"),
    ("grey", "500", "#9E9E9E"),
]


def normalize_project_company_color(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized.startswith("#"):
        return None
    hex_value = normalized[1:]
    if len(hex_value) == 3 and all(char in "0123456789abcdef" for char in hex_value):
        expanded = "".join(f"{char}{char}" for char in hex_value)
        return f"#{expanded}"
    if len(hex_value) == 6 and all(char in "0123456789abcdef" for char in hex_value):
        return f"#{hex_value}"
    return None


def hex_to_project_company_rgb(value: str) -> tuple[int, int, int]:
    normalized = normalize_project_company_color(value)
    if normalized is None:
        raise ValueError("Colore progetto non valido.")
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def srgb_channel_to_linear(value: int) -> float:
    normalized = value / 255
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def rgb_to_project_company_lab(value: str) -> tuple[float, float, float]:
    red, green, blue = hex_to_project_company_rgb(value)
    linear_red = srgb_channel_to_linear(red)
    linear_green = srgb_channel_to_linear(green)
    linear_blue = srgb_channel_to_linear(blue)

    x = (0.4124 * linear_red + 0.3576 * linear_green + 0.1805 * linear_blue) / 0.95047
    y = 0.2126 * linear_red + 0.7152 * linear_green + 0.0722 * linear_blue
    z = (0.0193 * linear_red + 0.1192 * linear_green + 0.9505 * linear_blue) / 1.08883

    def pivot(channel: float) -> float:
        if channel > 0.008856:
            return channel ** (1 / 3)
        return (7.787 * channel) + (16 / 116)

    fx = pivot(x)
    fy = pivot(y)
    fz = pivot(z)

    return (
        (116 * fy) - 16,
        500 * (fx - fy),
        200 * (fy - fz),
    )


def project_company_color_distance(left: str, right: str) -> float:
    left_lab = rgb_to_project_company_lab(left)
    right_lab = rgb_to_project_company_lab(right)
    return math.sqrt(
        ((left_lab[0] - right_lab[0]) ** 2)
        + ((left_lab[1] - right_lab[1]) ** 2)
        + ((left_lab[2] - right_lab[2]) ** 2)
    )


def build_google_project_company_color_palette() -> list[str]:
    candidate_entries: list[tuple[str, str]] = []
    seen_colors: set[str] = set()
    for family, _tone, raw_color in PROJECT_COMPANY_COLOR_GOOGLE_CANDIDATES:
        normalized = normalize_project_company_color(raw_color)
        if normalized is None or normalized in seen_colors:
            continue
        candidate_entries.append((family, normalized))
        seen_colors.add(normalized)

    if not candidate_entries:
        return []

    ordered_entries: list[tuple[str, str]] = []
    family_counts: dict[str, int] = defaultdict(int)
    remaining_entries = candidate_entries.copy()

    preferred_seed = normalize_project_company_color("#2196f3")
    seed_entry = next(
        (entry for entry in remaining_entries if entry[1] == preferred_seed),
        remaining_entries[0],
    )
    ordered_entries.append(seed_entry)
    family_counts[seed_entry[0]] += 1
    remaining_entries.remove(seed_entry)

    while remaining_entries:

        def score(entry: tuple[str, str]) -> tuple[float, float, int]:
            family, color = entry
            min_distance = min(
                project_company_color_distance(color, selected_color)
                for _selected_family, selected_color in ordered_entries
            )
            avg_distance = sum(
                project_company_color_distance(color, selected_color)
                for _selected_family, selected_color in ordered_entries
            ) / len(ordered_entries)
            return (
                round(min_distance, 6),
                round(avg_distance, 6),
                -family_counts.get(family, 0),
            )

        best_entry = max(remaining_entries, key=score)
        ordered_entries.append(best_entry)
        family_counts[best_entry[0]] += 1
        remaining_entries.remove(best_entry)

    return [color for _family, color in ordered_entries]


PROJECT_COMPANY_COLOR_PALETTE = build_google_project_company_color_palette()


def build_project_company_color_sequence(project_id: int) -> list[str]:
    if not PROJECT_COMPANY_COLOR_PALETTE:
        return []

    variation_window = min(
        PROJECT_COMPANY_COLOR_PROJECT_VARIATION_WINDOW,
        len(PROJECT_COMPANY_COLOR_PALETTE),
    )
    seed_index = (max(project_id, 1) - 1) % variation_window
    seed_color = PROJECT_COMPANY_COLOR_PALETTE[seed_index]
    return [
        seed_color,
        *PROJECT_COMPANY_COLOR_PALETTE[:seed_index],
        *PROJECT_COMPANY_COLOR_PALETTE[seed_index + 1 :],
    ]


def build_project_company_color(*, project_id: int, attempt_index: int) -> str:
    project_palette = build_project_company_color_sequence(project_id)
    palette_size = len(project_palette)
    if attempt_index < palette_size:
        return project_palette[attempt_index]

    offset = attempt_index - palette_size
    hue = (((project_id * 47) + (offset * 137.508)) % 360) / 360
    lightness = 0.46 if offset % 2 == 0 else 0.4
    saturation = 0.72
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def pick_next_project_company_color(*, project_id: int, used_colors: set[str]) -> str:
    candidate_index = 0
    while True:
        candidate = build_project_company_color(
            project_id=project_id,
            attempt_index=candidate_index,
        )
        candidate_index += 1
        if candidate not in used_colors:
            return candidate


def collect_project_company_workspace_ids(
    *,
    members: list[ProjectMember] | None = None,
    tasks: list[ProjectTask] | None = None,
    profiles: list[Profile] | None = None,
    workspace_ids: list[int] | tuple[int, ...] | set[int] | None = None,
) -> list[int]:
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()

    def add(value: int | None) -> None:
        if value is None or value <= 0 or value in seen_ids:
            return
        seen_ids.add(value)
        ordered_ids.append(value)

    for member in members or []:
        add(member.profile.workspace_id if member.profile_id else None)
    for task in tasks or []:
        add(task.assigned_company_id)
    for profile in profiles or []:
        add(profile.workspace_id)
    for workspace_id in workspace_ids or []:
        add(workspace_id)

    return ordered_ids


def ensure_project_company_colors(
    *,
    project: Project,
    workspace_ids: list[int] | tuple[int, ...] | set[int] | None = None,
) -> dict[int, str]:
    ordered_ids = collect_project_company_workspace_ids(workspace_ids=workspace_ids)
    if not ordered_ids:
        return {}

    assignments = list(ProjectCompanyColor.objects.filter(project=project).order_by("id"))
    colors_by_workspace_id: dict[int, str] = {}
    used_colors: set[str] = set()

    for assignment in assignments:
        normalized = normalize_project_company_color(assignment.color_project)
        if normalized is None or normalized in used_colors:
            normalized = pick_next_project_company_color(
                project_id=project.id,
                used_colors=used_colors,
            )
            assignment.color_project = normalized
            assignment.save(update_fields=("color_project", "updated_at"))
        colors_by_workspace_id[assignment.workspace_id] = normalized
        used_colors.add(normalized)

    for workspace_id in ordered_ids:
        if workspace_id in colors_by_workspace_id:
            continue
        candidate = pick_next_project_company_color(
            project_id=project.id,
            used_colors=used_colors,
        )
        ProjectCompanyColor.objects.create(
            project=project,
            workspace_id=workspace_id,
            color_project=candidate,
        )
        colors_by_workspace_id[workspace_id] = candidate
        used_colors.add(candidate)

    return colors_by_workspace_id


def serialize_project_realtime_actor(profile: Profile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "id": profile.id,
        "firstName": profile.first_name or None,
        "lastName": profile.last_name or None,
        "companyId": profile.workspace_id,
        "companyName": profile.workspace.name if profile.workspace_id else None,
    }


def make_realtime_payload_safe(value):
    if isinstance(value, dict):
        return {str(key): make_realtime_payload_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_realtime_payload_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def build_project_realtime_event(
    *,
    event_type: str,
    project_id: int,
    actor_profile: Profile | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    folder_id: int | None = None,
    document_id: int | None = None,
    data: dict | None = None,
) -> dict:
    return {
        "eventId": str(uuid.uuid4()),
        "channel": "project",
        "type": event_type,
        "timestamp": timezone.now().isoformat(),
        "projectId": project_id,
        "profileId": actor_profile.id if actor_profile is not None else None,
        "taskId": task_id,
        "activityId": activity_id,
        "postId": post_id,
        "commentId": comment_id,
        "folderId": folder_id,
        "documentId": document_id,
        "actor": serialize_project_realtime_actor(actor_profile),
        "data": make_realtime_payload_safe(data or {}),
    }


def emit_project_realtime_event(
    *,
    event_type: str,
    project_id: int,
    actor_profile: Profile | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    folder_id: int | None = None,
    document_id: int | None = None,
    data: dict | None = None,
) -> None:
    payload = build_project_realtime_event(
        event_type=event_type,
        project_id=project_id,
        actor_profile=actor_profile,
        task_id=task_id,
        activity_id=activity_id,
        post_id=post_id,
        comment_id=comment_id,
        folder_id=folder_id,
        document_id=document_id,
        data=data,
    )
    publish_project_event(project_id=project_id, payload=payload)
    persist_project_operational_event(project_id=project_id, payload=payload)


def build_feed_realtime_event(
    *,
    recipient_profile_id: int,
    project_id: int,
    actor_profile: Profile | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    data: dict | None = None,
) -> dict:
    return {
        "eventId": str(uuid.uuid4()),
        "channel": "feed",
        "type": "feed.updated",
        "timestamp": timezone.now().isoformat(),
        "projectId": project_id,
        "profileId": recipient_profile_id,
        "taskId": task_id,
        "activityId": activity_id,
        "postId": post_id,
        "commentId": comment_id,
        "actor": serialize_project_realtime_actor(actor_profile),
        "data": data or {},
    }


def emit_feed_realtime_events(
    *,
    recipients: list[Profile],
    project_id: int,
    actor_profile: Profile | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    data: dict | None = None,
) -> None:
    sent_profile_ids: set[int] = set()
    for recipient in recipients:
        if recipient.id in sent_profile_ids:
            continue
        sent_profile_ids.add(recipient.id)
        publish_notification_event(
            profile_id=recipient.id,
            payload=build_feed_realtime_event(
                recipient_profile_id=recipient.id,
                project_id=project_id,
                actor_profile=actor_profile,
                task_id=task_id,
                activity_id=activity_id,
                post_id=post_id,
                comment_id=comment_id,
                data=data,
            ),
        )


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


PROJECT_CONTENT_TRANSLATION_LANGUAGES = {"it", "en", "fr", "ro", "ru", "ar"}
PROJECT_CONTENT_TRANSLATION_PROVIDER = "openai"


def normalize_content_language(value: str | None) -> str:
    normalized = normalize_text(value).lower().replace("_", "-")
    if not normalized:
        return ""
    primary = normalized.split("-", 1)[0]
    return primary if primary in PROJECT_CONTENT_TRANSLATION_LANGUAGES else ""


def resolve_project_content_language(
    *, preferred_language: str | None, fallback_language: str | None = None
) -> str:
    return normalize_content_language(preferred_language) or normalize_content_language(
        fallback_language
    )


def project_content_translation_model() -> str:
    configured = getattr(settings, "PROJECT_CONTENT_TRANSLATION_MODEL", "").strip()
    if configured:
        return configured
    return getattr(settings, "AI_DRAFT_MODEL", "gpt-4o-mini") or "gpt-4o-mini"


def extract_openai_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    collected: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                text_value = content["text"].strip()
                if text_value:
                    collected.append(text_value)
    return "\n\n".join(collected).strip()


def build_project_content_translation_signature(*, source_text: str, source_language: str) -> str:
    digest = hashlib.sha256()
    digest.update(normalize_text(source_language).encode("utf-8"))
    digest.update(b"\n")
    digest.update(normalize_text(source_text).encode("utf-8"))
    return digest.hexdigest()


def project_content_source_text(*, text: str | None, original_text: str | None) -> str:
    return normalize_text(original_text) or normalize_text(text)


def project_content_source_language(
    *, source_language: str | None, display_language: str | None = None
) -> str:
    return normalize_content_language(source_language) or normalize_content_language(
        display_language
    )


def should_translate_project_content(
    *,
    source_text: str,
    source_language: str,
    target_language: str,
) -> bool:
    normalized_target = normalize_content_language(target_language)
    if not normalized_target or not normalize_text(source_text):
        return False
    normalized_source = normalize_content_language(source_language)
    return not normalized_source or normalized_source != normalized_target


def generate_project_content_translation(
    *,
    source_text: str,
    source_language: str,
    target_language: str,
) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY non configurata per le traduzioni dei post.")

    normalized_source_text = normalize_text(source_text)
    normalized_source_language = normalize_content_language(source_language)
    normalized_target_language = normalize_content_language(target_language)
    if not normalized_source_text or not normalized_target_language:
        raise RuntimeError("Contenuto o lingua di destinazione non validi per la traduzione.")

    source_language_hint = normalized_source_language or "auto-detect"
    response = httpx.post(
        f"{settings.OPENAI_API_BASE_URL}/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": project_content_translation_model(),
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You translate construction project updates with high fidelity. "
                                "Return only the translated text in the requested target language. "
                                "Preserve names, codes, bullets, markdown, line breaks, measurements, dates, "
                                "and operational meaning. Do not explain your work."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"Source language: {source_language_hint}\n"
                                f"Target language: {normalized_target_language}\n\n"
                                "Translate the following project post or comment exactly:\n"
                                f"{normalized_source_text}"
                            ),
                        }
                    ],
                },
            ],
            "temperature": 0.1,
            "max_output_tokens": 1600,
        },
        timeout=30.0,
    )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI ha restituito una risposta non valida: {exc}") from exc

    if not response.is_success:
        detail = (
            payload.get("error", {}).get("message")
            if isinstance(payload.get("error"), dict)
            else None
        )
        raise RuntimeError(detail or f"OpenAI HTTP {response.status_code}")

    translated_text = extract_openai_output_text(payload)
    if not translated_text:
        raise RuntimeError("OpenAI ha restituito una traduzione vuota.")
    return translated_text


def invalidate_post_translation_memory(post: ProjectPost) -> None:
    ProjectPostTranslation.objects.filter(post=post).delete()


def invalidate_comment_translation_memory(comment: PostComment) -> None:
    PostCommentTranslation.objects.filter(comment=comment).delete()


def upsert_post_translation_memory(
    *,
    post: ProjectPost,
    target_language: str,
    translated_text: str,
    source_language: str,
    source_signature: str,
) -> ProjectPostTranslation:
    defaults = {
        "source_language": source_language,
        "source_signature": source_signature,
        "translated_text": translated_text,
        "provider": PROJECT_CONTENT_TRANSLATION_PROVIDER,
        "model": project_content_translation_model(),
    }
    try:
        ProjectPostTranslation.objects.update_or_create(
            post=post,
            target_language=target_language,
            defaults=defaults,
        )
    except IntegrityError:
        ProjectPostTranslation.objects.filter(post=post, target_language=target_language).update(
            **defaults
        )
    return ProjectPostTranslation.objects.get(post=post, target_language=target_language)


def upsert_comment_translation_memory(
    *,
    comment: PostComment,
    target_language: str,
    translated_text: str,
    source_language: str,
    source_signature: str,
) -> PostCommentTranslation:
    defaults = {
        "source_language": source_language,
        "source_signature": source_signature,
        "translated_text": translated_text,
        "provider": PROJECT_CONTENT_TRANSLATION_PROVIDER,
        "model": project_content_translation_model(),
    }
    try:
        PostCommentTranslation.objects.update_or_create(
            comment=comment,
            target_language=target_language,
            defaults=defaults,
        )
    except IntegrityError:
        PostCommentTranslation.objects.filter(
            comment=comment, target_language=target_language
        ).update(**defaults)
    return PostCommentTranslation.objects.get(comment=comment, target_language=target_language)


def resolve_post_translation_memory(
    posts: list[ProjectPost],
    *,
    target_language: str | None,
    fallback_language: str | None,
) -> dict[int, ProjectPostTranslation]:
    normalized_target_language = resolve_project_content_language(
        preferred_language=target_language,
        fallback_language=fallback_language,
    )
    if not normalized_target_language or not posts:
        return {}

    translations = {
        translation.post_id: translation
        for translation in ProjectPostTranslation.objects.filter(
            post_id__in=[post.id for post in posts],
            target_language=normalized_target_language,
        )
    }
    resolved: dict[int, ProjectPostTranslation] = {}

    for post in posts:
        source_text = project_content_source_text(text=post.text, original_text=post.original_text)
        source_language = project_content_source_language(
            source_language=post.source_language,
            display_language=post.display_language,
        )
        if not should_translate_project_content(
            source_text=source_text,
            source_language=source_language,
            target_language=normalized_target_language,
        ):
            continue

        source_signature = build_project_content_translation_signature(
            source_text=source_text,
            source_language=source_language,
        )
        cached_translation = translations.get(post.id)
        if (
            cached_translation is not None
            and cached_translation.source_signature == source_signature
        ):
            resolved[post.id] = cached_translation
            continue

        try:
            translated_text = generate_project_content_translation(
                source_text=source_text,
                source_language=source_language,
                target_language=normalized_target_language,
            )
        except Exception:
            continue

        resolved[post.id] = upsert_post_translation_memory(
            post=post,
            target_language=normalized_target_language,
            translated_text=translated_text,
            source_language=source_language,
            source_signature=source_signature,
        )

    return resolved


def resolve_comment_translation_memory(
    comments: list[PostComment],
    *,
    target_language: str | None,
    fallback_language: str | None,
) -> dict[int, PostCommentTranslation]:
    normalized_target_language = resolve_project_content_language(
        preferred_language=target_language,
        fallback_language=fallback_language,
    )
    if not normalized_target_language or not comments:
        return {}

    translations = {
        translation.comment_id: translation
        for translation in PostCommentTranslation.objects.filter(
            comment_id__in=[comment.id for comment in comments],
            target_language=normalized_target_language,
        )
    }
    resolved: dict[int, PostCommentTranslation] = {}

    for comment in comments:
        source_text = project_content_source_text(
            text=comment.text, original_text=comment.original_text
        )
        source_language = project_content_source_language(
            source_language=comment.source_language,
            display_language=comment.display_language,
        )
        if not should_translate_project_content(
            source_text=source_text,
            source_language=source_language,
            target_language=normalized_target_language,
        ):
            continue

        source_signature = build_project_content_translation_signature(
            source_text=source_text,
            source_language=source_language,
        )
        cached_translation = translations.get(comment.id)
        if (
            cached_translation is not None
            and cached_translation.source_signature == source_signature
        ):
            resolved[comment.id] = cached_translation
            continue

        try:
            translated_text = generate_project_content_translation(
                source_text=source_text,
                source_language=source_language,
                target_language=normalized_target_language,
            )
        except Exception:
            continue

        resolved[comment.id] = upsert_comment_translation_memory(
            comment=comment,
            target_language=normalized_target_language,
            translated_text=translated_text,
            source_language=source_language,
            source_signature=source_signature,
        )

    return resolved


def localized_post_content(
    post: ProjectPost,
    *,
    translation: ProjectPostTranslation | None = None,
) -> dict[str, Any]:
    source_text = project_content_source_text(text=post.text, original_text=post.original_text)
    source_language = project_content_source_language(
        source_language=post.source_language,
        display_language=post.display_language,
    )
    if translation is None:
        return {
            "text": post.text or None,
            "original_text": source_text or None,
            "source_language": source_language or None,
            "display_language": normalize_content_language(
                post.display_language or post.source_language
            )
            or source_language
            or None,
            "is_translated": bool(post.is_translated),
        }

    return {
        "text": translation.translated_text or source_text or None,
        "original_text": source_text or None,
        "source_language": source_language or None,
        "display_language": translation.target_language or None,
        "is_translated": True,
    }


def localized_comment_content(
    comment: PostComment,
    *,
    translation: PostCommentTranslation | None = None,
) -> dict[str, Any]:
    source_text = project_content_source_text(
        text=comment.text, original_text=comment.original_text
    )
    source_language = project_content_source_language(
        source_language=comment.source_language,
        display_language=comment.display_language,
    )
    if translation is None:
        return {
            "text": comment.text or None,
            "original_text": source_text or None,
            "source_language": source_language or None,
            "display_language": normalize_content_language(
                comment.display_language or comment.source_language
            )
            or source_language
            or None,
            "is_translated": bool(comment.is_translated),
        }

    return {
        "text": translation.translated_text or source_text or None,
        "original_text": source_text or None,
        "source_language": source_language or None,
        "display_language": translation.target_language or None,
        "is_translated": True,
    }


def normalize_import_lookup(value: str | None) -> str:
    return normalize_text(value).lower().replace("_", " ").replace("-", " ")


def normalize_email(value: str | None) -> str:
    return normalize_text(value).lower()


def normalize_project_progress(value: int | float | None) -> int:
    try:
        numeric = int(round(float(value or 0)))
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(100, numeric))


def normalize_project_assignment_role_codes(
    codes: list[str] | tuple[str, ...] | None,
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_code in codes or []:
        code = normalize_text(raw_code)
        if not code or code not in PROJECT_ASSIGNMENT_ROLE_LABELS or code in seen:
            continue
        seen.add(code)
        normalized.append(code)

    return normalized


def project_assignment_role_label(code: str | None) -> str:
    normalized_code = normalize_text(code)
    return PROJECT_ASSIGNMENT_ROLE_LABELS.get(normalized_code, normalized_code)


def project_assignment_role_labels(codes: list[str] | tuple[str, ...] | None) -> list[str]:
    return [
        project_assignment_role_label(code)
        for code in normalize_project_assignment_role_codes(codes)
    ]


def project_member_assignment_role_codes(member: ProjectMember) -> list[str]:
    return normalize_project_assignment_role_codes(
        member.project_role_codes if isinstance(member.project_role_codes, list) else [],
    )


def is_execution_company_type(value: str | None) -> bool:
    normalized = normalize_text(value).replace("-", "_").replace(" ", "_")
    return normalized in {"impresa_affidataria", "impresa_esecutrice"}


def parse_calendar_date(value: date | datetime | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    normalized = normalize_text(value).replace("Z", "+00:00")
    if not normalized:
        return None

    if "T" in normalized or " " in normalized:
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def require_imported_calendar_date(value: date | datetime | str | None, *, label: str) -> date:
    parsed = parse_calendar_date(value)
    if parsed is None:
        raise ValueError(f"{label} non valida nel file Gantt importato.")
    return parsed


def task_activity_status_to_progress(status: str | None) -> int:
    if status == TaskActivityStatus.COMPLETED:
        return 100
    if status == TaskActivityStatus.PROGRESS:
        return 55
    return 0


def task_activity_progress_to_status(progress: int | float | None) -> str:
    normalized = normalize_project_progress(progress)
    if normalized >= 100:
        return TaskActivityStatus.COMPLETED
    if normalized > 0:
        return TaskActivityStatus.PROGRESS
    return TaskActivityStatus.TODO


def timeline_value(value: object | None) -> str | None:
    if value in {None, ""}:
        return None
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    normalized = str(value).strip()
    return normalized or None


def build_timeline_change(
    *,
    label: str,
    before: object | None = None,
    after: object | None = None,
    value: object | None = None,
    tone: str = "neutral",
) -> dict | None:
    rendered_value = timeline_value(value)
    rendered_before = timeline_value(before)
    rendered_after = timeline_value(after)
    if rendered_value is None and rendered_before == rendered_after:
        return None

    payload = {
        "label": label,
        "tone": tone,
    }
    if rendered_value is not None:
        payload["value"] = rendered_value
    else:
        payload["before"] = rendered_before or "-"
        payload["after"] = rendered_after or "-"
    return payload


def task_activity_status_label(status: str | None) -> str:
    if status == TaskActivityStatus.TODO:
        return "Da fare"
    if status == TaskActivityStatus.PROGRESS:
        return "In corso"
    if status == TaskActivityStatus.COMPLETED:
        return "Completata"
    return timeline_value(status) or "-"


def post_kind_label(post_kind: str | None) -> str:
    if post_kind == PostKind.ISSUE:
        return "Segnalazione"
    if post_kind == PostKind.DOCUMENTATION:
        return "Documentazione"
    if post_kind == PostKind.WORK_PROGRESS:
        return "Avanzamento"
    return timeline_value(post_kind) or "Post"


def attachment_count_label(count: int) -> str:
    if count == 1:
        return "1 file"
    return f"{count} file"


def normalize_coordinate(
    value: float | int | str | None,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    if value in {None, ""}:
        return None
    try:
        numeric = round(float(value), 6)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} non valida.") from exc
    if numeric < minimum or numeric > maximum:
        raise ValueError(f"{label} non valida.")
    return numeric


def resolve_project_coordinates(
    *,
    address: str,
    latitude: float | None,
    longitude: float | None,
) -> tuple[float | None, float | None]:
    normalized_latitude = normalize_coordinate(
        latitude,
        label="Latitudine",
        minimum=-90,
        maximum=90,
    )
    normalized_longitude = normalize_coordinate(
        longitude,
        label="Longitudine",
        minimum=-180,
        maximum=180,
    )
    if (normalized_latitude is None) != (normalized_longitude is None):
        raise ValueError("Latitudine e longitudine devono essere valorizzate insieme.")
    if normalized_latitude is not None and normalized_longitude is not None:
        return normalized_latitude, normalized_longitude

    normalized_address = normalize_text(address)
    if not normalized_address:
        return None, None

    geocoded = geocode_address(normalized_address)
    if geocoded is None:
        return None, None
    return geocoded.latitude, geocoded.longitude


def project_location_source(project: Project) -> str | None:
    if project.google_place_id:
        return "google"
    if project.latitude is not None and project.longitude is not None:
        return "coordinates"
    if project.address:
        return "address"
    return None


def build_project_map_url(project: Project) -> str | None:
    if project.latitude is not None and project.longitude is not None:
        return (
            "https://www.google.com/maps/search/?api=1&query="
            f"{project.latitude:.6f},{project.longitude:.6f}"
        )
    normalized_address = normalize_text(project.address)
    if normalized_address:
        return f"https://www.google.com/maps/search/?api=1&query={quote(normalized_address)}"
    return None


def attachment_name(file_field) -> str:
    return Path(getattr(file_field, "name", "") or "").name


def attachment_extension(file_field) -> str | None:
    suffix = Path(getattr(file_field, "name", "") or "").suffix.lower().lstrip(".")
    return suffix or None


def attachment_size(file_field) -> int | None:
    if not file_field:
        return None
    try:
        return file_field.size
    except Exception:
        return None


def attachment_kind_from_extension(extension: str | None) -> str:
    normalized = (extension or "").lower()
    if normalized in {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "avif",
        "svg",
        "bmp",
        "tif",
        "tiff",
        "heic",
    }:
        return "image"
    if normalized in {"mp4", "mov", "avi", "mkv", "webm", "m4v"}:
        return "video"
    if normalized in {"mp3", "wav", "ogg", "aac", "flac", "m4a"}:
        return "audio"
    if normalized in {"pdf"}:
        return "pdf"
    return "file"


def get_current_profile(*, user, claims: dict) -> Profile:
    """Resolve the active workspace profile carried by the JWT claims."""
    profile_id = claims.get("main_profile")
    if profile_id:
        try:
            normalized_profile_id = int(profile_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Profilo attivo non valido.") from exc
        if normalized_profile_id != user.id:
            profile = get_user_profile(user, normalized_profile_id)
            if profile is not None:
                return profile

    profile = select_default_profile(user)
    if profile is None:
        raise ValueError("Nessun profilo workspace attivo disponibile.")
    return profile


def serialize_project_company(
    workspace: Workspace | None,
    *,
    company_colors_by_workspace_id: dict[int, str] | None = None,
) -> dict | None:
    if workspace is None:
        return None
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug or None,
        "email": workspace.email or None,
        "tax_code": workspace.vat_number or None,
        "logo": file_url(workspace.logo),
        "color_project": (
            company_colors_by_workspace_id.get(workspace.id)
            if company_colors_by_workspace_id is not None
            else normalize_project_company_color(workspace.color)
        ),
    }


def serialize_project_user(profile: Profile | None) -> dict | None:
    if profile is None:
        return None
    user = profile.user
    return {
        "id": user.id,
        "username": user.username or None,
        "email": user.email or None,
        "first_name": user.first_name or None,
        "last_name": user.last_name or None,
        "is_active": user.is_active,
    }


def serialize_project_profile(
    profile: Profile | None,
    *,
    company_colors_by_workspace_id: dict[int, str] | None = None,
) -> dict | None:
    if profile is None:
        return None
    return {
        "id": profile.id,
        "first_name": profile.first_name or None,
        "last_name": profile.last_name or None,
        "email": profile.email or None,
        "phone": profile.phone or None,
        "position": profile.position or None,
        "photo": file_url(profile.photo),
        "role": profile.role or None,
        "language": profile.language or None,
        "company": serialize_project_company(
            profile.workspace,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
        "user": serialize_project_user(profile),
    }


def serialize_project_team_member(
    member: ProjectMember,
    *,
    company_colors_by_workspace_id: dict[int, str] | None = None,
) -> dict:
    project_role_codes = project_member_assignment_role_codes(member)
    return {
        "id": member.id,
        "role": project_member_effective_role(member),
        "status": member.status,
        "disabled": member.disabled,
        "project_invitation_date": member.project_invitation_date,
        "project_role_codes": project_role_codes,
        "project_role_labels": project_assignment_role_labels(project_role_codes),
        "profile": serialize_project_profile(
            member.profile,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
    }


def calculate_project_progress(project: Project) -> int:
    annotated = getattr(project, "avg_task_progress", None)
    if annotated is not None:
        return normalize_project_progress(annotated)
    tasks = getattr(project, "prefetched_tasks_for_progress", None)
    if tasks is not None:
        if not tasks:
            return 0
        return normalize_project_progress(sum(task.progress for task in tasks) / len(tasks))
    return 0


def project_is_delayed(project: Project, *, progress: int) -> bool:
    if project.status in {ProjectStatus.CLOSED, ProjectStatus.DRAFT}:
        return False
    if progress >= 100:
        return False
    if not project.date_end:
        return False
    return project.date_end < timezone.localdate()


def serialize_project_summary(project: Project) -> dict:
    sync_project_archive_schedule(project=project, save=True)
    mark_project_archived_if_due(project=project, save=True)
    progress = calculate_project_progress(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or None,
        "address": project.address or None,
        "google_place_id": project.google_place_id or None,
        "latitude": project.latitude,
        "longitude": project.longitude,
        "date_start": project.date_start,
        "date_end": project.date_end,
        "status": project.status,
        "completed": progress,
        "logo": file_url(project.logo),
        "progress_percentage": progress,
        "team_count": getattr(project, "team_count", None),
        "alert_count": getattr(project, "alert_count", 0),
        "is_delayed": project_is_delayed(project, progress=progress),
        "has_coordinates": project.latitude is not None and project.longitude is not None,
        "location_source": project_location_source(project),
        "map_url": build_project_map_url(project),
        "closed_at": project.closed_at,
        "archive_due_at": project.archive_due_at,
        "archived_at": project.archived_at,
        "purge_due_at": project.purge_due_at,
        "last_export_at": project.last_export_at,
        "owner_export_sent_at": project.owner_export_sent_at,
    }


def project_access_queryset(profile: Profile):
    return (
        Project.objects.filter(
            members__profile=profile,
            members__status=ProjectMemberStatus.ACTIVE,
            members__disabled=False,
        )
        .select_related("workspace", "created_by__workspace", "created_by__user")
        .distinct()
    )


def get_project_membership(project: Project, profile: Profile) -> ProjectMember:
    membership = (
        ProjectMember.objects.select_related(
            "project", "profile", "profile__workspace", "profile__user"
        )
        .filter(
            project=project,
            profile=profile,
            status=ProjectMemberStatus.ACTIVE,
            disabled=False,
        )
        .first()
    )
    if membership is None:
        raise ValueError("Non hai accesso a questo progetto.")
    return ensure_project_member_role_alignment(membership)


def get_project_for_profile(*, profile: Profile, project_id: int) -> Project:
    project = (
        project_access_queryset(profile)
        .filter(id=project_id)
        .annotate(
            team_count=Count(
                "members",
                filter=Q(
                    members__status=ProjectMemberStatus.ACTIVE,
                    members__disabled=False,
                ),
                distinct=True,
            ),
            alert_count=Count(
                "posts",
                filter=Q(posts__alert=True, posts__is_deleted=False),
                distinct=True,
            ),
            avg_task_progress=Avg("tasks__progress"),
        )
        .first()
    )
    if project is None:
        raise ValueError("Progetto non trovato o non accessibile.")
    return project


def get_project_with_team_context(
    *, profile: Profile, project_id: int
) -> tuple[Project, ProjectMember, list[ProjectMember]]:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    membership = get_project_membership(project, profile)
    members = list(
        project.members.select_related("profile", "profile__workspace", "profile__user")
        .filter(disabled=False)
        .order_by("profile__first_name", "profile__last_name", "id")
    )
    return project, membership, [ensure_project_member_role_alignment(member) for member in members]


def project_company_colors_for_context(
    *,
    project: Project,
    members: list[ProjectMember] | None = None,
    tasks: list[ProjectTask] | None = None,
    profiles: list[Profile] | None = None,
    workspace_ids: list[int] | tuple[int, ...] | set[int] | None = None,
) -> dict[int, str]:
    company_workspace_ids = collect_project_company_workspace_ids(
        members=members,
        tasks=tasks,
        profiles=profiles,
        workspace_ids=workspace_ids,
    )
    return ensure_project_company_colors(project=project, workspace_ids=company_workspace_ids)


def list_projects(*, profile: Profile) -> list[dict]:
    projects = list(
        project_access_queryset(profile)
        .annotate(
            team_count=Count(
                "members",
                filter=Q(
                    members__status=ProjectMemberStatus.ACTIVE,
                    members__disabled=False,
                ),
                distinct=True,
            ),
            alert_count=Count(
                "posts",
                filter=Q(posts__alert=True, posts__is_deleted=False),
                distinct=True,
            ),
            avg_task_progress=Avg("tasks__progress"),
        )
        .order_by("-created_at", "-id")
    )
    return [serialize_project_summary(project) for project in projects]


def get_project_summary(*, profile: Profile, project_id: int) -> dict:
    return serialize_project_summary(
        get_project_for_profile(profile=profile, project_id=project_id)
    )


def serialize_task_context(task: ProjectTask | None) -> dict | None:
    if task is None:
        return None
    return {
        "id": task.id,
        "name": task.name,
        "alert": task.alert,
        "note": task.note or None,
    }


def serialize_activity_context(activity: ProjectActivity | None) -> dict | None:
    if activity is None:
        return None
    return {
        "id": activity.id,
        "title": activity.title,
        "status": activity.status,
        "progress": activity.progress,
        "datetime_start": activity.datetime_start,
        "datetime_end": activity.datetime_end,
        "alert": activity.alert,
        "note": activity.note or None,
    }


def serialize_attachment(attachment) -> dict:
    extension = attachment_extension(attachment.file)
    return {
        "id": attachment.id,
        "media_url": file_url(attachment.file),
        "size": attachment_size(attachment.file),
        "name": attachment_name(attachment.file),
        "extension": extension,
        "type": attachment_kind_from_extension(extension),
    }


def guess_download_content_type(file_name: str | None) -> str:
    content_type, _encoding = mimetypes.guess_type(file_name or "")
    return content_type or "application/octet-stream"


def build_inline_file_response(file_field, *, filename: str | None):
    if not file_field:
        raise ValueError("File non disponibile.")
    file_field.open("rb")
    response = FileResponse(file_field, content_type=guess_download_content_type(filename))
    if filename:
        response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def can_manage_project(membership: ProjectMember) -> bool:
    return project_member_effective_role(membership) in PROJECT_MANAGE_ROLES


def resolve_effective_project_role(
    *,
    project_workspace_id: int,
    profile: Profile,
    stored_role: str | None,
    is_external: bool = False,
) -> str:
    normalized_role = normalize_role(stored_role, default=WorkspaceRole.WORKER)
    if is_external or profile.workspace_id != project_workspace_id:
        return normalized_role

    workspace_role = normalize_role(profile.role, default=normalized_role)
    if get_role_priority(workspace_role) >= get_role_priority(normalized_role):
        return workspace_role
    return normalized_role


def project_member_effective_role(membership: ProjectMember) -> str:
    return resolve_effective_project_role(
        project_workspace_id=membership.project.workspace_id,
        profile=membership.profile,
        stored_role=membership.role,
        is_external=membership.is_external,
    )


def ensure_project_member_role_alignment(member: ProjectMember) -> ProjectMember:
    normalized_role = project_member_effective_role(member)
    normalized_is_external = member.profile.workspace_id != member.project.workspace_id
    update_fields: list[str] = []
    if member.role != normalized_role:
        member.role = normalized_role
        update_fields.append("role")
    if member.is_external != normalized_is_external:
        member.is_external = normalized_is_external
        update_fields.append("is_external")
    if update_fields:
        member.save(update_fields=update_fields)
    return member


def can_edit_project(membership: ProjectMember) -> bool:
    return project_member_effective_role(membership) in PROJECT_EDIT_ROLES


def can_edit_project_content(membership: ProjectMember, *, author_profile_id: int | None) -> bool:
    return membership.profile_id == author_profile_id or can_edit_project(membership)


def profile_display_name(profile: Profile | None) -> str:
    if profile is None:
        return "Qualcuno"
    name = " ".join(
        chunk
        for chunk in [profile.first_name or "", profile.last_name or ""]
        if chunk and chunk.strip()
    ).strip()
    return name or profile.email or profile.workspace.name or "Qualcuno"


def project_role_label(role: str | None) -> str:
    return PROJECT_ROLE_LABELS.get(role, (role or "Membro").strip().title() or "Membro")


def notification_excerpt(value: str | None, *, limit: int = 140) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def project_notification_recipients(
    project: Project,
    *,
    exclude_profile_ids: set[int] | None = None,
) -> list[Profile]:
    excluded = exclude_profile_ids or set()
    profiles = (
        Profile.objects.select_related("workspace", "user")
        .filter(
            project_memberships__project=project,
            project_memberships__status=ProjectMemberStatus.ACTIVE,
            project_memberships__disabled=False,
            is_active=True,
            workspace__is_active=True,
        )
        .distinct()
    )
    if excluded:
        profiles = profiles.exclude(id__in=excluded)
    return list(profiles.order_by("first_name", "last_name", "id"))


def project_participant_recipients(
    post: ProjectPost,
    *,
    exclude_profile_ids: set[int] | None = None,
) -> list[Profile]:
    participant_ids = set(
        PostComment.objects.filter(post=post, is_deleted=False)
        .exclude(author_id__isnull=True)
        .values_list("author_id", flat=True)
    )
    if post.author_id:
        participant_ids.add(post.author_id)
    if exclude_profile_ids:
        participant_ids -= exclude_profile_ids
    if not participant_ids:
        return []
    return list(
        Profile.objects.select_related("workspace", "user")
        .filter(id__in=participant_ids, is_active=True, workspace__is_active=True)
        .order_by("first_name", "last_name", "id")
    )


def resolve_project_mentioned_profiles(
    *,
    project: Project,
    mentioned_profile_ids: list[int] | None,
    exclude_profile_ids: set[int] | None = None,
) -> list[Profile]:
    normalized_ids = {
        int(profile_id)
        for profile_id in (mentioned_profile_ids or [])
        if isinstance(profile_id, int) or str(profile_id).isdigit()
    }
    if exclude_profile_ids:
        normalized_ids -= exclude_profile_ids
    if not normalized_ids:
        return []
    return list(
        Profile.objects.select_related("workspace", "user")
        .filter(
            id__in=normalized_ids,
            is_active=True,
            workspace__is_active=True,
            project_memberships__project=project,
            project_memberships__status=ProjectMemberStatus.ACTIVE,
            project_memberships__disabled=False,
        )
        .distinct()
        .order_by("first_name", "last_name", "id")
    )


def create_project_notification(
    *,
    recipient_profile: Profile,
    actor_profile: Profile | None,
    kind: str,
    subject: str,
    body: str = "",
    content_type: str = "",
    object_id: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    folder_id: int | None = None,
    document_id: int | None = None,
    data: dict | None = None,
) -> None:
    from edilcloud.modules.notifications.services import create_notification

    create_notification(
        recipient_profile=recipient_profile,
        sender_user=actor_profile.user
        if actor_profile is not None and actor_profile.user_id
        else None,
        sender_profile=actor_profile,
        sender_company_name=actor_profile.workspace.name if actor_profile is not None else "",
        sender_position=actor_profile.position if actor_profile is not None else "",
        subject=subject,
        body=body,
        kind=kind,
        content_type=content_type,
        object_id=object_id,
        project_id=project_id,
        task_id=task_id,
        activity_id=activity_id,
        post_id=post_id,
        comment_id=comment_id,
        folder_id=folder_id,
        document_id=document_id,
        data=data or {},
    )


def create_project_notification_from_blueprint(
    *,
    recipient_profile: Profile,
    actor_profile: Profile | None,
    blueprint: NotificationBlueprint,
) -> None:
    create_project_notification(
        recipient_profile=recipient_profile,
        actor_profile=actor_profile,
        kind=blueprint.kind,
        subject=blueprint.subject,
        body=blueprint.body,
        content_type=blueprint.content_type,
        object_id=blueprint.object_id,
        project_id=blueprint.project_id,
        task_id=blueprint.task_id,
        activity_id=blueprint.activity_id,
        post_id=blueprint.post_id,
        comment_id=blueprint.comment_id,
        folder_id=blueprint.folder_id,
        document_id=blueprint.document_id,
        data=blueprint.data,
    )


def notify_profiles(
    *,
    recipients: list[Profile],
    actor_profile: Profile | None,
    kind: str,
    subject: str,
    body: str = "",
    content_type: str = "",
    object_id: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    folder_id: int | None = None,
    document_id: int | None = None,
    data: dict | None = None,
) -> None:
    seen_profile_ids: set[int] = set()
    for recipient in recipients:
        if recipient.id in seen_profile_ids:
            continue
        seen_profile_ids.add(recipient.id)
        create_project_notification(
            recipient_profile=recipient,
            actor_profile=actor_profile,
            kind=kind,
            subject=subject,
            body=body,
            content_type=content_type,
            object_id=object_id,
            project_id=project_id,
            task_id=task_id,
            activity_id=activity_id,
            post_id=post_id,
            comment_id=comment_id,
            folder_id=folder_id,
            document_id=document_id,
            data=data,
        )


def notify_profiles_with_blueprint(
    *,
    recipients: list[Profile],
    actor_profile: Profile | None,
    blueprint: NotificationBlueprint,
) -> None:
    seen_profile_ids: set[int] = set()
    for recipient in recipients:
        if recipient.id in seen_profile_ids:
            continue
        seen_profile_ids.add(recipient.id)
        create_project_notification_from_blueprint(
            recipient_profile=recipient,
            actor_profile=actor_profile,
            blueprint=blueprint,
        )


def annotate_posts_with_feed_activity(queryset):
    return queryset.annotate(
        latest_comment_activity=Max("comments__updated_at"),
    ).annotate(
        effective_last_activity_at=Case(
            When(latest_comment_activity__isnull=True, then=F("updated_at")),
            When(latest_comment_activity__gt=F("updated_at"), then=F("latest_comment_activity")),
            default=F("updated_at"),
            output_field=DateTimeField(),
        ),
    )


def prefetch_post_feed_seen_state(queryset, *, profile: Profile | None):
    if profile is None:
        return queryset
    return queryset.prefetch_related(
        Prefetch(
            "seen_states",
            queryset=ProjectPostSeenState.objects.filter(profile=profile).order_by(
                "-seen_at", "-id"
            ),
            to_attr="_viewer_seen_states",
        ),
    )


def comment_activity_at(comment: PostComment) -> datetime | None:
    return comment.updated_at or comment.deleted_at or comment.edited_at or comment.created_at


def compute_post_last_activity_at(
    *,
    post: ProjectPost,
    comments: list[PostComment] | None = None,
) -> datetime | None:
    activity_at = getattr(post, "effective_last_activity_at", None) or post.updated_at
    effective_comments = comments if comments is not None else list(post.comments.all())
    for comment in effective_comments:
        candidate = comment_activity_at(comment)
        if candidate is not None and (activity_at is None or candidate > activity_at):
            activity_at = candidate
    return activity_at or post.published_date or post.created_at


def get_viewer_seen_state_for_post(
    *,
    post: ProjectPost,
    viewer_profile: Profile | None,
) -> ProjectPostSeenState | None:
    if viewer_profile is None:
        return None
    prefetched = getattr(post, "_viewer_seen_states", None)
    if isinstance(prefetched, list):
        return prefetched[0] if prefetched else None
    return (
        ProjectPostSeenState.objects.filter(post=post, profile=viewer_profile)
        .order_by("-seen_at", "-id")
        .first()
    )


def mark_post_seen_for_profile(
    *,
    post: ProjectPost,
    profile: Profile,
    seen_at: datetime | None = None,
) -> ProjectPostSeenState:
    timestamp = seen_at or compute_post_last_activity_at(post=post) or timezone.now()
    state, _created = ProjectPostSeenState.objects.update_or_create(
        post=post,
        profile=profile,
        defaults={"seen_at": timestamp},
    )
    setattr(post, "_viewer_seen_states", [state])
    return state


def emit_feed_refresh_for_post(
    *,
    post: ProjectPost,
    actor_profile: Profile | None,
    comment_id: int | None = None,
    action: str,
) -> None:
    emit_feed_realtime_events(
        recipients=project_notification_recipients(post.project),
        project_id=post.project_id,
        actor_profile=actor_profile,
        task_id=post.task_id,
        activity_id=post.activity_id,
        post_id=post.id,
        comment_id=comment_id,
        data={
            "action": action,
            "post_kind": post.post_kind,
            "alert": post.alert,
            "is_deleted": post.is_deleted,
        },
    )


def serialize_comment(
    comment: PostComment,
    *,
    membership: ProjectMember,
    comments_by_parent: dict[int | None, list[PostComment]] | None = None,
    company_colors_by_workspace_id: dict[int, str] | None = None,
    translation_by_comment_id: dict[int, PostCommentTranslation] | None = None,
) -> dict:
    replies = (
        comments_by_parent.get(comment.id, [])
        if comments_by_parent is not None
        else list(comment.replies.all())
    )
    localized_content = localized_comment_content(
        comment,
        translation=(translation_by_comment_id or {}).get(comment.id),
    )
    return {
        "id": comment.id,
        **localized_content,
        "is_deleted": comment.is_deleted,
        "deleted_at": comment.deleted_at,
        "edited_at": comment.edited_at,
        "can_edit": can_edit_project_content(membership, author_profile_id=comment.author_id),
        "can_delete": can_edit_project_content(membership, author_profile_id=comment.author_id),
        "unique_code": comment.unique_code,
        "created_date": comment.created_at,
        "parent": comment.parent_id,
        "media_set": [serialize_attachment(attachment) for attachment in comment.attachments.all()],
        "author": serialize_project_profile(
            comment.author,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
        "replies_set": [
            serialize_comment(
                reply,
                membership=membership,
                comments_by_parent=comments_by_parent,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
                translation_by_comment_id=translation_by_comment_id,
            )
            for reply in replies
        ],
    }


def serialize_comment_tree(
    *,
    comments: list[PostComment],
    membership: ProjectMember,
    company_colors_by_workspace_id: dict[int, str] | None = None,
    translation_by_comment_id: dict[int, PostCommentTranslation] | None = None,
) -> list[dict]:
    comments_by_parent: dict[int | None, list[PostComment]] = defaultdict(list)
    for comment in comments:
        comments_by_parent[comment.parent_id].append(comment)
    return [
        serialize_comment(
            comment,
            membership=membership,
            comments_by_parent=comments_by_parent,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_comment_id=translation_by_comment_id,
        )
        for comment in comments_by_parent.get(None, [])
    ]


def serialize_post(
    *,
    post: ProjectPost,
    membership: ProjectMember,
    comments: list[PostComment] | None = None,
    viewer_profile: Profile | None = None,
    effective_last_activity_at: datetime | None = None,
    company_colors_by_workspace_id: dict[int, str] | None = None,
    translation_by_post_id: dict[int, ProjectPostTranslation] | None = None,
    translation_by_comment_id: dict[int, PostCommentTranslation] | None = None,
) -> dict:
    effective_comments = comments if comments is not None else list(post.comments.all())
    last_activity_at = effective_last_activity_at or compute_post_last_activity_at(
        post=post,
        comments=effective_comments,
    )
    viewer_seen_state = get_viewer_seen_state_for_post(post=post, viewer_profile=viewer_profile)
    viewer_seen_at = viewer_seen_state.seen_at if viewer_seen_state is not None else None
    localized_content = localized_post_content(
        post,
        translation=(translation_by_post_id or {}).get(post.id),
    )
    return {
        "id": post.id,
        "author": serialize_project_profile(
            post.author,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
        "project": {
            "id": post.project_id,
            "name": post.project.name,
            "description": post.project.description or None,
            "date_start": post.project.date_start,
            "date_end": post.project.date_end,
            "shared_project": None,
        },
        "task": serialize_task_context(post.task),
        "sub_task": serialize_activity_context(post.activity),
        "published_date": post.published_date,
        "created_date": post.created_at,
        "last_activity_at": last_activity_at,
        "feed_seen_at": viewer_seen_at,
        "feed_is_unread": (
            bool(viewer_profile)
            and last_activity_at is not None
            and (viewer_seen_at is None or viewer_seen_at < last_activity_at)
        ),
        "post_kind": post.post_kind,
        **localized_content,
        "is_deleted": post.is_deleted,
        "deleted_at": post.deleted_at,
        "edited_at": post.edited_at,
        "can_edit": can_edit_project_content(membership, author_profile_id=post.author_id),
        "can_delete": can_edit_project_content(membership, author_profile_id=post.author_id),
        "alert": post.alert,
        "is_public": post.is_public,
        "unique_code": post.unique_code,
        "weather_snapshot": post.weather_snapshot or None,
        "media_set": [serialize_attachment(attachment) for attachment in post.attachments.all()],
        "comment_set": serialize_comment_tree(
            comments=effective_comments,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_comment_id=translation_by_comment_id,
        ),
    }


def serialize_post_summary(
    *,
    post: ProjectPost,
    membership: ProjectMember,
    viewer_profile: Profile | None = None,
    effective_last_activity_at: datetime | None = None,
    company_colors_by_workspace_id: dict[int, str] | None = None,
    translation_by_post_id: dict[int, ProjectPostTranslation] | None = None,
    translation_by_comment_id: dict[int, PostCommentTranslation] | None = None,
) -> dict:
    """Serialize the overview-safe post shape without the full comment tree."""
    last_activity_at = effective_last_activity_at or compute_post_last_activity_at(post=post)
    viewer_seen_state = get_viewer_seen_state_for_post(post=post, viewer_profile=viewer_profile)
    viewer_seen_at = viewer_seen_state.seen_at if viewer_seen_state is not None else None
    localized_content = localized_post_content(
        post,
        translation=(translation_by_post_id or {}).get(post.id),
    )
    return {
        "id": post.id,
        "author": serialize_project_profile(
            post.author,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
        "project": {
            "id": post.project_id,
            "name": post.project.name,
            "description": post.project.description or None,
            "date_start": post.project.date_start,
            "date_end": post.project.date_end,
            "shared_project": None,
        },
        "task": serialize_task_context(post.task),
        "sub_task": serialize_activity_context(post.activity),
        "published_date": post.published_date,
        "created_date": post.created_at,
        "last_activity_at": last_activity_at,
        "feed_seen_at": viewer_seen_at,
        "feed_is_unread": (
            bool(viewer_profile)
            and last_activity_at is not None
            and (viewer_seen_at is None or viewer_seen_at < last_activity_at)
        ),
        "post_kind": post.post_kind,
        **localized_content,
        "is_deleted": post.is_deleted,
        "deleted_at": post.deleted_at,
        "edited_at": post.edited_at,
        "can_edit": can_edit_project_content(membership, author_profile_id=post.author_id),
        "can_delete": can_edit_project_content(membership, author_profile_id=post.author_id),
        "alert": post.alert,
        "is_public": post.is_public,
        "unique_code": post.unique_code,
        "weather_snapshot": post.weather_snapshot or None,
        "media_set": [serialize_attachment(attachment) for attachment in post.attachments.all()],
        "comment_set": [],
    }


def serialize_activity(
    activity: ProjectActivity,
    *,
    project_members: list[ProjectMember],
    include_posts: bool = False,
    membership: ProjectMember | None = None,
    company_colors_by_workspace_id: dict[int, str] | None = None,
) -> dict:
    worker_ids = {worker.id for worker in activity.workers.all()}
    return {
        "id": activity.id,
        "title": activity.title,
        "description": activity.description or None,
        "status": activity.status,
        "progress": activity.progress,
        "datetime_start": activity.datetime_start,
        "datetime_end": activity.datetime_end,
        "alert": activity.alert,
        "starred": activity.starred,
        "note": activity.note or None,
        "workers": [
            serialize_project_profile(
                worker,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for worker in activity.workers.all()
        ],
        "media_set": [],
        "can_assign_in_activity": [
            serialize_project_team_member(
                member,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for member in project_members
        ],
        "workers_in_activity": [
            serialize_project_team_member(
                member,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for member in project_members
            if member.profile_id in worker_ids
        ],
        "post_set": (
            [
                serialize_post(
                    post=post,
                    membership=membership,
                    company_colors_by_workspace_id=company_colors_by_workspace_id,
                )
                for post in activity.posts.all()
            ]
            if include_posts and membership is not None
            else []
        ),
    }


def serialize_task(
    task: ProjectTask,
    *,
    project_members: list[ProjectMember],
    include_activity_posts: bool = False,
    membership: ProjectMember | None = None,
    company_colors_by_workspace_id: dict[int, str] | None = None,
) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "project": {
            "id": task.project_id,
            "name": task.project.name,
            "description": task.project.description or None,
            "date_start": task.project.date_start,
            "date_end": task.project.date_end,
            "shared_project": None,
        },
        "assigned_company": serialize_project_company(
            task.assigned_company,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        ),
        "date_start": task.date_start,
        "date_end": task.date_end,
        "date_completed": task.date_completed,
        "progress": task.progress,
        "status": task.status,
        "share_status": task.share_status,
        "shared_task": task.shared_task,
        "only_read": task.only_read,
        "alert": task.alert,
        "starred": task.starred,
        "note": task.note or None,
        "activities": [
            serialize_activity(
                activity,
                project_members=project_members,
                include_posts=include_activity_posts,
                membership=membership,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for activity in task.activities.all()
        ],
        "media_set": [],
    }


def schedule_link_entity_ref(
    *,
    task: ProjectTask | None = None,
    activity: ProjectActivity | None = None,
) -> str | None:
    if activity is not None:
        return f"activity-{activity.id}"
    if task is not None:
        return f"task-{task.id}"
    return None


def serialize_schedule_link(link: ProjectScheduleLink) -> dict:
    return {
        "id": link.id,
        "source": schedule_link_entity_ref(task=link.source_task, activity=link.source_activity),
        "target": schedule_link_entity_ref(task=link.target_task, activity=link.target_activity),
        "type": link.link_type,
        "lag_days": link.lag_days,
        "origin": link.origin or None,
    }


def project_schedule_links_queryset(project: Project):
    return project.schedule_links.select_related(
        "source_task",
        "source_activity",
        "target_task",
        "target_activity",
    ).order_by("id")


@transaction.atomic
def create_project_gantt_link(
    *,
    profile: Profile,
    project_id: int,
    source_ref: str,
    target_ref: str,
    link_type: str | None = None,
    lag_days: int | None = None,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare i vincoli del Gantt.")

    link = create_project_schedule_link_record(
        project=project,
        source_ref=source_ref,
        target_ref=target_ref,
        link_type=link_type,
        lag_days=lag_days,
        origin="manual",
        apply_constraints=True,
    )
    emit_project_realtime_event(
        event_type="schedule.link.created",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "task",
            "project_name": project.name,
            "source_ref": schedule_link_entity_ref(
                task=link.source_task, activity=link.source_activity
            ),
            "target_ref": schedule_link_entity_ref(
                task=link.target_task, activity=link.target_activity
            ),
            "link_type": link.link_type,
            "lag_days": link.lag_days,
            "origin": link.origin or None,
        },
    )
    return serialize_schedule_link(link)


@transaction.atomic
def update_project_gantt_link(
    *,
    profile: Profile,
    project_id: int,
    link_id: int,
    source_ref: str | None = None,
    target_ref: str | None = None,
    link_type: str | None = None,
    lag_days: int | None = None,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare i vincoli del Gantt.")

    link = project_schedule_links_queryset(project).filter(id=link_id).first()
    if link is None:
        raise ValueError("Vincolo Gantt non trovato.")

    previous_payload = serialize_schedule_link(link)
    link = update_project_schedule_link_record(
        link=link,
        source_ref=source_ref,
        target_ref=target_ref,
        link_type=link_type,
        lag_days=lag_days,
        apply_constraints=True,
    )
    emit_project_realtime_event(
        event_type="schedule.link.updated",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "task",
            "project_name": project.name,
            "source_ref": schedule_link_entity_ref(
                task=link.source_task, activity=link.source_activity
            ),
            "target_ref": schedule_link_entity_ref(
                task=link.target_task, activity=link.target_activity
            ),
            "link_type": link.link_type,
            "lag_days": link.lag_days,
            "changes": [
                build_timeline_change(
                    label="Sorgente",
                    before=previous_payload.get("source"),
                    after=schedule_link_entity_ref(
                        task=link.source_task, activity=link.source_activity
                    ),
                ),
                build_timeline_change(
                    label="Destinazione",
                    before=previous_payload.get("target"),
                    after=schedule_link_entity_ref(
                        task=link.target_task, activity=link.target_activity
                    ),
                ),
                build_timeline_change(
                    label="Tipo", before=previous_payload.get("type"), after=link.link_type
                ),
                build_timeline_change(
                    label="Lag", before=previous_payload.get("lag_days"), after=link.lag_days
                ),
            ],
        },
    )
    return serialize_schedule_link(link)


@transaction.atomic
def delete_project_gantt_link(
    *,
    profile: Profile,
    project_id: int,
    link_id: int,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare i vincoli del Gantt.")

    link = project_schedule_links_queryset(project).filter(id=link_id).first()
    if link is None:
        raise ValueError("Vincolo Gantt non trovato.")

    payload = serialize_schedule_link(link)
    delete_project_schedule_link_record(link=link)
    emit_project_realtime_event(
        event_type="schedule.link.deleted",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "task",
            "project_name": project.name,
            "source_ref": payload.get("source"),
            "target_ref": payload.get("target"),
            "link_type": payload.get("type"),
            "lag_days": payload.get("lag_days"),
        },
    )
    return {"deleted": True, "id": payload.get("id")}


def serialize_document(document: ProjectDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title or None,
        "description": document.description or None,
        "document": file_url(document.document),
        "date_create": document.created_at,
        "date_last_modify": document.updated_at,
        "extension": attachment_extension(document.document),
        "size": attachment_size(document.document),
        "relative_path": document.document.name if document.document else None,
        "folder_relative_path": document.folder.path if document.folder else None,
        "folder": document.folder_id,
    }


def serialize_drawing_pin(
    pin: ProjectDrawingPin,
    *,
    membership: ProjectMember,
    company_colors_by_workspace_id: dict[int, str] | None = None,
    translation_by_post_id: dict[int, ProjectPostTranslation] | None = None,
    translation_by_comment_id: dict[int, PostCommentTranslation] | None = None,
) -> dict:
    return {
        "id": pin.id,
        "project": pin.project_id,
        "drawing_document": serialize_document(pin.drawing_document),
        "post": serialize_post(
            post=pin.post,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=translation_by_post_id,
            translation_by_comment_id=translation_by_comment_id,
        ),
        "x": pin.x,
        "y": pin.y,
        "page_number": pin.page_number,
        "label": pin.label or "",
        "created_by": serialize_project_profile(
            pin.created_by,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        )
        if pin.created_by_id
        else None,
        "created_at": pin.created_at,
        "updated_at": pin.updated_at,
    }


def serialize_photo(photo: ProjectPhoto) -> dict:
    return {
        "id": photo.id,
        "title": photo.title or None,
        "pub_date": photo.created_at,
        "photo": file_url(photo.photo),
        "extension": attachment_extension(photo.photo),
        "size": attachment_size(photo.photo),
        "relative_path": photo.photo.name if photo.photo else None,
        "folder_relative_path": None,
    }


def serialize_folder(folder: ProjectFolder) -> dict:
    return {
        "id": folder.id,
        "name": folder.name,
        "parent": folder.parent_id,
        "path": folder.path or None,
        "is_public": folder.is_public,
        "is_root": folder.is_root,
    }


def list_project_team(*, profile: Profile, project_id: int) -> list[dict]:
    project, _membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    return [
        serialize_project_team_member(
            member,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        )
        for member in members
    ]


def get_project_team_compliance(*, profile: Profile, project_id: int) -> dict:
    _project, _membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )

    assigned_role_codes = normalize_project_assignment_role_codes(
        [code for member in members for code in project_member_assignment_role_codes(member)],
    )
    assigned_role_set = set(assigned_role_codes)
    execution_company_ids: set[int] = set()

    for member in members:
        company = getattr(member.profile, "workspace", None)
        if company and company.id and is_execution_company_type(company.workspace_type):
            execution_company_ids.add(company.id)

    requires_csp_cse = len(execution_company_ids) >= 2
    checks = [
        {
            "id": "committente",
            "label": "Committente",
            "required": True,
            "met": "committente" in assigned_role_set,
            "required_role_codes": ["committente"],
            "missing_role_codes": [] if "committente" in assigned_role_set else ["committente"],
            "missing_role_labels": [] if "committente" in assigned_role_set else ["Committente"],
        },
        {
            "id": "coordinators",
            "label": "Coordinatori (CSP/CSE)",
            "required": requires_csp_cse,
            "met": all(
                code in assigned_role_set for code in PROJECT_ASSIGNMENT_COORDINATOR_ROLE_CODES
            ),
            "reason": (
                "Obbligatorio quando nel cantiere operano piu imprese esecutrici o affidatarie."
                if requires_csp_cse
                else None
            ),
            "required_role_codes": PROJECT_ASSIGNMENT_COORDINATOR_ROLE_CODES,
            "missing_role_codes": [
                code
                for code in PROJECT_ASSIGNMENT_COORDINATOR_ROLE_CODES
                if code not in assigned_role_set
            ],
            "missing_role_labels": [
                project_assignment_role_label(code)
                for code in PROJECT_ASSIGNMENT_COORDINATOR_ROLE_CODES
                if code not in assigned_role_set
            ],
        },
        {
            "id": "rspp",
            "label": "RSPP",
            "required": True,
            "met": "rspp" in assigned_role_set,
            "required_role_codes": ["rspp"],
            "missing_role_codes": [] if "rspp" in assigned_role_set else ["rspp"],
            "missing_role_labels": [] if "rspp" in assigned_role_set else ["RSPP"],
        },
        {
            "id": "addetti_emergenza",
            "label": "Addetti Emergenza e Primo Soccorso",
            "required": True,
            "met": all(
                code in assigned_role_set for code in PROJECT_ASSIGNMENT_EMERGENCY_ROLE_CODES
            ),
            "required_role_codes": PROJECT_ASSIGNMENT_EMERGENCY_ROLE_CODES,
            "missing_role_codes": [
                code
                for code in PROJECT_ASSIGNMENT_EMERGENCY_ROLE_CODES
                if code not in assigned_role_set
            ],
            "missing_role_labels": [
                project_assignment_role_label(code)
                for code in PROJECT_ASSIGNMENT_EMERGENCY_ROLE_CODES
                if code not in assigned_role_set
            ],
        },
    ]

    return {
        "compliant": all(not check["required"] or check["met"] for check in checks),
        "execution_company_count": len(execution_company_ids),
        "requires_csp_cse": requires_csp_cse,
        "assigned_role_codes": assigned_role_codes,
        "assigned_role_labels": project_assignment_role_labels(assigned_role_codes),
        "checks": checks,
        "missing_requirements": [
            check for check in checks if check["required"] and not check["met"]
        ],
    }


def project_tasks_queryset(project: Project):
    return (
        project.tasks.select_related("project", "assigned_company")
        .prefetch_related(
            Prefetch(
                "activities",
                queryset=ProjectActivity.objects.order_by("datetime_start", "id").prefetch_related(
                    "workers"
                ),
            )
        )
        .order_by("date_start", "id")
    )


def list_project_tasks(*, profile: Profile, project_id: int) -> list[dict]:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    tasks = list(project_tasks_queryset(project))
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=tasks,
    )
    return [
        serialize_task(
            task,
            project_members=members,
            include_activity_posts=False,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        )
        for task in tasks
    ]


def build_project_gantt_company_lookup(
    *,
    project: Project,
    members: list[ProjectMember],
) -> dict[str, Workspace]:
    task_workspace_ids = list(
        project.tasks.exclude(assigned_company_id__isnull=True).values_list(
            "assigned_company_id", flat=True
        )
    )
    company_workspace_ids = collect_project_company_workspace_ids(
        members=members,
        workspace_ids=[project.workspace_id, *task_workspace_ids],
    )
    lookup: dict[str, Workspace] = {}
    for workspace in Workspace.objects.filter(id__in=company_workspace_ids, is_active=True):
        for token in {
            normalize_import_lookup(workspace.name),
            normalize_import_lookup(workspace.slug),
            normalize_import_lookup(workspace.email),
        }:
            if token and token not in lookup:
                lookup[token] = workspace
    return lookup


def resolve_project_import_company(
    *,
    lookup: dict[str, Workspace],
    label: str | None,
) -> Workspace | None:
    normalized_label = normalize_import_lookup(label)
    return lookup.get(normalized_label) if normalized_label else None


def serialize_gantt_import_warning(warning: ImportWarning) -> dict:
    return {
        "code": warning.code,
        "message": warning.message,
        "level": warning.level,
    }


def serialize_gantt_import_phase(phase: ImportedPhase) -> dict:
    return {
        "ref": phase.ref,
        "name": phase.name,
        "date_start": phase.date_start,
        "date_end": phase.date_end,
        "progress": phase.progress,
        "company_label": phase.company_label or None,
        "note": phase.note or None,
        "activity_count": len(phase.activities),
        "activities": [
            {
                "ref": activity.ref,
                "title": activity.title,
                "date_start": activity.date_start,
                "date_end": activity.date_end,
                "progress": activity.progress,
                "description": activity.description or None,
                "note": activity.note or None,
            }
            for activity in phase.activities
        ],
    }


def serialize_gantt_import_link(link: ImportedLink) -> dict:
    return {
        "source_ref": link.source_ref,
        "target_ref": link.target_ref,
        "type": link.link_type,
        "lag_days": link.lag_days,
    }


def build_project_gantt_import_preview(
    *,
    project: Project,
    members: list[ProjectMember],
    imported_plan: ImportedPlan,
) -> dict:
    company_lookup = build_project_gantt_company_lookup(project=project, members=members)
    unresolved_company_labels = [
        label
        for label in imported_plan.detected_company_labels
        if label and resolve_project_import_company(lookup=company_lookup, label=label) is None
    ]
    unresolved_company_labels = list(dict.fromkeys(unresolved_company_labels))
    warnings = [*imported_plan.warnings]
    warnings.extend(
        ImportWarning(
            code="unresolved-company",
            message=f"Azienda '{label}' non trovata nel progetto: la fase verra importata senza assegnazione.",
        )
        for label in unresolved_company_labels
    )
    activity_count = sum(len(phase.activities) for phase in imported_plan.phases)
    return {
        "detected_format": imported_plan.detected_format,
        "source_system": imported_plan.source_system,
        "summary": {
            "phases": len(imported_plan.phases),
            "activities": activity_count,
            "links": len(imported_plan.links),
            "warnings": len(warnings),
            "unresolved_companies": len(unresolved_company_labels),
        },
        "phases": [serialize_gantt_import_phase(phase) for phase in imported_plan.phases],
        "links": [serialize_gantt_import_link(link) for link in imported_plan.links],
        "warnings": [serialize_gantt_import_warning(warning) for warning in warnings],
        "detected_companies": imported_plan.detected_company_labels,
        "unresolved_companies": unresolved_company_labels,
        "replace_supported": True,
    }


def create_project_schedule_link(
    *,
    project: Project,
    imported_link: ImportedLink,
    ref_to_task: dict[str, ProjectTask],
    ref_to_activity: dict[str, ProjectActivity],
) -> None:
    source_task = ref_to_task.get(imported_link.source_ref)
    source_activity = ref_to_activity.get(imported_link.source_ref)
    target_task = ref_to_task.get(imported_link.target_ref)
    target_activity = ref_to_activity.get(imported_link.target_ref)
    if (source_task is None) == (source_activity is None):
        return
    if (target_task is None) == (target_activity is None):
        return
    source_ref = schedule_link_entity_ref(task=source_task, activity=source_activity)
    target_ref = schedule_link_entity_ref(task=target_task, activity=target_activity)
    if not source_ref or not target_ref:
        return
    try:
        create_project_schedule_link_record(
            project=project,
            source_ref=source_ref,
            target_ref=target_ref,
            link_type=(
                imported_link.link_type
                if imported_link.link_type in ProjectScheduleLinkType.values
                else ProjectScheduleLinkType.END_TO_START
            ),
            lag_days=imported_link.lag_days,
            origin="import",
            apply_constraints=False,
        )
    except ValueError:
        return


def preview_project_gantt_import(*, profile: Profile, project_id: int, uploaded_file) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per importare il Gantt di questo progetto.")
    imported_plan = parse_gantt_import_file(uploaded_file)
    return build_project_gantt_import_preview(
        project=project,
        members=members,
        imported_plan=imported_plan,
    )


@transaction.atomic
def apply_project_gantt_import(
    *,
    profile: Profile,
    project_id: int,
    uploaded_file,
    replace_existing: bool = False,
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per importare il Gantt di questo progetto.")

    imported_plan = parse_gantt_import_file(uploaded_file)
    preview = build_project_gantt_import_preview(
        project=project,
        members=members,
        imported_plan=imported_plan,
    )
    company_lookup = build_project_gantt_company_lookup(project=project, members=members)

    if replace_existing:
        project.schedule_links.all().delete()
        project.tasks.all().delete()

    ref_to_task: dict[str, ProjectTask] = {}
    ref_to_activity: dict[str, ProjectActivity] = {}
    created_tasks: list[ProjectTask] = []
    created_activity_count = 0

    for phase in imported_plan.phases:
        company = resolve_project_import_company(lookup=company_lookup, label=phase.company_label)
        task = ProjectTask.objects.create(
            project=project,
            name=normalize_text(phase.name) or "Fase importata",
            assigned_company=company,
            date_start=phase.date_start,
            date_end=phase.date_end,
            progress=normalize_project_progress(phase.progress),
            note=normalize_text(phase.note),
        )
        ref_to_task[phase.ref] = task
        created_tasks.append(task)

        for activity_seed in phase.activities:
            activity_start_date = require_imported_calendar_date(
                activity_seed.date_start,
                label=f"Data inizio attivita '{normalize_text(activity_seed.title) or 'importata'}'",
            )
            activity_end_date = require_imported_calendar_date(
                activity_seed.date_end,
                label=f"Data fine attivita '{normalize_text(activity_seed.title) or 'importata'}'",
            )
            start_at = timezone.make_aware(
                datetime.combine(activity_start_date, datetime.min.time()),
                timezone.get_current_timezone(),
            )
            end_at = timezone.make_aware(
                datetime.combine(activity_end_date, datetime.min.time()),
                timezone.get_current_timezone(),
            )
            activity = ProjectActivity.objects.create(
                task=task,
                title=normalize_text(activity_seed.title) or "Attivita importata",
                description=normalize_text(activity_seed.description),
                status=task_activity_progress_to_status(activity_seed.progress),
                progress=normalize_project_progress(activity_seed.progress),
                datetime_start=start_at,
                datetime_end=end_at,
                note=normalize_text(activity_seed.note),
            )
            ref_to_activity[activity_seed.ref] = activity
            created_activity_count += 1

    project_company_colors_for_context(project=project, members=members, tasks=created_tasks)
    for imported_link in imported_plan.links:
        create_project_schedule_link(
            project=project,
            imported_link=imported_link,
            ref_to_task=ref_to_task,
            ref_to_activity=ref_to_activity,
        )

    emit_project_realtime_event(
        event_type="gantt.imported",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "task",
            "project_name": project.name,
            "replace_existing": replace_existing,
            "phase_count": len(created_tasks),
            "activity_count": created_activity_count,
            "link_count": len(imported_plan.links),
            "detected_format": imported_plan.detected_format,
            "source_system": imported_plan.source_system,
        },
    )
    return {
        **preview,
        "applied": True,
        "replace_existing": replace_existing,
    }


def list_project_gantt(*, profile: Profile, project_id: int) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    tasks = list(project_tasks_queryset(project))
    schedule_links = list(project_schedule_links_queryset(project))
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=tasks,
    )
    return {
        "tasks": [
            serialize_task(
                task,
                project_members=members,
                include_activity_posts=False,
                membership=membership,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for task in tasks
        ],
        "links": [serialize_schedule_link(link) for link in schedule_links],
    }


def list_project_documents(*, profile: Profile, project_id: int) -> list[dict]:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    documents = list(project.documents.select_related("folder").order_by("-updated_at", "-id"))
    return [serialize_document(document) for document in documents]


def normalize_pin_coordinate(value: float | int | str, *, field_name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Coordinata {field_name} non valida.") from exc
    if normalized < 0 or normalized > 1:
        raise ValueError(f"Coordinata {field_name} fuori dal disegno.")
    return normalized


def normalize_pin_page_number(value: int | str | None) -> int:
    try:
        normalized = int(value or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Pagina disegno non valida.") from exc
    if normalized < 1:
        raise ValueError("Pagina disegno non valida.")
    return normalized


def drawing_pin_queryset():
    return ProjectDrawingPin.objects.select_related(
        "project",
        "drawing_document",
        "drawing_document__folder",
        "post",
        "post__author",
        "post__author__workspace",
        "post__author__user",
        "post__task",
        "post__activity",
        "post__project",
        "created_by",
        "created_by__workspace",
        "created_by__user",
    ).prefetch_related(
        "post__attachments",
        Prefetch(
            "post__comments",
            queryset=PostComment.objects.select_related(
                "author",
                "author__workspace",
                "author__user",
            )
            .prefetch_related("attachments")
            .order_by("created_at", "id"),
        ),
    )


def list_project_drawing_pins(
    *,
    profile: Profile,
    project_id: int,
    target_language: str | None = None,
) -> list[dict]:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    pins = list(drawing_pin_queryset().filter(project=project))
    posts = [pin.post for pin in pins]
    comments = [comment for post in posts for comment in post.comments.all()]
    post_translation_map = resolve_post_translation_memory(
        posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        comments,
        target_language=target_language,
        fallback_language=profile.language,
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    return [
        serialize_drawing_pin(
            pin,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for pin in pins
    ]


def upsert_project_drawing_pin(
    *,
    profile: Profile,
    project_id: int,
    drawing_document_id: int,
    post_id: int,
    x: float,
    y: float,
    page_number: int = 1,
    label: str = "",
    target_language: str | None = None,
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    document = project.documents.filter(id=drawing_document_id).first()
    if document is None:
        raise ValueError("Disegno non trovato nel progetto.")

    post = project_posts_queryset().filter(project=project, id=post_id, is_deleted=False).first()
    if post is None:
        raise ValueError("Post non trovato nel progetto.")

    normalized_x = normalize_pin_coordinate(x, field_name="x")
    normalized_y = normalize_pin_coordinate(y, field_name="y")
    normalized_page = normalize_pin_page_number(page_number)
    trimmed_label = (label or "").strip()[:255]

    pin, _created = ProjectDrawingPin.objects.update_or_create(
        drawing_document=document,
        post=post,
        defaults={
            "project": project,
            "created_by": profile,
            "x": normalized_x,
            "y": normalized_y,
            "page_number": normalized_page,
            "label": trimmed_label,
        },
    )
    pin = drawing_pin_queryset().get(id=pin.id)
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        [pin.post],
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        list(pin.post.comments.all()),
        target_language=target_language,
        fallback_language=profile.language,
    )
    return serialize_drawing_pin(
        pin,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_post_id=post_translation_map,
        translation_by_comment_id=comment_translation_map,
    )


def update_project_drawing_pin(
    *,
    profile: Profile,
    project_id: int,
    pin_id: int,
    drawing_document_id: int | None = None,
    post_id: int | None = None,
    x: float | None = None,
    y: float | None = None,
    page_number: int | None = None,
    label: str | None = None,
    target_language: str | None = None,
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    pin = ProjectDrawingPin.objects.filter(project=project, id=pin_id).first()
    if pin is None:
        raise ValueError("Pin disegno non trovato.")

    if drawing_document_id is not None:
        document = project.documents.filter(id=drawing_document_id).first()
        if document is None:
            raise ValueError("Disegno non trovato nel progetto.")
        pin.drawing_document = document
    if post_id is not None:
        post = project.posts.filter(id=post_id, is_deleted=False).first()
        if post is None:
            raise ValueError("Post non trovato nel progetto.")
        pin.post = post
    if x is not None:
        pin.x = normalize_pin_coordinate(x, field_name="x")
    if y is not None:
        pin.y = normalize_pin_coordinate(y, field_name="y")
    if page_number is not None:
        pin.page_number = normalize_pin_page_number(page_number)
    if label is not None:
        pin.label = label.strip()[:255]
    pin.save()

    pin = drawing_pin_queryset().get(id=pin.id)
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        [pin.post],
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        list(pin.post.comments.all()),
        target_language=target_language,
        fallback_language=profile.language,
    )
    return serialize_drawing_pin(
        pin,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_post_id=post_translation_map,
        translation_by_comment_id=comment_translation_map,
    )


def delete_project_drawing_pin(*, profile: Profile, project_id: int, pin_id: int) -> None:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    deleted, _ = ProjectDrawingPin.objects.filter(project=project, id=pin_id).delete()
    if not deleted:
        raise ValueError("Pin disegno non trovato.")


def list_project_photos(*, profile: Profile, project_id: int) -> list[dict]:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    photos = list(project.photos.order_by("-created_at", "-id"))
    return [serialize_photo(photo) for photo in photos]


def get_project_document_file_response(*, profile: Profile, document_id: int):
    document = ProjectDocument.objects.select_related("project").filter(id=document_id).first()
    if document is None:
        raise ValueError("Documento non trovato.")
    get_project_with_team_context(profile=profile, project_id=document.project_id)
    file_name = (
        Path(document.document.name).name if document.document else document.title or "documento"
    )
    return build_inline_file_response(document.document, filename=file_name)


def get_project_photo_file_response(*, profile: Profile, photo_id: int):
    photo = ProjectPhoto.objects.select_related("project").filter(id=photo_id).first()
    if photo is None:
        raise ValueError("Foto non trovata.")
    get_project_with_team_context(profile=profile, project_id=photo.project_id)
    file_name = Path(photo.photo.name).name if photo.photo else photo.title or "foto"
    return build_inline_file_response(photo.photo, filename=file_name)


def list_project_folders(*, profile: Profile, project_id: int) -> list[dict]:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    folders = list(project.folders.select_related("parent").order_by("path", "id"))
    return [serialize_folder(folder) for folder in folders]


def project_posts_queryset():
    return ProjectPost.objects.select_related(
        "author",
        "author__workspace",
        "author__user",
        "task",
        "activity",
        "project",
    ).prefetch_related(
        "attachments",
        Prefetch(
            "comments",
            queryset=PostComment.objects.select_related(
                "author",
                "author__workspace",
                "author__user",
            )
            .prefetch_related("attachments")
            .order_by("created_at", "id"),
        ),
    )


def list_project_alert_posts(
    *,
    profile: Profile,
    project_id: int,
    lightweight: bool = False,
    target_language: str | None = None,
) -> list[dict]:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    posts = list(
        annotate_posts_with_feed_activity(project_posts_queryset())
        .filter(project=project, alert=True, is_deleted=False)
        .order_by("-effective_last_activity_at", "-id")
    )
    serializer = serialize_post_summary if lightweight else serialize_post
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = (
        {}
        if lightweight
        else resolve_comment_translation_memory(
            [comment for post in posts for comment in post.comments.all()],
            target_language=target_language,
            fallback_language=profile.language,
        )
    )
    return [
        serializer(
            post=post,
            membership=membership,
            effective_last_activity_at=getattr(post, "effective_last_activity_at", None),
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for post in posts
    ]


def list_project_recent_posts(
    *,
    profile: Profile,
    project_id: int,
    limit: int = 8,
    lightweight: bool = False,
    target_language: str | None = None,
) -> list[dict]:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    posts = list(
        annotate_posts_with_feed_activity(project_posts_queryset())
        .filter(project=project, is_deleted=False)
        .order_by("-effective_last_activity_at", "-id")[:limit]
    )
    serializer = serialize_post_summary if lightweight else serialize_post
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = (
        {}
        if lightweight
        else resolve_comment_translation_memory(
            [comment for post in posts for comment in post.comments.all()],
            target_language=target_language,
            fallback_language=profile.language,
        )
    )
    return [
        serializer(
            post=post,
            membership=membership,
            effective_last_activity_at=getattr(post, "effective_last_activity_at", None),
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for post in posts
    ]


def list_project_feed(
    *,
    profile: Profile,
    limit: int = 50,
    offset: int = 0,
    target_language: str | None = None,
) -> dict:
    safe_limit = min(max(int(limit or 50), 1), 250)
    safe_offset = max(int(offset or 0), 0)

    queryset = accessible_feed_posts_queryset(profile=profile)
    posts = list(
        queryset.order_by("-effective_last_activity_at", "-id")[
            safe_offset : safe_offset + safe_limit + 1
        ]
    )
    page_posts = posts[:safe_limit]
    membership_by_project_id = {
        membership.project_id: membership
        for membership in ProjectMember.objects.filter(
            profile=profile,
            project_id__in={post.project_id for post in page_posts},
            status=ProjectMemberStatus.ACTIVE,
            disabled=False,
        ).select_related("profile")
    }
    post_translation_map = resolve_post_translation_memory(
        page_posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        [comment for post in page_posts for comment in post.comments.all()],
        target_language=target_language,
        fallback_language=profile.language,
    )

    items = [
        serialize_post(
            post=post,
            membership=membership_by_project_id[post.project_id],
            viewer_profile=profile,
            effective_last_activity_at=getattr(post, "effective_last_activity_at", None),
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for post in page_posts
        if post.project_id in membership_by_project_id
    ]

    has_more = len(posts) > safe_limit
    return {
        "items": items,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": has_more,
        "next_offset": safe_offset + safe_limit if has_more else None,
    }


def accessible_feed_posts_queryset(*, profile: Profile):
    accessible_project_ids = ProjectMember.objects.filter(
        profile=profile,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        project__workspace__is_active=True,
    ).values_list("project_id", flat=True)

    return prefetch_post_feed_seen_state(
        annotate_posts_with_feed_activity(project_posts_queryset()).filter(
            project_id__in=accessible_project_ids
        ),
        profile=profile,
    )


@transaction.atomic
def mark_feed_post_seen(*, profile: Profile, post_id: int) -> dict:
    post, _membership = get_post_for_profile(profile=profile, post_id=post_id)
    state = mark_post_seen_for_profile(post=post, profile=profile)
    return {
        "post_id": post.id,
        "seen_at": state.seen_at,
        "is_unread": False,
    }


@transaction.atomic
def mark_feed_posts_seen(*, profile: Profile, post_ids: list[int] | None = None) -> dict:
    normalized_ids: list[int] = []
    seen_ids: set[int] = set()
    for raw_value in post_ids or []:
        try:
            normalized_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)

    if not normalized_ids:
        return {"count": 0, "items": []}

    posts = {
        post.id: post
        for post in accessible_feed_posts_queryset(profile=profile).filter(id__in=normalized_ids)
    }
    items: list[dict] = []
    for post_id in normalized_ids:
        post = posts.get(post_id)
        if post is None:
            continue
        state = mark_post_seen_for_profile(post=post, profile=profile)
        items.append(
            {
                "post_id": post.id,
                "seen_at": state.seen_at,
                "is_unread": False,
            }
        )

    return {
        "count": len(items),
        "items": items,
    }


def get_project_overview(
    *, profile: Profile, project_id: int, target_language: str | None = None
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    tasks = list(project_tasks_queryset(project))
    documents = list(project.documents.select_related("folder").order_by("-updated_at", "-id"))
    photos = list(project.photos.order_by("-created_at", "-id"))
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=tasks,
    )
    alert_posts = list_project_alert_posts(
        profile=profile,
        project_id=project_id,
        lightweight=True,
        target_language=target_language,
    )
    recent_posts = list_project_recent_posts(
        profile=profile,
        project_id=project_id,
        lightweight=True,
        target_language=target_language,
    )

    return {
        "tasks": [
            serialize_task(
                task,
                project_members=members,
                include_activity_posts=False,
                membership=membership,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for task in tasks
        ],
        "team": [
            serialize_project_team_member(
                member,
                company_colors_by_workspace_id=company_colors_by_workspace_id,
            )
            for member in members
        ],
        "documents": [serialize_document(document) for document in documents],
        "photos": [serialize_photo(photo) for photo in photos],
        "alertPosts": alert_posts,
        "recentPosts": recent_posts,
        "failures": [],
    }


def list_posts_for_task(
    *, profile: Profile, task_id: int, target_language: str | None = None
) -> list[dict]:
    task = ProjectTask.objects.select_related("project").filter(id=task_id).first()
    if task is None:
        raise ValueError("Task non trovato.")
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=task.project_id
    )
    posts = list(
        project_posts_queryset()
        .filter(task=task, activity__isnull=True)
        .order_by("-published_date", "-id")
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        [comment for post in posts for comment in post.comments.all()],
        target_language=target_language,
        fallback_language=profile.language,
    )
    return [
        serialize_post(
            post=post,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for post in posts
    ]


def list_posts_for_activity(
    *, profile: Profile, activity_id: int, target_language: str | None = None
) -> list[dict]:
    activity = (
        ProjectActivity.objects.select_related("task", "task__project")
        .filter(id=activity_id)
        .first()
    )
    if activity is None:
        raise ValueError("Attivita non trovata.")
    project, membership, members = get_project_with_team_context(
        profile=profile,
        project_id=activity.task.project_id,
    )
    posts = list(
        project_posts_queryset().filter(activity=activity).order_by("-published_date", "-id")
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project, members=members
    )
    post_translation_map = resolve_post_translation_memory(
        posts,
        target_language=target_language,
        fallback_language=profile.language,
    )
    comment_translation_map = resolve_comment_translation_memory(
        [comment for post in posts for comment in post.comments.all()],
        target_language=target_language,
        fallback_language=profile.language,
    )
    return [
        serialize_post(
            post=post,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=post_translation_map,
            translation_by_comment_id=comment_translation_map,
        )
        for post in posts
    ]


@transaction.atomic
def create_project(
    *,
    profile: Profile,
    name: str,
    description: str = "",
    address: str = "",
    google_place_id: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    date_start: date,
    date_end: date | None = None,
) -> dict:
    if not normalize_text(name):
        raise ValueError("Il nome del progetto e obbligatorio.")

    normalized_address = normalize_text(address)
    resolved_latitude, resolved_longitude = resolve_project_coordinates(
        address=normalized_address,
        latitude=latitude,
        longitude=longitude,
    )

    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name=normalize_text(name),
        description=normalize_text(description),
        address=normalized_address,
        google_place_id=normalize_text(google_place_id),
        latitude=resolved_latitude,
        longitude=resolved_longitude,
        date_start=date_start,
        date_end=date_end,
        status=ProjectStatus.ACTIVE,
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=resolve_effective_project_role(
            project_workspace_id=project.workspace_id,
            profile=profile,
            stored_role=profile.role,
            is_external=False,
        ),
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        is_external=False,
    )
    ensure_project_company_colors(project=project, workspace_ids=[profile.workspace_id])
    project.team_count = 1
    project.alert_count = 0
    project.avg_task_progress = 0
    return serialize_project_summary(project)


def resolve_project_member_profile_ids(*, project: Project, ids: list[int]) -> list[Profile]:
    if not ids:
        return []
    members = list(
        ProjectMember.objects.select_related("profile").filter(
            project=project,
            profile_id__in=ids,
            status=ProjectMemberStatus.ACTIVE,
            disabled=False,
        )
    )
    found_ids = {member.profile_id for member in members}
    missing = sorted(set(ids) - found_ids)
    if missing:
        raise ValueError("Alcuni profili selezionati non fanno parte del progetto.")
    by_id = {member.profile_id: member.profile for member in members}
    return [by_id[profile_id] for profile_id in ids if profile_id in by_id]


@transaction.atomic
def add_project_team_member(
    *,
    profile: Profile,
    project_id: int,
    target_profile_id: int,
    role: str,
    is_external: bool = False,
    project_role_codes: list[str] | None = None,
) -> dict:
    del is_external

    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_manage_project(membership):
        raise ValueError("Non hai permessi per invitare membri su questo progetto.")

    target_profile = (
        Profile.objects.select_related("workspace", "user")
        .filter(id=target_profile_id, is_active=True, workspace__is_active=True)
        .first()
    )
    if target_profile is None:
        raise ValueError("Profilo progetto non valido.")

    member, _created = ProjectMember.objects.update_or_create(
        project=project,
        profile=target_profile,
        defaults={
            "role": resolve_effective_project_role(
                project_workspace_id=project.workspace_id,
                profile=target_profile,
                stored_role=normalize_role(role, default=WorkspaceRole.WORKER),
                is_external=target_profile.workspace_id != project.workspace_id,
            ),
            "status": ProjectMemberStatus.ACTIVE,
            "disabled": False,
            "is_external": target_profile.workspace_id != project.workspace_id,
            "project_invitation_date": timezone.now(),
            "project_role_codes": normalize_project_assignment_role_codes(project_role_codes),
        },
    )
    member = ensure_project_member_role_alignment(member)
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=[member],
        workspace_ids=[profile.workspace_id, target_profile.workspace_id],
    )
    emit_project_realtime_event(
        event_type="team.member.added",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "team",
            "project_level": True,
            "project_name": project.name,
            "member_name": profile_display_name(target_profile),
            "member_role": project_role_label(project_member_effective_role(member)),
            "member_company_name": target_profile.workspace.name
            if target_profile.workspace_id
            else None,
        },
    )
    create_project_notification_from_blueprint(
        recipient_profile=target_profile,
        actor_profile=profile,
        blueprint=build_project_member_added_notification(
            project=project,
            member=member,
            target_profile=target_profile,
            actor_profile=profile,
            role_label=project_role_label(project_member_effective_role(member)),
        ),
    )
    return serialize_project_team_member(
        member,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


@transaction.atomic
def update_project_team_member(
    *,
    profile: Profile,
    project_id: int,
    member_id: int,
    company_color_project: str | None = None,
    project_role_codes: list[str] | None = None,
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_manage_project(membership):
        raise ValueError("Non hai permessi per gestire questo membro del progetto.")

    member = (
        ProjectMember.objects.select_related(
            "project", "profile", "profile__workspace", "profile__user"
        )
        .filter(project=project, id=member_id, disabled=False)
        .first()
    )
    if member is None:
        raise ValueError("Membro progetto non trovato.")

    workspace_id = member.profile.workspace_id if member.profile_id else None
    if workspace_id is None:
        raise ValueError("Membro senza azienda associata.")

    if company_color_project is not None:
        normalized_color = normalize_project_company_color(company_color_project)
        if normalized_color is None:
            raise ValueError("Colore non valido. Usa un valore HEX (#RRGGBB).")
        ProjectCompanyColor.objects.update_or_create(
            project=project,
            workspace_id=workspace_id,
            defaults={"color_project": normalized_color},
        )
        emit_project_realtime_event(
            event_type="team.member.color.updated",
            project_id=project.id,
            actor_profile=profile,
            data={
                "category": "team",
                "project_level": True,
                "project_name": project.name,
                "member_id": member.id,
                "workspace_id": workspace_id,
                "company_color_project": normalized_color,
            },
        )

    if project_role_codes is not None:
        normalized_codes = normalize_project_assignment_role_codes(project_role_codes)
        if member.project_role_codes != normalized_codes:
            member.project_role_codes = normalized_codes
            member.save(update_fields=["project_role_codes", "updated_at"])
        emit_project_realtime_event(
            event_type="team.member.roles.updated",
            project_id=project.id,
            actor_profile=profile,
            data={
                "category": "team",
                "project_level": True,
                "project_name": project.name,
                "member_id": member.id,
                "workspace_id": workspace_id,
                "project_role_codes": normalized_codes,
                "project_role_labels": project_assignment_role_labels(normalized_codes),
            },
        )

    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        workspace_ids=[workspace_id],
    )
    return serialize_project_team_member(
        member,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


@transaction.atomic
def generate_project_invite(
    *,
    profile: Profile,
    project_id: int,
    email: str,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_manage_project(membership):
        raise ValueError("Non hai permessi per invitare aziende o collaboratori esterni.")

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("L'email da invitare e obbligatoria.")

    invite = ProjectInviteCode.objects.create(
        project=project,
        created_by=profile,
        email=normalized_email,
        expires_at=timezone.now() + timedelta(days=14),
    )
    send_project_invite_code_email(
        to_email=invite.email,
        project_name=project.name,
        inviter_name=profile.member_name,
        invite_code=invite.unique_code,
    )
    emit_project_realtime_event(
        event_type="invite.created",
        project_id=project.id,
        actor_profile=profile,
        data={
            "category": "team",
            "project_level": True,
            "project_name": project.name,
            "invite_email": invite.email,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        },
    )

    recipient_profile = resolve_existing_profile_for_email(invite.email)
    if recipient_profile is not None and recipient_profile.id != profile.id:
        blueprint = build_project_invite_notification(
            invite=invite,
            inviter_profile=profile,
        )
        create_project_notification_from_blueprint(
            recipient_profile=recipient_profile,
            actor_profile=profile,
            blueprint=blueprint,
        )

    return {
        "id": invite.id,
        "email": invite.email,
        "project": project.id,
        "status": invite.status,
        "unique_code": invite.unique_code,
    }


@transaction.atomic
def create_project_task(
    *,
    profile: Profile,
    project_id: int,
    name: str,
    assigned_company_id: int | None,
    date_start: date,
    date_end: date,
    progress: int = 0,
    note: str = "",
    alert: bool = False,
    starred: bool = False,
) -> dict:
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per creare task in questo progetto.")
    if not normalize_text(name):
        raise ValueError("Il nome del task e obbligatorio.")

    assigned_company = None
    if assigned_company_id is not None:
        assigned_company = Workspace.objects.filter(id=assigned_company_id, is_active=True).first()
        if assigned_company is None:
            raise ValueError("Azienda assegnataria non valida.")

    task = ProjectTask.objects.create(
        project=project,
        name=normalize_text(name),
        assigned_company=assigned_company,
        date_start=date_start,
        date_end=date_end,
        progress=normalize_project_progress(progress),
        note=normalize_text(note),
        alert=bool(alert),
        starred=bool(starred),
    )
    task.project = project
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=[task],
    )
    emit_project_realtime_event(
        event_type="task.created",
        project_id=project.id,
        actor_profile=profile,
        task_id=task.id,
        data={
            "category": "task",
            "project_name": project.name,
            "task_name": task.name,
            "assigned_company_name": task.assigned_company.name if task.assigned_company else None,
            "date_start": task.date_start,
            "date_end": task.date_end,
            "progress": task.progress,
            "alert": task.alert,
            "note": task.note or None,
        },
    )
    recipients = project_notification_recipients(
        project,
        exclude_profile_ids={profile.id},
    )
    assigned_recipients = [
        recipient
        for recipient in recipients
        if task.assigned_company_id and recipient.workspace_id == task.assigned_company_id
    ]
    generic_recipients = [
        recipient
        for recipient in recipients
        if recipient.id not in {item.id for item in assigned_recipients}
    ]
    if assigned_recipients:
        notify_profiles_with_blueprint(
            recipients=assigned_recipients,
            actor_profile=profile,
            blueprint=build_project_task_notification(
                task=task,
                actor_profile=profile,
                action="created",
                audience="assigned",
            ),
        )
    if generic_recipients:
        notify_profiles_with_blueprint(
            recipients=generic_recipients,
            actor_profile=profile,
            blueprint=build_project_task_notification(
                task=task,
                actor_profile=profile,
                action="created",
                audience="generic",
            ),
        )
    return serialize_task(
        task,
        project_members=members,
        include_activity_posts=False,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


@transaction.atomic
def update_project_task(
    *,
    profile: Profile,
    task_id: int,
    name: str,
    assigned_company_id: int | None,
    date_start: date,
    date_end: date,
    date_completed: date | None = None,
    progress: int = 0,
    note: str = "",
    alert: bool = False,
    starred: bool = False,
) -> dict:
    task = (
        ProjectTask.objects.select_related("project", "assigned_company").filter(id=task_id).first()
    )
    if task is None:
        raise ValueError("Task non trovato.")
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=task.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare task in questo progetto.")
    previous_name = task.name
    previous_date_start = task.date_start
    previous_date_end = task.date_end
    previous_date_completed = task.date_completed
    previous_progress = task.progress
    previous_note = task.note
    previous_alert = task.alert
    previous_starred = task.starred
    previous_assigned_company_id = task.assigned_company_id
    previous_assigned_company_name = task.assigned_company.name if task.assigned_company else None

    task.name = normalize_text(name) or task.name
    task.date_start = date_start
    task.date_end = date_end
    task.date_completed = date_completed
    task.progress = normalize_project_progress(progress)
    task.note = normalize_text(note)
    task.alert = bool(alert)
    task.starred = bool(starred)
    if assigned_company_id is None:
        task.assigned_company = None
    else:
        assigned_company = Workspace.objects.filter(id=assigned_company_id, is_active=True).first()
        if assigned_company is None:
            raise ValueError("Azienda assegnataria non valida.")
        task.assigned_company = assigned_company
    task.save()
    shifted_activity_refs: list[str] = []
    shift_delta_days = (task.date_start - previous_date_start).days
    if shift_delta_days != 0 and shift_delta_days == (task.date_end - previous_date_end).days:
        shifted_activity_refs = shift_task_activities_only(
            task_id=task.id, delta_days=shift_delta_days
        )
    sync_task_bounds_to_activities(task_id=task.id)
    propagate_project_schedule_delays(
        project=project,
        seed_refs=[
            schedule_link_entity_ref(task=task),
            *shifted_activity_refs,
        ],
    )
    task.refresh_from_db()
    task.project = project
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=[task],
    )
    changes = [
        build_timeline_change(label="Nome", before=previous_name, after=task.name),
        build_timeline_change(
            label="Azienda",
            before=previous_assigned_company_name,
            after=task.assigned_company.name if task.assigned_company else None,
        ),
        build_timeline_change(label="Inizio", before=previous_date_start, after=task.date_start),
        build_timeline_change(label="Fine", before=previous_date_end, after=task.date_end),
        build_timeline_change(
            label="Chiusura", before=previous_date_completed, after=task.date_completed
        ),
        build_timeline_change(
            label="Progresso",
            before=f"{previous_progress}%",
            after=f"{task.progress}%",
            tone="positive",
        ),
        build_timeline_change(
            label="Alert", before=previous_alert, after=task.alert, tone="warning"
        ),
        build_timeline_change(label="Star", before=previous_starred, after=task.starred),
        build_timeline_change(label="Nota", before=previous_note, after=task.note),
    ]
    emit_project_realtime_event(
        event_type="task.updated",
        project_id=project.id,
        actor_profile=profile,
        task_id=task.id,
        data={
            "category": "task",
            "project_name": project.name,
            "task_name": task.name,
            "assigned_company_name": task.assigned_company.name if task.assigned_company else None,
            "date_start": task.date_start,
            "date_end": task.date_end,
            "date_completed": task.date_completed,
            "progress": task.progress,
            "alert": task.alert,
            "completed": task.date_completed is not None
            and previous_date_completed != task.date_completed,
            "changes": [change for change in changes if change],
        },
    )
    recipients = project_notification_recipients(
        project,
        exclude_profile_ids={profile.id},
    )
    newly_assigned_recipients = [
        recipient
        for recipient in recipients
        if task.assigned_company_id
        and task.assigned_company_id != previous_assigned_company_id
        and recipient.workspace_id == task.assigned_company_id
    ]
    generic_recipients = [
        recipient
        for recipient in recipients
        if recipient.id not in {item.id for item in newly_assigned_recipients}
    ]
    if newly_assigned_recipients:
        notify_profiles_with_blueprint(
            recipients=newly_assigned_recipients,
            actor_profile=profile,
            blueprint=build_project_task_notification(
                task=task,
                actor_profile=profile,
                action="updated",
                audience="assigned",
            ),
        )
    if generic_recipients:
        notify_profiles_with_blueprint(
            recipients=generic_recipients,
            actor_profile=profile,
            blueprint=build_project_task_notification(
                task=task,
                actor_profile=profile,
                action="updated",
                audience="generic",
            ),
        )
    return serialize_task(
        task,
        project_members=members,
        include_activity_posts=False,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


@transaction.atomic
def create_task_activity(
    *,
    profile: Profile,
    task_id: int,
    title: str,
    description: str = "",
    status: str = TaskActivityStatus.TODO,
    datetime_start: datetime,
    datetime_end: datetime,
    progress: int | None = None,
    workers: list[int] | None = None,
    note: str = "",
    alert: bool = False,
    starred: bool = False,
) -> dict:
    task = ProjectTask.objects.select_related("project").filter(id=task_id).first()
    if task is None:
        raise ValueError("Task non trovato.")
    _project, membership, members = get_project_with_team_context(
        profile=profile, project_id=task.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per creare attivita in questo progetto.")

    next_progress = (
        normalize_project_progress(progress)
        if progress is not None
        else task_activity_status_to_progress(status)
    )
    next_status = (
        task_activity_progress_to_status(next_progress)
        if progress is not None
        else (status if status in TaskActivityStatus.values else TaskActivityStatus.TODO)
    )

    activity = ProjectActivity.objects.create(
        task=task,
        title=normalize_text(title) or "Attivita",
        description=normalize_text(description),
        status=next_status,
        progress=next_progress,
        datetime_start=datetime_start,
        datetime_end=datetime_end,
        note=normalize_text(note),
        alert=bool(alert),
        starred=bool(starred),
    )
    selected_workers = resolve_project_member_profile_ids(project=task.project, ids=workers or [])
    if selected_workers:
        activity.workers.set(selected_workers)
    activity.refresh_from_db()
    expanded_task_ref = sync_task_bounds_to_activities(task_id=task.id)
    if expanded_task_ref:
        propagate_project_schedule_delays(project=task.project, seed_refs=[expanded_task_ref])
        task.refresh_from_db()
    worker_names = [profile_display_name(worker) for worker in activity.workers.all()]
    emit_project_realtime_event(
        event_type="activity.created",
        project_id=task.project_id,
        actor_profile=profile,
        task_id=task.id,
        activity_id=activity.id,
        data={
            "category": "activity",
            "project_name": task.project.name,
            "task_name": task.name,
            "activity_title": activity.title,
            "status": activity.status,
            "progress": activity.progress,
            "datetime_start": activity.datetime_start,
            "datetime_end": activity.datetime_end,
            "alert": activity.alert,
            "worker_names": worker_names,
            "note": activity.note or None,
        },
    )
    recipients = project_notification_recipients(
        task.project,
        exclude_profile_ids={profile.id},
    )
    worker_ids = set(activity.workers.values_list("id", flat=True))
    assigned_recipients = [recipient for recipient in recipients if recipient.id in worker_ids]
    generic_recipients = [
        recipient
        for recipient in recipients
        if recipient.id not in {item.id for item in assigned_recipients}
    ]
    if assigned_recipients:
        notify_profiles_with_blueprint(
            recipients=assigned_recipients,
            actor_profile=profile,
            blueprint=build_project_activity_notification(
                activity=activity,
                actor_profile=profile,
                action="created",
                audience="assigned",
            ),
        )
    if generic_recipients:
        notify_profiles_with_blueprint(
            recipients=generic_recipients,
            actor_profile=profile,
            blueprint=build_project_activity_notification(
                activity=activity,
                actor_profile=profile,
                action="created",
                audience="generic",
            ),
        )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=task.project,
        members=members,
        tasks=[task],
    )
    return serialize_activity(
        activity,
        project_members=members,
        include_posts=False,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


@transaction.atomic
def update_task_activity(
    *,
    profile: Profile,
    activity_id: int,
    title: str,
    description: str = "",
    status: str = TaskActivityStatus.TODO,
    datetime_start: datetime,
    datetime_end: datetime,
    progress: int | None = None,
    workers: list[int] | None = None,
    note: str = "",
    alert: bool = False,
    starred: bool = False,
) -> dict:
    activity = (
        ProjectActivity.objects.select_related("task", "task__project")
        .prefetch_related("workers")
        .filter(id=activity_id)
        .first()
    )
    if activity is None:
        raise ValueError("Attivita non trovata.")
    _project, membership, members = get_project_with_team_context(
        profile=profile, project_id=activity.task.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare attivita in questo progetto.")
    previous_title = activity.title
    previous_description = activity.description
    previous_status = activity.status
    previous_progress = activity.progress
    previous_datetime_start = activity.datetime_start
    previous_datetime_end = activity.datetime_end
    previous_note = activity.note
    previous_alert = activity.alert
    previous_starred = activity.starred
    previous_worker_ids = set(activity.workers.values_list("id", flat=True))
    previous_worker_names = [profile_display_name(worker) for worker in activity.workers.all()]

    next_progress = (
        normalize_project_progress(progress)
        if progress is not None
        else task_activity_status_to_progress(status)
    )
    next_status = (
        task_activity_progress_to_status(next_progress)
        if progress is not None
        else (status if status in TaskActivityStatus.values else TaskActivityStatus.TODO)
    )

    activity.title = normalize_text(title) or activity.title
    activity.description = normalize_text(description)
    activity.status = next_status
    activity.progress = next_progress
    activity.datetime_start = datetime_start
    activity.datetime_end = datetime_end
    activity.note = normalize_text(note)
    activity.alert = bool(alert)
    activity.starred = bool(starred)
    activity.save()
    activity.workers.set(
        resolve_project_member_profile_ids(project=activity.task.project, ids=workers or [])
    )
    activity.refresh_from_db()
    expanded_task_ref = sync_task_bounds_to_activities(task_id=activity.task_id)
    propagate_seed_refs = [
        schedule_link_entity_ref(activity=activity),
        expanded_task_ref,
    ]
    propagate_project_schedule_delays(project=activity.task.project, seed_refs=propagate_seed_refs)
    next_worker_names = [profile_display_name(worker) for worker in activity.workers.all()]
    changes = [
        build_timeline_change(label="Titolo", before=previous_title, after=activity.title),
        build_timeline_change(
            label="Descrizione", before=previous_description, after=activity.description
        ),
        build_timeline_change(
            label="Stato",
            before=task_activity_status_label(previous_status),
            after=task_activity_status_label(activity.status),
            tone="positive" if activity.status == TaskActivityStatus.COMPLETED else "neutral",
        ),
        build_timeline_change(
            label="Progresso",
            before=f"{previous_progress}%",
            after=f"{activity.progress}%",
            tone="positive",
        ),
        build_timeline_change(
            label="Inizio", before=previous_datetime_start, after=activity.datetime_start
        ),
        build_timeline_change(
            label="Fine", before=previous_datetime_end, after=activity.datetime_end
        ),
        build_timeline_change(
            label="Squadra",
            before=", ".join(previous_worker_names),
            after=", ".join(next_worker_names),
        ),
        build_timeline_change(
            label="Alert", before=previous_alert, after=activity.alert, tone="warning"
        ),
        build_timeline_change(label="Star", before=previous_starred, after=activity.starred),
        build_timeline_change(label="Nota", before=previous_note, after=activity.note),
    ]
    emit_project_realtime_event(
        event_type="activity.updated",
        project_id=activity.task.project_id,
        actor_profile=profile,
        task_id=activity.task_id,
        activity_id=activity.id,
        data={
            "category": "activity",
            "project_name": activity.task.project.name,
            "task_name": activity.task.name,
            "activity_title": activity.title,
            "status": activity.status,
            "progress": activity.progress,
            "alert": activity.alert,
            "completed": activity.status == TaskActivityStatus.COMPLETED
            and previous_status != activity.status,
            "changes": [change for change in changes if change],
        },
    )
    recipients = project_notification_recipients(
        activity.task.project,
        exclude_profile_ids={profile.id},
    )
    worker_ids = set(activity.workers.values_list("id", flat=True))
    newly_assigned_ids = worker_ids - previous_worker_ids
    assigned_recipients = [
        recipient for recipient in recipients if recipient.id in newly_assigned_ids
    ]
    generic_recipients = [
        recipient
        for recipient in recipients
        if recipient.id not in {item.id for item in assigned_recipients}
    ]
    if assigned_recipients:
        notify_profiles_with_blueprint(
            recipients=assigned_recipients,
            actor_profile=profile,
            blueprint=build_project_activity_notification(
                activity=activity,
                actor_profile=profile,
                action="updated",
                audience="assigned",
            ),
        )
    if generic_recipients:
        notify_profiles_with_blueprint(
            recipients=generic_recipients,
            actor_profile=profile,
            blueprint=build_project_activity_notification(
                activity=activity,
                actor_profile=profile,
                action="updated",
                audience="generic",
            ),
        )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=activity.task.project,
        members=members,
        tasks=[activity.task],
    )
    return serialize_activity(
        activity,
        project_members=members,
        include_posts=False,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
    )


def save_post_attachments(post: ProjectPost, files: list[object]) -> None:
    from edilcloud.modules.billing.services import assert_storage_quota_available

    prepared_files = [optimize_media_for_storage(uploaded_file) for uploaded_file in files]
    incoming_bytes = sum(
        int(getattr(uploaded_file, "size", 0) or 0) for uploaded_file in prepared_files
    )
    assert_storage_quota_available(post.project.workspace, incoming_bytes=incoming_bytes)
    for uploaded_file in prepared_files:
        PostAttachment.objects.create(post=post, file=uploaded_file)


def save_comment_attachments(comment: PostComment, files: list[object]) -> None:
    from edilcloud.modules.billing.services import assert_storage_quota_available

    prepared_files = [optimize_media_for_storage(uploaded_file) for uploaded_file in files]
    incoming_bytes = sum(
        int(getattr(uploaded_file, "size", 0) or 0) for uploaded_file in prepared_files
    )
    assert_storage_quota_available(comment.post.project.workspace, incoming_bytes=incoming_bytes)
    for uploaded_file in prepared_files:
        CommentAttachment.objects.create(comment=comment, file=uploaded_file)


def get_post_for_profile(*, profile: Profile, post_id: int) -> tuple[ProjectPost, ProjectMember]:
    post = (
        ProjectPost.objects.select_related("project", "task", "activity", "author")
        .filter(id=post_id)
        .first()
    )
    if post is None:
        raise ValueError("Post non trovato.")
    membership = get_project_membership(post.project, profile)
    return post, membership


def get_comment_for_profile(
    *, profile: Profile, comment_id: int
) -> tuple[PostComment, ProjectMember]:
    comment = (
        PostComment.objects.select_related("post", "post__project", "author")
        .filter(id=comment_id)
        .first()
    )
    if comment is None:
        raise ValueError("Commento non trovato.")
    membership = get_project_membership(comment.post.project, profile)
    return comment, membership


def get_post_attachment_file_response(*, profile: Profile, attachment_id: int):
    attachment = (
        PostAttachment.objects.select_related("post", "post__project")
        .filter(id=attachment_id)
        .first()
    )
    if attachment is None:
        raise ValueError("Allegato post non trovato.")
    get_project_membership(attachment.post.project, profile)
    file_name = Path(attachment.file.name).name if attachment.file else "allegato-post"
    return build_inline_file_response(attachment.file, filename=file_name)


def get_comment_attachment_file_response(*, profile: Profile, attachment_id: int):
    attachment = (
        CommentAttachment.objects.select_related(
            "comment", "comment__post", "comment__post__project"
        )
        .filter(id=attachment_id)
        .first()
    )
    if attachment is None:
        raise ValueError("Allegato commento non trovato.")
    get_project_membership(attachment.comment.post.project, profile)
    file_name = Path(attachment.file.name).name if attachment.file else "allegato-commento"
    return build_inline_file_response(attachment.file, filename=file_name)


def notify_post_created(
    *,
    actor_profile: Profile,
    post: ProjectPost,
    mentioned_profiles: list[Profile],
) -> None:
    actor_name = profile_display_name(actor_profile)
    post_excerpt = notification_excerpt(post.text)
    mentioned_profile_ids = {profile.id for profile in mentioned_profiles}

    if mentioned_profiles:
        mention_kind = "project.mention.post"
        mention_subject = f"{actor_name} ti ha menzionato in un aggiornamento"
        if post.alert or post.post_kind == PostKind.ISSUE:
            mention_kind = "project.mention.issue"
            mention_subject = f"{actor_name} ti ha menzionato in una segnalazione"
        notify_profiles_with_blueprint(
            recipients=mentioned_profiles,
            actor_profile=actor_profile,
            blueprint=build_project_thread_notification(
                kind=mention_kind,
                subject=mention_subject,
                actor_profile=actor_profile,
                post=post,
                category="mention",
                action="created",
                snippet=post_excerpt,
            ),
        )

    generic_recipients = project_notification_recipients(
        post.project,
        exclude_profile_ids={actor_profile.id, *mentioned_profile_ids},
    )
    if not generic_recipients:
        return

    kind = "project.post.created"
    subject = f"{actor_name} ha pubblicato un aggiornamento"
    category = "post"
    if post.alert or post.post_kind == PostKind.ISSUE:
        kind = "project.issue.created"
        subject = f"{actor_name} ha aperto una segnalazione"
        category = "issue"

    notify_profiles_with_blueprint(
        recipients=generic_recipients,
        actor_profile=actor_profile,
        blueprint=build_project_thread_notification(
            kind=kind,
            subject=subject,
            actor_profile=actor_profile,
            post=post,
            category=category,
            action="created",
            snippet=post_excerpt,
        ),
    )


def notify_comment_created(
    *,
    actor_profile: Profile,
    post: ProjectPost,
    comment: PostComment,
    mentioned_profiles: list[Profile],
) -> None:
    actor_name = profile_display_name(actor_profile)
    comment_excerpt = notification_excerpt(comment.text)
    mentioned_profile_ids = {profile.id for profile in mentioned_profiles}
    already_notified = {actor_profile.id, *mentioned_profile_ids}

    if mentioned_profiles:
        notify_profiles_with_blueprint(
            recipients=mentioned_profiles,
            actor_profile=actor_profile,
            blueprint=build_project_thread_notification(
                kind="project.mention.comment",
                subject=f"{actor_name} ti ha menzionato in una risposta",
                actor_profile=actor_profile,
                post=post,
                comment=comment,
                category="mention",
                action="created",
                snippet=comment_excerpt,
                extra={"parent_id": comment.parent_id},
            ),
        )

    personalized_recipients: list[tuple[Profile, str, str]] = []
    if (
        comment.parent_id
        and comment.parent
        and comment.parent.author_id
        and comment.parent.author_id not in already_notified
    ):
        personalized_recipients.append(
            (
                comment.parent.author,
                "project.comment.reply",
                f"{actor_name} ha risposto al tuo commento",
            )
        )
        already_notified.add(comment.parent.author_id)
    if post.author_id and post.author_id not in already_notified:
        personalized_recipients.append(
            (
                post.author,
                "project.comment.created",
                f"{actor_name} ha commentato il tuo aggiornamento",
            )
        )
        already_notified.add(post.author_id)

    for recipient, kind, subject in personalized_recipients:
        create_project_notification_from_blueprint(
            recipient_profile=recipient,
            actor_profile=actor_profile,
            blueprint=build_project_thread_notification(
                kind=kind,
                subject=subject,
                actor_profile=actor_profile,
                post=post,
                comment=comment,
                category="comment",
                action="created",
                snippet=comment_excerpt,
                extra={"parent_id": comment.parent_id},
            ),
        )

    participant_recipients = project_participant_recipients(
        post,
        exclude_profile_ids=already_notified,
    )
    if participant_recipients:
        notify_profiles_with_blueprint(
            recipients=participant_recipients,
            actor_profile=actor_profile,
            blueprint=build_project_thread_notification(
                kind="project.comment.created",
                subject=f"{actor_name} ha scritto nel thread operativo",
                actor_profile=actor_profile,
                post=post,
                comment=comment,
                category="comment",
                action="created",
                snippet=comment_excerpt,
                extra={"parent_id": comment.parent_id},
            ),
        )


def notify_post_change(
    *,
    actor_profile: Profile,
    post: ProjectPost,
    kind: str,
    subject: str,
    category: str,
    action: str,
) -> None:
    recipients = project_participant_recipients(post, exclude_profile_ids={actor_profile.id})
    if not recipients:
        recipients = project_notification_recipients(
            post.project, exclude_profile_ids={actor_profile.id}
        )
    if not recipients:
        return
    post_excerpt = notification_excerpt(post.text)
    notify_profiles_with_blueprint(
        recipients=recipients,
        actor_profile=actor_profile,
        blueprint=build_project_thread_notification(
            kind=kind,
            subject=subject,
            actor_profile=actor_profile,
            post=post,
            category=category,
            action=action,
            snippet=post_excerpt,
        ),
    )


def notify_comment_change(
    *,
    actor_profile: Profile,
    comment: PostComment,
    kind: str,
    subject: str,
    action: str,
) -> None:
    post = comment.post
    recipients = project_participant_recipients(post, exclude_profile_ids={actor_profile.id})
    if not recipients:
        return
    comment_excerpt = notification_excerpt(comment.text)
    notify_profiles_with_blueprint(
        recipients=recipients,
        actor_profile=actor_profile,
        blueprint=build_project_thread_notification(
            kind=kind,
            subject=subject,
            actor_profile=actor_profile,
            post=post,
            comment=comment,
            category="comment",
            action=action,
            snippet=comment_excerpt,
            extra={"parent_id": comment.parent_id},
        ),
    )


def get_existing_project_client_mutation(
    *,
    profile: Profile,
    client_mutation_id: str,
    operation: str,
) -> ProjectClientMutation | None:
    normalized_mutation_id = normalize_text(client_mutation_id)
    if not normalized_mutation_id:
        return None

    mutation = (
        ProjectClientMutation.objects.select_related("post", "comment")
        .filter(profile=profile, mutation_id=normalized_mutation_id)
        .first()
    )
    if mutation is None:
        return None
    if mutation.operation != operation:
        raise ValueError("Client mutation id gia utilizzato per un'altra operazione.")
    return mutation


def record_project_client_mutation(
    *,
    profile: Profile,
    client_mutation_id: str,
    operation: str,
    post: ProjectPost | None = None,
    comment: PostComment | None = None,
) -> None:
    normalized_mutation_id = normalize_text(client_mutation_id)
    if not normalized_mutation_id:
        return

    try:
        ProjectClientMutation.objects.create(
            profile=profile,
            mutation_id=normalized_mutation_id,
            operation=operation,
            post=post,
            comment=comment,
        )
    except IntegrityError:
        existing = (
            ProjectClientMutation.objects.select_related("post", "comment")
            .filter(profile=profile, mutation_id=normalized_mutation_id)
            .first()
        )
        if existing is None:
            raise
        if existing.operation != operation:
            raise ValueError("Client mutation id gia utilizzato per un'altra operazione.")


@transaction.atomic
def create_task_post(
    *,
    profile: Profile,
    task_id: int,
    text: str,
    post_kind: str = PostKind.WORK_PROGRESS,
    is_public: bool = False,
    alert: bool = False,
    source_language: str = "",
    files: list[object] | None = None,
    mentioned_profile_ids: list[int] | None = None,
    weather_payload: dict | None = None,
    target_language: str | None = None,
    client_mutation_id: str = "",
) -> dict:
    task = ProjectTask.objects.select_related("project").filter(id=task_id).first()
    if task is None:
        raise ValueError("Task non trovato.")
    project, membership, members = get_project_with_team_context(
        profile=profile, project_id=task.project_id
    )
    existing_mutation = get_existing_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="task_post_create",
    )
    if existing_mutation is not None and existing_mutation.post_id is not None:
        existing_post = project_posts_queryset().get(id=existing_mutation.post_id)
        company_colors_by_workspace_id = project_company_colors_for_context(
            project=project,
            members=members,
            tasks=[task],
        )
        return serialize_post(
            post=existing_post,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=resolve_post_translation_memory(
                [existing_post],
                target_language=target_language,
                fallback_language=profile.language,
            ),
        )
    post = ProjectPost.objects.create(
        project=task.project,
        task=task,
        author=profile,
        post_kind=post_kind if post_kind in PostKind.values else PostKind.WORK_PROGRESS,
        text=normalize_text(text),
        original_text=normalize_text(text),
        source_language=normalize_text(source_language),
        display_language=normalize_text(source_language),
        alert=bool(alert),
        is_public=bool(is_public),
        weather_snapshot=weather_payload or {},
    )
    save_post_attachments(post, files or [])
    post = (
        ProjectPost.objects.select_related(
            "author",
            "author__workspace",
            "author__user",
            "task",
            "project",
        )
        .prefetch_related("attachments", "comments__attachments")
        .get(id=post.id)
    )
    record_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="task_post_create",
        post=post,
    )
    mentioned_profiles = resolve_project_mentioned_profiles(
        project=task.project,
        mentioned_profile_ids=mentioned_profile_ids,
        exclude_profile_ids={profile.id},
    )
    mark_post_seen_for_profile(post=post, profile=profile, seen_at=post.updated_at)
    emit_project_realtime_event(
        event_type="post.created",
        project_id=task.project_id,
        actor_profile=profile,
        task_id=task.id,
        post_id=post.id,
        data={
            "category": "post",
            "project_name": task.project.name,
            "task_name": task.name,
            "activity_title": None,
            "post_kind": post.post_kind,
            "alert": post.alert,
            "is_public": post.is_public,
            "has_attachments": post.attachments.exists(),
            "attachment_count": post.attachments.count(),
            "mentioned_count": len(mentioned_profiles),
            "excerpt": notification_excerpt(post.text),
            "weather_snapshot": post.weather_snapshot or None,
        },
    )
    emit_feed_refresh_for_post(
        post=post,
        actor_profile=profile,
        action="post.created",
    )
    notify_post_created(
        actor_profile=profile,
        post=post,
        mentioned_profiles=mentioned_profiles,
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=[task],
    )
    return serialize_post(
        post=post,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_post_id=resolve_post_translation_memory(
            [post],
            target_language=target_language,
            fallback_language=profile.language,
        ),
    )


@transaction.atomic
def create_activity_post(
    *,
    profile: Profile,
    activity_id: int,
    text: str,
    post_kind: str = PostKind.WORK_PROGRESS,
    is_public: bool = False,
    alert: bool = False,
    source_language: str = "",
    files: list[object] | None = None,
    mentioned_profile_ids: list[int] | None = None,
    weather_payload: dict | None = None,
    target_language: str | None = None,
    client_mutation_id: str = "",
) -> dict:
    activity = (
        ProjectActivity.objects.select_related("task", "task__project")
        .filter(id=activity_id)
        .first()
    )
    if activity is None:
        raise ValueError("Attivita non trovata.")
    project, membership, members = get_project_with_team_context(
        profile=profile,
        project_id=activity.task.project_id,
    )
    existing_mutation = get_existing_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="activity_post_create",
    )
    if existing_mutation is not None and existing_mutation.post_id is not None:
        existing_post = project_posts_queryset().get(id=existing_mutation.post_id)
        company_colors_by_workspace_id = project_company_colors_for_context(
            project=project,
            members=members,
            tasks=[activity.task],
        )
        return serialize_post(
            post=existing_post,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_post_id=resolve_post_translation_memory(
                [existing_post],
                target_language=target_language,
                fallback_language=profile.language,
            ),
        )
    post = ProjectPost.objects.create(
        project=activity.task.project,
        task=activity.task,
        activity=activity,
        author=profile,
        post_kind=post_kind if post_kind in PostKind.values else PostKind.WORK_PROGRESS,
        text=normalize_text(text),
        original_text=normalize_text(text),
        source_language=normalize_text(source_language),
        display_language=normalize_text(source_language),
        alert=bool(alert),
        is_public=bool(is_public),
        weather_snapshot=weather_payload or {},
    )
    save_post_attachments(post, files or [])
    post = (
        ProjectPost.objects.select_related(
            "author",
            "author__workspace",
            "author__user",
            "task",
            "activity",
            "project",
        )
        .prefetch_related("attachments", "comments__attachments")
        .get(id=post.id)
    )
    record_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="activity_post_create",
        post=post,
    )
    mentioned_profiles = resolve_project_mentioned_profiles(
        project=activity.task.project,
        mentioned_profile_ids=mentioned_profile_ids,
        exclude_profile_ids={profile.id},
    )
    mark_post_seen_for_profile(post=post, profile=profile, seen_at=post.updated_at)
    emit_project_realtime_event(
        event_type="post.created",
        project_id=activity.task.project_id,
        actor_profile=profile,
        task_id=activity.task_id,
        activity_id=activity.id,
        post_id=post.id,
        data={
            "category": "post",
            "project_name": activity.task.project.name,
            "task_name": activity.task.name,
            "activity_title": activity.title,
            "post_kind": post.post_kind,
            "alert": post.alert,
            "is_public": post.is_public,
            "has_attachments": post.attachments.exists(),
            "attachment_count": post.attachments.count(),
            "mentioned_count": len(mentioned_profiles),
            "excerpt": notification_excerpt(post.text),
            "weather_snapshot": post.weather_snapshot or None,
        },
    )
    emit_feed_refresh_for_post(
        post=post,
        actor_profile=profile,
        action="post.created",
    )
    notify_post_created(
        actor_profile=profile,
        post=post,
        mentioned_profiles=mentioned_profiles,
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=[activity.task],
    )
    return serialize_post(
        post=post,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_post_id=resolve_post_translation_memory(
            [post],
            target_language=target_language,
            fallback_language=profile.language,
        ),
    )


@transaction.atomic
def create_post_comment(
    *,
    profile: Profile,
    post_id: int,
    text: str,
    parent_id: int | None = None,
    source_language: str = "",
    files: list[object] | None = None,
    mentioned_profile_ids: list[int] | None = None,
    target_language: str | None = None,
    client_mutation_id: str = "",
) -> dict:
    post, membership = get_post_for_profile(profile=profile, post_id=post_id)
    _project, _membership, members = get_project_with_team_context(
        profile=profile, project_id=post.project_id
    )
    existing_mutation = get_existing_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="post_comment_create",
    )
    if existing_mutation is not None and existing_mutation.comment_id is not None:
        existing_comment = (
            PostComment.objects.select_related("author", "author__workspace", "author__user")
            .prefetch_related("attachments", "replies__attachments")
            .get(id=existing_mutation.comment_id)
        )
        company_colors_by_workspace_id = project_company_colors_for_context(
            project=post.project,
            members=members,
            tasks=[post.task] if post.task is not None else None,
        )
        return serialize_comment(
            existing_comment,
            membership=membership,
            company_colors_by_workspace_id=company_colors_by_workspace_id,
            translation_by_comment_id=resolve_comment_translation_memory(
                [existing_comment],
                target_language=target_language,
                fallback_language=profile.language,
            ),
        )
    parent = None
    if parent_id is not None:
        parent = PostComment.objects.filter(id=parent_id, post=post).first()
        if parent is None:
            raise ValueError("Commento padre non valido.")
    comment = PostComment.objects.create(
        post=post,
        author=profile,
        parent=parent,
        text=normalize_text(text),
        original_text=normalize_text(text),
        source_language=normalize_text(source_language),
        display_language=normalize_text(source_language),
    )
    save_comment_attachments(comment, files or [])
    comment = (
        PostComment.objects.select_related("author", "author__workspace", "author__user")
        .prefetch_related("attachments", "replies__attachments")
        .get(id=comment.id)
    )
    record_project_client_mutation(
        profile=profile,
        client_mutation_id=client_mutation_id,
        operation="post_comment_create",
        comment=comment,
    )
    mentioned_profiles = resolve_project_mentioned_profiles(
        project=post.project,
        mentioned_profile_ids=mentioned_profile_ids,
        exclude_profile_ids={profile.id},
    )
    emit_project_realtime_event(
        event_type="comment.created",
        project_id=post.project_id,
        actor_profile=profile,
        task_id=post.task_id,
        activity_id=post.activity_id,
        post_id=post.id,
        comment_id=comment.id,
        data={
            "category": "comment",
            "project_name": post.project.name,
            "task_name": post.task.name if post.task else None,
            "activity_title": post.activity.title if post.activity else None,
            "parent_id": comment.parent_id,
            "has_attachments": comment.attachments.exists(),
            "attachment_count": comment.attachments.count(),
            "mentioned_count": len(mentioned_profiles),
            "excerpt": notification_excerpt(comment.text),
        },
    )
    mark_post_seen_for_profile(
        post=post,
        profile=profile,
        seen_at=comment_activity_at(comment),
    )
    emit_feed_refresh_for_post(
        post=post,
        actor_profile=profile,
        comment_id=comment.id,
        action="comment.created",
    )
    notify_comment_created(
        actor_profile=profile,
        post=post,
        comment=comment,
        mentioned_profiles=mentioned_profiles,
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=post.project,
        members=members,
        tasks=[post.task] if post.task is not None else None,
    )
    return serialize_comment(
        comment,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_comment_id=resolve_comment_translation_memory(
            [comment],
            target_language=target_language,
            fallback_language=profile.language,
        ),
    )


@transaction.atomic
def update_post(
    *,
    profile: Profile,
    post_id: int,
    text: str | None = None,
    post_kind: str | None = None,
    is_public: bool | None = None,
    alert: bool | None = None,
    source_language: str | None = None,
    files: list[object] | None = None,
    remove_media_ids: list[int] | None = None,
    mentioned_profile_ids: list[int] | None = None,
    target_language: str | None = None,
) -> dict:
    post, membership = get_post_for_profile(profile=profile, post_id=post_id)
    _project, _membership, members = get_project_with_team_context(
        profile=profile, project_id=post.project_id
    )
    if not can_edit_project_content(membership, author_profile_id=post.author_id):
        raise ValueError("Non hai permessi per modificare questo post.")
    was_alert = bool(post.alert)
    previous_text = post.text
    previous_post_kind = post.post_kind
    previous_is_public = post.is_public
    previous_alert = post.alert
    previous_source_language = post.source_language
    previous_attachment_count = post.attachments.count()

    if text is not None:
        post.text = normalize_text(text)
        post.original_text = post.text
    if post_kind and post_kind in PostKind.values:
        post.post_kind = post_kind
    if is_public is not None:
        post.is_public = bool(is_public)
    if alert is not None:
        post.alert = bool(alert)
    if source_language is not None:
        post.source_language = normalize_text(source_language)
        post.display_language = normalize_text(source_language)
    post.edited_at = timezone.now()
    post.save()

    if remove_media_ids:
        PostAttachment.objects.filter(post=post, id__in=remove_media_ids).delete()
    save_post_attachments(post, files or [])

    refreshed = (
        ProjectPost.objects.select_related(
            "author",
            "author__workspace",
            "author__user",
            "task",
            "activity",
            "project",
        )
        .prefetch_related(
            "attachments",
            Prefetch(
                "comments",
                queryset=PostComment.objects.select_related(
                    "author",
                    "author__workspace",
                    "author__user",
                )
                .prefetch_related("attachments")
                .order_by("created_at", "id"),
            ),
        )
        .get(id=post.id)
    )
    emit_project_realtime_event(
        event_type="post.resolved" if was_alert and not refreshed.alert else "post.updated",
        project_id=refreshed.project_id,
        actor_profile=profile,
        task_id=refreshed.task_id,
        activity_id=refreshed.activity_id,
        post_id=refreshed.id,
        data={
            "category": "post",
            "project_name": refreshed.project.name,
            "task_name": refreshed.task.name if refreshed.task else None,
            "activity_title": refreshed.activity.title if refreshed.activity else None,
            "post_kind": refreshed.post_kind,
            "alert": refreshed.alert,
            "is_public": refreshed.is_public,
            "attachment_count": refreshed.attachments.count(),
            "excerpt": notification_excerpt(refreshed.text),
            "weather_snapshot": refreshed.weather_snapshot or None,
            "changes": [
                change
                for change in [
                    build_timeline_change(
                        label="Testo",
                        before=notification_excerpt(previous_text),
                        after=notification_excerpt(refreshed.text),
                    ),
                    build_timeline_change(
                        label="Tipo",
                        before=post_kind_label(previous_post_kind),
                        after=post_kind_label(refreshed.post_kind),
                    ),
                    build_timeline_change(
                        label="Visibilita",
                        before="Pubblico" if previous_is_public else "Privato",
                        after="Pubblico" if refreshed.is_public else "Privato",
                    ),
                    build_timeline_change(
                        label="Alert", before=previous_alert, after=refreshed.alert, tone="warning"
                    ),
                    build_timeline_change(
                        label="Lingua",
                        before=previous_source_language,
                        after=refreshed.source_language,
                    ),
                    build_timeline_change(
                        label="Allegati",
                        before=attachment_count_label(previous_attachment_count),
                        after=attachment_count_label(refreshed.attachments.count()),
                    ),
                ]
                if change
            ],
        },
    )
    mark_post_seen_for_profile(post=refreshed, profile=profile, seen_at=refreshed.updated_at)
    emit_feed_refresh_for_post(
        post=refreshed,
        actor_profile=profile,
        action="post.resolved" if was_alert and not refreshed.alert else "post.updated",
    )
    if mentioned_profile_ids:
        mentioned_profiles = resolve_project_mentioned_profiles(
            project=refreshed.project,
            mentioned_profile_ids=mentioned_profile_ids,
            exclude_profile_ids={profile.id},
        )
        notify_post_created(
            actor_profile=profile,
            post=refreshed,
            mentioned_profiles=mentioned_profiles,
        )
    notify_post_change(
        actor_profile=profile,
        post=refreshed,
        kind="project.issue.resolved"
        if was_alert and not refreshed.alert
        else ("project.issue.updated" if refreshed.alert else "project.post.updated"),
        subject=(
            f"{profile_display_name(profile)} ha risolto una segnalazione"
            if was_alert and not refreshed.alert
            else (
                f"{profile_display_name(profile)} ha aggiornato una segnalazione"
                if refreshed.alert
                else f"{profile_display_name(profile)} ha aggiornato un aggiornamento"
            )
        ),
        category="issue" if refreshed.alert or was_alert else "post",
        action="resolved" if was_alert and not refreshed.alert else "updated",
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=refreshed.project,
        members=members,
        tasks=[refreshed.task] if refreshed.task is not None else None,
    )
    return serialize_post(
        post=refreshed,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_post_id=resolve_post_translation_memory(
            [refreshed],
            target_language=target_language,
            fallback_language=profile.language,
        ),
    )


@transaction.atomic
def delete_post(*, profile: Profile, post_id: int) -> None:
    post, membership = get_post_for_profile(profile=profile, post_id=post_id)
    if not can_edit_project_content(membership, author_profile_id=post.author_id):
        raise ValueError("Non hai permessi per eliminare questo post.")
    post_excerpt = notification_excerpt(post.text)
    attachment_count = post.attachments.count()
    task_name = post.task.name if post.task else None
    activity_title = post.activity.title if post.activity else None
    post_kind = post.post_kind
    is_public = post.is_public
    alert = post.alert
    post.is_deleted = True
    post.deleted_at = timezone.now()
    post.text = ""
    post.save(update_fields=["is_deleted", "deleted_at", "text", "updated_at"])
    post.project = post.project
    mark_post_seen_for_profile(post=post, profile=profile, seen_at=post.updated_at)
    emit_project_realtime_event(
        event_type="post.deleted",
        project_id=post.project_id,
        actor_profile=profile,
        task_id=post.task_id,
        activity_id=post.activity_id,
        post_id=post.id,
        data={
            "category": "post",
            "project_name": post.project.name,
            "task_name": task_name,
            "activity_title": activity_title,
            "post_kind": post_kind,
            "alert": alert,
            "is_public": is_public,
            "attachment_count": attachment_count,
            "excerpt": post_excerpt,
            "is_deleted": True,
        },
    )
    emit_feed_refresh_for_post(
        post=post,
        actor_profile=profile,
        action="post.deleted",
    )
    notify_post_change(
        actor_profile=profile,
        post=post,
        kind="project.issue.deleted" if post.alert else "project.post.deleted",
        subject=(
            f"{profile_display_name(profile)} ha rimosso una segnalazione"
            if post.alert
            else f"{profile_display_name(profile)} ha rimosso un aggiornamento"
        ),
        category="issue" if post.alert else "post",
        action="deleted",
    )


@transaction.atomic
def update_comment(
    *,
    profile: Profile,
    comment_id: int,
    text: str | None = None,
    source_language: str | None = None,
    files: list[object] | None = None,
    remove_media_ids: list[int] | None = None,
    mentioned_profile_ids: list[int] | None = None,
    target_language: str | None = None,
) -> dict:
    comment, membership = get_comment_for_profile(profile=profile, comment_id=comment_id)
    _project, _membership, members = get_project_with_team_context(
        profile=profile, project_id=comment.post.project_id
    )
    if not can_edit_project_content(membership, author_profile_id=comment.author_id):
        raise ValueError("Non hai permessi per modificare questo commento.")
    previous_text = comment.text
    previous_source_language = comment.source_language
    previous_attachment_count = comment.attachments.count()

    if text is not None:
        comment.text = normalize_text(text)
        comment.original_text = comment.text
    if source_language is not None:
        comment.source_language = normalize_text(source_language)
        comment.display_language = normalize_text(source_language)
    comment.edited_at = timezone.now()
    comment.save()

    if remove_media_ids:
        CommentAttachment.objects.filter(comment=comment, id__in=remove_media_ids).delete()
    save_comment_attachments(comment, files or [])

    refreshed = (
        PostComment.objects.select_related("author", "author__workspace", "author__user")
        .prefetch_related("attachments", "replies__attachments")
        .get(id=comment.id)
    )
    emit_project_realtime_event(
        event_type="comment.updated",
        project_id=comment.post.project_id,
        actor_profile=profile,
        task_id=comment.post.task_id,
        activity_id=comment.post.activity_id,
        post_id=comment.post_id,
        comment_id=refreshed.id,
        data={
            "category": "comment",
            "project_name": comment.post.project.name,
            "task_name": comment.post.task.name if comment.post.task else None,
            "activity_title": comment.post.activity.title if comment.post.activity else None,
            "parent_id": refreshed.parent_id,
            "attachment_count": refreshed.attachments.count(),
            "excerpt": notification_excerpt(refreshed.text),
            "changes": [
                change
                for change in [
                    build_timeline_change(
                        label="Testo",
                        before=notification_excerpt(previous_text),
                        after=notification_excerpt(refreshed.text),
                    ),
                    build_timeline_change(
                        label="Lingua",
                        before=previous_source_language,
                        after=refreshed.source_language,
                    ),
                    build_timeline_change(
                        label="Allegati",
                        before=attachment_count_label(previous_attachment_count),
                        after=attachment_count_label(refreshed.attachments.count()),
                    ),
                ]
                if change
            ],
        },
    )
    mark_post_seen_for_profile(
        post=comment.post,
        profile=profile,
        seen_at=comment_activity_at(refreshed),
    )
    emit_feed_refresh_for_post(
        post=comment.post,
        actor_profile=profile,
        comment_id=refreshed.id,
        action="comment.updated",
    )
    if mentioned_profile_ids:
        mentioned_profiles = resolve_project_mentioned_profiles(
            project=comment.post.project,
            mentioned_profile_ids=mentioned_profile_ids,
            exclude_profile_ids={profile.id},
        )
        notify_comment_created(
            actor_profile=profile,
            post=comment.post,
            comment=refreshed,
            mentioned_profiles=mentioned_profiles,
        )
    notify_comment_change(
        actor_profile=profile,
        comment=refreshed,
        kind="project.comment.updated",
        subject=f"{profile_display_name(profile)} ha aggiornato una risposta",
        action="updated",
    )
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=comment.post.project,
        members=members,
        tasks=[comment.post.task] if comment.post.task is not None else None,
    )
    return serialize_comment(
        refreshed,
        membership=membership,
        company_colors_by_workspace_id=company_colors_by_workspace_id,
        translation_by_comment_id=resolve_comment_translation_memory(
            [refreshed],
            target_language=target_language,
            fallback_language=profile.language,
        ),
    )


@transaction.atomic
def delete_comment(*, profile: Profile, comment_id: int) -> None:
    comment, membership = get_comment_for_profile(profile=profile, comment_id=comment_id)
    if not can_edit_project_content(membership, author_profile_id=comment.author_id):
        raise ValueError("Non hai permessi per eliminare questo commento.")
    comment_excerpt = notification_excerpt(comment.text)
    comment.is_deleted = True
    comment.deleted_at = timezone.now()
    comment.text = ""
    comment.save(update_fields=["is_deleted", "deleted_at", "text", "updated_at"])
    mark_post_seen_for_profile(
        post=comment.post,
        profile=profile,
        seen_at=comment_activity_at(comment),
    )
    emit_project_realtime_event(
        event_type="comment.deleted",
        project_id=comment.post.project_id,
        actor_profile=profile,
        task_id=comment.post.task_id,
        activity_id=comment.post.activity_id,
        post_id=comment.post_id,
        comment_id=comment.id,
        data={
            "category": "comment",
            "project_name": comment.post.project.name,
            "task_name": comment.post.task.name if comment.post.task else None,
            "activity_title": comment.post.activity.title if comment.post.activity else None,
            "parent_id": comment.parent_id,
            "excerpt": comment_excerpt,
            "is_deleted": True,
        },
    )
    emit_feed_refresh_for_post(
        post=comment.post,
        actor_profile=profile,
        comment_id=comment.id,
        action="comment.deleted",
    )
    notify_comment_change(
        actor_profile=profile,
        comment=comment,
        kind="project.comment.deleted",
        subject=f"{profile_display_name(profile)} ha rimosso una risposta",
        action="deleted",
    )


def build_folder_path(*, parent: ProjectFolder | None, name: str) -> str:
    normalized_name = normalize_text(name)
    if not normalized_name:
        raise ValueError("Il nome cartella e obbligatorio.")
    if parent is None or not parent.path:
        return normalized_name
    return f"{parent.path}/{normalized_name}"


@transaction.atomic
def create_project_folder(
    *,
    profile: Profile,
    project_id: int,
    name: str,
    parent_id: int | None = None,
    is_public: bool = False,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per creare cartelle in questo progetto.")
    parent = None
    if parent_id is not None:
        parent = ProjectFolder.objects.filter(project=project, id=parent_id).first()
        if parent is None:
            raise ValueError("Cartella padre non valida.")
    folder = ProjectFolder.objects.create(
        project=project,
        parent=parent,
        name=normalize_text(name),
        path=build_folder_path(parent=parent, name=name),
        is_public=bool(is_public),
    )
    emit_project_realtime_event(
        event_type="folder.created",
        project_id=project.id,
        actor_profile=profile,
        folder_id=folder.id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": project.name,
            "folder_name": folder.name,
            "path": folder.path,
            "parent_id": folder.parent_id,
            "is_public": folder.is_public,
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(project, exclude_profile_ids={profile.id}),
        actor_profile=profile,
        blueprint=build_project_folder_notification(
            kind="project.folder.created",
            action="created",
            actor_profile=profile,
            project=project,
            folder_id=folder.id,
            folder_name=folder.name,
            folder_path=folder.path,
        ),
    )
    return serialize_folder(folder)


def rebase_folder_paths(*, folder: ProjectFolder) -> None:
    for child in folder.children.all().order_by("id"):
        child.path = build_folder_path(parent=folder, name=child.name)
        child.save(update_fields=["path", "updated_at"])
        rebase_folder_paths(folder=child)


@transaction.atomic
def update_project_folder(
    *,
    profile: Profile,
    folder_id: int,
    name: str | None = None,
    parent_id: int | None = None,
    is_public: bool | None = None,
    is_root: bool | None = None,
) -> dict:
    folder = (
        ProjectFolder.objects.select_related("project", "parent")
        .prefetch_related("children")
        .filter(id=folder_id)
        .first()
    )
    if folder is None:
        raise ValueError("Cartella non trovata.")
    _project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=folder.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare cartelle in questo progetto.")
    previous_name = folder.name
    previous_path = folder.path
    previous_parent_id = folder.parent_id
    previous_is_public = folder.is_public
    previous_is_root = folder.is_root

    if name is not None:
        folder.name = normalize_text(name) or folder.name
    if parent_id is not None:
        if parent_id == 0:
            folder.parent = None
        else:
            parent = ProjectFolder.objects.filter(project=folder.project, id=parent_id).first()
            if parent is None:
                raise ValueError("Cartella padre non valida.")
            folder.parent = parent
    if is_public is not None:
        folder.is_public = bool(is_public)
    if is_root is not None:
        folder.is_root = bool(is_root)
    folder.path = build_folder_path(parent=folder.parent, name=folder.name)
    folder.save()
    rebase_folder_paths(folder=folder)
    emit_project_realtime_event(
        event_type="folder.updated",
        project_id=folder.project_id,
        actor_profile=profile,
        folder_id=folder.id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": folder.project.name,
            "folder_name": folder.name,
            "path": folder.path,
            "parent_id": folder.parent_id,
            "is_public": folder.is_public,
            "changes": [
                change
                for change in [
                    build_timeline_change(label="Nome", before=previous_name, after=folder.name),
                    build_timeline_change(
                        label="Percorso", before=previous_path, after=folder.path
                    ),
                    build_timeline_change(
                        label="Parent", before=previous_parent_id, after=folder.parent_id
                    ),
                    build_timeline_change(
                        label="Visibilita", before=previous_is_public, after=folder.is_public
                    ),
                    build_timeline_change(
                        label="Root", before=previous_is_root, after=folder.is_root
                    ),
                ]
                if change
            ],
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(
            folder.project, exclude_profile_ids={profile.id}
        ),
        actor_profile=profile,
        blueprint=build_project_folder_notification(
            kind="project.folder.updated",
            action="updated",
            actor_profile=profile,
            project=folder.project,
            folder_id=folder.id,
            folder_name=folder.name,
            folder_path=folder.path,
        ),
    )
    return serialize_folder(folder)


@transaction.atomic
def delete_project_folder(*, profile: Profile, folder_id: int) -> None:
    folder = ProjectFolder.objects.select_related("project").filter(id=folder_id).first()
    if folder is None:
        raise ValueError("Cartella non trovata.")
    _project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=folder.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per eliminare cartelle in questo progetto.")
    project_id = folder.project_id
    deleted_folder_id = folder.id
    folder_name = folder.name
    folder_path = folder.path
    project_name = folder.project.name
    folder.delete()
    emit_project_realtime_event(
        event_type="folder.deleted",
        project_id=project_id,
        actor_profile=profile,
        folder_id=deleted_folder_id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": project_name,
            "folder_name": folder_name,
            "path": folder_path,
            "is_deleted": True,
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(_project, exclude_profile_ids={profile.id}),
        actor_profile=profile,
        blueprint=build_project_folder_notification(
            kind="project.folder.deleted",
            action="deleted",
            actor_profile=profile,
            project=_project,
            folder_id=deleted_folder_id,
            folder_name=folder_name,
            folder_path=folder_path,
        ),
    )


def _assert_project_document_upload_size(uploaded_file) -> None:
    max_bytes = int(getattr(settings, "PROJECT_DOCUMENT_MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        return
    if size > max_bytes:
        max_mb = max(1, math.ceil(max_bytes / (1024 * 1024)))
        raise ValueError(
            f"Il documento supera il limite consentito di {max_mb:.0f} MB."
        )


@transaction.atomic
def upload_project_document(
    *,
    profile: Profile,
    project_id: int,
    uploaded_file,
    title: str = "",
    description: str = "",
    folder_id: int | None = None,
    additional_path: str = "",
    is_public: bool = False,
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per caricare documenti in questo progetto.")
    from edilcloud.modules.billing.services import assert_storage_quota_available

    _assert_project_document_upload_size(uploaded_file)
    prepared_file = optimize_media_for_storage(uploaded_file)
    assert_storage_quota_available(
        project.workspace,
        incoming_bytes=int(getattr(prepared_file, "size", 0) or 0),
    )

    folder = None
    parent = None
    if folder_id is not None:
        folder = ProjectFolder.objects.filter(project=project, id=folder_id).first()
        if folder is None:
            raise ValueError("Cartella documento non valida.")
        parent = folder

    if normalize_text(additional_path):
        path_chunks = [chunk for chunk in normalize_text(additional_path).split("/") if chunk]
        for chunk in path_chunks:
            folder, _created = ProjectFolder.objects.get_or_create(
                project=project,
                path=build_folder_path(parent=parent, name=chunk),
                defaults={
                    "parent": parent,
                    "name": chunk,
                },
            )
            parent = folder

    document = ProjectDocument.objects.create(
        project=project,
        folder=folder,
        title=normalize_text(title) or Path(getattr(prepared_file, "name", "") or "Documento").stem,
        description=normalize_text(description),
        document=prepared_file,
        is_public=bool(is_public),
    )
    emit_project_realtime_event(
        event_type="document.created",
        project_id=project.id,
        actor_profile=profile,
        folder_id=document.folder_id,
        document_id=document.id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": project.name,
            "document_title": document.title,
            "folder_id": document.folder_id,
            "folder_path": document.folder.path if document.folder else None,
            "is_public": document.is_public,
            "size_label": attachment_size(document.document),
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(project, exclude_profile_ids={profile.id}),
        actor_profile=profile,
        blueprint=build_project_document_notification(
            kind="project.document.created",
            action="created",
            actor_profile=profile,
            project=project,
            document_id=document.id,
            document_title=document.title,
            folder_id=document.folder_id,
            folder_path=document.folder.path if document.folder else None,
            file_field=document.document,
        ),
    )
    return serialize_document(document)


def _clone_uploaded_binary(
    *,
    file_name: str,
    content: bytes,
    content_type: str,
):
    return SimpleUploadedFile(
        file_name or "document.pdf",
        content,
        content_type=content_type or "application/octet-stream",
    )


def _build_inspection_report_post_text(
    *,
    document_title: str,
    summary: str,
    general_summary: str = "",
) -> str:
    lines = [
        f"Verbale di sopralluogo: {normalize_text(document_title) or 'Documento'}",
        "",
        normalize_text(summary),
    ]
    if normalize_text(general_summary):
        lines.extend(["", f"Contesto generale: {normalize_text(general_summary)}"])
    lines.extend(
        [
            "",
            "Documento completo disponibile nel drive di progetto e in allegato PDF.",
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip()


@transaction.atomic
def create_project_inspection_report(
    *,
    profile: Profile,
    project_id: int,
    uploaded_file,
    title: str = "",
    description: str = "",
    folder_id: int | None = None,
    additional_path: str = "",
    is_public: bool = False,
    source_language: str = "",
    general_summary: str = "",
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    project, membership, _members = get_project_with_team_context(
        profile=profile,
        project_id=project_id,
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per creare verbali in questo progetto.")

    if uploaded_file is None:
        raise ValueError("File PDF del verbale obbligatorio.")

    prepared_entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entries or []):
        if not isinstance(raw_entry, dict):
            raise ValueError("Le fasi operative del verbale non sono valide.")

        raw_summary = raw_entry.get("summary")
        summary = normalize_text(raw_summary)
        if not summary:
            raise ValueError(
                f"Il riepilogo della fase/lavorazione #{index + 1} e obbligatorio."
            )

        task_id = raw_entry.get("task_id")
        activity_id = raw_entry.get("activity_id")
        task_id = int(task_id) if str(task_id or "").isdigit() else None
        activity_id = int(activity_id) if str(activity_id or "").isdigit() else None

        if activity_id is not None:
            activity = (
                ProjectActivity.objects.select_related("task", "task__project")
                .filter(id=activity_id, task__project_id=project.id)
                .first()
            )
            if activity is None:
                raise ValueError("Una lavorazione selezionata non appartiene al progetto.")
            if task_id is not None and activity.task_id != task_id:
                raise ValueError("La lavorazione selezionata non corrisponde alla fase scelta.")
            prepared_entries.append(
                {
                    "task": activity.task,
                    "activity": activity,
                    "summary": summary,
                    "target_label": f"{activity.task.name} > {activity.title}",
                }
            )
            continue

        if task_id is None:
            raise ValueError("Ogni riepilogo deve essere collegato a una fase o lavorazione.")

        task = ProjectTask.objects.select_related("project").filter(
            id=task_id,
            project_id=project.id,
        ).first()
        if task is None:
            raise ValueError("Una fase selezionata non appartiene al progetto.")
        prepared_entries.append(
            {
                "task": task,
                "activity": None,
                "summary": summary,
                "target_label": task.name,
            }
        )

    if not prepared_entries:
        raise ValueError("Seleziona almeno una fase o lavorazione per il verbale.")

    file_name = Path(getattr(uploaded_file, "name", "") or "verbale-sopralluogo.pdf").name
    content_type = (
        getattr(uploaded_file, "content_type", "")
        or mimetypes.guess_type(file_name)[0]
        or "application/pdf"
    )
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    content = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    if not content:
        raise ValueError("Il file del verbale e vuoto o non leggibile.")

    created_document = upload_project_document(
        profile=profile,
        project_id=project.id,
        uploaded_file=_clone_uploaded_binary(
            file_name=file_name,
            content=content,
            content_type=content_type,
        ),
        title=title,
        description=description,
        folder_id=folder_id,
        additional_path=additional_path,
        is_public=is_public,
    )

    normalized_general_summary = normalize_text(general_summary)
    normalized_source_language = normalize_text(source_language)
    created_posts: list[dict[str, Any]] = []

    for prepared_entry in prepared_entries:
        post_text = _build_inspection_report_post_text(
            document_title=created_document["title"],
            summary=prepared_entry["summary"],
            general_summary=normalized_general_summary,
        )
        post_attachment = _clone_uploaded_binary(
            file_name=file_name,
            content=content,
            content_type=content_type,
        )

        activity = prepared_entry["activity"]
        if activity is not None:
            created_post = create_activity_post(
                profile=profile,
                activity_id=activity.id,
                text=post_text,
                post_kind=PostKind.DOCUMENTATION,
                is_public=is_public,
                alert=False,
                source_language=normalized_source_language,
                files=[post_attachment],
            )
        else:
            created_post = create_task_post(
                profile=profile,
                task_id=prepared_entry["task"].id,
                text=post_text,
                post_kind=PostKind.DOCUMENTATION,
                is_public=is_public,
                alert=False,
                source_language=normalized_source_language,
                files=[post_attachment],
            )

        created_posts.append(
            {
                "post_id": created_post["id"],
                "task_id": prepared_entry["task"].id,
                "activity_id": activity.id if activity is not None else None,
                "target_label": prepared_entry["target_label"],
            }
        )

    return {
        "document": created_document,
        "created_count": len(created_posts),
        "posts": created_posts,
    }


@transaction.atomic
def update_project_document(
    *,
    profile: Profile,
    document_id: int,
    title: str | None = None,
    description: str | None = None,
    folder_id: int | None = None,
    uploaded_file=None,
) -> dict:
    document = (
        ProjectDocument.objects.select_related("project", "folder").filter(id=document_id).first()
    )
    if document is None:
        raise ValueError("Documento non trovato.")
    _project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=document.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per modificare documenti in questo progetto.")
    previous_title = document.title
    previous_description = document.description
    previous_folder_path = document.folder.path if document.folder else None
    previous_folder_id = document.folder_id
    previous_is_public = document.is_public
    previous_size = attachment_size(document.document)

    if title is not None:
        document.title = normalize_text(title) or document.title
    if description is not None:
        document.description = normalize_text(description)
    if folder_id is not None:
        if folder_id == 0:
            document.folder = None
        else:
            folder = ProjectFolder.objects.filter(project=document.project, id=folder_id).first()
            if folder is None:
                raise ValueError("Cartella documento non valida.")
            document.folder = folder
    if uploaded_file is not None:
        _assert_project_document_upload_size(uploaded_file)
        document.document = optimize_media_for_storage(uploaded_file)
    document.save()
    emit_project_realtime_event(
        event_type="document.updated",
        project_id=document.project_id,
        actor_profile=profile,
        folder_id=document.folder_id,
        document_id=document.id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": document.project.name,
            "document_title": document.title,
            "folder_id": document.folder_id,
            "folder_path": document.folder.path if document.folder else None,
            "is_public": document.is_public,
            "changes": [
                change
                for change in [
                    build_timeline_change(
                        label="Titolo", before=previous_title, after=document.title
                    ),
                    build_timeline_change(
                        label="Descrizione", before=previous_description, after=document.description
                    ),
                    build_timeline_change(
                        label="Cartella",
                        before=previous_folder_path or previous_folder_id,
                        after=(document.folder.path if document.folder else None)
                        or document.folder_id,
                    ),
                    build_timeline_change(
                        label="Visibilita", before=previous_is_public, after=document.is_public
                    ),
                    build_timeline_change(
                        label="Dimensione",
                        before=previous_size,
                        after=attachment_size(document.document),
                    ),
                ]
                if change
            ],
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(
            document.project, exclude_profile_ids={profile.id}
        ),
        actor_profile=profile,
        blueprint=build_project_document_notification(
            kind="project.document.updated",
            action="updated",
            actor_profile=profile,
            project=document.project,
            document_id=document.id,
            document_title=document.title,
            folder_id=document.folder_id,
            folder_path=document.folder.path if document.folder else None,
            file_field=document.document,
        ),
    )
    return serialize_document(document)


@transaction.atomic
def delete_project_document(*, profile: Profile, document_id: int) -> None:
    document = ProjectDocument.objects.select_related("project").filter(id=document_id).first()
    if document is None:
        raise ValueError("Documento non trovato.")
    _project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=document.project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per eliminare documenti in questo progetto.")
    project_id = document.project_id
    deleted_document_id = document.id
    folder_id = document.folder_id
    folder_path = document.folder.path if document.folder else None
    document_title = document.title
    project_name = document.project.name
    document.delete()
    emit_project_realtime_event(
        event_type="document.deleted",
        project_id=project_id,
        actor_profile=profile,
        folder_id=folder_id,
        document_id=deleted_document_id,
        data={
            "category": "document",
            "project_level": True,
            "project_name": project_name,
            "document_title": document_title,
            "folder_id": folder_id,
            "folder_path": folder_path,
            "is_deleted": True,
        },
    )
    notify_profiles_with_blueprint(
        recipients=project_notification_recipients(_project, exclude_profile_ids={profile.id}),
        actor_profile=profile,
        blueprint=build_project_document_notification(
            kind="project.document.deleted",
            action="deleted",
            actor_profile=profile,
            project=_project,
            document_id=deleted_document_id,
            document_title=document_title,
            folder_id=folder_id,
            folder_path=folder_path,
        ),
    )
