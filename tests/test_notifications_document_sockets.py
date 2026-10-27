"""ASGI websocket frames through actual routes and consumers, without send mocks.

PostgreSQL is disposable. This exercises ASGI transport, not TCP or Redis.
"""

from datetime import timedelta

from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.utils import timezone
import pytest

from edilcloud.modules.elaborati.models import ElaboratoOwnership, ElaboratoRevision
from edilcloud.modules.elaborati.visibility import publication_group
from edilcloud.modules.identity.models import AuthTokenSession
from edilcloud.modules.projects.models import ProjectMember
from edilcloud.modules.workspaces.models import Profile
from edilcloud.platform.realtime.routing import websocket_urlpatterns
from edilcloud.platform.realtime.services import issue_realtime_ticket
from tests import test_notifications_document_scope as document_scope

pytestmark = pytest.mark.django_db(transaction=True)
site = document_scope.site
issued = document_scope.issued
notice = document_scope.notice


def test_asgi_routes_filter_company_legacy_alias_and_recheck_session_context(
    site, issued, settings
):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    project, owner, worker, other, _ = site
    revision, document, alias = issued

    async def run():
        application = URLRouter(websocket_urlpatterns)
        layer = get_channel_layer()
        clients = []

        async def connect(profile, *, personal=False, capture_workspace=True):
            session = await sync_to_async(AuthTokenSession.objects.create)(
                user_id=profile.user_id,
                current_profile_id=profile.pk,
                expires_at=timezone.now() + timedelta(hours=1),
            )
            ticket, _ = await sync_to_async(issue_realtime_ticket)(
                user_id=profile.user_id,
                profile_id=profile.pk,
                channel="notifications" if personal else "project",
                project_id=None if personal else project.pk,
                auth_session=str(session.session_token),
                workspace_id=profile.workspace_id if capture_workspace else None,
            )
            path = "notifications/" if personal else f"projects/{project.pk}/"
            client = WebsocketCommunicator(application, f"/ws/realtime/{path}?ticket={ticket}")
            clients.append(client)
            connected, _ = await client.connect()
            assert connected
            return client, session

        async def emit(group, payload):
            await layer.group_send(group, {"type": "realtime.event", "payload": payload})

        async def through(client, barrier):
            seen = []
            while True:
                payload = await client.receive_json_from(timeout=3)
                seen.append(payload["eventId"])
                if payload["eventId"] == barrier:
                    return seen

        async def closed(client):
            result = await client.receive_output(timeout=3)
            assert result["type"] == "websocket.close" and result["code"] == 4403, result

        base = f"projects.{project.pk}"
        company = await sync_to_async(publication_group)(revision)
        private = {
            "eventId": "company-private",
            "type": "document.created",
            "projectId": project.pk,
            "documentId": document.pk,
            "profileId": owner.pk,
            "data": {"elaborato_revision_id": str(revision.pk)},
        }
        def barrier(key):
            return {"eventId": key, "type": "post.created", "projectId": project.pk}
        try:
            owner_socket, _ = await connect(owner)
            worker_socket, _ = await connect(worker)
            other_socket, other_session = await connect(other, capture_workspace=False)
            alias_socket, _ = await connect(alias)
            await emit(company, private)
            await emit(base, barrier("company-barrier"))
            for client, allowed in [
                (owner_socket, True),
                (worker_socket, True),
                (other_socket, False),
                (alias_socket, False),
            ]:
                assert await through(client, "company-barrier") == (
                    ["company-private", "company-barrier"] if allowed else ["company-barrier"]
                )
            await emit(base, {**private, "eventId": "global-private"})
            await emit(base, barrier("global-barrier"))
            for client, allowed in [
                (owner_socket, True),
                (worker_socket, True),
                (other_socket, False),
                (alias_socket, False),
            ]:
                assert await through(client, "global-barrier") == (
                    ["global-private", "global-barrier"] if allowed else ["global-barrier"]
                )
            personal, _ = await connect(owner, personal=True)
            alias_personal, _ = await connect(alias, personal=True)
            notification = await sync_to_async(notice)(owner, revision, document)
            user_group = f"notifications.user.{owner.user_id}"
            await emit(
                user_group,
                {
                    **private,
                    "eventId": "personal-private",
                    "type": "notification.created",
                    "profileId": owner.pk,
                    "notificationId": notification.pk,
                },
            )
            await emit(user_group, {"eventId": "personal-barrier", "type": "notification.read_all"})
            assert await through(personal, "personal-barrier") == [
                "personal-private",
                "personal-barrier",
            ]
            assert await through(alias_personal, "personal-barrier") == ["personal-barrier"]
            await sync_to_async(
                ProjectMember.objects.filter(project=project, profile=worker).update
            )(disabled=True)
            await emit(company, private)
            await closed(worker_socket)
            await sync_to_async(
                ProjectMember.objects.filter(project=project, profile=worker).update
            )(disabled=False)
            switched, switched_session = await connect(worker)
            worker_alias = await sync_to_async(Profile.objects.create)(
                workspace_id=alias.workspace_id,
                user_id=worker.user_id,
                email=worker.email,
                first_name="Worker alias",
                role="w",
            )
            await sync_to_async(AuthTokenSession.objects.filter(pk=switched_session.pk).update)(
                current_profile_id=worker_alias.pk
            )
            await emit(company, private)
            await closed(switched)
            legacy_worker, _ = await connect(worker, capture_workspace=False)
            await emit(company, {**private, "eventId": "legacy-ticket-private"})
            assert await through(legacy_worker, "legacy-ticket-private") == [
                "legacy-ticket-private"
            ]
            await sync_to_async(
                ElaboratoOwnership.objects.filter(document_id=revision.elaborato_id).delete
            )()
            fresh = await sync_to_async(
                lambda: ElaboratoRevision.objects.select_related("elaborato").get(pk=revision.pk)
            )()
            legacy_group = await sync_to_async(publication_group)(fresh)
            assert legacy_group == f"{base}.profile.{owner.pk}"
            await emit(legacy_group, {**private, "eventId": "legacy-private"})
            await emit(base, barrier("legacy-barrier"))
            assert await through(legacy_worker, "legacy-barrier") == ["legacy-barrier"]
            assert "legacy-private" in await through(owner_socket, "legacy-barrier")
            assert await through(alias_socket, "legacy-barrier") == ["legacy-barrier"]
            assert await through(other_socket, "legacy-barrier") == ["legacy-barrier"]
            await sync_to_async(AuthTokenSession.objects.filter(pk=other_session.pk).update)(
                revoked_at=timezone.now()
            )
            await emit(f"{base}.profile.{other.pk}", barrier("after-logout"))
            await closed(other_socket)
            changed_company, _ = await connect(owner)
            await sync_to_async(Profile.objects.filter(pk=owner.pk).update)(
                workspace_id=other.workspace_id
            )
            await emit(f"{base}.profile.{owner.pk}", private)
            await closed(changed_company)
        finally:
            for client in clients:
                await client.disconnect(timeout=3)

    async_to_sync(run)()
