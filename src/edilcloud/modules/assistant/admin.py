from django.contrib import admin

from edilcloud.modules.assistant.models import (
    ProjectAssistantChunkMap,
    ProjectAssistantChunkSource,
    ProjectAssistantGraphSnapshot,
    ProjectAssistantMessage,
    ProjectAssistantState,
    ProjectAssistantThread,
    ProjectAssistantUsage,
    ProjectAssistantWikiPage,
)


@admin.register(ProjectAssistantState)
class ProjectAssistantStateAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "chat_model",
        "embedding_model",
        "current_version",
        "last_indexed_version",
        "source_count",
        "chunk_count",
        "is_dirty",
        "background_sync_scheduled",
        "last_indexed_at",
    )
    list_filter = ("is_dirty", "background_sync_scheduled", "chat_model", "embedding_model")
    search_fields = ("project__name", "project__workspace__name")


@admin.register(ProjectAssistantChunkSource)
class ProjectAssistantChunkSourceAdmin(admin.ModelAdmin):
    list_display = (
        "project",
        "scope",
        "source_key",
        "source_type",
        "chunk_count",
        "is_indexed",
        "embedding_model",
        "last_indexed_at",
    )
    list_filter = ("scope", "source_type", "is_indexed", "embedding_model")
    search_fields = ("project__name", "source_key", "label")


@admin.register(ProjectAssistantChunkMap)
class ProjectAssistantChunkMapAdmin(admin.ModelAdmin):
    list_display = ("project", "scope", "source_key", "source_type", "chunk_index", "file_name", "embedding_model")
    list_filter = ("scope", "source_type", "embedding_model")
    search_fields = ("project__name", "source_key", "point_id", "label", "file_name")


@admin.register(ProjectAssistantWikiPage)
class ProjectAssistantWikiPageAdmin(admin.ModelAdmin):
    list_display = ("project", "slug", "page_type", "is_stale", "schema_version", "generated_at")
    list_filter = ("page_type", "is_stale", "schema_version")
    search_fields = ("project__name", "slug", "title", "body_markdown", "summary")
    readonly_fields = ("content_hash", "generated_version", "generated_at", "created_at", "updated_at")


@admin.register(ProjectAssistantGraphSnapshot)
class ProjectAssistantGraphSnapshotAdmin(admin.ModelAdmin):
    list_display = ("project", "is_stale", "schema_version", "generated_at", "node_count", "edge_count")
    list_filter = ("is_stale", "schema_version")
    search_fields = ("project__name", "summary_markdown")
    readonly_fields = (
        "content_hash",
        "generated_version",
        "generated_at",
        "created_at",
        "updated_at",
        "node_count",
        "edge_count",
    )

    def node_count(self, obj: ProjectAssistantGraphSnapshot) -> int:
        return len(obj.nodes or [])

    def edge_count(self, obj: ProjectAssistantGraphSnapshot) -> int:
        return len(obj.edges or [])


@admin.register(ProjectAssistantThread)
class ProjectAssistantThreadAdmin(admin.ModelAdmin):
    list_display = ("project", "author", "title", "last_message_at", "archived_at")
    list_filter = ("archived_at",)
    search_fields = ("project__name", "title", "summary", "author__email")


@admin.register(ProjectAssistantMessage)
class ProjectAssistantMessageAdmin(admin.ModelAdmin):
    list_display = ("project", "thread", "role", "author", "created_at")
    list_filter = ("role",)
    search_fields = ("project__name", "content")


@admin.register(ProjectAssistantUsage)
class ProjectAssistantUsageAdmin(admin.ModelAdmin):
    list_display = ("project", "profile", "provider", "model", "total_tokens", "created_at")
    list_filter = ("provider", "model")
    search_fields = ("project__name", "profile__email", "assistant_message__content")
