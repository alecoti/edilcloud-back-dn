from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone


_request_context_var: contextvars.ContextVar[dict[str, object]] = contextvars.ContextVar(
    "edilcloud_request_context",
    default={},
)

_STANDARD_RECORD_ATTRS = set(vars(logging.makeLogRecord({})).keys())


def set_request_context(context: dict[str, object]) -> contextvars.Token[dict[str, object]]:
    normalized = {key: value for key, value in (context or {}).items() if value not in (None, "")}
    return _request_context_var.set(normalized)


def update_request_context(**values: object) -> None:
    current = dict(_request_context_var.get({}))
    for key, value in values.items():
        if value in (None, ""):
            current.pop(key, None)
        else:
            current[key] = value
    _request_context_var.set(current)


def reset_request_context(token: contextvars.Token[dict[str, object]]) -> None:
    _request_context_var.reset(token)


def get_request_context() -> dict[str, object]:
    return dict(_request_context_var.get({}))


def get_request_id() -> str:
    return str(get_request_context().get("request_id", "-"))


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.request_id = context.get("request_id", "-")
        for key, value in context.items():
            setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", get_request_id()),
        }

        for key, value in get_request_context().items():
            if value not in (None, ""):
                payload[key] = value

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key in {"message", "asctime"}:
                continue
            if key.startswith("_") or value in (None, ""):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=True, default=str)
