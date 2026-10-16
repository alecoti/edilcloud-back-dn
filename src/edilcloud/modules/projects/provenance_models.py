"""Project identities and immutable evidence versions, independent of login ACLs."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from edilcloud.modules.elaborati.storage import private_document_storage
from edilcloud.modules.workspaces.models import TimestampedModel


class Company(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="documentary_companies"
    )
    linked_workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="company_records",
    )
    name = models.CharField(max_length=255)
    tax_id = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "linked_workspace"),
                condition=models.Q(linked_workspace__isnull=False),
                name="company_workspace_link",
            )
        ]


class Person(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="documentary_people"
    )
    profile = models.ForeignKey(
        "workspaces.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="person_records",
    )
    name = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "profile"),
                condition=models.Q(profile__isnull=False),
                name="person_workspace_profile",
            )
        ]


class ProjectParticipation(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="participations"
    )
    person = models.ForeignKey(Person, on_delete=models.RESTRICT, related_name="participations")
    company = models.ForeignKey(Company, on_delete=models.RESTRICT, related_name="participations")
    # These are assignment-time values. Renaming a company or a person does
    # not silently change an earlier participation or a source snapshot.
    person_name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255)
    qualification = models.CharField(max_length=255, blank=True)
    function = models.CharField(max_length=255, blank=True)
    role_codes = models.JSONField(default=list, blank=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default="declared")
    appointment_reference = models.CharField(max_length=1000, blank=True)
    recorded_by = models.ForeignKey(
        "workspaces.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_participations",
    )
    origin = models.CharField(max_length=24, default="manual")

    class Meta:
        ordering = ("person_name", "-valid_from", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="participation_valid_interval",
            )
        ]
        indexes = [models.Index(fields=("project", "person", "valid_from"))]


class ProjectSource(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="evidence_sources"
    )
    # Numeric keys are private locators, never the public documentary identity.
    kind = models.CharField(max_length=40)
    record_key = models.CharField(max_length=255)
    prefix = models.CharField(max_length=3)
    number = models.PositiveIntegerField()
    actor_snapshot = models.JSONField(default=dict)
    recorded_at = models.DateTimeField()
    identity_state = models.CharField(max_length=24, default="captured")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project", "kind", "record_key"), name="project_source_locator"
            ),
            models.UniqueConstraint(
                fields=("project", "prefix", "number"), name="project_source_reference"
            ),
        ]

    @property
    def reference(self):
        return f"{self.prefix}{self.number:02d}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "L'identità e l'attribuzione iniziale di una fonte sono immutabili."
            )
        return super().save(*args, **kwargs)


class EvidenceBlob(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="evidence_blobs"
    )
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    file = models.FileField(storage=private_document_storage, upload_to="evidence/")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("project", "sha256"), name="evidence_blob_project_hash")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Una copia originale di evidenza non può essere sovrascritta.")
        return super().save(*args, **kwargs)


class ProjectSourceVersion(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(ProjectSource, on_delete=models.CASCADE, related_name="versions")
    hash = models.CharField(max_length=64)
    snapshot = models.JSONField()
    # Working bytes and acquisition original may differ. Neither is overwritten.
    file_blob = models.ForeignKey(
        EvidenceBlob,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="working_versions",
    )
    original_blob = models.ForeignKey(
        EvidenceBlob,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="original_versions",
    )
    filename = models.CharField(max_length=255, blank=True)
    original_state = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("source", "hash"), name="project_source_version_hash")
        ]
        indexes = [models.Index(fields=("source", "-created_at"))]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La versione di una fonte è immutabile.")
        return super().save(*args, **kwargs)
