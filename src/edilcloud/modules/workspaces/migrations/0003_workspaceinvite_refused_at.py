from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0002_profile_phone_verified_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceinvite",
            name="refused_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
