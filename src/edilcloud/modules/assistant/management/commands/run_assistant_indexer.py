import time

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.assistant.models import ProjectAssistantState
from edilcloud.modules.assistant.services import (
    assistant_rag_enabled,
    get_or_create_project_assistant_state,
    index_project_assistant_state,
    schedule_project_assistant_sync,
)
from edilcloud.modules.projects.models import Project


class Command(BaseCommand):
    help = "Indicizza i contenuti assistant di progetto su Postgres/pgvector."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Esegue un solo ciclo e termina.")
        parser.add_argument("--project-id", type=int, help="Indicizza solo il progetto specificato.")
        parser.add_argument("--force", action="store_true", help="Forza reindex anche se la versione e gia allineata.")
        parser.add_argument("--sleep-seconds", type=float, default=10.0, help="Intervallo tra i poll del worker.")
        parser.add_argument("--batch-size", type=int, default=4, help="Numero massimo di progetti per ciclo.")

    def handle(self, *args, **options):
        if not assistant_rag_enabled():
            self.stdout.write(self.style.WARNING("OpenAI embeddings non configurati: indexer fermato."))
            return

        project_id = options.get("project_id")
        force = bool(options.get("force"))
        once = bool(options.get("once"))
        sleep_seconds = max(float(options.get("sleep_seconds") or 10.0), 1.0)
        batch_size = max(int(options.get("batch_size") or 4), 1)

        if project_id:
            project = Project.objects.filter(id=project_id).first()
            if project is None:
                raise CommandError(f"Progetto #{project_id} non trovato.")
            state = get_or_create_project_assistant_state(project)
            schedule_project_assistant_sync(state)
            index_project_assistant_state(state=state, force=True)
            self.stdout.write(self.style.SUCCESS(f"Progetto #{project_id} indicizzato su Postgres/pgvector."))
            return

        while True:
            processed = self.process_batch(batch_size=batch_size, force=force)
            if once:
                if processed == 0:
                    self.stdout.write("Nessun progetto assistant in coda.")
                return
            if processed == 0:
                time.sleep(sleep_seconds)

    def process_batch(self, *, batch_size: int, force: bool) -> int:
        states = list(
            ProjectAssistantState.objects.select_related("project")
            .filter(background_sync_scheduled=True)
            .order_by("-is_dirty", "last_indexed_at", "id")[:batch_size]
        )
        processed = 0
        for state in states:
            try:
                index_project_assistant_state(state=state, force=force)
                processed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Indicizzato progetto #{state.project_id} ({state.project.name}) con {state.chunk_count} chunk."
                    )
                )
            except Exception as exc:
                state.last_sync_error = str(exc)
                state.is_dirty = True
                state.background_sync_scheduled = True
                state.save(update_fields=["last_sync_error", "is_dirty", "background_sync_scheduled"])
                self.stderr.write(
                    self.style.ERROR(f"Indicizzazione fallita per progetto #{state.project_id}: {exc}")
                )
        return processed
