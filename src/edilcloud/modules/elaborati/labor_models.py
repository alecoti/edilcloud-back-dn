"""Company-private labor identities and immutable register snapshots."""
import uuid
from django.db import models
from django.utils import timezone as django_timezone


class LaborIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=(("person", "Person"), ("team", "Team")))
    name = models.CharField(max_length=200)
    external_reference = models.CharField(max_length=100, blank=True)
    profile = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True, blank=True)
    basis = models.CharField(max_length=16, choices=(("profile", "Profile"), ("declared", "Declared")))
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "elaborati_laboridentity"
        constraints = [
            models.UniqueConstraint(fields=("workspace", "profile"), condition=models.Q(profile__isnull=False), name="labor_identity_profile_uq"),
            models.CheckConstraint(condition=models.Q(kind__in=("person", "team")), name="labor_identity_kind_ck"),
            models.CheckConstraint(condition=models.Q(basis__in=("profile", "declared")), name="labor_identity_basis_ck"),
        ]
        indexes = [models.Index(fields=("workspace", "active", "name"), name="labor_identity_catalog_idx")]


class LaborRegister(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.PROTECT)
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    created_by = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True, related_name="+")
    current_version = models.PositiveIntegerField(default=1)
    effective_version = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "elaborati_laborregister"
        constraints = [models.CheckConstraint(condition=models.Q(current_version__gte=1), name="labor_register_version_ck")]
        indexes = [models.Index(fields=("workspace", "project", "-updated_at"), name="labor_register_scope_idx")]


class LaborRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    register = models.ForeignKey(LaborRegister, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=tuple((s, s) for s in ("draft", "confirmed", "submitted", "approved", "rejected")))
    work_date = models.DateField()
    timezone = models.CharField(max_length=100)
    data = models.JSONField()
    content_hash = models.CharField(max_length=64)
    actor = models.ForeignKey("workspaces.Profile", on_delete=models.SET_NULL, null=True, related_name="+")
    actor_snapshot = models.JSONField()
    action = models.CharField(max_length=16)
    reason = models.CharField(max_length=1000, blank=True)
    review_mode = models.CharField(max_length=16, blank=True)
    replaces_version = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "elaborati_laborrevision"
        constraints = [
            models.UniqueConstraint(fields=("register", "number"), name="labor_revision_number_uq"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="labor_revision_number_ck"),
            models.CheckConstraint(condition=models.Q(state__in=("draft", "confirmed", "submitted", "approved", "rejected")), name="labor_revision_state_ck"),
        ]
        indexes = [models.Index(fields=("work_date", "register"), name="labor_revision_day_idx")]


class LaborOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.PROTECT)
    actor_key = models.BigIntegerField()
    command_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    register = models.ForeignKey(LaborRegister, on_delete=models.PROTECT, null=True, blank=True)
    revision = models.ForeignKey(LaborRevision, on_delete=models.PROTECT, null=True, blank=True)
    identity = models.ForeignKey(LaborIdentity, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "elaborati_laboroperation"
        constraints = [
            models.UniqueConstraint(fields=("workspace", "actor_key", "command_id"), name="labor_operation_idempotency"),
            models.CheckConstraint(condition=(models.Q(identity__isnull=False, register__isnull=True, revision__isnull=True) | models.Q(identity__isnull=True, register__isnull=False, revision__isnull=False)), name="labor_operation_target_ck"),
        ]

class LaborLine(models.Model):
    """Indexed projection of resolved immutable rows, never another source."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(LaborRevision, on_delete=models.PROTECT, related_name="lines")
    identity = models.ForeignKey(LaborIdentity, on_delete=models.PROTECT)
    row_id = models.UUIDField()
    work_date = models.DateField()
    minutes = models.PositiveIntegerField()
    person_minutes = models.PositiveIntegerField()
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    break_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "elaborati_laborline"
        constraints = [
            models.UniqueConstraint(fields=("revision", "row_id"), name="labor_line_row_uq"),
            models.CheckConstraint(condition=models.Q(minutes__gt=0, person_minutes__gt=0), name="labor_line_quantity_ck"),
            models.CheckConstraint(condition=(models.Q(started_at__isnull=True, ended_at__isnull=True) | models.Q(started_at__isnull=False, ended_at__gt=models.F("started_at"))), name="labor_line_interval_ck"),
        ]
        indexes = [
            models.Index(fields=("identity", "work_date"), name="labor_line_identity_day_idx"),
            models.Index(fields=("identity", "started_at", "ended_at"), name="labor_line_interval_idx"),
        ]
