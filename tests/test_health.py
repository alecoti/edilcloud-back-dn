import pytest
from django.test import Client

from edilcloud.platform.telemetry import reset_metrics


@pytest.mark.django_db
def test_root_endpoint_returns_service_metadata():
    client = Client()
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "edilcloud-back-dn"
    assert payload["status"] == "ok"


@pytest.mark.django_db
def test_health_endpoint_returns_ok():
    client = Client()
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "edilcloud-back-dn"
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0-dev"
    assert payload["cache"] == "ok"
    assert payload["realtime"] == "ok"
    assert payload["log_format"] == "console"
    assert payload["log_level"] == "INFO"
    assert payload["sentry"] == "disabled"
    assert payload["openai"] in {"configured", "disabled"}
    assert payload["vector_store"] in {"pgvector", "disabled"}
    assert response.headers["X-Request-ID"]


@pytest.mark.django_db
def test_request_context_echoes_request_id_header():
    client = Client()
    response = client.get("/", HTTP_X_REQUEST_ID="req-test-123")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-123"


@pytest.mark.django_db
def test_metrics_summary_reports_slowest_endpoints_and_totals():
    reset_metrics()
    client = Client()

    assert client.get("/").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    response = client.get("/api/v1/health/metrics/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    summary = payload["summary"]
    assert summary["http"]["totals"]["requests"] >= 3
    assert summary["http"]["totals"]["errors"] == 0
    assert summary["http"]["endpoints"]
    health_endpoint = next(
        item
        for item in summary["http"]["endpoints"]
        if item["path"] == "/api/v1/health" and item["method"] == "GET"
    )
    assert health_endpoint["requests"] >= 2
    assert health_endpoint["performance_status"] in {"ok", "warning", "critical"}
    assert isinstance(summary["http"]["top_slowest"], list)
    assert isinstance(summary["http"]["hot_paths"], list)


@pytest.mark.django_db
def test_metrics_budget_reports_rules_and_status():
    reset_metrics()
    client = Client()

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    response = client.get("/api/v1/health/metrics/budget")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    budget = payload["budget"]
    assert budget["status"] in {"pass", "partial", "fail"}
    assert budget["checked_rules"] >= 1
    assert isinstance(budget["rules"], list)
    health_rule = next(item for item in budget["rules"] if item["key"] == "health")
    assert health_rule["status"] in {"pass", "fail", "no_data"}
    assert health_rule["requests"] >= 2


@pytest.mark.django_db
def test_metrics_reset_clears_telemetry_in_dev():
    reset_metrics()
    client = Client()

    assert client.get("/api/v1/health").status_code == 200
    before = client.get("/api/v1/health/metrics/summary").json()["summary"]
    assert before["http"]["totals"]["requests"] >= 1

    reset_response = client.post("/api/v1/health/metrics/reset")
    assert reset_response.status_code == 200
    assert reset_response.json() == {"status": "ok", "reset": True}

    after = client.get("/api/v1/health/metrics/summary").json()["summary"]
    assert after["http"]["totals"]["requests"] <= 1
