"""Explicit, private AI interpretations. Retrying a command never sends it twice."""
import json
from datetime import timedelta
import httpx
from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Sum, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from ninja.errors import HttpError
from edilcloud.modules.billing.models import BillingAccount
from edilcloud.modules.billing.services import (
    account_workspace_ids, ai_quota_is_unlimited, apply_ai_usage_to_billing,
    billing_month_bounds, calculate_account_ai_usage, get_workspace_billing_account,
)
from . import labor_interpretation as domain, labor_registers as ledger
from .content import digest
from .labor_models import LaborAIRequest
from .models import DocumentJob, DocumentStepAttempt


def pending(workspace_ids):
    return LaborAIRequest.objects.filter(workspace_id__in=workspace_ids).aggregate(n=Sum("reserved_tokens"))["n"] or 0


def _reserve(profile, amount):
    account = get_workspace_billing_account(profile.workspace)
    account = BillingAccount.objects.select_for_update().get(pk=account.pk)
    if ai_quota_is_unlimited(account):
        return
    workspace_ids = account_workspace_ids(account)
    held = pending(workspace_ids)
    held += DocumentStepAttempt.objects.filter(
        step__job__revision__elaborato__project__workspace_id__in=workspace_ids,
        state__in=("sent", "unknown", "completed", "incomplete_output"),
    ).aggregate(n=Sum("reserved_tokens"))["n"] or 0
    held += DocumentJob.objects.filter(
        revision__elaborato__project__workspace_id__in=workspace_ids,
        state__in=("queued", "running"), workflow_version="v1",
    ).aggregate(n=Sum(Greatest(F("reserved_tokens") - F("consumed_tokens"), Value(0))))["n"] or 0
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('edilcloud_runtime.ai_token_reservation') IS NOT NULL")
            if cursor.fetchone()[0]:
                cursor.execute("SELECT coalesce(sum(token_count),0) FROM edilcloud_runtime.ai_token_reservation WHERE account_id=%s AND period_start=%s AND expires_at>clock_timestamp()", [account.pk, billing_month_bounds()[0]])
                held += int(cursor.fetchone()[0])
    used = calculate_account_ai_usage(account)["used"]
    if account.monthly_ai_tokens_base + account.ai_token_balance_topup - used - held < amount:
        raise HttpError(402, "Budget AI insufficiente per interpretare le ore. Verifica il piano o attendi le altre elaborazioni.")


def view(request):
    return {"schema": "labor-interpretation-v1", "command_id": str(request.command_id), "actor_profile_id": request.actor_key,
        "project_id": request.project_id, "workspace_id": request.workspace_id,
        "visibility": "private", "state": request.state, "request": request.request,
        "result": request.result or None, "error_code": request.error_code,
        "provenance": {"model": request.model, "contract": domain.CONTRACT["version"],
            "request_hash": request.request_hash, "response_id": request.response_id},
        "usage": {"input_tokens": request.input_tokens, "output_tokens": request.output_tokens,
            "total_tokens": request.total_tokens, "known": request.total_tokens is not None},
        "requires_human_review": True, "registered_minutes": 0}


def read(profile, command_id):
    profile = ledger.actor(profile)
    request = LaborAIRequest.objects.filter(workspace_id=profile.workspace_id, actor_key=profile.pk, command_id=command_id).first()
    if request is None:
        raise HttpError(404, "Interpretazione non trovata o non accessibile.")
    ledger.project_access(profile, request.project_id)
    return view(request)


def origins(profile, payload):
    refs = payload.get("interpretations", [])
    if not isinstance(refs, list) or len(refs) > 20:
        raise HttpError(400, "Riferimenti alle interpretazioni AI non validi.")
    rows = {row["id"]: row for row in payload["rows"]}
    seen, result = set(), []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"command_id", "actor_profile_id", "row_ids"}:
            raise HttpError(400, "Riferimenti alle interpretazioni AI non validi.")
        key = ledger.identifier(ref["command_id"], "interpretation.command_id")
        owner = ref["actor_profile_id"]
        if type(owner) is not int or (owner != profile.pk and profile.role not in ledger.MANAGERS):
            raise HttpError(400, "Riferimenti alle interpretazioni AI non validi.")
        request = LaborAIRequest.objects.filter(workspace_id=profile.workspace_id, project_id=payload["project_id"], actor_key=owner, command_id=key, state="completed").first()
        ids = ref["row_ids"]
        originals = {row["id"]: row for row in (request.result.get("input") or {}).get("rows", [])} if request else {}
        if not isinstance(ids, list) or not 1 <= len(ids) <= 64 or any(not isinstance(row, str) for row in ids) or len(set(ids)) != len(ids) or any(row not in originals or row not in rows or row in seen for row in ids):
            raise HttpError(400, "Riferimenti alle interpretazioni AI non validi.")
        seen.update(ids)
        result.append({"command_id": str(key), "actor_profile_id": owner,
            "request_hash": request.request_hash, "contract": domain.CONTRACT["version"], "model": request.model,
            "response_id": request.response_id, "source": request.request["source"],
            "source_changed": request.request["source"] != payload["source"],
            "context": {"work_date": request.request["work_date"], "timezone": request.request["timezone"]},
            "accepted_rows": [originals[row] for row in ids]})
    return result


