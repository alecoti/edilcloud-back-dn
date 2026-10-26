import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F, Sum, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from ninja.errors import HttpError

from .content import digest
from .models import DocumentAudit, DocumentJob, ElaboratoRevision

logger = logging.getLogger(__name__)


def queue_job(*, revision, profile, action, key, payload=None, input_version=None):
    """Caller holds the revision/document lock. Reserve budget across the account."""
    payload = payload or {}
    input_version = revision.version if input_version is None else input_version
    request_hash = digest(
        {
            "revision": str(revision.pk),
            "version": input_version,
            "action": action,
            "payload": payload,
        }
    )
    prior = DocumentJob.objects.filter(requested_by=profile, idempotency_key=key).first()
    if prior:
        if prior.request_hash != request_hash:
            raise HttpError(
                409, "La chiave della richiesta è già stata usata per un'operazione diversa."
            )
        return prior
    if DocumentJob.objects.filter(revision=revision, state__in=("queued", "running")).exists():
        raise HttpError(409, "Questa revisione è già in lavorazione.")
    from edilcloud.modules.billing.models import BillingAccount
    from edilcloud.modules.billing.services import (
        account_workspace_ids,
        entitlement_snapshot,
        get_workspace_billing_account,
        ai_quota_is_unlimited,
    )

    workspace = revision.elaborato.project.workspace
    account = get_workspace_billing_account(workspace)
    account = BillingAccount.objects.select_for_update().get(pk=account.pk)
    reserved = (
        DocumentJob.objects.filter(
            revision__elaborato__project__workspace_id__in=account_workspace_ids(account),
            state__in=("queued", "running"),
        ).aggregate(total=Sum(Greatest(F("reserved_tokens") - F("consumed_tokens"), Value(0))))[
            "total"
        ]
        or 0
    )
    workflow = getattr(settings, "ELABORATI_WORKFLOW_VERSION", "v1") if action == "generate" else "v1"
    # V3 chooses FAST_0 before reserving paid attempts. Per-attempt reservations
    # are made when a specialist is about to execute, not for an empty report.
    tokens = 0 if action == "preview" or workflow.startswith("v3") else 90_000 if action == "generate" else 45_000
    if tokens and settings.AI_TOKEN_QUOTA_ENFORCED and not ai_quota_is_unlimited(account):
        remaining = entitlement_snapshot(account)["ai_tokens"]["remaining_this_period"]
        if remaining - reserved < tokens:
            raise HttpError(
                402,
                "Budget AI insufficiente per questa redazione. Attendi il completamento delle altre elaborazioni o verifica il piano.",
            )
    return DocumentJob.objects.create(
        revision=revision,
        requested_by=profile,
        action=action,
        idempotency_key=key,
        request_hash=request_hash,
        input_version=input_version,
        payload=payload,
        reserved_tokens=tokens,
        workflow_version=workflow,
    )


def renew_lease(job):
    if not DocumentJob.objects.filter(
        pk=job.pk, state="running", lease_token=job.lease_token, lease_expires_at__gt=timezone.now()
    ).update(lease_expires_at=timezone.now() + timedelta(minutes=8)):
        raise RuntimeError("L'elaborazione non detiene più la propria prenotazione.")


def set_stage(job, stage):
    renew_lease(job)
    DocumentJob.objects.filter(pk=job.pk, state="running", lease_token=job.lease_token).update(
        stage=stage
    )


def expire_jobs():
    # A timed out provider request could already have been billed. Never replay
    # it automatically; a new explicit request is visible to the author.
    expired = DocumentJob.objects.filter(state="running", lease_expires_at__lt=timezone.now())
    from .models import DocumentStep, DocumentStepAttempt

    # A sent provider request is never replayed, even if its worker vanished.
    DocumentStepAttempt.objects.filter(step__job__in=expired, state="sent").update(
        state="unknown", error_code="WORKER_INTERRUPTED",
    )
    DocumentStep.objects.filter(job__in=expired, attempts__state="unknown").update(state="unknown")
    DocumentStep.objects.filter(job__in=expired, state="running").update(
        state="failed", lease_expires_at=timezone.now(), error_code="WORKER_INTERRUPTED",
    )
    resumable = expired.filter(workflow_version__startswith="v3").exclude(steps__state="unknown")
    recovered = resumable.update(state="queued", stage="resuming", lease_token=None, lease_expires_at=None)
    return recovered + expired.update(
        state="failed",
        stage="failed",
        error_code="WORKER_INTERRUPTED",
        error_message="Elaborazione interrotta. La bozza precedente è intatta; puoi avviare una nuova richiesta.",
    )


