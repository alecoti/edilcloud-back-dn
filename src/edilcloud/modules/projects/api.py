"""HTTP API for project list/detail, task operations and thread mutations."""

from __future__ import annotations

import json
from typing import Any

from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.projects.archive import export_project_archive
from edilcloud.modules.projects.demo_master_admin import (
    create_demo_master_snapshot,
    get_demo_master_admin_status,
    get_demo_master_scenarios_report,
    reset_demo_master_project,
    run_demo_master_admin_scenario,
    restore_demo_master_snapshot,
)
from edilcloud.modules.projects.schemas import (
    CreateDemoMasterSnapshotRequestSchema,
    CreateProjectGanttLinkRequestSchema,
    CreateProjectFolderRequestSchema,
    CreateProjectDrawingPinRequestSchema,
    CreateProjectRequestSchema,
    CreateProjectTaskRequestSchema,
    CreateProjectTeamMemberRequestSchema,
    CreateTaskActivityRequestSchema,
    ProjectFeedBulkSeenRequestSchema,
    ProjectFeedBulkSeenSchema,
    GenerateProjectInviteCodeRequestSchema,
    ProjectFeedPageSchema,
    ProjectFeedSeenSchema,
    ProjectInviteCodeSchema,
    ProjectOverviewSchema,
    ProjectRealtimeSessionSchema,
    ProjectSummarySchema,
    ProjectTeamMemberSchema,
    ResetDemoMasterProjectRequestSchema,
    RestoreDemoMasterSnapshotRequestSchema,
    RunDemoMasterScenarioRequestSchema,
    UpdateCommentRequestSchema,
    UpdateProjectDrawingPinRequestSchema,
    UpdateProjectGanttLinkRequestSchema,
    UpdateProjectTeamMemberRequestSchema,
    UpdatePostRequestSchema,
    UpdateProjectFolderRequestSchema,
    UpdateProjectTaskRequestSchema,
    UpdateTaskActivityRequestSchema,
)
from edilcloud.modules.projects.operational_history import list_project_operational_timeline
from edilcloud.modules.projects.services import (
    add_project_team_member,
    apply_project_gantt_import,
    create_activity_post,
    create_project_inspection_report,
    create_post_comment,
    create_project,
    create_project_folder,
    delete_project_drawing_pin,
    create_project_gantt_link,
    create_project_task,
    create_task_activity,
    create_task_post,
    delete_comment,
    delete_post,
    delete_project_document,
    delete_project_folder,
    delete_project_gantt_link,
    generate_project_invite,
    get_comment_attachment_file_response,
    get_current_profile,
    get_post_attachment_file_response,
    get_project_document_file_response,
    get_project_overview,
    get_project_for_profile,
    get_project_photo_file_response,
    get_project_summary,
    get_project_team_compliance,
    list_posts_for_activity,
    list_posts_for_task,
    list_project_alert_posts,
    list_project_documents,
    list_project_drawing_pins,
    list_project_feed,
    list_project_folders,
    list_project_gantt,
    list_project_photos,
    list_project_tasks,
    list_project_team,
    list_projects,
    mark_feed_post_seen,
    mark_feed_posts_seen,
    preview_project_gantt_import,
    update_comment,
    update_post,
    update_project_document,
    update_project_drawing_pin,
    update_project_folder,
    update_project_gantt_link,
    update_project_team_member,
    update_project_task,
    update_task_activity,
    upload_project_document,
    upsert_project_drawing_pin,
)
from edilcloud.platform.realtime.services import build_project_realtime_session


auth = JWTAuth()
router = Router(tags=["projects"])
tasks_router = Router(tags=["tasks"])
activities_router = Router(tags=["activities"])
posts_router = Router(tags=["posts"])
comments_router = Router(tags=["comments"])
folders_router = Router(tags=["folders"])
documents_router = Router(tags=["documents"])
photos_router = Router(tags=["photos"])
REQUEST_LOCALE_HEADER = "X-Edilcloud-Locale"
REQUEST_CLIENT_MUTATION_HEADER = "X-Edilcloud-Client-Mutation-Id"


def is_multipart_request(request) -> bool:
    return "multipart/form-data" in (request.headers.get("content-type") or "").lower()


def parse_json_schema(request, schema_class):
    return schema_class(**json.loads(request.body.decode() or "{}"))


