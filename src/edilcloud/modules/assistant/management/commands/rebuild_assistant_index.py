from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.assistant.models import ProjectAssistantState
from edilcloud.modules.assistant.services import get_or_create_project_assistant_state, index_project_assistant_state
from edilcloud.modules.projects.models import Project


class Command(BaseCommand):
    help = "Forza il rebuild dell'indice assistant per un progetto o per tutti i progetti."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, help="Rebuild di un singolo progetto.")
        parser.add_argument("--all", action="store_true", help="Rebuild di tutti i progetti.")

    def handle(self, *args, **options):
        project_id = options.get("project_id")
        rebuild_all = bool(options.get("all"))

        if not project_id and not rebuild_all:
            raise CommandError("Specifica --project-id oppure --all.")

        if project_id:
            project = Project.objects.filter(id=project_id).first()
            if project is None:
                raise CommandError(f"Progetto #{project_id} non trovato.")
            state = get_or_create_project_assistant_state(project)
            state.is_dirty = True
            state.background_sync_scheduled = True
            state.save(update_fields=["is_dirty", "background_sync_scheduled"])
            index_project_assistant_state(state=state, force=True)
            self.stdout.write(self.style.SUCCESS(f"Indice assistant ricostruito per progetto #{project.id}."))
            return

        states = []
        for project in Project.objects.order_by("id"):
            state = get_or_create_project_assistant_state(project)
            state.is_dirty = True
            state.background_sync_scheduled = True
            state.save(update_fields=["is_dirty", "background_sync_scheduled"])
            states.append(state)

        for state in states:
            index_project_assistant_state(state=state, force=True)
            self.stdout.write(self.style.SUCCESS(f"Rebuild completato per progetto #{state.project_id}."))
