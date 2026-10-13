import json

import pytest
from django.test import Client, RequestFactory

from edilcloud.modules.projects.api import parse_post_form_payload, parse_post_weather_snapshot
from edilcloud.modules.projects.models import ProjectPost
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.parametrize("raw", [None, "{broken", "[]", "null", "x" * 8193, '{"latitude":45}'])
def test_invalid_weather_never_blocks_publication(raw):
    assert parse_post_weather_snapshot(raw) == {}


def test_coordinates_alone_do_not_masquerade_as_weather():
    request = RequestFactory().post("/", {"project_latitude": "45", "project_longitude": "9"})
    assert parse_post_form_payload(request)["weather_payload"] == {}


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["tasks", "activities"])
def test_observed_weather_survives_post_creation_and_feed_read(kind):
    client = Client()
    _, _, profile = create_workspace_profile(email="weather@example.com", password="TestPass123!")
    _, task, activity, _ = create_project_fixture(profile)
    headers = auth_headers(client, email="weather@example.com", password="TestPass123!")
    snapshot = {"source": "google-weather", "recordedAt": "2026-10-13T10:00:00Z",
                "summary": "Pioggia", "conditionType": "RAIN", "temperatureC": 16,
                "latitude": 45.4642, "longitude": 9.19, "irrelevant_secret": "discard"}
    response = client.post(f"/api/v1/{kind}/{task.id if kind == 'tasks' else activity.id}/posts",
                           {"text": "Meteo registrato", "is_public": "true",
                            "weather_snapshot": json.dumps(snapshot)}, **headers)
    assert response.status_code == 201, response.content
    result = response.json()
    assert result["weather_snapshot"]["summary"] == "Pioggia"
    assert "irrelevant_secret" not in result["weather_snapshot"]
    stored = ProjectPost.objects.get(id=result["id"]).weather_snapshot
    assert stored["recordedAt"] == snapshot["recordedAt"]
    feed = client.get("/api/v1/projects/feed", **headers)
    assert feed.status_code == 200
    item = next(item for item in feed.json()["items"] if item["id"] == result["id"])
    assert item["weather_snapshot"] == stored
