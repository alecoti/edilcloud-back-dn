from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0019_projectmodel3d_projectmodelpin")]

    operations = [
        migrations.AddField(
            model_name=name,
            name="file_size",
            field=models.PositiveBigIntegerField(null=True, blank=True, editable=False),
        )
        for name in ("projectdocument", "projectphoto", "postattachment", "commentattachment", "projectmodel3d")
    ]
