"""Persisted stages and per-request attempts; no automatic ambiguous replay."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import uuid

from django.db import close_old_connections, transaction
from django.db.models import Max
from django.utils import timezone

from .content import digest
from .errors import IncompleteDocumentOutput
from .models import DocumentJob, DocumentStep, DocumentStepAttempt

CURRENT_STEP = ContextVar("elaborati_step", default=None)


class StepUnavailable(RuntimeError):
    pass


class AmbiguousProviderResult(StepUnavailable):
    pass


def assert_job_owner(job):
    from .services import authorize_revision

    if not DocumentJob.objects.filter(
        pk=job.pk, state="running", lease_token=job.lease_token,
        lease_expires_at__gt=timezone.now(),
    ).exists():
        raise StepUnavailable("La prenotazione dell'elaborazione non è più valida.")
    job.revision.refresh_from_db(fields=("version", "state"))
    authorize_revision(profile=job.requested_by, revision=job.revision, edit=True)
    if job.revision.state != "draft" or job.revision.version != job.input_version:
        raise StepUnavailable("La bozza è cambiata durante l'elaborazione.")


@contextmanager
def step_context(step):
    token = CURRENT_STEP.set(step)
    try:
        yield
    finally:
        CURRENT_STEP.reset(token)


def run_step(*, job, key, kind, data, execute, schema=None, contract_version="v3.1", dependencies=()):
    """Apply a stage once, or restore its exact successful output on restart."""
    assert_job_owner(job)
    input_hash = digest({"contract": contract_version, "input": data})
    with transaction.atomic():
        # Serializes creation/attempt transitions, not the remote provider call.
        DocumentJob.objects.select_for_update().get(pk=job.pk)
        step, _ = DocumentStep.objects.get_or_create(job=job, key=key, defaults={
            "kind": kind, "contract_version": contract_version,
            "input_hash": input_hash, "input": data,
        })
        step = DocumentStep.objects.select_for_update().get(pk=step.pk)
        if step.input_hash != input_hash or step.contract_version != contract_version:
            raise StepUnavailable("Il contenuto della fase è cambiato: avvia una nuova elaborazione.")
        if dependencies:
            if any(d.job_id != job.pk or d.state != "completed" for d in dependencies):
                raise StepUnavailable("Le fasi precedenti non sono ancora complete.")
            step.dependencies.add(*dependencies)
        if step.state == "completed":
            if digest(step.output) != step.output_hash:
                raise StepUnavailable("Integrità del risultato della fase non verificata.")
            return schema.model_validate(step.output) if schema else step.output
        if step.state == "incomplete_output":
            raise IncompleteDocumentOutput("L'incarico ha esaurito l'output: occorre suddividerlo.")
        if step.state in {"unknown", "cancelled"}:
            raise AmbiguousProviderResult("Questa fase richiede una decisione esplicita prima di ripartire.")
        if step.state == "running" and step.lease_expires_at and step.lease_expires_at > timezone.now():
            raise StepUnavailable("Questa fase è già in elaborazione.")
        step.state = "running"
        step.lease_token = uuid.uuid4()
        step.lease_expires_at = timezone.now() + timedelta(minutes=8)
        step.started_at = timezone.now()
        step.error_code = step.error_message = ""
        step.save()
    try:
        with step_context(step):
            value = execute(step)
        output = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if schema:
            output = schema.model_validate(output).model_dump(mode="json")
        assert_job_owner(job)
        updated = DocumentStep.objects.filter(
            pk=step.pk, state="running", lease_token=step.lease_token,
        ).update(state="completed", output=output, output_hash=digest(output),
                 completed_at=timezone.now(), updated_at=timezone.now())
        if not updated:
            raise StepUnavailable("La fase non detiene più la propria prenotazione.")
        return schema.model_validate(output) if schema else output
    except Exception as exc:
        ambiguous = isinstance(exc, AmbiguousProviderResult) or step.attempts.filter(
            state__in=("sent", "unknown"),
        ).exists()
        DocumentStep.objects.filter(pk=step.pk, state="running", lease_token=step.lease_token).update(
            state="unknown" if ambiguous else "incomplete_output" if isinstance(exc, IncompleteDocumentOutput) else "failed",
            error_code="PROVIDER_RESULT_UNKNOWN" if ambiguous else "INCOMPLETE_OUTPUT" if isinstance(exc, IncompleteDocumentOutput) else "STEP_FAILED",
            # Diagnostic errors must not copy arbitrary provider/source text.
            error_message=(
                "Esito remoto non confermato: nessuna nuova chiamata è stata avviata."
                if ambiguous else "La fase non è riuscita. I risultati precedenti sono conservati."
            ), updated_at=timezone.now(),
        )
        raise


def renew_current_step():
    step = CURRENT_STEP.get()
    if step and not DocumentStep.objects.filter(
        pk=step.pk, state="running", lease_token=step.lease_token,
    ).update(lease_expires_at=timezone.now() + timedelta(minutes=8)):
        raise StepUnavailable("La fase non detiene più la propria prenotazione.")


class ProviderCheckpoint:
    def __init__(self, job, *, stage, model, effort):
        self.job, self.stage, self.model, self.effort = job, stage, model, effort
        self.step = CURRENT_STEP.get()
        self.attempt = None
        if self.step and self.step.job_id != job.pk:
            raise StepUnavailable("La fase non appartiene alla richiesta corrente.")

    def restore(self):
        if not self.step:
            return None
        attempt = self.step.attempts.filter(state="completed").order_by("-number").first()
        if attempt:
            self.attempt = attempt
            if attempt.input_hash != self.step.input_hash:
                raise StepUnavailable("La risposta salvata non corrisponde alla fase.")
            return attempt.response
        # A crash may occur after persisting the terminal response, before the
        # ledger commit. Restore it so accounting finishes once without HTTP.
        attempt = self.step.attempts.filter(state="incomplete_output").order_by("-number").first()
        if attempt:
            self.attempt = attempt
            if attempt.input_hash != self.step.input_hash:
                raise StepUnavailable("La risposta salvata non corrisponde alla fase.")
            return attempt.response
        if self.step.attempts.filter(state__in=("sent", "unknown")).exists():
            raise AmbiguousProviderResult("Esito remoto da verificare; retry automatico disabilitato.")
        return None

    def sent(self, reservation=0):
        if not self.step:
            return
        assert_job_owner(self.job)
        renew_current_step()
        with transaction.atomic():
            from django.conf import settings
            from django.db.models import F, Sum, Value
            from django.db.models.functions import Greatest
            from edilcloud.modules.billing.models import BillingAccount
            from edilcloud.modules.billing.services import (
                account_workspace_ids, ai_quota_is_unlimited, entitlement_snapshot,
                get_workspace_billing_account,
            )

            account = get_workspace_billing_account(self.job.revision.elaborato.project.workspace)
            account = BillingAccount.objects.select_for_update().get(pk=account.pk)
            if settings.AI_TOKEN_QUOTA_ENFORCED and not ai_quota_is_unlimited(account):
                workspace_ids = account_workspace_ids(account)
                attempts = DocumentStepAttempt.objects.filter(
                    step__job__revision__elaborato__project__workspace_id__in=workspace_ids,
                    # A terminal response is checkpointed before accounting.
                    # Keep its reservation until the ledger transaction commits,
                    # including recovery after a crash between these operations.
                    reserved_tokens__gt=0,
                    state__in=("sent", "unknown", "completed", "incomplete_output"),
                ).aggregate(n=Sum("reserved_tokens"))["n"] or 0
                legacy = DocumentJob.objects.filter(
                    revision__elaborato__project__workspace_id__in=workspace_ids,
                    state__in=("queued", "running"), workflow_version="v1",
                ).aggregate(n=Sum(Greatest(F("reserved_tokens") - F("consumed_tokens"), Value(0))))["n"] or 0
                remaining = entitlement_snapshot(account)["ai_tokens"]["remaining_this_period"]
                from .labor_ai_requests import pending
                if reservation <= 0 or remaining - attempts - legacy - pending(workspace_ids) < reservation:
                    raise StepUnavailable("Budget insufficiente per la fase richiesta. I risultati precedenti sono conservati.")
            DocumentStep.objects.select_for_update().get(pk=self.step.pk)
            number = (self.step.attempts.aggregate(n=Max("number"))["n"] or 0) + 1
            self.attempt = DocumentStepAttempt.objects.create(
                step=self.step, number=number, state="sent", input_hash=self.step.input_hash,
                model=self.model, effort=self.effort,
                reserved_tokens=reservation,
            )

    def created(self, response_id):
        if self.attempt:
            self.attempt.response_id = response_id
            self.attempt.save(update_fields=("response_id", "updated_at"))

    def rejected(self, code):
        if self.attempt:
            self.attempt.state = "rejected"
            self.attempt.error_code = str(code)[:48]
            self.attempt.reserved_tokens = 0
            self.attempt.save(update_fields=("state", "error_code", "reserved_tokens", "updated_at"))

    def completed(self, payload):
        if not self.attempt:
            return
        # Store only the structured public answer and usage. Raw/private
        # reasoning items, encrypted contexts and tool internals are not saved.
        public = {key: payload[key] for key in ("id", "status", "usage", "incomplete_details", "max_output_tokens", "service_tier") if key in payload}
        public["output"] = [
            {"type": "message", "content": [
                {"type": "output_text", "text": part["text"]}
                for part in item.get("content", []) if part.get("type") == "output_text"
            ]}
            for item in payload.get("output", []) if item.get("type") == "message"
        ]
        truncated = payload.get("status") == "incomplete" and (payload.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
        self.attempt.state = "incomplete_output" if truncated else "completed"
        self.attempt.response_id = payload.get("id") or ""
        self.attempt.usage = payload.get("usage") or {}
        self.attempt.response = public
        self.attempt.save(update_fields=("state", "response_id", "usage", "response", "updated_at"))

    def interrupted(self):
        if self.attempt:
            DocumentStepAttempt.objects.filter(pk=self.attempt.pk, state="sent").update(
                state="unknown", error_code="PROVIDER_RESULT_UNKNOWN", updated_at=timezone.now(),
            )


def threaded_step(callback):
    """Worker threads get their own Django connection and ContextVar scope."""
    close_old_connections()
    try:
        return callback()
    finally:
        close_old_connections()
