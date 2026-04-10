from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_projectschedulelink_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="archive_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="last_export_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="owner_export_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="purge_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
