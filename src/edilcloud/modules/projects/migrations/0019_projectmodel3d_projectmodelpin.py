from django.db import migrations, models
import django.db.models.deletion

import edilcloud.modules.projects.models


class Migration(migrations.Migration):
    dependencies = [("projects", "0018_projectdocument_drawing_preview")]

    operations = [
        migrations.CreateModel(
            name="ProjectModel3D",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=255)),
                ("file", models.FileField(upload_to=edilcloud.modules.projects.models.project_model_3d_upload_to)),
                ("vertex_count", models.PositiveIntegerField(default=0)),
                ("triangle_count", models.PositiveIntegerField(default=0)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="workspaces.profile")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="models_3d", to="projects.project")),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="ProjectModelPin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("x", models.FloatField()),
                ("y", models.FloatField()),
                ("z", models.FloatField()),
                ("label", models.CharField(blank=True, max_length=255)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="workspaces.profile")),
                ("model", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pins", to="projects.projectmodel3d")),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="model_pins", to="projects.projectpost")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="model_pins", to="projects.project")),
            ],
            options={"ordering": ("model_id", "id")},
        ),
        migrations.AddIndex(
            model_name="projectmodelpin",
            index=models.Index(fields=["project", "model"], name="proj_m3pin_proj_model_idx"),
        ),
        migrations.AddIndex(
            model_name="projectmodelpin",
            index=models.Index(fields=["project", "post"], name="proj_m3pin_proj_post_idx"),
        ),
    ]
