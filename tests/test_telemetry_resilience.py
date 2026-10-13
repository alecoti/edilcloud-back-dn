"""Regressions for session timeouts caused by an unbounded shared metric blob."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import resolve

from edilcloud.platform import telemetry
from edilcloud.platform.middleware.request_context import metric_path
from edilcloud.platform.performance_budget import evaluate_runtime_summary


@pytest.fixture(autouse=True)
def clean_metrics():
    telemetry.reset_metrics()
    yield
    telemetry.reset_metrics()


def test_request_write_uses_only_one_series_and_does_not_read_snapshot(monkeypatch):
    store = Mock()
    store.snapshot.side_effect = AssertionError("Request writes must not read all series")
    monkeypatch.setattr(telemetry, "redis_metric_store", lambda: store)
    telemetry.increment_counter("http.requests", method="POST", path="/api/v1/auth/token/verify", status=200)
    telemetry.observe_duration("http.request.duration", 2.5, method="POST", path="/api/v1/auth/token/verify", status=200)
    store.increment.assert_called_once()
    store.observe.assert_called_once()
    store.snapshot.assert_not_called()


def test_old_large_blob_is_not_read_or_modified(monkeypatch):
    legacy = {"counters": {f"http.requests|path=/scan/{n}": 1 for n in range(38000)}}
    cache.set("telemetry:state:v2", legacy, timeout=None)
    original_get = cache.get

    def checked_get(key, *args, **kwargs):
        assert key != "telemetry:state:v2", "Legacy state must stay outside request work"
        return original_get(key, *args, **kwargs)

    monkeypatch.setattr(cache, "get", checked_get)
    telemetry.increment_counter("auth.test")
    telemetry.observe_duration("auth.test", 1)
    assert telemetry.metrics_snapshot()["counters"]["auth.test"] == 1
    assert original_get("telemetry:state:v2") == legacy
    cache.delete("telemetry:state:v2")


@pytest.mark.django_db
def test_unknown_urls_and_project_ids_do_not_create_individual_series():
    client = Client()
    for path in ("/unknown/a", "/unknown/b", "/api/v1/projects/14/tasks", "/api/v1/projects/33/tasks"):
        assert client.get(path).status_code in {401, 404}
    summary = telemetry.metrics_summary()["http"]
    paths = {row["path"] for row in summary["endpoints"]}
    assert paths == {"/<unmatched>", "/api/v1/projects/<project_id>/tasks"}
    assert summary["totals"]["requests"] == 4


def test_root_health_and_route_parameters_have_stable_metric_paths():
    factory = RequestFactory()
    for path, expected in (("/", "/"), ("/api/v1/health", "/api/v1/health"),
                           ("/api/v1/activities/169/posts", "/api/v1/activities/<activity_id>/posts")):
        request = factory.get(path)
        request.resolver_match = resolve(path)
        assert metric_path(request) == expected
    assert metric_path(SimpleNamespace()) == "/<unmatched>"


def test_telemetry_failure_preserves_application_response(monkeypatch):
    store = Mock()
    store.increment.side_effect = ConnectionError("Offline")
    store.observe.side_effect = ConnectionError("Offline")
    monkeypatch.setattr(telemetry, "redis_metric_store", lambda: store)
    response = Client().get("/")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_busy_fallback_lock_does_not_sleep_or_write_unlocked(monkeypatch):
    cache.add(telemetry._LOCK_KEY, "another-owner", timeout=5)
    telemetry.increment_counter("must-not-write-unlocked")
    assert "must-not-write-unlocked" not in telemetry.metrics_snapshot()["counters"]
    assert cache.get(telemetry._LOCK_KEY) == "another-owner"
    cache.delete(telemetry._LOCK_KEY)


def test_fallback_series_and_sample_limits_preserve_existing_counters(monkeypatch):
    monkeypatch.setattr(telemetry, "MAX_SERIES", 3)
    for n in range(10):
        telemetry.increment_counter(f"counter-{n}")
        telemetry.observe_duration(f"timing-{n}", n)
    for n in range(600):
        telemetry.increment_counter("counter-0")
        telemetry.observe_duration("timing-0", n)
    snapshot = telemetry.metrics_snapshot()
    assert len(snapshot["counters"]) == len(snapshot["timings"]) == 3
    assert snapshot["counters"]["counter-0"] == 601
    assert snapshot["timings"]["timing-0"]["count"] == 601
    assert snapshot["timings"]["timing-0"]["sample_size"] == 512


def test_concurrent_fallback_counter_updates_are_not_lost():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: telemetry.increment_counter("concurrent"), range(240)))
    assert telemetry.metrics_snapshot()["counters"]["concurrent"] == 240


def test_performance_budget_matches_normalized_routes_and_legacy_paths():
    for path in ("/api/v1/projects/14/tasks", "/api/v1/projects/<project_id>/tasks"):
        summary = {"http": {"endpoints": [{"method": "GET", "path": path,
            "requests": 20, "error_ratio": 0, "p95_ms": 100}]}}
        rules = evaluate_runtime_summary(summary)["rules"]
        assert next(row for row in rules if row["key"] == "projects.tasks")["status"] == "pass"
