from django.db import models
from pgvector.django import VectorField

from edilcloud.modules.projects.models import Project
from edilcloud.modules.workspaces.models import Profile, TimestampedModel


class AssistantMessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class AssistantTone(models.TextChoices):
    PRAGMATICO = "pragmatico", "Pragmatico"
    DISCORSIVO = "discorsivo", "Discorsivo"
    TECNICO = "tecnico", "Tecnico"


class AssistantResponseMode(models.TextChoices):
    AUTO = "auto", "Auto"
    SINTESI = "sintesi", "Sintesi operativa"
    TIMELINE = "timeline", "Timeline"
    CHECKLIST = "checklist", "Checklist"
    DOCUMENTALE = "documentale", "Documentale"


class AssistantCitationMode(models.TextChoices):
    ESSENZIALE = "essenziale", "Essenziale"
    STANDARD = "standard", "Standard"
    DETTAGLIATO = "dettagliato", "Dettagliato"


class ProjectAssistantState(TimestampedModel):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_state",
    )
    container_tag = models.CharField(max_length=100, unique=True)
    chat_model = models.CharField(max_length=128, blank=True)
    embedding_model = models.CharField(max_length=128, blank=True)
    chunk_schema_version = models.CharField(max_length=64, blank=True)
    index_version = models.CharField(max_length=255, blank=True)
    current_version = models.BigIntegerField(default=0)
    last_indexed_version = models.BigIntegerField(default=0)
    source_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    last_indexed_at = models.DateTimeField(null=True, blank=True)
    is_dirty = models.BooleanField(default=True)
    background_sync_scheduled = models.BooleanField(default=False)
    last_sync_error = models.TextField(blank=True)

    class Meta:
        ordering = ("project_id",)

    def __str__(self) -> str:
        return f"Assistant state for project #{self.project_id}"


class AssistantSourceScope(models.TextChoices):
    PROJECT = "project", "Project"
    DRAFTING = "drafting", "Drafting"


