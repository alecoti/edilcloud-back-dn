import pgvector.django.vector
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0011_assistant_pgvector_extension"),
        ("projects", "0003_rename_projects_pr_profile_d0de4f_idx_projects_pr_profile_e61b4b_idx_and_more"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="projectassistantchunkmap",
            new_name="assistant_p_assista_2ff8e3_idx",
            old_name="assistant_p_assista_3d929f_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantchunkmap",
            new_name="assistant_p_chunk_s_509541_idx",
            old_name="assistant_p_chunk_s_3f2baa_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantchunkmap",
            new_name="assistant_p_project_1f4739_idx",
            old_name="assistant_p_project_57aef6_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantchunksource",
            new_name="assistant_p_assista_4f3455_idx",
            old_name="assistant_p_assista_e4385e_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantchunksource",
            new_name="assistant_p_project_f0e609_idx",
            old_name="assistant_p_project_df51cd_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantchunksource",
            new_name="assistant_p_project_a934f6_idx",
            old_name="assistant_p_project_a0e070_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantprojectsettings",
            new_name="assistant_p_project_4b79d4_idx",
            old_name="assistant_p_project_3de6df_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantrunlog",
            new_name="assistant_p_project_4ece2c_idx",
            old_name="assistant_p_project_25a6db_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantrunlog",
            new_name="assistant_p_project_3839f2_idx",
            old_name="assistant_p_project_2cc569_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantrunlog",
            new_name="assistant_p_profile_a788ed_idx",
            old_name="assistant_p_profile_27faf7_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantrunlog",
            new_name="assistant_p_thread__91e55c_idx",
            old_name="assistant_p_thread__ca944f_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantthread",
            new_name="assistant_p_project_b450de_idx",
            old_name="assistant_p_project_author_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantusage",
            new_name="assistant_p_profile_13ac7f_idx",
            old_name="assistant_p_profile_86ce36_idx",
        ),
        migrations.RenameIndex(
            model_name="projectassistantusage",
            new_name="assistant_p_project_9002dd_idx",
            old_name="assistant_p_project_5f33a8_idx",
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="activity_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="alert",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="author_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="chunk_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="company_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="content",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="document_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=1536, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="entity_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="event_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="extracted_char_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="extracted_line_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="extraction_quality",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="extraction_status",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="file_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="is_public",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="issue_status",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="label",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="media_kind",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="metadata_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="page_reference",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="post_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="post_kind",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="section_reference",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="source_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="source_type",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="task_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "scope", "source_type"], name="assistant_p_project_605eb3_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "task_id"], name="assistant_p_project_53617c_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "activity_id"], name="assistant_p_project_c2a55c_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "post_id"], name="assistant_p_project_cf7848_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "document_id"], name="assistant_p_project_f3033a_idx"),
        ),
        migrations.AddIndex(
            model_name="projectassistantchunkmap",
            index=models.Index(fields=["project", "event_at"], name="assistant_p_project_a9ec33_idx"),
        ),
    ]
