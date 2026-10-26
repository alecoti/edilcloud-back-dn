"""Attribution only. Authorization/legacy confirmation are separate services."""
from .models import ElaboratoOwnership
from django.db import transaction
from ninja.errors import HttpError


def ownership_view(document, *, profile=None, can_edit=False):
    ownership = ElaboratoOwnership.objects.filter(document=document).first()
    if ownership:
        return {
            "state": "assigned", "workspace_id": ownership.workspace_id,
            "workspace_name": ownership.assignment_snapshot["workspace_name"],
            "basis": ownership.basis, "assigned_at": ownership.assigned_at.isoformat(),
            "can_confirm": False,
        }
    can_confirm = bool(profile and can_edit and document.created_by_id == profile.pk)
    return {
        "state": "unassigned", "workspace_id": None, "workspace_name": None,
        "basis": None, "assigned_at": None, "can_confirm": can_confirm,
        "confirmation_workspace_name": profile.workspace.name if can_confirm else None,
        "confirmation_workspace_id": profile.workspace_id if can_confirm else None,
    }


@transaction.atomic
def confirm_legacy(*, profile, revision_id, version, confirmed, reason):
    from django.utils import timezone
    from . import services
    from .models import Elaborato, DocumentAudit

    type(profile).objects.select_for_update().get(pk=profile.pk)
    revision = services.get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    document = Elaborato.objects.select_for_update().get(pk=revision.elaborato_id)
    if document.created_by_id != profile.pk:
        raise HttpError(403, "Solo l’autore originario può confermare l’azienda. I casi diversi richiedono una verifica amministrativa.")
    if not confirmed or len(reason.strip()) < 12:
        raise HttpError(400, "Conferma l’attribuzione e indica una motivazione di almeno 12 caratteri.")
    prior = ElaboratoOwnership.objects.filter(document=document).first()
    if prior:
        if prior.workspace_id == profile.workspace_id:
            return revision
        raise HttpError(409, "L’elaborato ha già un’azienda attribuita. Non è possibile sostituirla qui.")
    if revision.version != version:
        raise HttpError(409, "La revisione è cambiata. Riaprila prima di confermare l’azienda.")
    ElaboratoOwnership.objects.create(
        document=document, workspace=profile.workspace, assigned_by=profile,
        assigned_at=timezone.now(), basis="author_confirmation",
        assignment_snapshot={
            "schema_version": 1, "basis": "author_confirmation", "workspace_id": profile.workspace_id,
            "workspace_name": profile.workspace.name, "actor_profile_id": profile.pk,
            "actor_user_id": profile.user_id, "reason": reason.strip(),
            "revision_id": str(revision.pk), "revision_version": version,
        },
    )
    DocumentAudit.objects.create(revision=revision, actor=profile, action="ownership.confirmed",
        detail={"workspace_id": profile.workspace_id, "basis": "author_confirmation"})
    return revision


def record_creation(*, document, profile):
    # The caller has locked the authenticated profile and project and owns the
    # creation transaction. Never take this identity from the request payload.
    return ElaboratoOwnership.objects.create(
        document=document, workspace_id=profile.workspace_id, assigned_by=profile,
        assigned_at=document.created_at, basis="creation",
        assignment_snapshot={
            "schema_version": 1, "basis": "creation", "workspace_id": profile.workspace_id,
            "workspace_name": profile.workspace.name,
            "actor_profile_id": profile.pk, "actor_user_id": profile.user_id,
        },
    )
