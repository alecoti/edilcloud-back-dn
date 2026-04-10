from django.contrib import admin

from edilcloud.modules.workspaces.models import (
    Profile,
    Workspace,
    WorkspaceAccessRequest,
    WorkspaceInvite,
)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "workspace_type", "email", "is_active", "created_at")
    search_fields = ("name", "slug", "email", "vat_number")
    list_filter = ("is_active", "workspace_type")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "member_name", "workspace", "user", "role", "email", "is_active")
    search_fields = ("first_name", "last_name", "email", "workspace__name", "user__email")
    list_filter = ("role", "is_active", "language")


@admin.register(WorkspaceInvite)
class WorkspaceInviteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workspace",
        "email",
        "role",
        "invite_code",
        "invited_by",
        "accepted_at",
        "expires_at",
    )
    search_fields = ("email", "workspace__name", "uidb36", "token", "invite_code")
    list_filter = ("role", "accepted_at")


@admin.register(WorkspaceAccessRequest)
class WorkspaceAccessRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workspace",
        "email",
        "status",
        "requested_by_user",
        "reviewed_by",
        "approved_at",
        "refused_at",
        "expires_at",
    )
    search_fields = ("email", "workspace__name", "request_token")
    list_filter = ("status", "language", "approved_at", "refused_at")
