from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0020_stored_file_sizes")]
    operations = [
        migrations.AddField(model_name="postattachment", name="content_type",
            field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="commentattachment", name="content_type",
            field=models.CharField(blank=True, default="", max_length=255)),
    ]
