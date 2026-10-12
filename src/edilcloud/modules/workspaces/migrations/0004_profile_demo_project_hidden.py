from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0003_workspaceinvite_refused_at")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="demo_project_hidden",
            field=models.BooleanField(default=False),
        ),
    ]
