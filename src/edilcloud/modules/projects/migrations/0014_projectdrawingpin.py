from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0013_projectclientmutation"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectDrawingPin",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("x", models.FloatField()),
                ("y", models.FloatField()),
                ("page_number", models.PositiveIntegerField(default=1)),
                ("label", models.CharField(blank=True, max_length=255)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_project_drawing_pins",
                        to="workspaces.profile",
                    ),
                ),
                (
                    "drawing_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drawing_pins",
                        to="projects.projectdocument",
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drawing_pins",
                        to="projects.projectpost",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drawing_pins",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "ordering": ("drawing_document_id", "page_number", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="projectdrawingpin",
            constraint=models.UniqueConstraint(
                fields=("drawing_document", "post"),
                name="unique_drawing_pin_document_post",
            ),
        ),
        migrations.AddConstraint(
            model_name="projectdrawingpin",
            constraint=models.CheckConstraint(
                check=models.Q(("x__gte", 0.0), ("x__lte", 1.0)),
                name="drawing_pin_x_normalized",
            ),
        ),
        migrations.AddConstraint(
            model_name="projectdrawingpin",
            constraint=models.CheckConstraint(
                check=models.Q(("y__gte", 0.0), ("y__lte", 1.0)),
                name="drawing_pin_y_normalized",
            ),
        ),
        migrations.AddIndex(
            model_name="projectdrawingpin",
            index=models.Index(
                fields=["project", "drawing_document"],
                name="projects_pr_project_b2403f_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="projectdrawingpin",
            index=models.Index(
                fields=["project", "post"],
                name="projects_pr_project_9fc9f9_idx",
            ),
        ),
    ]
