from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0003_workspaceinvite_refused_at"),
        ("projects", "0012_project_demo_snapshot_version_project_is_demo_master_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectClientMutation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mutation_id", models.CharField(max_length=128)),
                ("operation", models.CharField(max_length=64)),
                (
                    "comment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="client_mutations",
                        to="projects.postcomment",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="client_mutations",
                        to="projects.projectpost",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_client_mutations",
                        to="workspaces.profile",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddConstraint(
            model_name="projectclientmutation",
            constraint=models.UniqueConstraint(
                fields=("profile", "mutation_id"),
                name="unique_project_client_mutation_profile",
            ),
        ),
        migrations.AddIndex(
            model_name="projectclientmutation",
            index=models.Index(
                fields=["profile", "operation"],
                name="projects_pr_profile_baa20d_idx",
            ),
        ),
    ]