def process_job(job_id):
    token = uuid.uuid4()
    if not DocumentJob.objects.filter(pk=job_id, state="queued").update(
        state="running",
        lease_token=token,
        lease_expires_at=timezone.now() + timedelta(minutes=8),
        stage="evidence",
    ):
        return False
    job = DocumentJob.objects.select_related(
        "revision__elaborato__project__workspace", "requested_by__user"
    ).get(pk=job_id)
    try:
        from .services import authorize_revision

        authorize_revision(profile=job.requested_by, revision=job.revision, edit=True)
        if job.revision.version != job.input_version:
            raise HttpError(409, "La bozza è stata modificata dopo l'avvio della richiesta.")
        from .engine import edit_proposal, generate_document, verify_document

        if job.action == "generate":
            if job.workflow_version.startswith("v3"):
                from .pipeline_v3 import generate_document as generate_v3

                result = generate_v3(job)
                # Render from the complete, checkpointed structured content.
                # Nothing is committed over a newer user revision.
                from copy import copy
                from .publication import prepare_preview

                rendering_job = copy(job)
                rendering_job.revision = copy(job.revision)
                rendering_job.revision.editor_doc = result["editor_doc"]
                rendering_job.revision.evidence = result["evidence"]
                rendering_job.payload = {"preview_purpose": "draft"}
                result.update(prepare_preview(rendering_job))
            else:
                result = generate_document(job)
        elif job.action in {"verify", "missing"}:
            result = {"quality": verify_document(job)}
        elif job.action == "preview":
            from .publication import prepare_preview

            result = prepare_preview(job)
        else:
            result = edit_proposal(job)
        renew_lease(job)
        with transaction.atomic():
            locked_job = DocumentJob.objects.select_for_update().get(pk=job.pk)
            revision = (
                ElaboratoRevision.objects.select_for_update()
                .select_related("elaborato__project__workspace")
                .get(pk=job.revision_id)
            )
            authorize_revision(profile=job.requested_by, revision=revision, edit=True)
            if (
                locked_job.state != "running"
                or locked_job.lease_token != token
                or revision.version != job.input_version
                or revision.state != "draft"
            ):
                raise HttpError(409, "La bozza o i permessi sono cambiati durante l'elaborazione.")
            if job.action in {"generate", "preview"}:
                from .pdf_cache import preserve_display_pdf
                preserve_display_pdf(revision)
                old_preview = revision.preview_file.name
            if job.action == "generate":
                from .services import invalidate_preview

                invalidate_preview(revision)
                revision.editor_doc = result["editor_doc"]
                revision.evidence = result["evidence"]
                revision.source_count = len(result["evidence"].get("sources", []))
                revision.reasoning = result["reasoning"]
                revision.quality = result["quality"]
                if result.get("preview"):
                    for field, value in result["preview"].items():
                        setattr(revision, field, value)
                revision.version += 1
                revision.save()
            elif job.action == "preview":
                for field, value in result["preview"].items():
                    setattr(revision, field, value)
                revision.save()
            elif job.action in {"verify", "missing"}:
                revision.quality = result["quality"]
                if not result["quality"].get("passed"):
                    from .services import invalidate_preview

                    invalidate_preview(revision)
                revision.save()
            if job.action in {"generate", "preview"}:
                from .pdf_cache import record_display_pdf, schedule_cleanup
                if result.get("preview"):
                    record_display_pdf(revision, profile_id=job.requested_by_id)
                if old_preview and old_preview != revision.preview_file.name:
                    schedule_cleanup(old_preview)
            locked_job.state = "completed"
            locked_job.stage = (
                "ready"
                if result.get("preview") or result.get("quality", {}).get("passed")
                else "review"
            )
            locked_job.result = (
                result
                if job.action not in {"generate", "preview"}
                else {
                    "revision_id": str(revision.pk),
                    **(
                        {"preview_ready": True, "ai_used": False}
                        if job.action == "preview"
                        else {"quality": result["quality"]}
                    ),
                }
            )
            locked_job.save(update_fields=("state", "stage", "result", "updated_at"))
            DocumentAudit.objects.create(
                revision=revision,
                actor=job.requested_by,
                action=f"{job.action}.completed",
                detail={"job_id": str(job.pk), "version": revision.version},
            )
    except Exception as exc:
        from .provider import DocumentProviderError
        from .errors import IncompleteDocumentOutput, UnusableDocumentResult

        known = isinstance(exc, (ValueError, HttpError, DocumentProviderError, IncompleteDocumentOutput))
        message = (
            str(exc) if known else "L'elaborazione non è riuscita. La bozza precedente è intatta."
        )
        logger.warning("Elaborato job failed job_id=%s kind=%s", job.pk, type(exc).__name__)
        DocumentJob.objects.filter(pk=job.pk, state="running", lease_token=token).update(
            state="failed",
            stage="failed",
            error_code=("INCOMPLETE_OUTPUT" if isinstance(exc, IncompleteDocumentOutput)
                        else "DOCUMENT_RESULT_INVALID" if isinstance(exc, UnusableDocumentResult)
                        else "DOCUMENT_REQUEST_FAILED"),
            error_message=message[:500],
        )
    return True


def process_batch(limit=2):
    close_old_connections()
    expire_jobs()
    ids = list(
        DocumentJob.objects.filter(state="queued")
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    for job_id in ids:
        process_job(job_id)
    return len(ids)
