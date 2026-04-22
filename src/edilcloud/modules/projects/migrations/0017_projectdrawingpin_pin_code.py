from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0016_remove_projectdrawingpin_unique_drawing_pin_document_post"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectdrawingpin",
            name="pin_code",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
