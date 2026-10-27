"""Storage policy only: no SQL/data rewrite and no filesystem migration."""

from django.db import migrations, models
import edilcloud.modules.projects.document_storage
import edilcloud.modules.projects.models


class Migration(migrations.Migration):
    dependencies = [("projects", "0028_phase_staff_inheritance")]
    operations = [
        migrations.AlterField(
            model_name="projectdocument",
            name="document",
            field=models.FileField(
                upload_to=edilcloud.modules.projects.models.project_document_upload_to,
                storage=edilcloud.modules.projects.document_storage.project_document_storage,
            ),
        )
    ]
