"""Document content, provenance and publication are revision-scoped.

Private previews/signatures never acquire a public media URL. A published PDF is
also stored in the existing project Drive, without making the editor mutable.
"""

import uuid

from django.conf import settings
from django.db import models

from edilcloud.modules.workspaces.models import TimestampedModel
from .storage import private_document_storage


class WorkspaceDocumentStyle(TimestampedModel):
    workspace = models.OneToOneField("workspaces.Workspace", on_delete=models.CASCADE)
    style = models.CharField(max_length=20, default="corporate")


class Elaborato(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="elaborati"
    )
    created_by = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True)
    document_type = models.CharField(max_length=32)
    title = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    language = models.CharField(max_length=8, default="it")
    style = models.CharField(max_length=20, default="corporate")
    # Sequential project identifier, assigned once under the project row lock.
    number = models.PositiveIntegerField()
    context = models.TextField(blank=True)
    creation_key = models.UUIDField()
    creation_hash = models.CharField(max_length=64)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("project", "number"), name="elaborato_project_number"),
            models.UniqueConstraint(
                fields=("created_by", "creation_key"), name="elaborato_creation_idempotency"
            ),
        ]
        indexes = [models.Index(fields=("project", "document_type", "-created_at"))]


class ElaboratoRevision(TimestampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Bozza"
        PUBLISHED = "published", "Pubblicato"
        SIGNED = "signed", "Firmato"
        SUPERSEDED = "superseded", "Superato"
        DELETED = "deleted", "Bozza eliminata"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    elaborato = models.ForeignKey(Elaborato, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True)
    template_snapshot = models.JSONField(default=dict)
    editor_doc = models.JSONField(default=dict)
    evidence = models.JSONField(default=dict)
    source_count = models.PositiveIntegerField(default=0)
    reasoning = models.JSONField(default=dict)
    quality = models.JSONField(default=dict)
    # Explicit declarations retain author and timestamp; they are not silently
    # promoted to observations recorded by a sensor or by somebody else.
    declarations = models.JSONField(default=list)
    preview_file = models.FileField(
        storage=private_document_storage, upload_to="elaborati/previews/", blank=True
    )
    preview_hash = models.CharField(max_length=64, blank=True)
    preview_content_hash = models.CharField(max_length=64, blank=True)
    preview_expires_at = models.DateTimeField(null=True, blank=True)
    preview_signature = models.JSONField(default=dict)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "workspaces.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_elaborato_revisions",
    )
    pdf_hash = models.CharField(max_length=64, blank=True)
    signature_audit = models.JSONField(default=dict)
    drive_document = models.OneToOneField(
        "projects.ProjectDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elaborato_revision",
    )

    class Meta:
        ordering = ("-number",)
        constraints = [
            models.UniqueConstraint(
                fields=("elaborato", "number"), name="elaborato_revision_number"
            ),
            models.UniqueConstraint(
                fields=("elaborato",), condition=models.Q(state="draft"), name="elaborato_one_draft"
            ),
        ]


class PersonalSignature(TimestampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    strokes = models.JSONField(default=list)
    image = models.FileField(
        storage=private_document_storage, upload_to="elaborati/signatures/", blank=True
    )
    fingerprint = models.CharField(max_length=64)


class DocumentJob(TimestampedModel):
    class State(models.TextChoices):
        QUEUED = "queued", "In attesa"
        RUNNING = "running", "In lavorazione"
        COMPLETED = "completed", "Completato"
        FAILED = "failed", "Non riuscito"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(ElaboratoRevision, on_delete=models.CASCADE, related_name="jobs")
    requested_by = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=24, default="generate")
    idempotency_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    input_version = models.PositiveIntegerField()
    payload = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    stage = models.CharField(max_length=32, default="queued")
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)
    # Public provider summaries are separate from the final document/proposal.
    # A database default permits old workers to insert during a rolling deploy.
    thinking = models.JSONField(default=list, db_default=[], blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    reserved_tokens = models.PositiveIntegerField(default=0)
    consumed_tokens = models.PositiveIntegerField(default=0)
    workflow_version = models.CharField(max_length=32, default="v1", db_default="v1")
    workflow_state = models.JSONField(default=dict, db_default={})

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("requested_by", "idempotency_key"), name="elaborato_job_idempotency"
            ),
            models.UniqueConstraint(
                fields=("revision",),
                condition=models.Q(state__in=("queued", "running")),
                name="elaborato_one_active_job",
            ),
        ]
        indexes = [models.Index(fields=("state", "created_at"))]


