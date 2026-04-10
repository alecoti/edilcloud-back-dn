from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def bootstrap_django() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")

    import django

    django.setup()


bootstrap_django()

from django.contrib.auth import get_user_model  # noqa: E402

from edilcloud.modules.workspaces.models import Workspace, WorkspaceRole  # noqa: E402


OWNER_EMAIL = "create.owner@example.com"
TEAM_EMAIL = "create.team@example.com"
DEFAULT_PASSWORD = "devpass123"
WORKSPACE_NAME = "Smoke Create Project Workspace"


def ensure_user(*, email: str, username: str, first_name: str, last_name: str):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        email=email,
        defaults={
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
            "is_active": True,
        },
    )
    if created:
        user.set_password(DEFAULT_PASSWORD)
    else:
        user.username = user.username or username
        user.first_name = first_name
        user.last_name = last_name
        user.language = getattr(user, "language", "it") or "it"
        user.is_active = True
        user.set_password(DEFAULT_PASSWORD)
    user.save()
    return user


def ensure_profile(workspace: Workspace, *, user, role: str, first_name: str, last_name: str, position: str):
    profile, _created = workspace.profiles.get_or_create(
        user=user,
        defaults={
            "email": user.email,
            "role": role,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
            "position": position,
            "is_active": True,
        },
    )
    profile.email = user.email
    profile.role = role
    profile.first_name = first_name
    profile.last_name = last_name
    profile.language = profile.language or "it"
    profile.position = position
    profile.is_default = True
    profile.is_active = True
    profile.save()
    return profile


def main() -> int:
    owner_user = ensure_user(
        email=OWNER_EMAIL,
        username="create-owner",
        first_name="Giulia",
        last_name="Bianchi",
    )
    team_user = ensure_user(
        email=TEAM_EMAIL,
        username="create-team",
        first_name="Luca",
        last_name="Ferretti",
    )

    workspace, _created = Workspace.objects.get_or_create(
        name=WORKSPACE_NAME,
        defaults={"email": OWNER_EMAIL, "is_active": True},
    )
    workspace.email = workspace.email or OWNER_EMAIL
    workspace.is_active = True
    workspace.save()

    owner_profile = ensure_profile(
        workspace,
        user=owner_user,
        role=WorkspaceRole.OWNER,
        first_name="Giulia",
        last_name="Bianchi",
        position="Owner di workspace",
    )
    team_profile = ensure_profile(
        workspace,
        user=team_user,
        role=WorkspaceRole.MANAGER,
        first_name="Luca",
        last_name="Ferretti",
        position="Capo commessa",
    )

    print(
        json.dumps(
            {
                "workspaceId": workspace.id,
                "workspaceName": workspace.name,
                "owner": {
                    "email": OWNER_EMAIL,
                    "password": DEFAULT_PASSWORD,
                    "profileId": owner_profile.id,
                },
                "teamMember": {
                    "email": TEAM_EMAIL,
                    "password": DEFAULT_PASSWORD,
                    "profileId": team_profile.id,
                },
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
