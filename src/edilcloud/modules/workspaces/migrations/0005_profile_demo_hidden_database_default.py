from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0004_profile_demo_project_hidden")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="demo_project_hidden",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
