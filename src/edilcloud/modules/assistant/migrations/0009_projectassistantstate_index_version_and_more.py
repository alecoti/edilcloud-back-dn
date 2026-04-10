from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0008_projectassistantstate_chunk_schema_version_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectassistantstate",
            name="index_version",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunksource",
            name="index_version",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="index_version",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