def parse_int_list(raw_value: str | None) -> list[int]:
    values: list[int] = []
    for chunk in (raw_value or "").split(","):
        normalized = chunk.strip()
        if normalized.isdigit():
            values.append(int(normalized))
    return values


def current_profile(request):
    try:
        return get_current_profile(user=request.auth.user, claims=request.auth.claims)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


def current_profile_or_none(request):
    try:
        return get_current_profile(user=request.auth.user, claims=request.auth.claims)
    except ValueError:
        return None


def require_superuser(request) -> None:
    if not getattr(request.auth.user, "is_superuser", False):
        raise HttpError(403, "Area riservata ai superuser.")


def request_locale(request) -> str:
    return (request.headers.get(REQUEST_LOCALE_HEADER) or "").strip()


def request_client_mutation_id(request) -> str:
    return (request.headers.get(REQUEST_CLIENT_MUTATION_HEADER) or "").strip()


def parse_post_form_payload(request) -> dict[str, Any]:
    return {
        "text": request.POST.get("text", ""),
        "post_kind": request.POST.get("post_kind", ""),
        "is_public": request.POST.get("is_public", "false").lower() == "true",
        "alert": request.POST.get("alert", "false").lower() == "true",
        "source_language": request.POST.get("source_language", ""),
        "mentioned_profile_ids": parse_int_list(request.POST.get("mentioned_profile_ids")),
        "files": list(request.FILES.values()),
        "weather_payload": {
            key: request.POST.get(key)
            for key in ("project_latitude", "project_longitude", "project_google_place_id")
            if request.POST.get(key) not in {None, ""}
        },
    }


def parse_comment_form_payload(request) -> dict[str, Any]:
    raw_parent = request.POST.get("parent")
    parent_id = None
    if raw_parent:
        try:
            parent_id = int(raw_parent)
        except (TypeError, ValueError):
            parent_id = None
    return {
        "text": request.POST.get("text", ""),
        "parent_id": parent_id,
        "source_language": request.POST.get("source_language", ""),
        "mentioned_profile_ids": parse_int_list(request.POST.get("mentioned_profile_ids")),
        "files": list(request.FILES.values()),
    }


def parse_update_post_payload(request) -> dict[str, Any]:
    if is_multipart_request(request):
        return {
            "text": request.POST.get("text"),
            "post_kind": request.POST.get("post_kind"),
            "is_public": (
                request.POST.get("is_public", "").lower() == "true"
                if "is_public" in request.POST
                else None
            ),
            "alert": (
                request.POST.get("alert", "").lower() == "true" if "alert" in request.POST else None
            ),
            "source_language": request.POST.get("source_language"),
            "mentioned_profile_ids": parse_int_list(request.POST.get("mentioned_profile_ids")),
            "files": list(request.FILES.values()),
            "remove_media_ids": [
                int(value)
                for value in request.POST.getlist("remove_media_ids")
                if str(value).isdigit()
            ],
        }
    return parse_json_schema(request, UpdatePostRequestSchema).dict()


def parse_update_comment_payload(request) -> dict[str, Any]:
    if is_multipart_request(request):
        return {
            "text": request.POST.get("text"),
            "source_language": request.POST.get("source_language"),
            "mentioned_profile_ids": parse_int_list(request.POST.get("mentioned_profile_ids")),
            "files": list(request.FILES.values()),
            "remove_media_ids": [
                int(value)
                for value in request.POST.getlist("remove_media_ids")
                if str(value).isdigit()
            ],
        }
    return parse_json_schema(request, UpdateCommentRequestSchema).dict()


def parse_project_document_upload_payload(request) -> dict[str, Any]:
    raw_folder = request.POST.get("folder")
    folder_id = None
    if raw_folder and raw_folder.strip():
        try:
            folder_id = int(raw_folder)
        except (TypeError, ValueError) as exc:
            raise HttpError(400, "Cartella documento non valida.") from exc

    uploaded_file = request.FILES.get("document")
    if uploaded_file is None:
        raise HttpError(400, "File documento obbligatorio.")

    return {
        "uploaded_file": uploaded_file,
        "title": request.POST.get("title", ""),
        "description": request.POST.get("description", ""),
        "folder_id": folder_id,
        "additional_path": request.POST.get("additional_path", ""),
        "is_public": request.POST.get("is_public", "false").lower() == "true",
    }


