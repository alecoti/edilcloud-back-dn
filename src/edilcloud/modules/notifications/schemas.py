from datetime import datetime

from ninja import Schema


class RealtimeSocketSchema(Schema):
    path: str
    ticket: str
    expires_at: str
    profile_id: int
    project_id: int | None = None


class NotificationRealtimeSessionSchema(Schema):
    enabled: bool
    notifications: RealtimeSocketSchema | None = None


class NotificationSenderSchema(Schema):
    id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    photo: str | None = None
    company_name: str | None = None
    position: str | None = None


class NotificationTargetSchema(Schema):
    project_id: int | None = None
    task_id: int | None = None
    activity_id: int | None = None
    post_id: int | None = None
    comment_id: int | None = None
    folder_id: int | None = None
    document_id: int | None = None
    object_id: int | None = None
    content_type: str | None = None


class NotificationSchema(Schema):
    id: int
    event_id: str
    kind: str | None = None
    subject: str
    body: str = ""
    created_at: datetime
    read_at: datetime | None = None
    is_read: bool
    sender: NotificationSenderSchema | None = None
    target: NotificationTargetSchema
    data: dict = {}


class NotificationCenterSchema(Schema):
    unread_count: int
    results: list[NotificationSchema]


class NotificationMarkAllSchema(Schema):
    ok: bool
    updated: int


class NotificationDeviceRegisterInputSchema(Schema):
    token: str
    platform: str = "unknown"
    installation_id: str = ""
    device_name: str = ""
    locale: str = ""
    timezone: str = ""
    app_version: str = ""
    push_enabled: bool = True


class NotificationDeviceUnregisterInputSchema(Schema):
    token: str | None = None
    installation_id: str | None = None


class NotificationDeviceSchema(Schema):
    id: int
    token_suffix: str
    platform: str
    installation_id: str = ""
    device_name: str = ""
    locale: str = ""
    timezone: str = ""
    app_version: str = ""
    push_enabled: bool
    is_active: bool


class NotificationDeviceUnregisterSchema(Schema):
    ok: bool
    updated: int
