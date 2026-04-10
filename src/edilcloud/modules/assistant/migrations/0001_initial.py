from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("projects", "0001_initial"),
        ("workspaces", "0003_workspaceinvite_refused_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectAssistantState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("container_tag", models.CharField(max_length=100, unique=True)),
                ("chat_model", models.CharField(blank=True, max_length=128)),
                ("embedding_model", models.CharField(blank=True, max_length=128)),
                ("current_version", models.BigIntegerField(default=0)),
                ("last_indexed_version", models.BigIntegerField(default=0)),
                ("source_count", models.PositiveIntegerField(default=0)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("last_indexed_at", models.DateTimeField(blank=True, null=True)),
                ("is_dirty", models.BooleanField(default=True)),
                ("background_sync_scheduled", models.BooleanField(default=False)),
                ("last_sync_error", models.TextField(blank=True)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_state",
                        to="projects.project",
                    ),
                ),
            ],
            options={"ordering": ("project_id",)},
        ),
        migrations.CreateModel(
            name="ProjectAssistantMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.CharField(choices=[("user", "User"), ("assistant", "Assistant")], max_length=16)),
                ("content", models.TextField(blank=True)),
                ("citations", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "author",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assistant_messages",
                        to="workspaces.profile",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_messages",
                        to="projects.project",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="projectassistantmessage",
            index=models.Index(fields=["project", "created_at"], name="assistant_m_project_4e2e6b_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantmessage",
            index=models.Index(fields=["project", "role"], name="assistant_m_project_58799b_idx"),
        ),
    ]
