"""Signed keyset cursors scoped to a particular shared read model."""
from django.core import signing
from django.db.models import Q
from django.utils.dateparse import parse_datetime


def apply_read_cursor(queryset, *, cursor, scope, timestamp):
    if not cursor:
        return queryset
    try:
        data = signing.loads(cursor, salt="edilcloud-read-window-v1", max_age=86400)
        when = parse_datetime(data["at"])
        if data["scope"] != scope or when is None or not isinstance(data["id"], int):
            raise ValueError
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Pagina scaduta o non valida. Ricarica l'elenco.") from exc
    return queryset.filter(Q(**{f"{timestamp}__lt": when}) | Q(**{timestamp: when, "pk__lt": data["id"]}))


def next_read_cursor(item, *, scope, timestamp):
    return signing.dumps({"scope": scope, "at": getattr(item, timestamp).isoformat(), "id": item.pk},
        salt="edilcloud-read-window-v1", compress=True)
