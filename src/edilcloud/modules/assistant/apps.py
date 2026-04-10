from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "edilcloud.modules.assistant"
    verbose_name = "EdilCloud Assistant"

    def ready(self) -> None:
        from edilcloud.modules.assistant import signals  # noqa: F401
