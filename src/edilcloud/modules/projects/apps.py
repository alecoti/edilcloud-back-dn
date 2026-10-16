from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "edilcloud.modules.projects"

    def ready(self):
        from . import provenance_signals  # noqa: F401
