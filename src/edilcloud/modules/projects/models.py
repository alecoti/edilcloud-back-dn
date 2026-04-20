import secrets
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from edilcloud.modules.workspaces.models import Profile, TimestampedModel, Workspace, WorkspaceRole


def generate_project_invite_code() -> str:
    return f"{secrets.randbelow(10000):04d}-{secrets.randbelow(10000):04d}"


def generate_content_code() -> str:
    return secrets.token_hex(6)


def project_logo_upload_to(_instance, filename: str) -> str:
    return f"projects/logos/{filename}"


def project_document_upload_to(instance, filename: str) -> str:
    if getattr(instance, "document_kind", "") == "drawing":
        return f"projects/{instance.project_id}/drawings/{filename}"
    return f"projects/{instance.project_id}/documents/{filename}"


def project_photo_upload_to(instance, filename: str) -> str:
    return f"projects/{instance.project_id}/photos/{filename}"


def post_attachment_upload_to(instance, filename: str) -> str:
    return f"projects/{instance.post.project_id}/posts/{instance.post_id}/{filename}"


def comment_attachment_upload_to(instance, filename: str) -> str:
    return f"projects/{instance.comment.post.project_id}/comments/{instance.comment_id}/{filename}"


class ProjectStatus(models.IntegerChoices):
    DRAFT = -1, "Draft"
    CLOSED = 0, "Closed"
    ACTIVE = 1, "Active"


class ProjectMemberStatus(models.IntegerChoices):
    PENDING = 0, "Pending"
    ACTIVE = 1, "Active"
    REFUSED = 2, "Refused"


class ProjectDocumentKind(models.TextChoices):
    DOCUMENT = "document", "Document"
    DRAWING = "drawing", "Drawing"


class TaskActivityStatus(models.TextChoices):
    TODO = "to-do", "To do"
    PROGRESS = "progress", "Progress"
    COMPLETED = "completed", "Completed"


class ProjectScheduleLinkType(models.TextChoices):
    END_TO_START = "e2s", "Finish to start"
    START_TO_START = "s2s", "Start to start"
    END_TO_END = "e2e", "Finish to finish"
    START_TO_END = "s2e", "Start to finish"


class PostKind(models.TextChoices):
    WORK_PROGRESS = "work-progress", "Work progress"
    ISSUE = "issue", "Issue"
    DOCUMENTATION = "documentation", "Documentation"


class DemoProjectSnapshotValidationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    VALIDATED = "validated", "Validated"
    INVALID = "invalid", "Invalid"


class Project(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    created_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="created_projects",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    google_place_id = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    date_start = models.DateField()
    date_end = models.DateField(null=True, blank=True)
    status = models.IntegerField(
        choices=ProjectStatus.choices,
        default=ProjectStatus.ACTIVE,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    archive_due_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    purge_due_at = models.DateTimeField(null=True, blank=True)
    last_export_at = models.DateTimeField(null=True, blank=True)
    owner_export_sent_at = models.DateTimeField(null=True, blank=True)
    logo = models.FileField(upload_to=project_logo_upload_to, blank=True)
    is_demo_master = models.BooleanField(default=False)
    demo_snapshot_version = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.name


class DemoProjectSnapshot(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        related_name="demo_snapshots",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="created_demo_project_snapshots",
        null=True,
        blank=True,
    )
    version = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    business_date = models.DateField()
    schema_version = models.PositiveSmallIntegerField(default=1)
    seed_hash = models.CharField(max_length=64, blank=True)
    asset_manifest_hash = models.CharField(max_length=64, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    validation_status = models.CharField(
        max_length=16,
        choices=DemoProjectSnapshotValidationStatus.choices,
        default=DemoProjectSnapshotValidationStatus.DRAFT,
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    active_in_production = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    export_relative_path = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("name", "version"),
                name="unique_demo_project_snapshot_name_version",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "active_in_production")),
            models.Index(fields=("project", "validation_status")),
            models.Index(fields=("version",)),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.version}]"


