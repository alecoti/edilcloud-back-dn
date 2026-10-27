"""Recheck identity and document scope immediately before socket delivery."""

from uuid import UUID
import re

from django.db.models import Exists, OuterRef
from django.utils import timezone


def positive_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit() or len(value) > 19:
            return None
        value = int(value)
    return value if isinstance(value, int) and 0 < value <= 9223372036854775807 else None


def active_ticket_profile(ticket):
    from edilcloud.modules.identity.models import AuthTokenSession
    from edilcloud.modules.projects.models import ProjectMember, ProjectMemberStatus
    from edilcloud.modules.workspaces.models import Profile

    profiles = Profile.objects.filter(
        pk=positive_id(ticket.get("profile_id")),
        user_id=positive_id(ticket.get("user_id")),
        is_active=True,
        user__is_active=True,
        workspace__is_active=True,
    )
    if ticket.get("workspace_id") is not None:
        profiles = profiles.filter(workspace_id=positive_id(ticket["workspace_id"]))
    if ticket.get("project_id") is not None:
        profiles = profiles.alias(
            _member=Exists(
                ProjectMember.objects.filter(
                    profile_id=OuterRef("pk"),
                    project_id=positive_id(ticket["project_id"]),
                    status=ProjectMemberStatus.ACTIVE,
                    disabled=False,
                )
            )
        ).filter(_member=True)
    if ticket.get("auth_session") is not None:
        try:
            session = UUID(str(ticket["auth_session"]))
        except (ValueError, TypeError):
            return None
        profiles = profiles.alias(
            _session=Exists(
                AuthTokenSession.objects.filter(
                    session_token=session,
                    user_id=OuterRef("user_id"),
                    current_profile_id=OuterRef("pk"),
                    revoked_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
            )
        ).filter(_session=True)
    return profiles.only("id", "workspace_id", "user_id").first()


def document_event_allowed(*, profile, event, channel):
    from edilcloud.modules.elaborati.visibility import delivery_revisions, visible_drive_documents
    from edilcloud.modules.notifications.document_access import (
        UUID_PATTERN,
        visible_document_notifications,
    )
    from edilcloud.modules.notifications.models import Notification
    from edilcloud.modules.projects.models import (
        ProjectDocument,
        ProjectMember,
        ProjectMemberStatus,
    )

    if not isinstance(event, dict):
        return False
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if channel == "notifications":
        if event.get("profileId") is not None and positive_id(event["profileId"]) != profile.pk:
            return False
        if event.get("notificationId") is not None:
            notification = visible_document_notifications(
                Notification.objects.filter(
                    pk=positive_id(event["notificationId"]),
                    recipient_profile_id=profile.pk,
                ),
                profile=profile,
            ).first()
            if notification is None:
                return False
            if (
                event.get("documentId") is not None
                and positive_id(event["documentId"]) != notification.document_id
            ):
                return False
            stored = notification.data if isinstance(notification.data, dict) else {}
            if "elaborato_revision_id" in data and data["elaborato_revision_id"] != stored.get(
                "elaborato_revision_id"
            ):
                return False
            return True
    tagged = "elaborato_revision_id" in data
    document = positive_id(event.get("documentId"))
    if document is None:
        return not tagged and event.get("documentId") is None
    project = positive_id(event.get("projectId"))
    memberships = ProjectMember.objects.filter(
        profile=profile,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
    ).values("project_id")
    documents = ProjectDocument.objects.filter(pk=document, project_id__in=memberships)
    if event.get("projectId") is not None:
        documents = documents.filter(project_id=project)
    if (
        not tagged
        and event.get("type") == "document.deleted"
        and data.get("document_origin") == "ordinary_upload"
        and project is not None
        and not ProjectDocument.objects.filter(pk=document).exists()
    ):
        return ProjectMember.objects.filter(
            profile=profile, project_id=project, status=ProjectMemberStatus.ACTIVE, disabled=False
        ).exists()
    if not visible_drive_documents(profile=profile, queryset=documents).exists():
        return False
    if tagged:
        marker = data["elaborato_revision_id"]
        if not isinstance(marker, str) or not re.fullmatch(UUID_PATTERN, marker):
            return False
        return (
            delivery_revisions(profile=profile)
            .filter(pk=UUID(marker), drive_document_id=document)
            .exists()
        )
    return True
