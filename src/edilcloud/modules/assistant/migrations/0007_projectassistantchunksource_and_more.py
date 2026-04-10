from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0006_assistantprofilesettings_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectAssistantChunkSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "scope",
                    models.CharField(
                        choices=[("project", "Project"), ("drafting", "Drafting")],
                        default="project",
                        max_length=32,
                    ),
                ),
                ("source_key", models.CharField(max_length=255)),
                ("source_type", models.CharField(max_length=64)),
                ("label", models.CharField(blank=True, max_length=255)),
                ("content_hash", models.CharField(blank=True, max_length=64)),
                ("file_hash", models.CharField(blank=True, max_length=64)),
                ("metadata_snapshot", models.JSONField(blank=True, default=dict)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("embedding_model", models.CharField(blank=True, max_length=128)),
                ("is_indexed", models.BooleanField(default=False)),
                ("last_indexed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                (
                    "assistant_state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunk_sources",
                        to="assistant.projectassistantstate",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_chunk_sources",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "ordering": ("assistant_state_id", "scope", "source_key"),
                "indexes": [
                    models.Index(fields=["assistant_state", "scope"], name="assistant_p_assista_e4385e_idx"),
                    models.Index(fields=["project", "scope", "source_type"], name="assistant_p_project_df51cd_idx"),
                    models.Index(fields=["project", "is_indexed", "last_indexed_at"], name="assistant_p_project_a0e070_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("assistant_state", "scope", "source_key"),
                        name="unique_assistant_chunk_source_scope_key",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProjectAssistantChunkMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "scope",
                    models.CharField(
                        choices=[("project", "Project"), ("drafting", "Drafting")],
                        default="project",
                        max_length=32,
                    ),
                ),
                ("source_key", models.CharField(max_length=255)),
                ("point_id", models.CharField(max_length=128, unique=True)),
                ("chunk_index", models.PositiveIntegerField(default=0)),
                ("content_hash", models.CharField(blank=True, max_length=64)),
                ("embedding_model", models.CharField(blank=True, max_length=128)),
                (
                    "assistant_state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunk_maps",
                        to="assistant.projectassistantstate",
                    ),
                ),
                (
                    "chunk_source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunk_maps",
                        to="assistant.projectassistantchunksource",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_chunk_maps",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "ordering": ("project_id", "source_key", "chunk_index"),
                "indexes": [
                    models.Index(fields=["assistant_state", "scope", "source_key"], name="assistant_p_assista_3d929f_idx"),
                    models.Index(fields=["chunk_source", "chunk_index"], name="assistant_p_chunk_s_3f2baa_idx"),
                    models.Index(fields=["project", "scope"], name="assistant_p_project_57aef6_idx"),
                ],
            },
        ),
    ]