def parse_project_document_update_payload(request) -> dict[str, Any]:
    if is_multipart_request(request):
        raw_folder = request.POST.get("folder")
        folder_id = None
        if raw_folder is not None:
            if raw_folder.strip():
                try:
                    folder_id = int(raw_folder)
                except (TypeError, ValueError) as exc:
                    raise HttpError(400, "Cartella documento non valida.") from exc
            else:
                folder_id = 0

        return {
            "title": request.POST.get("title"),
            "description": request.POST.get("description"),
            "folder_id": folder_id,
            "uploaded_file": request.FILES.get("document"),
        }

    payload = json.loads(request.body.decode() or "{}")
    return {
        "title": payload.get("title"),
        "description": payload.get("description"),
        "folder_id": payload.get("folder"),
        "uploaded_file": None,
    }


def parse_project_inspection_report_payload(request) -> dict[str, Any]:
    raw_folder = request.POST.get("folder")
    folder_id = None
    if raw_folder and raw_folder.strip():
        try:
            folder_id = int(raw_folder)
        except (TypeError, ValueError) as exc:
            raise HttpError(400, "Cartella documento non valida.") from exc

    uploaded_file = request.FILES.get("document")
    if uploaded_file is None:
        raise HttpError(400, "File PDF del verbale obbligatorio.")

    raw_entries = request.POST.get("entries", "[]")
    try:
        entries = json.loads(raw_entries)
    except json.JSONDecodeError as exc:
        raise HttpError(400, "Le fasi/lavorazioni del verbale non sono valide.") from exc
    if not isinstance(entries, list):
        raise HttpError(400, "Le fasi/lavorazioni del verbale devono essere una lista.")

    return {
        "uploaded_file": uploaded_file,
        "title": request.POST.get("title", ""),
        "description": request.POST.get("description", ""),
        "folder_id": folder_id,
        "additional_path": request.POST.get("additional_path", ""),
        "is_public": request.POST.get("is_public", "false").lower() == "true",
        "source_language": request.POST.get("source_language", ""),
        "general_summary": request.POST.get("general_summary", ""),
        "entries": entries,
    }


def parse_gantt_import_payload(request) -> dict[str, Any]:
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        raise HttpError(400, "File Gantt obbligatorio.")
    return {
        "uploaded_file": uploaded_file,
        "replace_existing": request.POST.get("replace_existing", "false").lower() == "true",
    }


@router.get("", response=list[ProjectSummarySchema], auth=auth)
def get_projects(request):
    return list_projects(profile=current_profile(request))


@router.post("", response={201: ProjectSummarySchema}, auth=auth)
def create_project_endpoint(request, payload: CreateProjectRequestSchema):
    try:
        project = create_project(profile=current_profile(request), **payload.dict())
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, project)


