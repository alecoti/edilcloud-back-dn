from __future__ import annotations

import hashlib

from django.core.cache import cache


class RateLimitExceeded(ValueError):
    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _normalize_key_part(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate or "anonymous"


def build_rate_limit_key(namespace: str, *parts: object) -> str:
    payload = ":".join(_normalize_key_part(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"rate-limit:{namespace}:{digest}"


def enforce_rate_limit(
    namespace: str,
    *,
    limit: int,
    window_seconds: int,
    key_parts: tuple[object, ...],
    message: str,
) -> None:
    cache_key = build_rate_limit_key(namespace, *key_parts)
    added = cache.add(cache_key, 1, timeout=window_seconds)
    count = 1

    if not added:
        try:
            count = cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, 1, timeout=window_seconds)
            count = 1

    if count > limit:
        raise RateLimitExceeded(message, retry_after=window_seconds)
