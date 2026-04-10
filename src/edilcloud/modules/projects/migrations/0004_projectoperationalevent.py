from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0003_rename_projects_pr_profile_d0de4f_idx_projects_pr_profile_e61b4b_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectOperationalEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_type", models.CharField(max_length=64)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("task_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("activity_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("post_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("comment_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("folder_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("document_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("photo_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("member_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("invite_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("actor_profile_id_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operational_events", to="projects.project")),
            ],
            options={
                "ordering": ("-occurred_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="projectoperationalevent",
            index=models.Index(fields=["project", "occurred_at"], name="projects_pr_project_459db1_idx"),
        ),
        migrations.AddIndex(
            model_name="projectoperationalevent",
            index=models.Index(fields=["project", "task_id_snapshot", "occurred_at"], name="projects_pr_project_645090_idx"),
        ),
        migrations.AddIndex(
            model_name="projectoperationalevent",
            index=models.Index(fields=["project", "activity_id_snapshot", "occurred_at"], name="projects_pr_project_53c056_idx"),
        ),
        migrations.AddIndex(
            model_name="projectoperationalevent",
            index=models.Index(fields=["project", "event_type", "occurred_at"], name="projects_pr_project_1f1480_idx"),
        ),
    ]