class ProjectCompanyColor(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="company_colors",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="project_colors",
    )
    color_project = models.CharField(max_length=16)

    class Meta:
        ordering = ("project_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "workspace"),
                name="unique_project_company_color",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "workspace")),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.workspace_id}:{self.color_project}"


class ProjectMember(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="members",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="project_memberships",
    )
    role = models.CharField(
        max_length=1,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.WORKER,
    )
    status = models.IntegerField(
        choices=ProjectMemberStatus.choices,
        default=ProjectMemberStatus.ACTIVE,
    )
    disabled = models.BooleanField(default=False)
    is_external = models.BooleanField(default=False)
    project_invitation_date = models.DateTimeField(default=timezone.now)
    project_role_codes = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("project_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "profile"),
                name="unique_project_profile",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "status")),
            models.Index(fields=("profile", "status")),
        ]

    def __str__(self) -> str:
        return f"{self.profile.member_name} -> {self.project.name}"


class ProjectInviteCode(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="invite_codes",
    )
    created_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="generated_project_invite_codes",
        null=True,
        blank=True,
    )
    email = models.EmailField()
    unique_code = models.CharField(max_length=9, unique=True, blank=True)
    status = models.IntegerField(
        choices=ProjectMemberStatus.choices,
        default=ProjectMemberStatus.PENDING,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("project", "email")),
        ]

    def __str__(self) -> str:
        return f"{self.email} -> {self.project.name}"

    def save(self, *args, **kwargs):
        if not self.unique_code:
            candidate = generate_project_invite_code()
            while ProjectInviteCode.objects.filter(unique_code=candidate).exists():
                candidate = generate_project_invite_code()
            self.unique_code = candidate
        super().save(*args, **kwargs)


class ProjectOperationalEvent(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="operational_events",
    )
    event_type = models.CharField(max_length=64)
    occurred_at = models.DateTimeField(default=timezone.now)
    task_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    activity_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    post_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    comment_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    folder_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    document_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    photo_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    member_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    invite_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    actor_profile_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(fields=("project", "occurred_at")),
            models.Index(fields=("project", "task_id_snapshot", "occurred_at")),
            models.Index(fields=("project", "activity_id_snapshot", "occurred_at")),
            models.Index(fields=("project", "event_type", "occurred_at")),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.event_type}:{self.occurred_at.isoformat()}"


class ProjectFolder(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    path = models.CharField(max_length=1024, blank=True)
    is_public = models.BooleanField(default=False)
    is_root = models.BooleanField(default=False)

    class Meta:
        ordering = ("path", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "path"),
                name="unique_project_folder_path",
            ),
        ]

    def __str__(self) -> str:
        return self.path or self.name


