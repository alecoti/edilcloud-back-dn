from django.db import migrations, models


def migrate_model_preferences(apps, schema_editor):
    for model_name in ("AssistantProfileSettings", "ProjectAssistantProjectSettings"):
        model = apps.get_model("assistant", model_name)
        model.objects.using(schema_editor.connection.alias).filter(
            preferred_model__regex=r"^gpt-4o-mini(-\d{4}-\d{2}-\d{2})?$"
        ).update(preferred_model="gpt-6-luna")


class Migration(migrations.Migration):
    dependencies = [("assistant", "0015_projectassistantgraphsnapshot")]
    operations = [
        migrations.AlterField(model_name="assistantprofilesettings", name="preferred_model",
                              field=models.CharField(blank=True, default="gpt-6-luna", max_length=64)),
        migrations.RunPython(migrate_model_preferences, migrations.RunPython.noop),
    ]