class DocumentStep(TimestampedModel):
    """A fenced, independently recoverable unit of a document workflow."""

    class State(models.TextChoices):
        PENDING = "pending", "In attesa"
        RUNNING = "running", "In elaborazione"
        COMPLETED = "completed", "Completata"
        FAILED = "failed", "Errore recuperabile"
        UNKNOWN = "unknown", "Esito remoto sconosciuto"
        CANCELLED = "cancelled", "Annullata"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(DocumentJob, on_delete=models.CASCADE, related_name="steps")
    key = models.CharField(max_length=200)
    kind = models.CharField(max_length=40)
    contract_version = models.CharField(max_length=40)
    input_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    dependencies = models.ManyToManyField("self", symmetrical=False, related_name="dependents")
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    input = models.JSONField(default=dict)
    output = models.JSONField(default=dict)
    output_hash = models.CharField(max_length=64, blank=True)
    thinking = models.JSONField(default=list)
    error_code = models.CharField(max_length=48, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "key")
        constraints = [models.UniqueConstraint(fields=("job", "key"), name="elaborato_step_key")]
        indexes = [models.Index(fields=("job", "state", "kind"))]


class DocumentStepAttempt(TimestampedModel):
    class State(models.TextChoices):
        PREPARED = "prepared", "Preparato"
        SENT = "sent", "Inviato"
        COMPLETED = "completed", "Completato"
        REJECTED = "rejected", "Rifiutato prima dell'elaborazione"
        UNKNOWN = "unknown", "Esito remoto sconosciuto"
        FAILED = "failed", "Risposta non applicabile"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    step = models.ForeignKey(DocumentStep, on_delete=models.CASCADE, related_name="attempts")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.PREPARED)
    input_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=64, blank=True)
    effort = models.CharField(max_length=16, blank=True)
    response_id = models.CharField(max_length=128, blank=True)
    usage = models.JSONField(default=dict)
    reserved_tokens = models.PositiveIntegerField(default=0)
    # Persist the complete provider result before later schema/quality checks.
    response = models.JSONField(default=dict)
    error_code = models.CharField(max_length=48, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("step", "number"), name="elaborato_attempt")]


class DocumentEvidenceItem(TimestampedModel):
    class State(models.TextChoices):
        PENDING = "pending", "Da esaminare"
        READ = "read", "Esaminata"
        EXCLUDED = "excluded", "Esclusa con motivazione"
        UNREADABLE = "unreadable", "Illeggibile"
        FAILED = "failed", "Lettura non riuscita"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(DocumentJob, on_delete=models.CASCADE, related_name="evidence_items")
    source_id = models.CharField(max_length=200)
    # An empty parent denotes an original record. Page/part rows have a parent.
    parent_source_id = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=40)
    source_hash = models.CharField(max_length=64)
    source_version = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    reason = models.CharField(max_length=500, blank=True)
    reading = models.JSONField(default=dict)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("source_id",)
        constraints = [models.UniqueConstraint(fields=("job", "source_id"), name="elaborato_source")]
        indexes = [models.Index(fields=("job", "state", "kind"))]


class DocumentAIUsage(TimestampedModel):
    job = models.ForeignKey(DocumentJob, on_delete=models.CASCADE, related_name="usage")
    attempt = models.ForeignKey(
        DocumentStepAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_records"
    )
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    stage = models.CharField(max_length=32)
    model = models.CharField(max_length=64, default="gpt-6-luna")
    response_id = models.CharField(max_length=128, unique=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)


class DocumentAudit(TimestampedModel):
    revision = models.ForeignKey(ElaboratoRevision, on_delete=models.CASCADE, related_name="audit")
    actor = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=32)
    detail = models.JSONField(default=dict)