class ProjectDocument(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    folder = models.ForeignKey(
        ProjectFolder,
        on_delete=models.SET_NULL,
        related_name="documents",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    document = models.FileField(upload_to=project_document_upload_to)
    is_public = models.BooleanField(default=False)
    document_kind = models.CharField(
        max_length=24,
        choices=ProjectDocumentKind.choices,
        default=ProjectDocumentKind.DOCUMENT,
    )

    class Meta:
        ordering = ("-updated_at", "-id")

    def __str__(self) -> str:
        return self.title


class ProjectDrawingPin(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="drawing_pins",
    )
    drawing_document = models.ForeignKey(
        ProjectDocument,
        on_delete=models.CASCADE,
        related_name="drawing_pins",
    )
    post = models.ForeignKey(
        "ProjectPost",
        on_delete=models.CASCADE,
        related_name="drawing_pins",
    )
    created_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="created_project_drawing_pins",
        null=True,
        blank=True,
    )
    x = models.FloatField()
    y = models.FloatField()
    page_number = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("drawing_document_id", "page_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("drawing_document", "post"),
                name="unique_drawing_pin_document_post",
            ),
            models.CheckConstraint(
                check=models.Q(x__gte=0.0) & models.Q(x__lte=1.0),
                name="drawing_pin_x_normalized",
            ),
            models.CheckConstraint(
                check=models.Q(y__gte=0.0) & models.Q(y__lte=1.0),
                name="drawing_pin_y_normalized",
            ),
        ]
        indexes = [
            models.Index(
                fields=("project", "drawing_document"),
                name="projects_pr_project_b2403f_idx",
            ),
            models.Index(
                fields=("project", "post"),
                name="projects_pr_project_9fc9f9_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Drawing pin #{self.id} doc={self.drawing_document_id} post={self.post_id}"


class ProjectPhoto(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    title = models.CharField(max_length=255, blank=True)
    photo = models.FileField(upload_to=project_photo_upload_to)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.title or Path(self.photo.name).name


class ProjectTask(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    name = models.CharField(max_length=255)
    assigned_company = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        related_name="assigned_project_tasks",
        null=True,
        blank=True,
    )
    date_start = models.DateField()
    date_end = models.DateField()
    date_completed = models.DateField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    status = models.IntegerField(default=1)
    share_status = models.BooleanField(default=False)
    shared_task = models.PositiveIntegerField(null=True, blank=True)
    only_read = models.BooleanField(default=False)
    alert = models.BooleanField(default=False)
    starred = models.BooleanField(default=False)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ("date_start", "id")
        indexes = [
            models.Index(fields=("project", "date_start")),
        ]

    def __str__(self) -> str:
        return self.name


class ProjectActivity(TimestampedModel):
    task = models.ForeignKey(
        ProjectTask,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=TaskActivityStatus.choices,
        default=TaskActivityStatus.TODO,
    )
    progress = models.PositiveSmallIntegerField(default=0)
    datetime_start = models.DateTimeField()
    datetime_end = models.DateTimeField()
    alert = models.BooleanField(default=False)
    starred = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    workers = models.ManyToManyField(
        Profile,
        related_name="project_activities",
        blank=True,
    )

    class Meta:
        ordering = ("datetime_start", "id")
        indexes = [
            models.Index(fields=("task", "datetime_start")),
        ]

    def __str__(self) -> str:
        return self.title


class ProjectScheduleLink(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="schedule_links",
    )
    source_task = models.ForeignKey(
        ProjectTask,
        on_delete=models.CASCADE,
        related_name="outgoing_schedule_links",
        null=True,
        blank=True,
    )
    source_activity = models.ForeignKey(
        ProjectActivity,
        on_delete=models.CASCADE,
        related_name="outgoing_schedule_links",
        null=True,
        blank=True,
    )
    target_task = models.ForeignKey(
        ProjectTask,
        on_delete=models.CASCADE,
        related_name="incoming_schedule_links",
        null=True,
        blank=True,
    )
    target_activity = models.ForeignKey(
        ProjectActivity,
        on_delete=models.CASCADE,
        related_name="incoming_schedule_links",
        null=True,
        blank=True,
    )
    link_type = models.CharField(
        max_length=3,
        choices=ProjectScheduleLinkType.choices,
        default=ProjectScheduleLinkType.END_TO_START,
    )
    lag_days = models.SmallIntegerField(default=0)
    origin = models.CharField(max_length=32, default="manual")

    class Meta:
        ordering = ("project_id", "id")
        indexes = [
            models.Index(fields=("project", "source_task")),
            models.Index(fields=("project", "source_activity")),
            models.Index(fields=("project", "target_task")),
            models.Index(fields=("project", "target_activity")),
            models.Index(fields=("project", "link_type")),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.link_type}:{self.id}"


class ProjectPost(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    task = models.ForeignKey(
        ProjectTask,
        on_delete=models.CASCADE,
        related_name="posts",
        null=True,
        blank=True,
    )
    activity = models.ForeignKey(
        ProjectActivity,
        on_delete=models.CASCADE,
        related_name="posts",
        null=True,
        blank=True,
    )
    author = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="project_posts",
    )
    post_kind = models.CharField(
        max_length=32,
        choices=PostKind.choices,
        default=PostKind.WORK_PROGRESS,
    )
    text = models.TextField(blank=True)
    original_text = models.TextField(blank=True)
    source_language = models.CharField(max_length=8, blank=True)
    display_language = models.CharField(max_length=8, blank=True)
    is_translated = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    alert = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    unique_code = models.CharField(max_length=32, default=generate_content_code, unique=True)
    published_date = models.DateTimeField(default=timezone.now)
    weather_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-published_date", "-id")
        indexes = [
            models.Index(fields=("task", "published_date")),
            models.Index(fields=("activity", "published_date")),
            models.Index(fields=("project", "alert")),
        ]

    def __str__(self) -> str:
        return f"{self.project.name} #{self.id}"


class PostAttachment(TimestampedModel):
    post = models.ForeignKey(
        ProjectPost,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=post_attachment_upload_to)

    class Meta:
        ordering = ("id",)


class PostComment(TimestampedModel):
    post = models.ForeignKey(
        ProjectPost,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="project_post_comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    text = models.TextField(blank=True)
    original_text = models.TextField(blank=True)
    source_language = models.CharField(max_length=8, blank=True)
    display_language = models.CharField(max_length=8, blank=True)
    is_translated = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    unique_code = models.CharField(max_length=32, default=generate_content_code, unique=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("post", "created_at")),
        ]

    def __str__(self) -> str:
        return f"Comment #{self.id} on post #{self.post_id}"


class ProjectPostTranslation(TimestampedModel):
    post = models.ForeignKey(
        ProjectPost,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    target_language = models.CharField(max_length=8)
    source_language = models.CharField(max_length=8, blank=True)
    source_signature = models.CharField(max_length=64, blank=True)
    translated_text = models.TextField(blank=True)
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("post_id", "target_language", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("post", "target_language"),
                name="unique_project_post_translation_language",
            ),
        ]
        indexes = [
            models.Index(fields=("post", "target_language")),
            models.Index(fields=("target_language", "updated_at")),
        ]

    def __str__(self) -> str:
        return f"Post translation #{self.id} ({self.target_language})"


class PostCommentTranslation(TimestampedModel):
    comment = models.ForeignKey(
        PostComment,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    target_language = models.CharField(max_length=8)
    source_language = models.CharField(max_length=8, blank=True)
    source_signature = models.CharField(max_length=64, blank=True)
    translated_text = models.TextField(blank=True)
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("comment_id", "target_language", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("comment", "target_language"),
                name="unique_post_comment_translation_language",
            ),
        ]
        indexes = [
            models.Index(fields=("comment", "target_language")),
            models.Index(fields=("target_language", "updated_at")),
        ]

    def __str__(self) -> str:
        return f"Comment translation #{self.id} ({self.target_language})"


class ProjectPostSeenState(TimestampedModel):
    post = models.ForeignKey(
        ProjectPost,
        on_delete=models.CASCADE,
        related_name="seen_states",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="seen_project_posts",
    )
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-seen_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("post", "profile"),
                name="unique_project_post_seen_state",
            ),
        ]
        indexes = [
            models.Index(fields=("profile", "seen_at")),
            models.Index(fields=("post", "seen_at")),
        ]

    def __str__(self) -> str:
        return f"Seen post #{self.post_id} by profile #{self.profile_id}"


class CommentAttachment(TimestampedModel):
    comment = models.ForeignKey(
        PostComment,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to=comment_attachment_upload_to)

    class Meta:
        ordering = ("id",)


class ProjectClientMutation(TimestampedModel):
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="project_client_mutations",
    )
    mutation_id = models.CharField(max_length=128)
    operation = models.CharField(max_length=64)
    post = models.ForeignKey(
        ProjectPost,
        on_delete=models.CASCADE,
        related_name="client_mutations",
        null=True,
        blank=True,
    )
    comment = models.ForeignKey(
        PostComment,
        on_delete=models.CASCADE,
        related_name="client_mutations",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "mutation_id"),
                name="unique_project_client_mutation_profile",
            ),
        ]
        indexes = [
            models.Index(
                fields=("profile", "operation"),
                name="projects_pr_profile_baa20d_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.profile_id}:{self.operation}:{self.mutation_id}"
