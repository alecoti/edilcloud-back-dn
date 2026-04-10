from django.db import migrations, models


def backfill_activity_progress(apps, schema_editor):
    ProjectActivity = apps.get_model("projects", "ProjectActivity")

    ProjectActivity.objects.filter(status="completed").update(progress=100)
    ProjectActivity.objects.filter(status="progress").update(progress=55)
    ProjectActivity.objects.filter(status="to-do").update(progress=0)


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0005_projectcompanycolor"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectactivity",
            name="progress",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(backfill_activity_progress, migrations.RunPython.noop),
    ]
