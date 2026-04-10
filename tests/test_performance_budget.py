from edilcloud.platform.performance_budget import evaluate_runtime_summary


def test_evaluate_runtime_summary_marks_rule_as_fail_when_p95_exceeds_budget():
    summary = {
        "http": {
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/overview",
                    "requests": 12,
                    "error_ratio": 0.0,
                    "p95_ms": 1820.0,
                }
            ]
        }
    }

    report = evaluate_runtime_summary(summary)

    overview_rule = next(item for item in report["rules"] if item["key"] == "projects.overview")
    assert overview_rule["status"] == "fail"
    assert report["status"] == "fail"


def test_evaluate_runtime_summary_marks_rule_as_no_data_when_path_was_not_seen():
    summary = {"http": {"endpoints": []}}

    report = evaluate_runtime_summary(summary)

    search_rule = next(item for item in report["rules"] if item["key"] == "search.global")
    assert search_rule["status"] == "no_data"
    assert report["no_data_rules"] >= 1


def test_evaluate_runtime_summary_supports_expanded_core_matrix():
    summary = {
        "http": {
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/api/v1/health",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 40.0,
                },
                {
                    "method": "POST",
                    "path": "/api/v1/auth/login",
                    "requests": 6,
                    "error_ratio": 0.0,
                    "p95_ms": 280.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 210.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/overview",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 310.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/feed",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 240.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/tasks",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 260.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/gantt",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 290.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/documents",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 250.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/search/global",
                    "requests": 20,
                    "error_ratio": 0.0,
                    "p95_ms": 180.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/notifications",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 170.0,
                },
                {
                    "method": "GET",
                    "path": "/api/v1/projects/12/assistant",
                    "requests": 8,
                    "error_ratio": 0.0,
                    "p95_ms": 420.0,
                },
            ]
        }
    }

    report = evaluate_runtime_summary(summary)

    assert report["status"] == "pass"
    assert report["score_percent"] == 100
    assert report["no_data_rules"] == 0
    auth_rule = next(item for item in report["rules"] if item["key"] == "auth.login")
    projects_list_rule = next(item for item in report["rules"] if item["key"] == "projects.list")
    feed_rule = next(item for item in report["rules"] if item["key"] == "projects.feed")
    notifications_rule = next(item for item in report["rules"] if item["key"] == "notifications.list")
    documents_rule = next(item for item in report["rules"] if item["key"] == "projects.documents")
    assistant_rule = next(item for item in report["rules"] if item["key"] == "assistant.state")
    assert auth_rule["status"] == "pass"
    assert projects_list_rule["status"] == "pass"
    assert feed_rule["status"] == "pass"
    assert notifications_rule["status"] == "pass"
    assert documents_rule["status"] == "pass"
    assert assistant_rule["status"] == "pass"
