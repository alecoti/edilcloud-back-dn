from concurrent.futures import ThreadPoolExecutor
from copy import copy
from datetime import timedelta
import time

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from edilcloud.modules.projects import weather
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.fixture
def site(db):
    cache.clear()
    _, _, profile = create_workspace_profile(email="shared-weather@example.com", password="TestPass123!")
    project, task, activity, _ = create_project_fixture(profile)
    yield profile, project, task, activity
    cache.clear()


@pytest.fixture
def provider(monkeypatch):
    calls = []
    def request(project, language, endpoint, **parameters):
        calls.append((endpoint, language, parameters))
        if endpoint == "currentConditions:lookup":
            return {"currentTime": "2026-10-14T09:00:00Z", "temperature": {"degrees": 22},
                    "weatherCondition": {"type": "CLEAR", "description": {"text": language}}}
        today = timezone.localdate()
        return {"forecastDays": [{"displayDate": {"year": day.year, "month": day.month, "day": day.day},
                                  "maxTemperature": {"degrees": 22}, "minTemperature": {"degrees": 12}}
                                 for day in (today + timedelta(days=n) for n in range(10))]}
    monkeypatch.setattr(weather, "_request", request)
    return calls


def test_shared_current_cache_has_three_hour_refresh_and_location_language_isolation(site, provider, monkeypatch):
    _, project, _, _ = site
    clock = time.time()
    monkeypatch.setattr(weather.time, "time", lambda: clock)
    first = weather.current_weather(project, "it")
    twin = copy(project)
    twin.pk += 999
    twin.google_place_id = "other-place"
    assert weather.current_weather(twin, "it")["googlePlaceId"] == "other-place"
    assert len(provider) == 1
    clock += 3 * 3600 - 1
    assert weather.current_weather(project, "it") == first
    assert len(provider) == 1
    clock += 2
    weather.current_weather(project, "it")
    assert len(provider) == 2
    assert weather.current_weather(project, "en")["summary"] == "en"
    project.latitude += .1
    weather.current_weather(project, "it")
    assert len(provider) == 4


def test_one_daily_forecast_window_serves_five_seven_and_ten_days(site, provider, monkeypatch):
    _, project, _, _ = site
    today = timezone.localdate()
    assert len(weather.forecast_weather(project, "it", 5)) == 5
    assert len(weather.forecast_weather(project, "it", 7)) == 7
    assert len(weather.forecast_weather(project, "it", 10)) == 10
    assert provider == [("forecast/days:lookup", "it", {"days": 10, "pageSize": 10})]
    monkeypatch.setattr(weather.timezone, "localdate", lambda: today + timedelta(days=1))
    assert weather.forecast_weather(project, "it")[0]["date"] == (today + timedelta(days=1)).isoformat()
    assert len(provider) == 2


@pytest.mark.parametrize("resource", ["weather", "forecast"])
def test_api_authorizes_before_cache_or_provider_and_supports_web_and_native(site, provider, resource):
    profile, project, _, _ = site
    client = Client()
    path = f"/api/v1/projects/{project.pk}/{resource}"
    assert client.get(path).status_code == 401
    _, _, outsider = create_workspace_profile(email="outside-weather@example.com", password="TestPass123!")
    headers = auth_headers(client, email=outsider.email, password="TestPass123!")
    assert client.get(path, **headers).status_code == 404
    assert provider == []
    headers = auth_headers(client, email=profile.email, password="TestPass123!")
    response = client.get(path, **headers)
    assert response.status_code == 200, response.content
    assert response.headers["Cache-Control"] == "private, no-store"
    assert len(provider) == 1
    assert client.get(path, **headers).json() == response.json()
    assert len(provider) == 1


@pytest.mark.parametrize("kind", ["tasks", "activities"])
def test_publishing_reads_shared_snapshot_without_provider_and_preserves_explicit_offline_weather(site, provider, kind, monkeypatch):
    profile, project, task, activity = site
    snapshot = weather.current_weather(project, "it")
    monkeypatch.setattr(weather, "_request", lambda *a, **k: pytest.fail("Publishing must not call Google"))
    client = Client()
    headers = auth_headers(client, email=profile.email, password="TestPass123!")
    path = f"/api/v1/{kind}/{task.id if kind == 'tasks' else activity.id}/posts"
    result = client.post(path, {"text": "Aggiornamento senza chiamata meteo"}, **headers)
    assert result.status_code == 201, result.content
    assert result.json()["weather_snapshot"] == snapshot
    cache.clear()
    result = client.post(path, {"text": "Anche senza cache pubblico subito"}, **headers)
    assert result.status_code == 201, result.content
    assert result.json()["weather_snapshot"] is None


def test_cache_read_failure_does_not_break_post_weather(site, monkeypatch):
    _, project, _, _ = site
    monkeypatch.setattr(weather.cache, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    assert weather.cached_post_weather(project, "it") is None


def test_stale_current_is_reused_on_provider_error_with_failure_backoff(site, provider, monkeypatch):
    _, project, _, _ = site
    snapshot = weather.current_weather(project, "it")
    key = weather._key(project, "it", "current")
    entry = cache.get(key)
    entry["refresh_after"] = 0
    cache.set(key, entry)
    failures = []
    def failing(*a, **k):
        failures.append(True)
        raise weather.WeatherUnavailable("Provider unavailable")
    monkeypatch.setattr(weather, "_request", failing)
    assert weather.current_weather(project, "it") == snapshot
    assert weather.current_weather(project, "it") == snapshot
    assert len(failures) == 1
    assert cache.get(key + ":lease") is None


@pytest.mark.parametrize("kind", ["current", "forecast"])
def test_concurrent_overviews_share_one_cold_provider_request(site, provider, monkeypatch, kind):
    _, project, _, _ = site
    original = weather._request
    def slow(*a, **k):
        time.sleep(.15)
        return original(*a, **k)
    monkeypatch.setattr(weather, "_request", slow)
    fetch = weather.current_weather if kind == "current" else weather.forecast_weather
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: fetch(project, "it"), range(5)))
    assert all(result == results[0] for result in results)
    assert len(provider) == 1


def test_scheduled_refresh_only_warms_active_real_sites(site, provider):
    _, project, _, _ = site
    assert weather.refresh_active_project_weather() == {"projects": 1, "errors": 0}
    assert len(provider) == 2
    assert weather.refresh_active_project_weather() == {"projects": 1, "errors": 0}
    assert len(provider) == 2
    project.is_demo_master = True
    project.save(update_fields=["is_demo_master"])
    assert weather.refresh_active_project_weather() == {"projects": 0, "errors": 0}


@pytest.mark.parametrize("latitude,longitude", [(None,9), (91,9), (45,181), (float("nan"),9)])
def test_invalid_or_missing_coordinates_do_not_call_provider(site, provider, latitude, longitude):
    _, project, _, _ = site
    project.latitude, project.longitude = latitude, longitude
    assert weather.current_weather(project, "it") is None
    assert weather.forecast_weather(project, "it") == []
    assert provider == []
