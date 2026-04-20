from django.db import migrations, models


def mark_existing_drawings(apps, _schema_editor):
    project_document = apps.get_model("projects", "ProjectDocument")
    drawing_ids = []
    for document in project_document.objects.all().only(
        "id",
        "title",
        "description",
        "document",
    ):
        file_name = getattr(document.document, "name", "") or ""
        haystack = f"{document.title} {document.description} {file_name}".lower()
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        is_drawing = (
            "disegn" in haystack
            or "planimetr" in haystack
            or "tavola" in haystack
            or "as built" in haystack
            or extension in {"dwg", "dxf"}
        )
        if is_drawing:
            drawing_ids.append(document.id)
    if drawing_ids:
        project_document.objects.filter(id__in=drawing_ids).update(document_kind="drawing")


def unmark_existing_drawings(apps, _schema_editor):
    project_document = apps.get_model("projects", "ProjectDocument")
    project_document.objects.filter(document_kind="drawing").update(document_kind="document")


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0014_projectdrawingpin"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectdocument",
            name="document_kind",
            field=models.CharField(
                choices=[
                    ("document", "Document"),
                    ("drawing", "Drawing"),
                ],
                default="document",
                max_length=24,
            ),
        ),
        migrations.RunPython(mark_existing_drawings, unmark_existing_drawings),
    ]
