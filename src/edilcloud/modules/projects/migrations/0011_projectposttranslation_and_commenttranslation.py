from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0010_rename_projects_pro_project_540f4a_idx_projects_pr_project_71a6e6_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectPostTranslation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("target_language", models.CharField(max_length=8)),
                ("source_language", models.CharField(blank=True, max_length=8)),
                ("source_signature", models.CharField(blank=True, max_length=64)),
                ("translated_text", models.TextField(blank=True)),
                ("provider", models.CharField(blank=True, max_length=32)),
                ("model", models.CharField(blank=True, max_length=64)),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="translations",
                        to="projects.projectpost",
                    ),
                ),
            ],
            options={
                "ordering": ("post_id", "target_language", "id"),
                "indexes": [
                    models.Index(fields=["post", "target_language"], name="projects_pr_post_id_24e67f_idx"),
                    models.Index(fields=["target_language", "updated_at"], name="projects_pr_target__19e3bc_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("post", "target_language"),
                        name="unique_project_post_translation_language",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PostCommentTranslation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("target_language", models.CharField(max_length=8)),
                ("source_language", models.CharField(blank=True, max_length=8)),
                ("source_signature", models.CharField(blank=True, max_length=64)),
                ("translated_text", models.TextField(blank=True)),
                ("provider", models.CharField(blank=True, max_length=32)),
                ("model", models.CharField(blank=True, max_length=64)),
                (
                    "comment",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="translations",
                        to="projects.postcomment",
                    ),
                ),
            ],
            options={
                "ordering": ("comment_id", "target_language", "id"),
                "indexes": [
                    models.Index(fields=["comment", "target_language"], name="projects_po_comment_98bf1f_idx"),
                    models.Index(fields=["target_language", "updated_at"], name="projects_po_target__94ec64_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("comment", "target_language"),
                        name="unique_post_comment_translation_language",
                    ),
                ],
            },
        ),
    ]