@router.get("/feed", response=ProjectFeedPageSchema, auth=auth)
def get_project_feed_endpoint(request, limit: int = 50, offset: int = 0):
    try:
        profile = current_profile(request)
        return list_project_feed(
            profile=profile,
            limit=limit,
            offset=offset,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/feed/seen", response=ProjectFeedBulkSeenSchema, auth=auth)
def mark_feed_posts_seen_endpoint(request, payload: ProjectFeedBulkSeenRequestSchema):
    try:
        return mark_feed_posts_seen(
            profile=current_profile(request),
            post_ids=payload.post_ids,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/demo-master/admin/status", response=dict[str, Any], auth=auth)
def get_demo_master_admin_status_endpoint(request):
    require_superuser(request)
    try:
        return get_demo_master_admin_status(user=request.auth.user)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/demo-master/admin/scenarios", response=dict[str, Any], auth=auth)
def get_demo_master_scenarios_report_endpoint(request):
    require_superuser(request)
    try:
        return get_demo_master_scenarios_report(user=request.auth.user)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/demo-master/admin/scenarios/run", response=dict[str, Any], auth=auth)
def run_demo_master_scenario_endpoint(request, payload: RunDemoMasterScenarioRequestSchema):
    require_superuser(request)
    try:
        return run_demo_master_admin_scenario(
            user=request.auth.user,
            scenario_id=payload.scenario_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/demo-master/admin/snapshots", response=dict[str, Any], auth=auth)
def create_demo_master_snapshot_endpoint(request, payload: CreateDemoMasterSnapshotRequestSchema):
    require_superuser(request)
    try:
        return create_demo_master_snapshot(
            user=request.auth.user,
            created_by_profile=current_profile_or_none(request),
            snapshot_version=payload.version,
            business_date=payload.business_date,
            notes=payload.notes,
            validate=payload.validate,
            activate=payload.activate,
            write_json=payload.write_json,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/demo-master/admin/reset", response=dict[str, Any], auth=auth)
def reset_demo_master_project_endpoint(request, payload: ResetDemoMasterProjectRequestSchema):
    require_superuser(request)
    try:
        return reset_demo_master_project(
            user=request.auth.user,
            skip_active_snapshot_link=payload.skip_active_snapshot_link,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/demo-master/admin/restore", response=dict[str, Any], auth=auth)
def restore_demo_master_snapshot_endpoint(request, payload: RestoreDemoMasterSnapshotRequestSchema):
    require_superuser(request)
    try:
        return restore_demo_master_snapshot(
            user=request.auth.user,
            snapshot_version=payload.snapshot_version,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/{project_id}", response=ProjectSummarySchema, auth=auth)
def get_project(request, project_id: int):
    try:
        return get_project_summary(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/overview", response=ProjectOverviewSchema, auth=auth)
def get_project_overview_endpoint(request, project_id: int):
    try:
        profile = current_profile(request)
        return get_project_overview(
            profile=profile,
            project_id=project_id,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/archive/export", auth=auth)
def export_project_archive_endpoint(request, project_id: int):
    try:
        return export_project_archive(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/timeline", response=dict[str, Any], auth=auth)
def get_project_timeline_endpoint(
    request,
    project_id: int,
    mode: str = "general",
    taskId: int | None = None,
    activityId: int | None = None,
):
    try:
        get_project_for_profile(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc

    if mode not in {"phase", "general", "activity"}:
        raise HttpError(400, "Modalita timeline non valida.")
    if mode == "activity" and activityId is None:
        raise HttpError(400, "activityId obbligatorio per questa cronologia.")
    if mode in {"phase", "general"} and taskId is None:
        raise HttpError(400, "taskId obbligatorio per questa cronologia.")

    return list_project_operational_timeline(
        project_id=project_id,
        mode=mode,
        task_id=taskId,
        activity_id=activityId,
    )


@router.get("/{project_id}/tasks", response=list[dict[str, Any]], auth=auth)
def get_project_tasks_endpoint(request, project_id: int):
    try:
        return list_project_tasks(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/tasks", response={201: dict[str, Any]}, auth=auth)
def create_project_task_endpoint(request, project_id: int, payload: CreateProjectTaskRequestSchema):
    try:
        task = create_project_task(
            profile=current_profile(request),
            project_id=project_id,
            name=payload.name,
            assigned_company_id=payload.assigned_company,
            date_start=payload.date_start,
            date_end=payload.date_end,
            progress=payload.progress,
            note=payload.note,
            alert=payload.alert,
            starred=payload.starred,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, task)


@router.get("/{project_id}/team", response=list[ProjectTeamMemberSchema], auth=auth)
def get_project_team_endpoint(request, project_id: int):
    try:
        return list_project_team(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/team/compliance", response=dict[str, Any], auth=auth)
def get_project_team_compliance_endpoint(request, project_id: int):
    try:
        return get_project_team_compliance(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/team", response={201: ProjectTeamMemberSchema}, auth=auth)
def add_project_team_member_endpoint(
    request, project_id: int, payload: CreateProjectTeamMemberRequestSchema
):
    try:
        member = add_project_team_member(
            profile=current_profile(request),
            project_id=project_id,
            target_profile_id=payload.profile,
            role=payload.role,
            is_external=payload.is_external,
            project_role_codes=payload.project_role_codes,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, member)


@router.patch("/{project_id}/team/{member_id}", response=ProjectTeamMemberSchema, auth=auth)
def update_project_team_member_endpoint(
    request,
    project_id: int,
    member_id: int,
    payload: UpdateProjectTeamMemberRequestSchema,
):
    try:
        return update_project_team_member(
            profile=current_profile(request),
            project_id=project_id,
            member_id=member_id,
            company_color_project=payload.company_color_project,
            project_role_codes=payload.project_role_codes,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/invite-code", response={201: ProjectInviteCodeSchema}, auth=auth)
def generate_project_invite_code_endpoint(
    request, project_id: int, payload: GenerateProjectInviteCodeRequestSchema
):
    try:
        invite = generate_project_invite(
            profile=current_profile(request),
            project_id=project_id,
            email=payload.email,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, invite)


@router.get("/{project_id}/documents", response=list[dict[str, Any]], auth=auth)
def get_project_documents_endpoint(request, project_id: int):
    try:
        return list_project_documents(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/documents", response={201: dict[str, Any]}, auth=auth)
def upload_project_document_endpoint(request, project_id: int):
    try:
        payload = parse_project_document_upload_payload(request)
        document = upload_project_document(
            profile=current_profile(request),
            project_id=project_id,
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, document)


@router.post("/{project_id}/inspection-reports", response={201: dict[str, Any]}, auth=auth)
def create_project_inspection_report_endpoint(request, project_id: int):
    try:
        payload = parse_project_inspection_report_payload(request)
        result = create_project_inspection_report(
            profile=current_profile(request),
            project_id=project_id,
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, result)


@router.get("/{project_id}/drawing-pins", response=list[dict[str, Any]], auth=auth)
def get_project_drawing_pins_endpoint(request, project_id: int):
    try:
        profile = current_profile(request)
        return list_project_drawing_pins(
            profile=profile,
            project_id=project_id,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/drawing-pins", response={201: dict[str, Any]}, auth=auth)
def create_project_drawing_pin_endpoint(
    request, project_id: int, payload: CreateProjectDrawingPinRequestSchema
):
    try:
        profile = current_profile(request)
        pin = upsert_project_drawing_pin(
            profile=profile,
            project_id=project_id,
            drawing_document_id=payload.drawing_document,
            post_id=payload.post,
            x=payload.x,
            y=payload.y,
            page_number=payload.page_number,
            label=payload.label,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, pin)


@router.patch("/{project_id}/drawing-pins/{pin_id}", response=dict[str, Any], auth=auth)
def update_project_drawing_pin_endpoint(
    request,
    project_id: int,
    pin_id: int,
    payload: UpdateProjectDrawingPinRequestSchema,
):
    try:
        profile = current_profile(request)
        return update_project_drawing_pin(
            profile=profile,
            project_id=project_id,
            pin_id=pin_id,
            drawing_document_id=payload.drawing_document,
            post_id=payload.post,
            x=payload.x,
            y=payload.y,
            page_number=payload.page_number,
            label=payload.label,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.delete("/{project_id}/drawing-pins/{pin_id}", response={204: None}, auth=auth)
def delete_project_drawing_pin_endpoint(request, project_id: int, pin_id: int):
    try:
        delete_project_drawing_pin(
            profile=current_profile(request),
            project_id=project_id,
            pin_id=pin_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc
    return 204, None


@router.get("/{project_id}/photos", response=list[dict[str, Any]], auth=auth)
def get_project_photos_endpoint(request, project_id: int):
    try:
        return list_project_photos(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/folders", response=list[dict[str, Any]], auth=auth)
def get_project_folders_endpoint(request, project_id: int):
    try:
        return list_project_folders(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/folders", response={201: dict[str, Any]}, auth=auth)
def create_project_folder_endpoint(
    request, project_id: int, payload: CreateProjectFolderRequestSchema
):
    try:
        folder = create_project_folder(
            profile=current_profile(request),
            project_id=project_id,
            name=payload.name,
            parent_id=payload.parent,
            is_public=payload.is_public,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, folder)


@router.get("/{project_id}/alerts", response=list[dict[str, Any]], auth=auth)
def get_project_alerts_endpoint(request, project_id: int):
    try:
        profile = current_profile(request)
        return list_project_alert_posts(
            profile=profile,
            project_id=project_id,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.get("/{project_id}/gantt", response=dict[str, Any], auth=auth)
def get_project_gantt_endpoint(request, project_id: int):
    try:
        return list_project_gantt(profile=current_profile(request), project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/gantt/import/preview", response=dict[str, Any], auth=auth)
def preview_project_gantt_import_endpoint(request, project_id: int):
    try:
        payload = parse_gantt_import_payload(request)
        return preview_project_gantt_import(
            profile=current_profile(request),
            project_id=project_id,
            uploaded_file=payload["uploaded_file"],
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/gantt/import/apply", response=dict[str, Any], auth=auth)
def apply_project_gantt_import_endpoint(request, project_id: int):
    try:
        payload = parse_gantt_import_payload(request)
        return apply_project_gantt_import(
            profile=current_profile(request),
            project_id=project_id,
            uploaded_file=payload["uploaded_file"],
            replace_existing=payload["replace_existing"],
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/gantt/links", response={201: dict[str, Any]}, auth=auth)
def create_project_gantt_link_endpoint(
    request,
    project_id: int,
    payload: CreateProjectGanttLinkRequestSchema,
):
    try:
        link = create_project_gantt_link(
            profile=current_profile(request),
            project_id=project_id,
            source_ref=payload.source,
            target_ref=payload.target,
            link_type=payload.type,
            lag_days=payload.lag_days,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, link)


@router.patch("/{project_id}/gantt/links/{link_id}", response=dict[str, Any], auth=auth)
def update_project_gantt_link_endpoint(
    request,
    project_id: int,
    link_id: int,
    payload: UpdateProjectGanttLinkRequestSchema,
):
    try:
        return update_project_gantt_link(
            profile=current_profile(request),
            project_id=project_id,
            link_id=link_id,
            source_ref=payload.source,
            target_ref=payload.target,
            link_type=payload.type,
            lag_days=payload.lag_days,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.delete("/{project_id}/gantt/links/{link_id}", response=dict[str, Any], auth=auth)
def delete_project_gantt_link_endpoint(request, project_id: int, link_id: int):
    try:
        return delete_project_gantt_link(
            profile=current_profile(request),
            project_id=project_id,
            link_id=link_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/{project_id}/realtime/session", response=ProjectRealtimeSessionSchema, auth=auth)
def project_realtime_session(request, project_id: int):
    return build_project_realtime_session(
        user=request.auth.user,
        claims=request.auth.claims,
        project_id=project_id,
    )


@tasks_router.patch("/{task_id}", response=dict[str, Any], auth=auth)
def update_task_endpoint(request, task_id: int, payload: UpdateProjectTaskRequestSchema):
    try:
        return update_project_task(
            profile=current_profile(request),
            task_id=task_id,
            name=payload.name,
            assigned_company_id=payload.assigned_company,
            date_start=payload.date_start,
            date_end=payload.date_end,
            date_completed=payload.date_completed,
            progress=payload.progress,
            note=payload.note,
            alert=payload.alert,
            starred=payload.starred,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@tasks_router.post("/{task_id}/activities", response={201: dict[str, Any]}, auth=auth)
def create_activity_endpoint(request, task_id: int, payload: CreateTaskActivityRequestSchema):
    try:
        activity = create_task_activity(
            profile=current_profile(request),
            task_id=task_id,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            progress=payload.progress,
            datetime_start=payload.datetime_start,
            datetime_end=payload.datetime_end,
            workers=payload.workers,
            note=payload.note,
            alert=payload.alert,
            starred=payload.starred,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, activity)


@tasks_router.get("/{task_id}/posts", response=list[dict[str, Any]], auth=auth)
def get_task_posts_endpoint(request, task_id: int):
    try:
        profile = current_profile(request)
        return list_posts_for_task(
            profile=profile,
            task_id=task_id,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@tasks_router.post("/{task_id}/posts", response={201: dict[str, Any]}, auth=auth)
def create_task_post_endpoint(request, task_id: int):
    try:
        payload = parse_post_form_payload(request)
        profile = current_profile(request)
        post = create_task_post(
            profile=profile,
            task_id=task_id,
            target_language=request_locale(request),
            client_mutation_id=request_client_mutation_id(request),
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, post)


@activities_router.patch("/{activity_id}", response=dict[str, Any], auth=auth)
def update_activity_endpoint(request, activity_id: int, payload: UpdateTaskActivityRequestSchema):
    try:
        return update_task_activity(
            profile=current_profile(request),
            activity_id=activity_id,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            progress=payload.progress,
            datetime_start=payload.datetime_start,
            datetime_end=payload.datetime_end,
            workers=payload.workers,
            note=payload.note,
            alert=payload.alert,
            starred=payload.starred,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@activities_router.get("/{activity_id}/posts", response=list[dict[str, Any]], auth=auth)
def get_activity_posts_endpoint(request, activity_id: int):
    try:
        profile = current_profile(request)
        return list_posts_for_activity(
            profile=profile,
            activity_id=activity_id,
            target_language=request_locale(request),
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@activities_router.post("/{activity_id}/posts", response={201: dict[str, Any]}, auth=auth)
def create_activity_post_endpoint(request, activity_id: int):
    try:
        payload = parse_post_form_payload(request)
        profile = current_profile(request)
        post = create_activity_post(
            profile=profile,
            activity_id=activity_id,
            target_language=request_locale(request),
            client_mutation_id=request_client_mutation_id(request),
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, post)


@posts_router.patch("/{post_id}", response=dict[str, Any], auth=auth)
def update_post_endpoint(request, post_id: int):
    try:
        payload = parse_update_post_payload(request)
        profile = current_profile(request)
        return update_post(
            profile=profile,
            post_id=post_id,
            target_language=request_locale(request),
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@posts_router.delete("/{post_id}", response={204: None}, auth=auth)
def delete_post_endpoint(request, post_id: int):
    try:
        delete_post(profile=current_profile(request), post_id=post_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(204, None)


@posts_router.post("/{post_id}/comments", response={201: dict[str, Any]}, auth=auth)
def create_comment_endpoint(request, post_id: int):
    try:
        payload = parse_comment_form_payload(request)
        profile = current_profile(request)
        comment = create_post_comment(
            profile=profile,
            post_id=post_id,
            target_language=request_locale(request),
            client_mutation_id=request_client_mutation_id(request),
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, comment)


@posts_router.post("/{post_id}/seen", response=ProjectFeedSeenSchema, auth=auth)
def mark_post_seen_endpoint(request, post_id: int):
    try:
        return mark_feed_post_seen(profile=current_profile(request), post_id=post_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@comments_router.patch("/{comment_id}", response=dict[str, Any], auth=auth)
def update_comment_endpoint(request, comment_id: int):
    try:
        payload = parse_update_comment_payload(request)
        profile = current_profile(request)
        return update_comment(
            profile=profile,
            comment_id=comment_id,
            target_language=request_locale(request),
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@comments_router.delete("/{comment_id}", response={204: None}, auth=auth)
def delete_comment_endpoint(request, comment_id: int):
    try:
        delete_comment(profile=current_profile(request), comment_id=comment_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(204, None)


@posts_router.get("/attachments/{attachment_id}/file", auth=auth)
def download_post_attachment_endpoint(request, attachment_id: int):
    try:
        return get_post_attachment_file_response(
            profile=current_profile(request),
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@comments_router.get("/attachments/{attachment_id}/file", auth=auth)
def download_comment_attachment_endpoint(request, attachment_id: int):
    try:
        return get_comment_attachment_file_response(
            profile=current_profile(request),
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@folders_router.patch("/{folder_id}", response=dict[str, Any], auth=auth)
def update_folder_endpoint(request, folder_id: int, payload: UpdateProjectFolderRequestSchema):
    try:
        return update_project_folder(
            profile=current_profile(request),
            folder_id=folder_id,
            name=payload.name,
            parent_id=payload.parent,
            is_public=payload.is_public,
            is_root=payload.is_root,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@folders_router.delete("/{folder_id}", response={204: None}, auth=auth)
def delete_folder_endpoint(request, folder_id: int):
    try:
        delete_project_folder(profile=current_profile(request), folder_id=folder_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(204, None)


@documents_router.patch("/{document_id}", response=dict[str, Any], auth=auth)
def update_document_endpoint(request, document_id: int):
    try:
        payload = parse_project_document_update_payload(request)
        return update_project_document(
            profile=current_profile(request),
            document_id=document_id,
            **payload,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@documents_router.delete("/{document_id}", response={204: None}, auth=auth)
def delete_document_endpoint(request, document_id: int):
    try:
        delete_project_document(profile=current_profile(request), document_id=document_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(204, None)


@documents_router.get("/{document_id}/file", auth=auth)
def download_document_file_endpoint(request, document_id: int):
    try:
        return get_project_document_file_response(
            profile=current_profile(request),
            document_id=document_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@photos_router.get("/{photo_id}/file", auth=auth)
def download_photo_file_endpoint(request, photo_id: int):
    try:
        return get_project_photo_file_response(
            profile=current_profile(request),
            photo_id=photo_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc
