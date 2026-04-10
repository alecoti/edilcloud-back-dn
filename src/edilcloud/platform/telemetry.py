from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from math import ceil
from threading import Lock
from time import sleep, time

from django.core.cache import cache


@dataclass
class MetricSeries:
    count: int = 0
    sum: float = 0.0
    max: float = 0.0
    min: float = 0.0
    samples: list[float] = field(default_factory=list)


_LOCAL_LOCK = Lock()
_MAX_TIMING_SAMPLES = 512
_CACHE_KEY = "telemetry:state:v2"
_LOCK_KEY = "telemetry:state:v2:lock"
_LOCK_TIMEOUT_SECONDS = 2
_LOCK_RETRY_SECONDS = 0.01
_LOCK_ATTEMPTS = 50


def _metric_key(name: str, labels: dict[str, object] | None = None) -> str:
    normalized_labels = {
        key: value
        for key, value in sorted((labels or {}).items())
        if value not in (None, "")
    }
    if not normalized_labels:
        return name
    serialized = ",".join(f"{key}={value}" for key, value in normalized_labels.items())
    return f"{name}|{serialized}"


def _empty_state() -> dict[str, object]:
    return {
        "started_at": time(),
        "counters": {},
        "timings": {},
    }


def _load_state() -> dict[str, object]:
    payload = cache.get(_CACHE_KEY)
    if isinstance(payload, dict):
        return payload
    state = _empty_state()
    cache.set(_CACHE_KEY, state, timeout=None)
    return state


def _save_state(state: dict[str, object]) -> None:
    cache.set(_CACHE_KEY, state, timeout=None)


def _acquire_cache_lock() -> bool:
    for _ in range(_LOCK_ATTEMPTS):
        if cache.add(_LOCK_KEY, "1", timeout=_LOCK_TIMEOUT_SECONDS):
            return True
        sleep(_LOCK_RETRY_SECONDS)
    return False


def _release_cache_lock() -> None:
    cache.delete(_LOCK_KEY)


def _mutate_shared_state(mutator) -> None:
    with _LOCAL_LOCK:
        acquired = _acquire_cache_lock()
        try:
            state = _load_state()
            mutator(state)
            _save_state(state)
        finally:
            if acquired:
                _release_cache_lock()


def increment_counter(name: str, value: int = 1, **labels: object) -> None:
    key = _metric_key(name, labels)

    def apply(state: dict[str, object]) -> None:
        counters = state.setdefault("counters", {})
        if not isinstance(counters, dict):
            counters = {}
            state["counters"] = counters
        counters[key] = int(counters.get(key, 0)) + value

    _mutate_shared_state(apply)


def observe_duration(name: str, value_ms: float, **labels: object) -> None:
    key = _metric_key(name, labels)
    numeric_value = float(value_ms)

    def apply(state: dict[str, object]) -> None:
        timings = state.setdefault("timings", {})
        if not isinstance(timings, dict):
            timings = {}
            state["timings"] = timings
        raw_series = timings.get(key)
        if not isinstance(raw_series, dict):
            raw_series = {
                "count": 0,
                "sum": 0.0,
                "max": 0.0,
                "min": 0.0,
                "samples": [],
            }
            timings[key] = raw_series

        raw_series["count"] = int(raw_series.get("count", 0)) + 1
        raw_series["sum"] = float(raw_series.get("sum", 0.0)) + numeric_value
        raw_series["max"] = max(float(raw_series.get("max", 0.0)), numeric_value)
        raw_series["min"] = (
            numeric_value
            if int(raw_series["count"]) == 1
            else min(float(raw_series.get("min", numeric_value)), numeric_value)
        )

        samples = raw_series.get("samples")
        if not isinstance(samples, list):
            samples = []
            raw_series["samples"] = samples
        if len(samples) < _MAX_TIMING_SAMPLES:
            samples.append(numeric_value)
        else:
            sample_index = int(raw_series["count"]) % _MAX_TIMING_SAMPLES
            samples[sample_index] = numeric_value

    _mutate_shared_state(apply)


