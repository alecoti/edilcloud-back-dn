from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0023_alter_projectscheduleplan_original_file")]
    operations = [
        migrations.AddIndex(
            model_name="postcomment",
            index=models.Index(fields=["post", "-updated_at", "-id"], name="projects_comment_activity_idx"),
        ),
    ]
