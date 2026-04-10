from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assistant", "0007_projectassistantchunksource_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectassistantstate",
            name="chunk_schema_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunksource",
            name="chunk_schema_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectassistantchunkmap",
            name="chunk_schema_version",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
