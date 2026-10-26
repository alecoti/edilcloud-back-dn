"""Shared attribution table. Never guess or backfill ownership of old documents."""
from pathlib import Path

from django.db import migrations, models
import django.db.models.deletion
from django.db.migrations.exceptions import IrreversibleError


class SharedOwnership(migrations.SeparateDatabaseAndState):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if not self.allow_migrate_model(
            schema_editor.connection.alias, to_state.apps.get_model(app_label, "ElaboratoOwnership")
        ):
            return
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"), params=None)
        else:
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if not self.allow_migrate_model(
            schema_editor.connection.alias, from_state.apps.get_model(app_label, "ElaboratoOwnership")
        ):
            return
        if schema_editor.connection.vendor == "postgresql":
            raise IrreversibleError("Ownership evidence must be preserved; roll forward with an explicit reviewed migration.")
        super().database_backwards(app_label, schema_editor, from_state, to_state)


def operations():
    return [migrations.CreateModel(
        name="ElaboratoOwnership",
        fields=[
            ("document", models.OneToOneField(to="elaborati.elaborato", on_delete=django.db.models.deletion.CASCADE,
                primary_key=True, serialize=False, related_name="ownership")),
            ("workspace", models.ForeignKey(to="workspaces.workspace", on_delete=django.db.models.deletion.PROTECT,
                related_name="owned_elaborati", db_index=False)),
            ("assigned_by", models.ForeignKey(to="workspaces.profile", on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True, related_name="elaborati_ownership_assignments", db_index=False)),
            ("assigned_at", models.DateTimeField()),
            ("basis", models.CharField(max_length=32, choices=[("creation", "Creation"),
                ("author_confirmation", "Author confirmation"), ("administrative_review", "Administrative review")])),
            ("assignment_snapshot", models.JSONField()),
        ],
        options={
            "indexes": [models.Index(fields=("workspace",), name="elab_owned_workspace_idx")],
            "constraints": [
                models.CheckConstraint(condition=models.Q(basis__in=("creation", "author_confirmation", "administrative_review")), name="elab_ownership_basis"),
                models.CheckConstraint(condition=~models.Q(assignment_snapshot={}), name="elab_ownership_snapshot"),
            ],
        },
    )]


class Migration(migrations.Migration):
    dependencies = [("elaborati", "0012_shared_display_cache")]
    operations = [SharedOwnership(database_operations=operations(), state_operations=operations())]
