from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ninja import Schema

from edilcloud.modules.notifications.schemas import RealtimeSocketSchema


class ProjectRealtimeSessionSchema(Schema):
    enabled: bool
    project: RealtimeSocketSchema | None = None
    notifications: RealtimeSocketSchema | None = None


class ProjectFeedPageSchema(Schema):
    items: list[dict[str, Any]]
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None = None


class ProjectFeedSeenSchema(Schema):
    post_id: int
    seen_at: datetime
    is_unread: bool = False


class ProjectFeedBulkSeenRequestSchema(Schema):
    post_ids: list[int] = []


class ProjectFeedBulkSeenSchema(Schema):
    count: int
    items: list[ProjectFeedSeenSchema]


class ProjectSummarySchema(Schema):
    id: int
    name: str
    description: str | None = None
    address: str | None = None
    google_place_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    date_start: date | None = None
    date_end: date | None = None
    status: int | None = None
    completed: int | None = None
    logo: str | None = None
    progress_percentage: int | None = None
    team_count: int | None = None
    alert_count: int | None = None
    is_delayed: bool | None = None
    has_coordinates: bool = False
    location_source: str | None = None
    map_url: str | None = None
    closed_at: datetime | None = None
    archive_due_at: datetime | None = None
    archived_at: datetime | None = None
    purge_due_at: datetime | None = None
    last_export_at: datetime | None = None
    owner_export_sent_at: datetime | None = None


class ProjectTeamMemberSchema(Schema):
    id: int
    role: str | None = None
    status: int | str | None = None
    disabled: bool | None = None
    project_invitation_date: datetime | None = None
    project_role_codes: list[str] | None = None
    project_role_labels: list[str] | None = None
    profile: dict[str, Any] | None = None


class ProjectInviteCodeSchema(Schema):
    id: int
    email: str
    project: int
    status: int | str | None = None
    unique_code: str


class ProjectOverviewSchema(Schema):
    tasks: list[dict[str, Any]]
    team: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    photos: list[dict[str, Any]]
    alertPosts: list[dict[str, Any]]
    recentPosts: list[dict[str, Any]]
    failures: list[str] = []


class CreateProjectRequestSchema(Schema):
    name: str
    description: str = ""
    address: str = ""
    google_place_id: str = ""
    latitude: float | None = None
    longitude: float | None = None
    date_start: date
    date_end: date | None = None


class CreateProjectTeamMemberRequestSchema(Schema):
    profile: int
    role: str
    is_external: bool = False
    project_role_codes: list[str] | None = None


class UpdateProjectTeamMemberRequestSchema(Schema):
    company_color_project: str | None = None
    project_role_codes: list[str] | None = None


class GenerateProjectInviteCodeRequestSchema(Schema):
    email: str


class CreateProjectTaskRequestSchema(Schema):
    name: str
    assigned_company: int | None = None
    date_start: date
    date_end: date
    progress: int = 0
    note: str = ""
    alert: bool = False
    starred: bool = False


class UpdateProjectTaskRequestSchema(CreateProjectTaskRequestSchema):
    date_completed: date | None = None


class CreateTaskActivityRequestSchema(Schema):
    title: str
    description: str = ""
    status: str = "to-do"
    progress: int | None = None
    datetime_start: datetime
    datetime_end: datetime
    workers: list[int] = []
    note: str = ""
    alert: bool = False
    starred: bool = False


class UpdateTaskActivityRequestSchema(CreateTaskActivityRequestSchema):
    pass


class CreateProjectGanttLinkRequestSchema(Schema):
    source: str
    target: str
    type: str = "e2s"
    lag_days: int = 0


class UpdateProjectGanttLinkRequestSchema(Schema):
    source: str | None = None
    target: str | None = None
    type: str | None = None
    lag_days: int | None = None


class UpdatePostRequestSchema(Schema):
    text: str | None = None
    post_kind: str | None = None
    is_public: bool | None = None
    alert: bool | None = None
    source_language: str | None = None
    mentioned_profile_ids: list[int] | None = None


class UpdateCommentRequestSchema(Schema):
    text: str | None = None
    source_language: str | None = None
    mentioned_profile_ids: list[int] | None = None


class CreateProjectFolderRequestSchema(Schema):
    name: str
    parent: int | None = None
    is_public: bool = False


class UpdateProjectFolderRequestSchema(Schema):
    name: str | None = None
    parent: int | None = None
    is_public: bool | None = None
    is_root: bool | None = None
