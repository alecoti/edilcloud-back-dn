"""Notification-facing API endpoints."""

from ninja import Router
from ninja.errors import HttpError

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.notifications.schemas import (
    NotificationCenterSchema,
    NotificationDeviceRegisterInputSchema,
    NotificationDeviceSchema,
    NotificationDeviceUnregisterInputSchema,
    NotificationDeviceUnregisterSchema,
    NotificationMarkAllSchema,
    NotificationRealtimeSessionSchema,
    NotificationSchema,
)
from edilcloud.modules.notifications.services import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    register_notification_device,
    unregister_notification_device,
)
from edilcloud.platform.realtime.services import build_notification_realtime_session


router = Router(tags=["notifications"])
auth = JWTAuth()


@router.get("/realtime/session", response=NotificationRealtimeSessionSchema, auth=auth)
def notification_realtime_session(request):
    return build_notification_realtime_session(
        user=request.auth.user,
        claims=request.auth.claims,
    )


@router.get("", response=NotificationCenterSchema, auth=auth)
def get_notifications(request, limit: int = 80):
    try:
        return list_notifications(
            user=request.auth.user,
            claims=request.auth.claims,
            limit=limit,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{notification_id}/read", response=NotificationSchema, auth=auth)
def mark_notification_read_endpoint(request, notification_id: int):
    try:
        return mark_notification_read(
            user=request.auth.user,
            claims=request.auth.claims,
            notification_id=notification_id,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "non trovata" in message.lower() else 400
        raise HttpError(status_code, message) from exc


@router.post("/read-all", response=NotificationMarkAllSchema, auth=auth)
def mark_all_notifications_read_endpoint(request):
    try:
        return mark_all_notifications_read(
            user=request.auth.user,
            claims=request.auth.claims,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/devices/register", response=NotificationDeviceSchema, auth=auth)
def register_notification_device_endpoint(
    request,
    payload: NotificationDeviceRegisterInputSchema,
):
    try:
        return register_notification_device(
            user=request.auth.user,
            claims=request.auth.claims,
            token=payload.token,
            platform=payload.platform,
            installation_id=payload.installation_id,
            device_name=payload.device_name,
            locale=payload.locale,
            timezone_name=payload.timezone,
            app_version=payload.app_version,
            push_enabled=payload.push_enabled,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/devices/unregister", response=NotificationDeviceUnregisterSchema, auth=auth)
def unregister_notification_device_endpoint(
    request,
    payload: NotificationDeviceUnregisterInputSchema,
):
    try:
        return unregister_notification_device(
            user=request.auth.user,
            claims=request.auth.claims,
            token=payload.token,
            installation_id=payload.installation_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
