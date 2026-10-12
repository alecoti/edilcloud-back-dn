"""Local browser fixture; never sends emails or creates/deletes the shared demo."""
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")
import django

django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from edilcloud.modules.projects.demo_master_admin import ensure_demo_master_project_for_profile, get_demo_master_project
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole

EMAIL = "ui.completion.qa@example.invalid"
SLUG = "ui-completion-qa"


@transaction.atomic
def seed():
    if not get_demo_master_project():
        raise RuntimeError("Shared demo must already exist; the fixture will not create one.")
    user, created = get_user_model().objects.get_or_create(
        email=EMAIL, defaults={"username": "ui-completion-qa", "first_name": "Giulia", "last_name": "QA", "language": "it", "phone": "+39 333 000 9999"},
    )
    if user.username != "ui-completion-qa":
        raise RuntimeError("Fixture email belongs to an unrelated account.")
    if created:
        user.set_password("uiqa123456")
        user.save()
    workspace, _ = Workspace.objects.get_or_create(slug=SLUG, defaults={"name": "Nuova Impresa QA", "email": EMAIL})
    profile, _ = Profile.objects.get_or_create(user=user, workspace=workspace, defaults={"email": EMAIL, "role": WorkspaceRole.OWNER, "first_name": user.first_name, "last_name": user.last_name, "phone": user.phone, "language": "it"})
    ensure_demo_master_project_for_profile(profile=profile)
    return {"user_id": user.id, "profile_id": profile.id, "workspace_id": workspace.id}


@transaction.atomic
def cleanup():
    from edilcloud.modules.projects.models import Project
    workspace = Workspace.objects.filter(slug=SLUG, profiles__user__email=EMAIL).first()
    if workspace and Project.objects.filter(workspace=workspace).exists():
        raise RuntimeError("Fixture workspace has projects; refusing automatic cleanup.")
    if workspace:
        workspace.delete()
    get_user_model().objects.filter(email=EMAIL, username="ui-completion-qa", workspace_profiles__isnull=True).delete()
    return {"cleaned": True}


print(json.dumps(cleanup() if "--cleanup" in sys.argv else seed()))
