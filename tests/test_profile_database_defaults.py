import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from edilcloud.modules.workspaces.models import Profile, Workspace


@pytest.mark.django_db
def test_demo_visibility_defaults_for_current_and_older_profile_writers():
    user = get_user_model().objects.create_user(
        email="profile-default@example.invalid", username="profile-default"
    )
    workspace = Workspace.objects.create(name="Current writer")
    profile = Profile.objects.create(user=user, workspace=workspace, email=user.email)
    assert profile.demo_project_hidden is False

    other_workspace = Workspace.objects.create(name="Older writer")
    quote = connection.ops.quote_name
    # Reproduce an older ORM insert that does not know about the new column.
    columns = [
        field.column for field in Profile._meta.concrete_fields
        if not field.primary_key and field.name != "demo_project_hidden"
    ]
    selected_columns = ["%s" if column == "workspace_id" else quote(column) for column in columns]
    table = quote(Profile._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} ({', '.join(map(quote, columns))}) "
            f"SELECT {', '.join(selected_columns)} FROM {table} WHERE {quote('id')} = %s",
            [other_workspace.id, profile.id],
        )
    older_profile = Profile.objects.get(user=user, workspace=other_workspace)
    assert older_profile.demo_project_hidden is False


@pytest.mark.django_db
def test_explicit_demo_visibility_is_not_overwritten_by_database_default():
    user = get_user_model().objects.create_user(
        email="profile-hidden@example.invalid", username="profile-hidden"
    )
    workspace = Workspace.objects.create(name="Hidden demo")
    profile = Profile.objects.create(
        user=user, workspace=workspace, email=user.email, demo_project_hidden=True
    )
    profile.refresh_from_db()
    assert profile.demo_project_hidden is True
