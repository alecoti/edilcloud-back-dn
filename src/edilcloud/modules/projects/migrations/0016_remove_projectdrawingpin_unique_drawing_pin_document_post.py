from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0015_projectdocument_document_kind"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="projectdrawingpin",
            name="unique_drawing_pin_document_post",
        ),
    ]
