import json
from datetime import date, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from tests.test_notifications_api import create_workspace_user, login_and_get_token, auth_header
from edilcloud.modules.projects.models import Project, ProjectMember, ProjectTask, ProjectPost, PostComment
from edilcloud.modules.projects.services import notify_post_created, notify_comment_created
from edilcloud.modules.notifications.models import Notification, NotificationDevice, NotificationPushJob, NotificationPushDelivery
from edilcloud.modules.notifications.services import create_notification
from edilcloud.modules.notifications.outbox import process_push_job, due_push_jobs
from edilcloud.modules.notifications.push import NotificationPushError
from edilcloud.modules.workspaces.models import Workspace, Profile

pytestmark = pytest.mark.django_db


@pytest.fixture
def site():
    from django.core.cache import cache
    cache.clear()  # Repeated fixture logins must not share another test's throttle budget.
    workspace = Workspace.objects.create(name="Cantiere impostazioni")
    owner_user, owner = create_workspace_user(workspace=workspace, email="owner.settings@example.com", password="test123", first_name="Laura", last_name="Verdi", role="o")
    worker_user, worker = create_workspace_user(workspace=workspace, email="worker.settings@example.com", password="test123", first_name="Mario", last_name="Rossi", role="w")
    project = Project.objects.create(workspace=workspace, created_by=owner, name="Nuovo cantiere", date_start=date.today())
    owner_member = ProjectMember.objects.create(project=project, profile=owner, role="o")
    worker_member = ProjectMember.objects.create(project=project, profile=worker, role="w")
    owner_token = login_and_get_token(email=owner_user.email, password="test123")
    worker_token = login_and_get_token(email=worker_user.email, password="test123")
    return project, owner, worker, owner_member, worker_member, owner_token, worker_token