def _percentile(values: list[float], target_percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(0, min(len(ordered) - 1, ceil((target_percentile / 100) * len(ordered)) - 1))
    return round(ordered[rank], 2)


def _parse_metric_key(key: str) -> tuple[str, dict[str, str]]:
    if "|" not in key:
        return key, {}
    name, raw_labels = key.split("|", 1)
    labels: dict[str, str] = {}
    for chunk in raw_labels.split(","):
        if "=" not in chunk:
            continue
        label_key, label_value = chunk.split("=", 1)
        labels[label_key] = label_value
    return name, labels


def reset_metrics() -> None:
    with _LOCAL_LOCK:
        cache.delete(_CACHE_KEY)
        cache.delete(_LOCK_KEY)
        _save_state(_empty_state())


def _build_http_endpoint_summary(
    counters: dict[str, int],
    timings: dict[str, MetricSeries],
) -> dict[str, object]:
    endpoint_index: dict[tuple[str, str], dict[str, object]] = {}

    for key, count in counters.items():
        name, labels = _parse_metric_key(key)
        if name != "http.requests":
            continue
        method = labels.get("method", "GET")
        path = labels.get("path", "/")
        status = labels.get("status", "unknown")
        endpoint = endpoint_index.setdefault(
            (method, path),
            {
                "method": method,
                "path": path,
                "requests": 0,
                "errors": 0,
                "status_counts": defaultdict(int),
                "avg_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
                "min_ms": 0.0,
            },
        )
        endpoint["requests"] = int(endpoint["requests"]) + count
        endpoint["status_counts"][status] += count
        try:
            if int(status) >= 400:
                endpoint["errors"] = int(endpoint["errors"]) + count
        except (TypeError, ValueError):
            endpoint["errors"] = int(endpoint["errors"]) + count

    for key, series in timings.items():
        name, labels = _parse_metric_key(key)
        if name != "http.request.duration":
            continue
        method = labels.get("method", "GET")
        path = labels.get("path", "/")
        endpoint = endpoint_index.setdefault(
            (method, path),
            {
                "method": method,
                "path": path,
                "requests": 0,
                "errors": 0,
                "status_counts": defaultdict(int),
                "avg_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
                "min_ms": 0.0,
            },
        )
        requests = max(int(endpoint["requests"]), series.count)
        endpoint["requests"] = requests
        endpoint["avg_ms"] = round(series.sum / series.count, 2) if series.count else 0.0
        endpoint["p95_ms"] = _percentile(series.samples, 95)
        endpoint["p99_ms"] = _percentile(series.samples, 99)
        endpoint["max_ms"] = round(series.max, 2)
        endpoint["min_ms"] = round(series.min, 2) if series.count else 0.0

    endpoints: list[dict[str, object]] = []
    total_requests = 0
    total_errors = 0
    for endpoint in endpoint_index.values():
        requests = int(endpoint["requests"])
        errors = int(endpoint["errors"])
        total_requests += requests
        total_errors += errors
        error_ratio = round(errors / requests, 4) if requests else 0.0
        p95_ms = float(endpoint["p95_ms"])
        if p95_ms >= 2000:
            performance_status = "critical"
        elif p95_ms >= 800:
            performance_status = "warning"
        else:
            performance_status = "ok"
        endpoints.append(
            {
                "method": endpoint["method"],
                "path": endpoint["path"],
                "requests": requests,
                "errors": errors,
                "error_ratio": error_ratio,
                "avg_ms": endpoint["avg_ms"],
                "p95_ms": endpoint["p95_ms"],
                "p99_ms": endpoint["p99_ms"],
                "max_ms": endpoint["max_ms"],
                "min_ms": endpoint["min_ms"],
                "performance_status": performance_status,
                "status_counts": dict(endpoint["status_counts"]),
            }
        )

    endpoints.sort(
        key=lambda item: (
            {"critical": 2, "warning": 1, "ok": 0}[str(item["performance_status"])],
            float(item["p95_ms"]),
            int(item["requests"]),
        ),
        reverse=True,
    )
    return {
        "totals": {
            "requests": total_requests,
            "errors": total_errors,
            "error_ratio": round(total_errors / total_requests, 4) if total_requests else 0.0,
        },
        "endpoints": endpoints,
        "top_slowest": endpoints[:5],
        "top_errors": sorted(
            [item for item in endpoints if int(item["errors"]) > 0],
            key=lambda item: (float(item["error_ratio"]), int(item["errors"])),
            reverse=True,
        )[:5],
        "hot_paths": sorted(
            endpoints,
            key=lambda item: (int(item["requests"]), float(item["p95_ms"])),
            reverse=True,
        )[:5],
    }


def _state_to_timings(raw_timings: dict[str, object]) -> dict[str, MetricSeries]:
    timings: dict[str, MetricSeries] = {}
    for key, value in raw_timings.items():
        if not isinstance(value, dict):
            continue
        samples = value.get("samples")
        timings[key] = MetricSeries(
            count=int(value.get("count", 0)),
            sum=float(value.get("sum", 0.0)),
            max=float(value.get("max", 0.0)),
            min=float(value.get("min", 0.0)),
            samples=[float(item) for item in samples] if isinstance(samples, list) else [],
        )
    return timings


def metrics_snapshot() -> dict[str, object]:
    state = _load_state()
    counters = state.get("counters") if isinstance(state, dict) else {}
    counters = counters if isinstance(counters, dict) else {}
    timings = state.get("timings") if isinstance(state, dict) else {}
    timings = timings if isinstance(timings, dict) else {}
    started_at = float(state.get("started_at") or time()) if isinstance(state, dict) else time()

    timing_payload = {}
    for key, series in _state_to_timings(timings).items():
        timing_payload[key] = {
            "count": series.count,
            "sum_ms": round(series.sum, 2),
            "avg_ms": round(series.sum / series.count, 2) if series.count else 0.0,
            "min_ms": round(series.min, 2) if series.count else 0.0,
            "p95_ms": _percentile(series.samples, 95),
            "p99_ms": _percentile(series.samples, 99),
            "max_ms": round(series.max, 2),
            "sample_size": len(series.samples),
        }

    return {
        "uptime_seconds": round(time() - started_at, 2),
        "counters": dict(counters),
        "timings": timing_payload,
    }


def metrics_summary() -> dict[str, object]:
    state = _load_state()
    counters = state.get("counters") if isinstance(state, dict) else {}
    counters = counters if isinstance(counters, dict) else {}
    timings = state.get("timings") if isinstance(state, dict) else {}
    timings = timings if isinstance(timings, dict) else {}
    started_at = float(state.get("started_at") or time()) if isinstance(state, dict) else time()

    http_summary = _build_http_endpoint_summary(
        {key: int(value) for key, value in counters.items()},
        _state_to_timings(timings),
    )
    return {
        "uptime_seconds": round(time() - started_at, 2),
        "http": http_summary,
    }