class ProjectAssistantSourceState(TimestampedModel):
    assistant_state = models.ForeignKey(
        ProjectAssistantState,
        on_delete=models.CASCADE,
        related_name="source_states",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_source_states",
    )
    scope = models.CharField(
        max_length=32,
        choices=AssistantSourceScope.choices,
        default=AssistantSourceScope.PROJECT,
    )
    source_key = models.CharField(max_length=255)
    source_type = models.CharField(max_length=64)
    label = models.CharField(max_length=255, blank=True)
    custom_id = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64, blank=True)
    file_hash = models.CharField(max_length=64, blank=True)
    metadata_snapshot = models.JSONField(default=dict, blank=True)
    remote_text_document_id = models.CharField(max_length=128, blank=True)
    remote_file_document_id = models.CharField(max_length=128, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("assistant_state_id", "scope", "source_key")
        constraints = [
            models.UniqueConstraint(
                fields=("assistant_state", "scope", "source_key"),
                name="unique_assistant_source_scope_key",
            ),
        ]
        indexes = [
            models.Index(fields=("assistant_state", "scope")),
            models.Index(fields=("project", "scope", "source_type")),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.source_key} for project #{self.project_id}"


class ProjectAssistantChunkSource(TimestampedModel):
    assistant_state = models.ForeignKey(
        ProjectAssistantState,
        on_delete=models.CASCADE,
        related_name="chunk_sources",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_chunk_sources",
    )
    scope = models.CharField(
        max_length=32,
        choices=AssistantSourceScope.choices,
        default=AssistantSourceScope.PROJECT,
    )
    source_key = models.CharField(max_length=255)
    source_type = models.CharField(max_length=64)
    label = models.CharField(max_length=255, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    file_hash = models.CharField(max_length=64, blank=True)
    metadata_snapshot = models.JSONField(default=dict, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    embedding_model = models.CharField(max_length=128, blank=True)
    chunk_schema_version = models.CharField(max_length=64, blank=True)
    index_version = models.CharField(max_length=255, blank=True)
    is_indexed = models.BooleanField(default=False)
    last_indexed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("assistant_state_id", "scope", "source_key")
        constraints = [
            models.UniqueConstraint(
                fields=("assistant_state", "scope", "source_key"),
                name="unique_assistant_chunk_source_scope_key",
            ),
        ]
        indexes = [
            models.Index(fields=("assistant_state", "scope")),
            models.Index(fields=("project", "scope", "source_type")),
            models.Index(fields=("project", "is_indexed", "last_indexed_at")),
        ]

    def __str__(self) -> str:
        return f"Chunk source {self.scope}:{self.source_key} for project #{self.project_id}"


class ProjectAssistantChunkMap(TimestampedModel):
    assistant_state = models.ForeignKey(
        ProjectAssistantState,
        on_delete=models.CASCADE,
        related_name="chunk_maps",
    )
    chunk_source = models.ForeignKey(
        ProjectAssistantChunkSource,
        on_delete=models.CASCADE,
        related_name="chunk_maps",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_chunk_maps",
    )
    scope = models.CharField(
        max_length=32,
        choices=AssistantSourceScope.choices,
        default=AssistantSourceScope.PROJECT,
    )
    source_key = models.CharField(max_length=255)
    source_type = models.CharField(max_length=64, blank=True)
    label = models.CharField(max_length=255, blank=True)
    point_id = models.CharField(max_length=128, unique=True)
    chunk_index = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    content = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    metadata_snapshot = models.JSONField(default=dict, blank=True)
    entity_id = models.PositiveIntegerField(null=True, blank=True)
    task_id = models.PositiveIntegerField(null=True, blank=True)
    activity_id = models.PositiveIntegerField(null=True, blank=True)
    post_id = models.PositiveIntegerField(null=True, blank=True)
    document_id = models.PositiveIntegerField(null=True, blank=True)
    post_kind = models.CharField(max_length=64, blank=True)
    alert = models.BooleanField(null=True, blank=True)
    is_public = models.BooleanField(null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    author_name = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    issue_status = models.CharField(max_length=64, blank=True)
    media_kind = models.CharField(max_length=64, blank=True)
    extraction_status = models.CharField(max_length=32, blank=True)
    extraction_quality = models.CharField(max_length=32, blank=True)
    extracted_char_count = models.PositiveIntegerField(default=0)
    extracted_line_count = models.PositiveIntegerField(default=0)
    page_reference = models.PositiveIntegerField(null=True, blank=True)
    section_reference = models.CharField(max_length=255, blank=True)
    source_created_at = models.DateTimeField(null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    event_at = models.DateTimeField(null=True, blank=True)
    embedding_model = models.CharField(max_length=128, blank=True)
    chunk_schema_version = models.CharField(max_length=64, blank=True)
    index_version = models.CharField(max_length=255, blank=True)
    embedding = VectorField(dimensions=3072, null=True, blank=True)

    class Meta:
        ordering = ("project_id", "source_key", "chunk_index")
        indexes = [
            models.Index(fields=("assistant_state", "scope", "source_key")),
            models.Index(fields=("chunk_source", "chunk_index")),
            models.Index(fields=("project", "scope")),
            models.Index(fields=("project", "scope", "source_type")),
            models.Index(fields=("project", "task_id")),
            models.Index(fields=("project", "activity_id")),
            models.Index(fields=("project", "post_id")),
            models.Index(fields=("project", "document_id")),
            models.Index(fields=("project", "event_at")),
        ]

    def __str__(self) -> str:
        return f"Chunk #{self.chunk_index} for {self.source_key} on project #{self.project_id}"


class ProjectAssistantThread(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_threads",
    )
    author = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="assistant_threads",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-last_message_at", "-updated_at", "-id")
        indexes = [
            models.Index(fields=("project", "archived_at", "last_message_at")),
            models.Index(fields=("project", "author", "archived_at", "last_message_at")),
            models.Index(fields=("project", "created_at")),
        ]

    def __str__(self) -> str:
        return f"Assistant thread #{self.id} for project #{self.project_id}"


class ProjectAssistantMessage(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_messages",
    )
    author = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="assistant_messages",
        null=True,
        blank=True,
    )
    thread = models.ForeignKey(
        ProjectAssistantThread,
        on_delete=models.CASCADE,
        related_name="messages",
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=16, choices=AssistantMessageRole.choices)
    content = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("project", "created_at")),
            models.Index(fields=("project", "role")),
            models.Index(fields=("thread", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.role} message #{self.id} for project #{self.project_id}"


class AssistantProfileSettings(TimestampedModel):
    profile = models.OneToOneField(
        Profile,
        on_delete=models.CASCADE,
        related_name="assistant_settings",
    )
    tone = models.CharField(
        max_length=24,
        choices=AssistantTone.choices,
        default=AssistantTone.PRAGMATICO,
    )
    response_mode = models.CharField(
        max_length=24,
        choices=AssistantResponseMode.choices,
        default=AssistantResponseMode.AUTO,
    )
    citation_mode = models.CharField(
        max_length=24,
        choices=AssistantCitationMode.choices,
        default=AssistantCitationMode.STANDARD,
    )
    custom_instructions = models.TextField(blank=True)
    preferred_model = models.CharField(max_length=64, blank=True, default="gpt-4o-mini")
    monthly_token_limit = models.PositiveIntegerField(default=100_000)

    class Meta:
        ordering = ("profile_id",)

    def __str__(self) -> str:
        return f"Assistant defaults for profile #{self.profile_id}"


class ProjectAssistantProjectSettings(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_project_settings",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="project_assistant_settings",
    )
    tone = models.CharField(
        max_length=24,
        choices=AssistantTone.choices,
        blank=True,
    )
    response_mode = models.CharField(
        max_length=24,
        choices=AssistantResponseMode.choices,
        blank=True,
    )
    citation_mode = models.CharField(
        max_length=24,
        choices=AssistantCitationMode.choices,
        blank=True,
    )
    custom_instructions = models.TextField(blank=True)
    preferred_model = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("project_id", "profile_id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "profile"),
                name="unique_project_assistant_settings_per_profile",
            ),
        ]
        indexes = [
            models.Index(fields=("project", "profile")),
        ]

    def __str__(self) -> str:
        return f"Assistant settings for profile #{self.profile_id} on project #{self.project_id}"


class ProjectAssistantUsage(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_usage_records",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="assistant_usage_records",
    )
    thread = models.ForeignKey(
        ProjectAssistantThread,
        on_delete=models.SET_NULL,
        related_name="usage_records",
        null=True,
        blank=True,
    )
    assistant_message = models.OneToOneField(
        ProjectAssistantMessage,
        on_delete=models.CASCADE,
        related_name="usage_record",
    )
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=64, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("profile", "created_at")),
            models.Index(fields=("project", "profile", "created_at")),
        ]

    def __str__(self) -> str:
        return f"Assistant usage #{self.id} for profile #{self.profile_id}"


class ProjectAssistantRunLog(TimestampedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="assistant_run_logs",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="assistant_run_logs",
    )
    thread = models.ForeignKey(
        ProjectAssistantThread,
        on_delete=models.SET_NULL,
        related_name="run_logs",
        null=True,
        blank=True,
    )
    user_message = models.ForeignKey(
        ProjectAssistantMessage,
        on_delete=models.SET_NULL,
        related_name="assistant_run_logs_as_user_message",
        null=True,
        blank=True,
    )
    assistant_message = models.ForeignKey(
        ProjectAssistantMessage,
        on_delete=models.SET_NULL,
        related_name="assistant_run_logs_as_assistant_message",
        null=True,
        blank=True,
    )
    question_original = models.TextField(blank=True)
    normalized_question = models.TextField(blank=True)
    retrieval_query = models.TextField(blank=True)
    retrieval_provider = models.CharField(max_length=32, blank=True)
    intent = models.CharField(max_length=64, blank=True)
    strategy = models.CharField(max_length=64, blank=True)
    context_scope = models.CharField(max_length=64, blank=True)
    response_length_mode = models.CharField(max_length=16, blank=True)
    selected_source_types = models.JSONField(default=list, blank=True)
    answer_sections = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    retrieval_metrics = models.JSONField(default=dict, blank=True)
    index_state = models.JSONField(default=dict, blank=True)
    top_results = models.JSONField(default=list, blank=True)
    evaluation = models.JSONField(default=dict, blank=True)
    assistant_output = models.TextField(blank=True)
    duration_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("project", "created_at")),
            models.Index(fields=("project", "intent", "created_at")),
            models.Index(fields=("profile", "created_at")),
            models.Index(fields=("thread", "created_at")),
        ]

    def __str__(self) -> str:
        return f"Assistant run log #{self.id} for project #{self.project_id}"