def _send(body):
    """Single bounded POST; no automatic retries after an ambiguous result."""
    if not settings.OPENAI_API_KEY:
        raise HttpError(503, "Servizio di interpretazione AI non configurato.")
    with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
        with client.stream("POST", f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/responses",
                json=body, headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}) as response:
            if response.status_code >= 400:
                return response.status_code, None
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Provider response too large")
            return response.status_code, json.loads(raw)


def _terminal(request, payload, status):
    state, code, result, usage = "unknown", "REMOTE_OUTCOME_UNKNOWN", {}, None
    response_id = None
    if status in (400, 401, 403, 404, 413, 422, 429):
        return "failed", "PROVIDER_REJECTED", result, usage, response_id
    if status < 400 and isinstance(payload, dict):
        response_id = payload.get("id")
        response_id = response_id if isinstance(response_id, str) and 0 < len(response_id) <= 128 else None
        raw_usage = payload.get("usage")
        if response_id and isinstance(raw_usage, dict) and all(type(raw_usage.get(k)) is int and 0 <= raw_usage[k] <= 2**31 - 1 for k in ("input_tokens", "output_tokens", "total_tokens")):
            if raw_usage["input_tokens"] + raw_usage["output_tokens"] == raw_usage["total_tokens"]:
                usage = {k: raw_usage[k] for k in ("input_tokens", "output_tokens", "total_tokens")}
        if usage is not None:
            state, code = "failed", "INVALID_PROVIDER_OUTPUT"
            try:
                parts = [item for output in payload.get("output", []) if isinstance(output, dict) and output.get("type") == "message" for item in output.get("content", []) if isinstance(item, dict)]
                if any(item.get("type") == "refusal" for item in parts):
                    code = "PROVIDER_REFUSAL"
                elif payload.get("status") == "completed":
                    answer = "".join(item["text"] for item in parts if item.get("type") == "output_text" and isinstance(item.get("text"), str))
                    result = domain.normalize(request, json.loads(answer))
                    state, code = "completed", ""
                else:
                    code = "INCOMPLETE_PROVIDER_OUTPUT"
            except (ValueError, TypeError, KeyError):
                result = {}
    return state, code, result, usage, response_id


def interpret(profile, payload):
    try:
        request = domain.request_input(payload)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    request_hash = digest({"contract": domain.CONTRACT, "request": request})
    with transaction.atomic():
        profile = ledger.actor(profile, lock=True)
        ledger.project_access(profile, request["project_id"], lock=True)
        prior = LaborAIRequest.objects.filter(workspace_id=profile.workspace_id, actor_key=profile.pk, command_id=request["command_id"]).first()
        if prior:
            if prior.request_hash != request_hash:
                raise HttpError(409, "La chiave di interpretazione è già associata a un altro testo.")
            return view(prior)
        if not settings.OPENAI_API_KEY:
            raise HttpError(503, "Servizio di interpretazione AI non configurato.")
        body = domain.provider_body(request)
        reservation = len(json.dumps(body, ensure_ascii=False).encode()) + 16000
        _reserve(profile, reservation)
        if LaborAIRequest.objects.filter(workspace_id=profile.workspace_id, state__in=("prepared", "sent"), updated_at__gte=timezone.now() - timedelta(minutes=3)).count() >= 2:
            raise HttpError(429, "Sono già in corso altre interpretazioni. Attendi prima di inviare.")
        record = LaborAIRequest.objects.create(workspace_id=profile.workspace_id, project_id=request["project_id"], actor_key=profile.pk,
            command_id=request["command_id"], request_hash=request_hash, request=request, state="sent", reserved_tokens=reservation)
    try:
        status, payload = _send(body)
        state, code, result, usage, response_id = _terminal(request, payload, status)
    except (httpx.HTTPError, ValueError, TypeError):
        state, code, result, usage, response_id = "unknown", "REMOTE_OUTCOME_UNKNOWN", {}, None, None
    # Record actual consumption even when access was revoked while the provider ran.
    with transaction.atomic():
        account = get_workspace_billing_account(profile.workspace)
        BillingAccount.objects.select_for_update().get(pk=account.pk)
        current = LaborAIRequest.objects.select_for_update().get(pk=record.pk)
        if current.state == "sent":
            current.state, current.error_code, current.result, current.response_id = state, code, result, response_id
            if usage is not None:
                for field, amount in usage.items():
                    setattr(current, field, amount)
            if state != "unknown":
                current.reserved_tokens = 0
            current.updated_at = timezone.now()
            current.save()
            if usage is not None:
                apply_ai_usage_to_billing(workspace=profile.workspace, total_tokens=usage["total_tokens"], reference_id=f"labor-ai:{record.pk}")
    return read(profile, record.command_id)