def patch(client, path, token, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json", **auth_header(token))


def test_general_settings_authorization_validation_and_persistence(site, monkeypatch):
    project, owner, worker, _, _, owner_token, worker_token = site
    client = Client(); url = f"/api/v1/projects/{project.id}/settings"
    response = client.get(url, **auth_header(worker_token))
    assert response.status_code == 200 and not response.json()["can_manage"]
    assert response.json()["permissions"]["publish"] and not response.json()["permissions"]["manage_schedule"]
    assert patch(client, url, worker_token, {"general": {"name": "Non autorizzato"}}).status_code == 403
    assert patch(client, url, owner_token, {"general": {"name": ""}}).status_code == 400
    assert patch(client, url, owner_token, {"general": {"date_end": "2001-01-01"}}).status_code == 400
    assert patch(client, url, owner_token, {"general": {"date_start": 1}}).status_code == 400
    assert patch(client, url, owner_token, {"general": {"workspace_id": 99}}).status_code == 400
    from edilcloud.platform.geocoding import GeocodingResult
    monkeypatch.setattr("edilcloud.platform.geocoding.geocode_address", lambda value: GeocodingResult(45.5, 9.2))
    response = patch(client, url, owner_token, {"general": {"name": "Cantiere aggiornato", "address": "Via Roma 1", "description": "Consegna", "date_end": (date.today()+timedelta(days=7)).isoformat()}})
    assert response.status_code == 200
    project.refresh_from_db(); assert project.name == "Cantiere aggiornato" and project.latitude == 45.5
    assert response.json()["project"]["description"] == "Consegna"


def test_member_permissions_are_applied_to_existing_apis_and_owner_protected(site):
    project, owner, worker, owner_member, worker_member, owner_token, worker_token = site
    client = Client(); root = f"/api/v1/projects/{project.id}"
    member_url = f"{root}/settings/members/{worker_member.id}"
    assert patch(client, member_url, worker_token, {"role":"d"}).status_code == 403
    assert patch(client, f"{root}/settings/members/{owner_member.id}", owner_token, {"enabled":False}).status_code == 403
    assert patch(client, member_url, owner_token, {"role":"o"}).status_code == 422
    response = patch(client, member_url, owner_token, {"role":"m"})
    assert response.status_code == 200
    member = next(item for item in response.json()["members"] if item["id"] == worker_member.id)
    assert member["permissions"]["manage_schedule"] and not member["permissions"]["manage_members"]
    assert patch(client, member_url, owner_token, {"role":"w", "enabled":False}).status_code == 200
    assert client.get(f"{root}/settings", **auth_header(worker_token)).status_code == 404
    assert client.get(f"{root}/tasks", **auth_header(worker_token)).status_code == 404
    assert patch(client, member_url, owner_token, {"enabled":True}).status_code == 200
    assert client.get(f"{root}/settings", **auth_header(worker_token)).status_code == 200


def test_preferences_are_personal_validated_and_enforced_for_posts_comments_push(site, monkeypatch):
    project, owner, worker, _, member, owner_token, worker_token = site
    client = Client(); url = f"/api/v1/projects/{project.id}/settings"
    assert patch(client, url, worker_token, {"notification_preferences":{"posts":False, "push":False}}).status_code == 200
    assert patch(client, url, worker_token, {"notification_preferences":{"bad":True}}).status_code == 400
    assert patch(client, url, worker_token, {"notification_preferences":{"posts":"false"}}).status_code == 422
    task = ProjectTask.objects.create(project=project, name="Fase", date_start=date.today(), date_end=date.today())
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Aggiornamento")
    notify_post_created(actor_profile=owner, post=post, mentioned_profiles=[])
    assert not Notification.objects.filter(recipient_profile=worker).exists()
    comment = PostComment.objects.create(post=post, author=owner, text="Risposta")
    notify_comment_created(actor_profile=owner, post=post, comment=comment, mentioned_profiles=[])
    notification = Notification.objects.get(recipient_profile=worker)
    assert notification.kind == "project.comment.created", "All members receive comments unless they choose otherwise"
    from edilcloud.modules.projects.notification_preferences import project_notification_allowed
    assert not project_notification_allowed(profile=worker, project_id=project.id, kind=notification.kind, push=True)
    assert client.get(url, **auth_header(owner_token)).json()["notification_preferences"]["posts"] is True


def test_self_notifications_excluded_by_user_even_with_other_company_profile(site):
    project, owner, _, _, _, _, _ = site
    company = Workspace.objects.create(name="Altra azienda della stessa persona")
    other_profile = Profile.objects.create(workspace=company, user=owner.user, email=owner.email, role="w")
    assert create_notification(recipient_profile=other_profile, sender_profile=owner,
        sender_user=owner.user, subject="Azione propria", project_id=project.id) is None
    assert not Notification.objects.filter(recipient_profile=other_profile).exists()
    assert create_notification(recipient_profile=owner, sender_profile=owner, subject="Azione propria") is None


def test_profile_badge_excludes_historical_self_notifications(site):
    from edilcloud.modules.workspaces.services import list_active_profiles
    _, owner, worker, *_ = site
    company = Workspace.objects.create(name="Altro profilo dello stesso utente")
    other = Profile.objects.create(workspace=company, user=owner.user, email=owner.email, role="w")
    # Legacy records must agree with the notification centre without deleting history.
    Notification.objects.bulk_create([
        Notification(recipient_profile=owner, sender_profile=other, subject="Propria azione"),
        Notification(recipient_profile=owner, sender_user=owner.user, subject="Propria azione"),
        Notification(recipient_profile=owner, sender_profile=worker, subject="Novità reale"),
    ])
    profiles = {item["id"]: item for item in list_active_profiles(owner.user)}
    assert profiles[owner.id]["unread_notification_count"] == 1
    assert profiles[other.id]["unread_notification_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_project_socket_closes_after_membership_revocation():
    from asgiref.sync import async_to_sync, sync_to_async
    from asgiref.testing import ApplicationCommunicator
    from edilcloud.platform.realtime.consumers import ProjectRealtimeConsumer
    from edilcloud.platform.realtime.services import issue_realtime_ticket
    workspace = Workspace.objects.create(name="Revoca accesso realtime")
    user, profile = create_workspace_user(workspace=workspace, email="socket.revoke@example.test",
        password="test123", first_name="Mario", last_name="Rossi", role="w")
    project = Project.objects.create(workspace=workspace, created_by=profile, name="Cantiere", date_start=date.today())
    member = ProjectMember.objects.create(project=project, profile=profile, role="w")

    async def scenario():
        ticket, _ = issue_realtime_ticket(user_id=user.id, profile_id=profile.id, channel="project", project_id=project.id)
        socket = ApplicationCommunicator(ProjectRealtimeConsumer.as_asgi(), {
            "type": "websocket", "path": f"/ws/realtime/projects/{project.id}/", "headers": [],
            "url_route": {"kwargs": {"project_id": project.id}},
            "query_string": f"ticket={ticket}".encode(), "subprotocols": [],
        })
        await socket.send_input({"type": "websocket.connect"})
        assert (await socket.receive_output())["type"] == "websocket.accept"
        await sync_to_async(lambda: ProjectMember.objects.filter(pk=member.pk).update(disabled=True))()
        await socket.send_input({"type": "realtime.event", "payload": {"type": "project.settings.updated"}})
        result = await socket.receive_output()
        assert result["type"] == "websocket.close" and result["code"] == 4403
        await socket.send_input({"type": "websocket.disconnect", "code": 4403})
        await socket.wait()
    async_to_sync(scenario)()


def test_push_outbox_retries_transient_errors_without_resending_successes(site, monkeypatch):
    project, owner, worker, *_ = site
    notification = create_notification(recipient_profile=worker, sender_profile=owner, subject="Avanzamento", kind="project.post.created", project_id=project.id)
    job = NotificationPushJob.objects.get(notification=notification); job.state="pending"; job.save()
    good = NotificationDevice.objects.create(user=worker.user, profile=worker, token="g"*80)
    bad = NotificationDevice.objects.create(user=worker.user, profile=worker, token="b"*80)
    attempts = []
    monkeypatch.setattr("edilcloud.modules.notifications.push.push_enabled", lambda: True)
    def send(*, device, notification):
        attempts.append(device.id)
        if device.id == bad.id and attempts.count(bad.id) == 1:
            raise NotificationPushError("busy", code="UNAVAILABLE", retry_after_seconds=600)
        return "accepted-by-fcm"
    monkeypatch.setattr("edilcloud.modules.notifications.push._send_push", send)
    assert process_push_job(notification.id)
    job.refresh_from_db(); assert job.state == "retry" and job.next_attempt_at >= timezone.now()+timedelta(seconds=590)
    assert not process_push_job(notification.id), "A job cannot be retried before its due time"
    job.next_attempt_at = timezone.now()-timedelta(seconds=1); job.save()
    assert process_push_job(notification.id)
    job.refresh_from_db(); assert job.state == "complete"
    assert attempts.count(good.id) == 1 and attempts.count(bad.id) == 2
    assert NotificationPushDelivery.objects.filter(notification=notification, status="sent").count() == 2


def test_expired_worker_lease_recovers_and_revoked_project_access_prevents_push(site, monkeypatch):
    project, owner, worker, _, member, *_ = site
    notification = create_notification(recipient_profile=worker, sender_profile=owner, subject="Avanzamento", kind="project.post.created", project_id=project.id)
    NotificationPushJob.objects.filter(notification=notification).update(state="processing", locked_until=timezone.now()-timedelta(minutes=1))
    assert notification.id in due_push_jobs()
    monkeypatch.setattr("edilcloud.modules.notifications.push.push_enabled", lambda: True)
    monkeypatch.setattr("edilcloud.modules.notifications.push._send_push", lambda **kwargs: pytest.fail("No push after access revocation"))
    member.disabled = True; member.save()
    assert process_push_job(notification.id)
    notification.push_job.refresh_from_db(); assert notification.push_job.state == "skipped"


def test_device_registration_binds_session_and_logout_does_not_disable_other_device(site):
    project, owner, worker, *_ = site
    client = Client()
    def login():
        response = client.post('/api/v1/auth/login', data=json.dumps({'username_or_email':worker.email,'password':'test123'}), content_type='application/json')
        assert response.status_code == 200
        return response.json()
    first, second = login(), login()
    for index, credentials in enumerate((first, second)):
        response = client.post('/api/v1/notifications/devices/register', data=json.dumps({'token':str(index)*80,'installation_id':f'phone-{index}','platform':'android'}),content_type='application/json', **auth_header(credentials['token']))
        assert response.status_code == 200
    one, two = NotificationDevice.objects.get(installation_id='phone-0'), NotificationDevice.objects.get(installation_id='phone-1')
    assert str(one.auth_session_id) == first['session_id']
    response = client.post('/api/v1/auth/logout',data=json.dumps({'refresh_token':first['refresh_token']}),content_type='application/json')
    assert response.status_code == 200
    one.refresh_from_db(); two.refresh_from_db()
    assert not one.is_active and two.is_active


@pytest.mark.parametrize('code,message,invalid',[
    ('INVALID_ARGUMENT', 'Invalid data key in message payload',False),
    ('INVALID_ARGUMENT', 'The registration token is not a valid FCM registration token',True),
    ('UNREGISTERED','Requested entity was not found',True),
])
def test_fcm_payload_errors_do_not_deactivate_valid_tokens(site, monkeypatch, code, message, invalid):
    import httpx
    from edilcloud.modules.notifications.push import _send_push, NotificationPushInvalidToken
    project, owner, worker, *_ = site
    notification = create_notification(recipient_profile=worker, subject='Prova', sender_profile=owner, project_id=project.id)
    device = NotificationDevice.objects.create(user=worker.user,profile=worker,token='a'*80)
    monkeypatch.setattr('edilcloud.modules.notifications.push._load_service_account_info',lambda:{'project_id':'test'})
    monkeypatch.setattr('edilcloud.modules.notifications.push._issue_access_token',lambda _: 'test-access')
    monkeypatch.setattr('edilcloud.modules.notifications.push.httpx.post',lambda *args,**kwargs: httpx.Response(400,json={'error':{'status':code,'message':message}}))
    with pytest.raises(NotificationPushError) as raised:
        _send_push(device=device,notification=notification)
    assert isinstance(raised.value,NotificationPushInvalidToken) is invalid
