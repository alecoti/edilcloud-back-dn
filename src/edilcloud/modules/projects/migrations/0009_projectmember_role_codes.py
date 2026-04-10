from django.db import migrations, models


def add_project_role_codes_if_missing(apps, schema_editor):
    table_name = "projects_projectmember"
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
    if "project_role_codes" in columns:
        return

    project_member = apps.get_model("projects", "ProjectMember")
    field = models.JSONField(default=list, blank=True)
    field.set_attributes_from_name("project_role_codes")
    schema_editor.add_field(project_member, field)


def remove_project_role_codes_if_present(apps, schema_editor):
    table_name = "projects_projectmember"
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
    if "project_role_codes" not in columns:
        return

    project_member = apps.get_model("projects", "ProjectMember")
    field = models.JSONField(default=list, blank=True)
    field.set_attributes_from_name("project_role_codes")
    schema_editor.remove_field(project_member, field)


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0008_project_archive_lifecycle"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_project_role_codes_if_missing,
                    reverse_code=remove_project_role_codes_if_present,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="projectmember",
                    name="project_role_codes",
                    field=models.JSONField(blank=True, default=list),
                ),
            ],
        ),
    ]
