"""Django and native SQL adopt the same derived cache without changing old migrations."""

from pathlib import Path

from django.db import migrations, models
import django.db.models.deletion


class CreateSharedCache(migrations.CreateModel):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            if not self.allow_migrate_model(
                schema_editor.connection.alias, to_state.apps.get_model(app_label, self.name)
            ):
                return
            schema_editor.execute(
                Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"), params=None
            )
        else:
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        # A rollback must not drop a table another running backend can still use.
        # The ORM state can be reversed; later reapplication validates/adopts it.
        if schema_editor.connection.vendor != "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    dependencies = [("elaborati", "0011_document_author_snapshot")]
    operations = [
        CreateSharedCache(
            name="DraftPdfCache",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "revision_id",
                        "profile_id",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        to="elaborati.elaboratorevision",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="display_pdfs",
                        db_index=False,
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        to="workspaces.profile",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="elaborati_display_pdfs",
                        db_index=False,
                    ),
                ),
                ("content_hash", models.TextField()),
                ("pdf_file", models.TextField()),
                ("pdf_hash", models.TextField()),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "elaborati_draftpdfcache",
                "indexes": [
                    models.Index(fields=("pdf_file",), name="elab_display_pdf_file_idx"),
                    models.Index(fields=("profile",), name="elab_display_profile_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(content_hash=""), name="elab_display_content_nonempty"
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(pdf_file=""), name="elab_display_file_nonempty"
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(pdf_hash=""), name="elab_display_hash_nonempty"
                    ),
                ],
            },
        )
    ]
