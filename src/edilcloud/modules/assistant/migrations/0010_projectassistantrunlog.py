from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0009_projectassistantstate_index_version_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectAssistantRunLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("question_original", models.TextField(blank=True)),
                ("normalized_question", models.TextField(blank=True)),
                ("retrieval_query", models.TextField(blank=True)),
                ("retrieval_provider", models.CharField(blank=True, max_length=32)),
                ("intent", models.CharField(blank=True, max_length=64)),
                ("strategy", models.CharField(blank=True, max_length=64)),
                ("context_scope", models.CharField(blank=True, max_length=64)),
                ("response_length_mode", models.CharField(blank=True, max_length=16)),
                ("selected_source_types", models.JSONField(blank=True, default=list)),
                ("answer_sections", models.JSONField(blank=True, default=list)),
                ("token_usage", models.JSONField(blank=True, default=dict)),
                ("retrieval_metrics", models.JSONField(blank=True, default=dict)),
                ("index_state", models.JSONField(blank=True, default=dict)),
                ("top_results", models.JSONField(blank=True, default=list)),
                ("evaluation", models.JSONField(blank=True, default=dict)),
                ("assistant_output", models.TextField(blank=True)),
                ("duration_ms", models.FloatField(default=0.0)),
                (
                    "assistant_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assistant_run_logs_as_assistant_message",
                        to="assistant.projectassistantmessage",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_run_logs",
                        to="workspaces.profile",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_run_logs",
                        to="projects.project",
                    ),
                ),
                (
                    "thread",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="run_logs",
                        to="assistant.projectassistantthread",
                    ),
                ),
                (
                    "user_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assistant_run_logs_as_user_message",
                        to="assistant.projectassistantmessage",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["project", "created_at"], name="assistant_p_project_25a6db_idx"),
                    models.Index(fields=["project", "intent", "created_at"], name="assistant_p_project_2cc569_idx"),
                    models.Index(fields=["profile", "created_at"], name="assistant_p_profile_27faf7_idx"),
                    models.Index(fields=["thread", "created_at"], name="assistant_p_thread__ca944f_idx"),
                ],
            },
        ),
    ]
