from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from django.db import OperationalError, connection

from edilcloud.modules.assistant.models import ProjectAssistantRunLog

try:
    from psycopg import connect as psycopg_connect
    from psycopg.rows import dict_row as psycopg_dict_row
except Exception:  # pragma: no cover - optional import guard
    psycopg_connect = None
    psycopg_dict_row = None


def build_quality_report(messages: list[dict[str, Any]]) -> dict[str, Any]:
    by_intent: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "count": 0,
            "supported": 0,
            "topical": 0,
            "grounding_sum": 0.0,
            "mismatch_sum": 0.0,
        }
    )
    weak_queries: list[dict[str, object]] = []
    top_errors = Counter()

    for message in messages:
        evaluation = message.get("evaluation") if isinstance(message.get("evaluation"), dict) else {}
        intent = str(message.get("intent") or "unknown")
        grounding = float(evaluation.get("answer_grounding_score") or 0.0)
        mismatch = float(evaluation.get("mismatch_rate") or 0.0)
        supported = not bool(evaluation.get("unsupported_answer"))
        topical = bool(evaluation.get("topical_source_match"))

        bucket = by_intent[intent]
        bucket["count"] += 1
        bucket["supported"] += 1 if supported else 0
        bucket["topical"] += 1 if topical else 0
        bucket["grounding_sum"] += grounding
        bucket["mismatch_sum"] += mismatch

        if not supported:
            top_errors["unsupported_answer"] += 1
        if mismatch:
            top_errors["mismatch"] += 1
        if grounding < 0.12:
            top_errors["low_grounding"] += 1

        if (not supported) or mismatch or grounding < 0.12:
            weak_queries.append(
                {
                    "message_id": message["id"],
                    "intent": intent,
                    "grounding": round(grounding, 3),
                    "mismatch": round(mismatch, 3),
                    "content_preview": (message.get("assistant_output") or "")[:220],
                }
            )

    success_rate_per_intent = {}
    for intent, bucket in by_intent.items():
        count = int(bucket["count"])
        success_rate_per_intent[intent] = {
            "count": count,
            "supported_rate": round((bucket["supported"] / max(1, count)) * 100, 2),
            "topical_rate": round((bucket["topical"] / max(1, count)) * 100, 2),
            "avg_grounding": round(bucket["grounding_sum"] / max(1, count), 3),
            "avg_mismatch": round(bucket["mismatch_sum"] / max(1, count), 3),
        }

    return {
        "analyzed_messages": len(messages),
        "success_rate_per_intent": success_rate_per_intent,
        "top_errors": top_errors.most_common(10),
        "weak_queries": weak_queries[:20],
    }


def load_project_assistant_run_logs(
    *,
    limit: int,
    project_id: int | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    limit = max(int(limit or 1), 1)
    if connection.vendor == "sqlite":
        sqlite_rows = load_project_assistant_run_logs_from_sqlite(limit=limit, project_id=project_id)
        if sqlite_rows is not None:
            return sqlite_rows, None
        orm_rows, orm_error = load_project_assistant_run_logs_from_orm(limit=limit, project_id=project_id)
        return orm_rows, orm_error
    if connection.vendor == "postgresql":
        postgres_rows, postgres_error = load_project_assistant_run_logs_from_postgres(
            limit=limit,
            project_id=project_id,
        )
        if postgres_rows is not None:
            return postgres_rows, None
        if postgres_error:
            return None, postgres_error
        orm_rows, orm_error = load_project_assistant_run_logs_from_orm(limit=limit, project_id=project_id)
        return orm_rows, orm_error
    return load_project_assistant_run_logs_from_orm(limit=limit, project_id=project_id)


def load_project_assistant_run_logs_from_orm(
    *,
    limit: int,
    project_id: int | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    queryset = ProjectAssistantRunLog.objects.all()
    if project_id:
        queryset = queryset.filter(project_id=project_id)
    try:
        rows = list(
            queryset.order_by("-created_at", "-id").values(
                "id",
                "intent",
                "evaluation",
                "assistant_output",
            )[:limit]
        )
    except OperationalError as exc:
        return None, {"error": "database_locked", "detail": str(exc), "loader": "orm"}
    return rows, None


def load_project_assistant_run_logs_from_sqlite(
    *,
    limit: int,
    project_id: int | None = None,
) -> list[dict[str, Any]] | None:
    if connection.in_atomic_block:
        return None
    db_name = str(connection.settings_dict.get("NAME") or "")
    if not db_name or db_name == ":memory:" or db_name.startswith("file:"):
        return None
    database_path = Path(db_name)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return None
    query = (
        "SELECT id, intent, evaluation, assistant_output "
        "FROM assistant_projectassistantrunlog "
    )
    params: list[object] = []
    if project_id:
        query += "WHERE project_id = ? "
        params.append(project_id)
    query += "ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    uri = f"file:{database_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1.0) as sqlite_connection:
            sqlite_connection.row_factory = sqlite3.Row
            rows = sqlite_connection.execute(query, params).fetchall()
    except sqlite3.Error:
        return None
    return [normalize_loaded_row(dict(row), loader="sqlite") for row in rows]


def load_project_assistant_run_logs_from_postgres(
    *,
    limit: int,
    project_id: int | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if psycopg_connect is None or psycopg_dict_row is None:
        return None, None
    settings_dict = connection.settings_dict
    connect_kwargs = {
        "dbname": settings_dict.get("NAME") or "",
        "user": settings_dict.get("USER") or None,
        "password": settings_dict.get("PASSWORD") or None,
        "host": settings_dict.get("HOST") or None,
        "port": settings_dict.get("PORT") or None,
        "connect_timeout": 2,
        "autocommit": True,
        "row_factory": psycopg_dict_row,
        "options": "-c statement_timeout=2000 -c default_transaction_read_only=on",
    }
    connect_kwargs = {key: value for key, value in connect_kwargs.items() if value not in {None, ""}}
    query = (
        "SELECT id, intent, evaluation, assistant_output "
        "FROM assistant_projectassistantrunlog "
    )
    params: list[object] = []
    if project_id:
        query += "WHERE project_id = %s "
        params.append(project_id)
    query += "ORDER BY created_at DESC, id DESC LIMIT %s"
    params.append(limit)
    try:
        with psycopg_connect(**connect_kwargs) as pg_connection:
            with pg_connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
    except Exception as exc:
        return None, {"error": "database_unavailable", "detail": str(exc), "loader": "postgres"}
    return [normalize_loaded_row(dict(row), loader="postgres") for row in rows], None


def normalize_loaded_row(row: dict[str, Any], *, loader: str) -> dict[str, Any]:
    evaluation_payload = row.get("evaluation")
    evaluation = {}
    if isinstance(evaluation_payload, dict):
        evaluation = evaluation_payload
    elif isinstance(evaluation_payload, str) and evaluation_payload:
        try:
            evaluation = json.loads(evaluation_payload)
        except json.JSONDecodeError:
            evaluation = {}
    return {
        "id": row.get("id"),
        "intent": row.get("intent"),
        "evaluation": evaluation,
        "assistant_output": row.get("assistant_output"),
        "loader": loader,
    }
