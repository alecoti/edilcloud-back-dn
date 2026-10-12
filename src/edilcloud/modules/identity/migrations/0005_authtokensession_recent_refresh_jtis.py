from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0004_authtokensession_passwordresetsession")]

    operations = [
        migrations.AddField(
            model_name="authtokensession",
            name="recent_refresh_jtis",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
