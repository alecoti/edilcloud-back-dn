from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from edilcloud.platform.logging import reset_request_context, set_request_context, update_request_context
from edilcloud.platform.telemetry import increment_counter, observe_duration


logger = logging.getLogger("edilcloud.request")


def get_client_ip(request) -> str:
    forwarded_for = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return (request.META.get("REMOTE_ADDR") or "").strip() or "unknown"


class RequestContextMiddleware:
    header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (request.headers.get(self.header_name) or uuid4().hex).strip() or uuid4().hex
        request.request_id = request_id
        start = perf_counter()
        token = set_request_context(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "query_string": request.META.get("QUERY_STRING", ""),
                "client_ip": get_client_ip(request),
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:255],
            }
        )
        try:
            response = self.get_response(request)
        finally:
            duration_ms = round((perf_counter() - start) * 1000, 2)
            status_code = getattr(locals().get("response"), "status_code", 500)
            update_request_context(status_code=status_code, duration_ms=duration_ms)
            increment_counter(
                "http.requests",
                method=request.method,
                path=request.path,
                status=status_code,
            )
            observe_duration(
                "http.request.duration",
                duration_ms,
                method=request.method,
                path=request.path,
                status=status_code,
            )
            logger.info(
                "http.request.completed",
                extra={
                    "event": "http.request.completed",
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            reset_request_context(token)
        response[self.header_name] = request_id
        return response
