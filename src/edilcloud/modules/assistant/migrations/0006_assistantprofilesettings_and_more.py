from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0005_rename_assistant_p_thread__299dbf_idx_assistant_p_thread__f702c1_idx_and_more"),
        ("projects", "0003_rename_projects_pr_profile_d0de4f_idx_projects_pr_profile_e61b4b_idx_and_more"),
        ("workspaces", "0003_workspaceinvite_refused_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantProfileSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tone", models.CharField(choices=[("pragmatico", "Pragmatico"), ("discorsivo", "Discorsivo"), ("tecnico", "Tecnico")], default="pragmatico", max_length=24)),
                ("response_mode", models.CharField(choices=[("auto", "Auto"), ("sintesi", "Sintesi operativa"), ("timeline", "Timeline"), ("checklist", "Checklist"), ("documentale", "Documentale")], default="auto", max_length=24)),
                ("citation_mode", models.CharField(choices=[("essenziale", "Essenziale"), ("standard", "Standard"), ("dettagliato", "Dettagliato")], default="standard", max_length=24)),
                ("custom_instructions", models.TextField(blank=True)),
                ("preferred_model", models.CharField(blank=True, default="gpt-4o-mini", max_length=64)),
                ("monthly_token_limit", models.PositiveIntegerField(default=100000)),
                ("profile", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_settings", to="workspaces.profile")),
            ],
            options={"ordering": ("profile_id",)},
        ),
        migrations.CreateModel(
            name="ProjectAssistantProjectSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tone", models.CharField(blank=True, choices=[("pragmatico", "Pragmatico"), ("discorsivo", "Discorsivo"), ("tecnico", "Tecnico")], max_length=24)),
                ("response_mode", models.CharField(blank=True, choices=[("auto", "Auto"), ("sintesi", "Sintesi operativa"), ("timeline", "Timeline"), ("checklist", "Checklist"), ("documentale", "Documentale")], max_length=24)),
                ("citation_mode", models.CharField(blank=True, choices=[("essenziale", "Essenziale"), ("standard", "Standard"), ("dettagliato", "Dettagliato")], max_length=24)),
                ("custom_instructions", models.TextField(blank=True)),
                ("preferred_model", models.CharField(blank=True, max_length=64)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="project_assistant_settings", to="workspaces.profile")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_project_settings", to="projects.project")),
            ],
            options={"ordering": ("project_id", "profile_id")},
        ),
        migrations.CreateModel(
            name="ProjectAssistantUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(blank=True, max_length=32)),
                ("model", models.CharField(blank=True, max_length=64)),
                ("prompt_tokens", models.PositiveIntegerField(default=0)),
                ("completion_tokens", models.PositiveIntegerField(default=0)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("estimated", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("assistant_message", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="usage_record", to="assistant.projectassistantmessage")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_usage_records", to="workspaces.profile")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_usage_records", to="projects.project")),
                ("thread", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usage_records", to="assistant.projectassistantthread")),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="projectassistantthread",
            index=models.Index(fields=["project", "author", "archived_at", "last_message_at"], name="assistant_p_project_author_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantprojectsettings",
            index=models.Index(fields=["project", "profile"], name="assistant_p_project_3de6df_idx"),
        ),
        migrations.AddConstraint(
            model_name="projectassistantprojectsettings",
            constraint=models.UniqueConstraint(fields=("project", "profile"), name="unique_project_assistant_settings_per_profile"),
        ),
        migrations.AddIndex(
            model_name="projectassistantusage",
            index=models.Index(fields=["profile", "created_at"], name="assistant_p_profile_86ce36_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantusage",
            index=models.Index(fields=["project", "profile", "created_at"], name="assistant_p_project_5f33a8_idx"),
        ),
    ]
