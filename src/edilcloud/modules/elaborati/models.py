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
    error_code = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    reserved_tokens = models.PositiveIntegerField(default=0)
    consumed_tokens = models.PositiveIntegerField(default=0)

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


class DocumentAIUsage(TimestampedModel):
    job = models.ForeignKey(DocumentJob, on_delete=models.CASCADE, related_name="usage")
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
