import pytest
from types import SimpleNamespace
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile

from edilcloud.modules.projects import services
from edilcloud.modules.projects.models import PostKind, ProjectPost
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.django_db
@pytest.mark.parametrize("content_type,expected_kind", [("audio/webm", "audio"), ("video/webm", "video")])
def test_webm_media_preserves_its_kind_in_posts_comments_and_feed(content_type, expected_kind):
    client = Client()
    _, _, profile = create_workspace_profile(email="webm-media@example.com", password="devpass123")
    _, task, _, _ = create_project_fixture(profile)
    headers = auth_headers(client, email="webm-media@example.com", password="devpass123")
    upload = lambda: SimpleUploadedFile("recording.webm", b"\x1a\x45\xdf\xa3QA", content_type=content_type)
    response = client.post(f"/api/v1/tasks/{task.id}/posts", {
        "text": "Registrazione QA", "source_language": "it", "attachment": upload()}, **headers)
    assert response.status_code == 201, response.content
    post_id = response.json()["id"]
    assert response.json()["media_set"][0]["type"] == expected_kind
    comment = client.post(f"/api/v1/posts/{post_id}/comments", {
        "text": "Commento QA", "source_language": "it", "attachment": upload()}, **headers)
    assert comment.status_code == 201, comment.content
    assert comment.json()["media_set"][0]["type"] == expected_kind
    feed = client.get("/api/v1/projects/feed", **headers).json()
    post = next(p for p in feed["items"] if p["id"] == post_id)
    assert post["media_set"][0]["type"] == expected_kind
    assert post["comment_set"][0]["media_set"][0]["type"] == expected_kind


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["nota-vocale-20261013-090000.webm", "commento-vocale-20261013-090000.webm"])
def test_legacy_web_recordings_are_audio_without_mime_metadata(name):
    from django.core.files.base import ContentFile
    from edilcloud.modules.projects.models import PostAttachment
    _, _, profile = create_workspace_profile(email="legacy-webm@example.com", password="devpass123")
    _, _, _, post = create_project_fixture(profile)
    attachment = PostAttachment.objects.create(post=post, file=ContentFile(b"QA", name=name))
    assert services.serialize_attachment(attachment)["type"] == "audio"


@pytest.mark.parametrize('kind,alert,expected', [
    (PostKind.WORK_PROGRESS, True, ('open', '#ef4444', 'danger')),
    (PostKind.ISSUE, False, ('resolved', '#16a34a', 'success')),
    (PostKind.WORK_PROGRESS, False, ('linked', '#2563eb', 'info')),
])
def test_drawing_pin_uses_the_same_issue_status_as_feed(kind, alert, expected):
    pin = SimpleNamespace(post=SimpleNamespace(post_kind=kind, alert=alert))
    assert services.drawing_pin_visual_state(pin) == expected


@pytest.mark.django_db
def test_legacy_alert_is_an_issue_in_feed_detail_and_after_resolution():
    client = Client()
    _, _, profile = create_workspace_profile(email="legacy-issue@example.com", password="devpass123")
    _, task, _, post = create_project_fixture(profile)
    ProjectPost.objects.filter(id=post.id).update(post_kind=PostKind.WORK_PROGRESS, alert=True)
    headers = auth_headers(client, email="legacy-issue@example.com", password="devpass123")
    for url in (f"/api/v1/tasks/{task.id}/posts?include_activities=true", "/api/v1/projects/feed"):
        response = client.get(url, **headers)
        assert response.status_code == 200, response.content
        payload = response.json()
        item = next(p for p in (payload if isinstance(payload, list) else payload["items"]) if p["id"] == post.id)
        assert item["post_kind"] == "issue"
        assert item["alert"] is True
    response = client.patch(f"/api/v1/posts/{post.id}", {"alert": False}, content_type="application/json", **headers)
    assert response.status_code == 200, response.content
    assert response.json()["post_kind"] == "issue"
    assert response.json()["alert"] is False
    post.refresh_from_db()
    assert post.post_kind == PostKind.ISSUE


@pytest.mark.django_db
def test_arabic_post_and_comment_are_localized_for_each_readers_settings(monkeypatch):
    client = Client()
    _, _, profile = create_workspace_profile(email="auto-language@example.com", password="devpass123")
    _, task, _, _ = create_project_fixture(profile)
    headers = auth_headers(client, email="auto-language@example.com", password="devpass123")
    source = "تم الانتهاء من أعمال الخرسانة"
    translations = {"it": "I lavori in calcestruzzo sono terminati.", "fr": "Les travaux de béton sont terminés."}
    calls = []

    def translate(*, source_text, source_language, target_language):
        calls.append((source_text, source_language, target_language))
        return translations[target_language]

    monkeypatch.setattr(services, "generate_project_content_translation", translate)
    response = client.post(f"/api/v1/tasks/{task.id}/posts", {"text": source, "source_language": ""}, **headers)
    assert response.status_code == 201, response.content
    post_id = response.json()["id"]
    comment = client.post(f"/api/v1/posts/{post_id}/comments", {"text": source, "source_language": ""}, **headers)
    assert comment.status_code == 201, comment.content
    for language in ("it", "fr", "it"):
        # No locale override: the server must use the viewing profile's preference.
        profile.language = language
        profile.save(update_fields=["language"])
        response = client.get(f"/api/v1/tasks/{task.id}/posts", **headers)
        assert response.status_code == 200, response.content
        payload = next(p for p in response.json() if p["id"] == post_id)
        for item in (payload, payload["comment_set"][0]):
            assert item["text"] == translations[language]
            assert item["original_text"] == source
            assert item["display_language"] == language
            assert item["is_translated"] is True
    assert len([c for c in calls if c[0] == source]) == 4
    stored = ProjectPost.objects.get(id=post_id)
    assert stored.text == stored.original_text == source
