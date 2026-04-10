from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from edilcloud.modules.identity.models import AccessSession, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("EdilCloud", {"fields": ("language",)}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("EdilCloud", {"fields": ("language",)}),
    )
    list_display = ("id", "email", "username", "language", "is_staff", "is_active")
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("id",)


@admin.register(AccessSession)
class AccessSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "email",
        "provider",
        "failed_attempts",
        "verified_at",
        "consumed_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("provider", "verified_at", "consumed_at")
    search_fields = ("email", "flow_token")
    ordering = ("-created_at", "-id")
    readonly_fields = ("flow_token", "created_at", "updated_at")
