"""Read-only union of authorized audit projections and surviving legacy records."""

from importlib.resources import files
import json

from django.core import signing
from django.db import connection
from django.db.models import F, IntegerField, Q, Value
from django.utils.dateparse import parse_datetime

from .event_access import visible_operational_events
from .models import ProjectOperationalEvent

INVALID = "Pagina scaduta o non valida. Ricarica l'elenco."
LEGACY_SQL = files(__package__).joinpath("legacy_history.sql").read_text(encoding="utf-8")


def decode_cursor(cursor, scope):
    if not cursor:
        return None
    try:
        if len(cursor) > 8192:
            raise ValueError
        value = signing.loads(cursor, salt="edilcloud-read-window-v1", max_age=86400)
        at = parse_datetime(value["at"])
        origin, entity, kind = value["origin"], value["id"], value["kind"]
        if (
            value["scope"] != scope
            or at is None
            or at.tzinfo is None
            or origin not in {"audit", "post", "comment"}
            or type(entity) is not int
            or not 0 < entity <= 9223372036854775807
            or type(kind) is not int
            or kind not in {0, 1, 2}
            or origin == "audit"
            and kind != 0
        ):
            raise ValueError
        return at, origin, entity, kind
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise ValueError(INVALID) from error


def encode_cursor(row, scope):
    at, origin, entity, kind, _ = row
    return signing.dumps(
        {"scope": scope, "at": at.isoformat(), "origin": origin, "id": entity, "kind": kind},
        salt="edilcloud-read-window-v1",
        compress=True,
    )


def scope_key(profile, project, mode, task, activity):
    return f"timeline-v2:{project}:{mode}:{task}:{activity}:{profile.pk}:{profile.workspace_id}"


def rows(*, profile, project_id, mode, task_id=None, activity_id=None, limit=None, cursor=None):
    """The SQL union is filtered and ordered before LIMIT; no data-writing fallback."""
    audit = visible_operational_events(
        ProjectOperationalEvent.objects.filter(
            project_id=project_id, payload__timeline__isnull=False
        ),
        profile=profile,
    )
    if mode == "activity":
        audit = audit.filter(activity_id_snapshot=activity_id)
    elif mode != "project" and task_id is not None:
        scope = Q(task_id_snapshot=task_id)
        if mode == "phase":
            scope |= Q(task_id_snapshot__isnull=True, activity_id_snapshot__isnull=True)
        else:
            audit = audit.filter(activity_id_snapshot__isnull=True)
        audit = audit.filter(scope)
    audit = (
        audit.order_by()
        .annotate(
            _at=F("occurred_at"),
            _origin=Value("audit"),
            _entity=F("pk"),
            _kind=Value(0, output_field=IntegerField()),
            _record=F("payload__timeline"),
        )
        .values_list("_at", "_origin", "_entity", "_kind", "_record")
    )
    audit_sql, audit_params = audit.query.sql_with_params()
    args = "SELECT %s::bigint AS project,%s::bigint AS profile,%s::bigint AS workspace,%s::text AS mode,%s::bigint AS task,%s::bigint AS activity"
    query = f"WITH args AS ({args}), audit AS ({audit_sql}), legacy AS ({LEGACY_SQL}), candidates(at,origin,entity,kind,payload) AS (SELECT * FROM audit UNION ALL SELECT * FROM legacy) SELECT at,origin,entity,kind,payload FROM candidates WHERE jsonb_typeof(payload)='object'"
    params = [
        project_id,
        profile.pk,
        profile.workspace_id,
        mode,
        task_id,
        activity_id,
        *audit_params,
    ]
    if cursor:
        query += ' AND (at,origin COLLATE "C",entity,kind)<(%s,%s COLLATE "C",%s,%s)'
        params.extend(cursor)
    query += ' ORDER BY at DESC,origin COLLATE "C" DESC,entity DESC,kind DESC'
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit + 1)
    with connection.cursor() as database_cursor:
        database_cursor.execute(query, params)
        return [
            (at, origin, entity, kind, json.loads(payload) if isinstance(payload, str) else payload)
            for at, origin, entity, kind, payload in database_cursor.fetchall()
        ]


def render(row):
    at, origin, entity, kind, payload = row
    if origin == "audit":
        return payload
    from .operational_history import build_timeline_event_from_realtime_payload

    event = build_timeline_event_from_realtime_payload(payload)
    if event is None:
        raise ValueError("La ricostruzione della cronologia non è valida.")
    event["id"] = f"derived:{origin}:{entity}:{kind}"
    event["source"] = "derived"
    event["reconstruction"] = payload["reconstruction"]
    event["details"].append(
        {
            "label": "Evento ricostruito",
            "tone": "neutral",
            "value": "Dati dall'ultimo stato conservato; modifiche intermedie non disponibili.",
        }
    )
    return event


def timeline(*, profile, project_id, mode, task_id=None, activity_id=None, limit=None, cursor=None):
    scope = scope_key(profile, project_id, mode, task_id, activity_id)
    after = decode_cursor(cursor, scope)
    limit = min(250, max(1, limit)) if limit is not None else None
    result = rows(
        profile=profile,
        project_id=project_id,
        mode=mode,
        task_id=task_id,
        activity_id=activity_id,
        limit=limit,
        cursor=after,
    )
    has_more = limit is not None and len(result) > limit
    page = result[:limit] if limit is not None else result
    return {
        "mode": mode,
        "project_id": project_id,
        "task_id": task_id,
        "activity_id": activity_id,
        "events": [render(row) for row in page],
        "has_more": has_more,
        "next_cursor": encode_cursor(page[-1], scope) if has_more else None,
    }
