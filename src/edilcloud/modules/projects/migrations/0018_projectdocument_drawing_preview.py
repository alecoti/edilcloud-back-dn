from django.db import migrations, models

import edilcloud.modules.projects.models


class Migration(migrations.Migration):
    dependencies = [("projects", "0017_projectdrawingpin_pin_code")]

    operations = [
        migrations.AddField(
            model_name="projectdocument",
            name="drawing_preview",
            field=models.ImageField(
                blank=True,
                upload_to=edilcloud.modules.projects.models.project_drawing_preview_upload_to,
            ),
        ),
    ]
