from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
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
from django.utils import timezone  # noqa: E402

from edilcloud.modules.workspaces.models import (  # noqa: E402
    Profile,
    Workspace,
    WorkspaceInvite,
    WorkspaceRole,
)


DEFAULT_PASSWORD = "devpass123"
WORKSPACE_NAME = "Smoke Team Panel Workspace"

OWNER_EMAIL = "team.owner@example.com"
DELEGATE_EMAIL = "team.delegate@example.com"
MANAGER_EMAIL = "team.manager@example.com"
WORKER_EMAIL = "team.worker@example.com"
DISABLED_EMAIL = "team.disabled@example.com"
WAITING_EMAIL = "team.waiting@example.com"
REFUSED_EMAIL = "team.refused@example.com"


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


def create_profile(
    *,
    workspace: Workspace,
    user,
    role: str,
    first_name: str,
    last_name: str,
    position: str,
    is_active: bool = True,
) -> Profile:
    return Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=role,
        first_name=first_name,
        last_name=last_name,
        language="it",
        position=position,
        is_active=is_active,
    )


def main() -> int:
    workspace, _created = Workspace.objects.get_or_create(
        name=WORKSPACE_NAME,
        defaults={"email": OWNER_EMAIL, "is_active": True},
    )
    workspace.email = workspace.email or OWNER_EMAIL
    workspace.is_active = True
    workspace.save()

    owner_user = ensure_user(
        email=OWNER_EMAIL,
        username="team-owner",
        first_name="Olivia",
        last_name="Rinaldi",
    )
    delegate_user = ensure_user(
        email=DELEGATE_EMAIL,
        username="team-delegate",
        first_name="Diego",
        last_name="Martini",
    )
    manager_user = ensure_user(
        email=MANAGER_EMAIL,
        username="team-manager",
        first_name="Marta",
        last_name="Leoni",
    )
    worker_user = ensure_user(
        email=WORKER_EMAIL,
        username="team-worker",
        first_name="Walter",
        last_name="Serra",
    )
    disabled_user = ensure_user(
        email=DISABLED_EMAIL,
        username="team-disabled",
        first_name="Debora",
        last_name="Mazza",
    )

    Profile.objects.filter(workspace=workspace).delete()
    WorkspaceInvite.objects.filter(workspace=workspace).delete()

    owner_profile = create_profile(
        workspace=workspace,
        user=owner_user,
        role=WorkspaceRole.OWNER,
        first_name="Olivia",
        last_name="Rinaldi",
        position="Owner di workspace",
        is_active=True,
    )
    delegate_profile = create_profile(
        workspace=workspace,
        user=delegate_user,
        role=WorkspaceRole.DELEGATE,
        first_name="Diego",
        last_name="Martini",
        position="Referente delegato",
        is_active=True,
    )
    manager_profile = create_profile(
        workspace=workspace,
        user=manager_user,
        role=WorkspaceRole.MANAGER,
        first_name="Marta",
        last_name="Leoni",
        position="Project manager",
        is_active=True,
    )
    worker_profile = create_profile(
        workspace=workspace,
        user=worker_user,
        role=WorkspaceRole.WORKER,
        first_name="Walter",
        last_name="Serra",
        position="Operativo di cantiere",
        is_active=True,
    )
    disabled_profile = create_profile(
        workspace=workspace,
        user=disabled_user,
        role=WorkspaceRole.WORKER,
        first_name="Debora",
        last_name="Mazza",
        position="Operativa sospesa",
        is_active=False,
    )

    waiting_invite = WorkspaceInvite.objects.create(
        workspace=workspace,
        invited_by=owner_user,
        email=WAITING_EMAIL,
        role=WorkspaceRole.WORKER,
        first_name="Wendy",
        last_name="Pace",
        position="Invito in attesa",
        expires_at=timezone.now() + timedelta(days=14),
    )
    refused_invite = WorkspaceInvite.objects.create(
        workspace=workspace,
        invited_by=owner_user,
        email=REFUSED_EMAIL,
        role=WorkspaceRole.MANAGER,
        first_name="Rita",
        last_name="Ferri",
        position="Invito rifiutato",
        expires_at=timezone.now() + timedelta(days=14),
        refused_at=timezone.now() - timedelta(hours=3),
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
                "approved": {
                    "ownerProfileId": owner_profile.id,
                    "delegateProfileId": delegate_profile.id,
                    "managerProfileId": manager_profile.id,
                    "workerProfileId": worker_profile.id,
                    "disabledProfileId": disabled_profile.id,
                },
                "invites": {
                    "waitingEmail": waiting_invite.email,
                    "refusedEmail": refused_invite.email,
                },
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
