"""Opaque, validated keyset cursors for activity ordered lists."""

import base64
import json
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime


def encode_activity_cursor(timestamp: datetime, item_id: int) -> str:
    value = json.dumps([timestamp.isoformat(), item_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_activity_cursor(value: str) -> tuple[datetime, int]:
    try:
        if len(value) > 256:
            raise ValueError
        timestamp, item_id = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        parsed = parse_datetime(timestamp)
        if parsed is None or timezone.is_naive(parsed) or not isinstance(item_id, int) or item_id <= 0:
            raise ValueError
        return parsed, item_id
    except (ValueError, TypeError, UnicodeError, OverflowError) as error:
        raise ValueError("Cursore di paginazione non valido.") from error
