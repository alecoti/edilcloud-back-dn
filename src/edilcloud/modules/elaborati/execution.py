"""Read-only execution diagnostics; never infer an outage or replay a request."""
from datetime import timedelta


def execution_status(*, state, created_at, lease_expires_at, now):
    if state == "queued" and created_at <= now - timedelta(seconds=60):
        return "queue_delayed"
    if state == "running" and (lease_expires_at is None or lease_expires_at <= now):
        return "lease_expired"
    return state
