"""Organization boundary, independent of (and additional to) project roles.

Legacy documents stay quarantined to their exact creator until attribution.
Sharing grants are deliberately not inferred from project membership.
"""
from django.db.models import Exists, OuterRef, Q
from ninja.errors import HttpError

from .models import Elaborato, ElaboratoRevision


def organization_documents(*, profile, queryset=None):
    queryset = Elaborato.objects.all() if queryset is None else queryset
    # Workers can hold an old Profile instance: recheck activation in the DB.
    if not type(profile).objects.filter(
        pk=profile.pk, workspace_id=profile.workspace_id,
        is_active=True, workspace__is_active=True, user__is_active=True,
    ).exists():
        return queryset.none()
    return queryset.filter(
        Q(ownership__workspace_id=profile.workspace_id)
        | Q(ownership__isnull=True, created_by_id=profile.pk)
    )


def require_document_scope(*, profile, document_id):
    if not organization_documents(profile=profile).filter(pk=document_id).exists():
        raise HttpError(404, "Elaborato non trovato o non accessibile.")


def visible_drive_documents(*, profile, queryset):
    linked = ElaboratoRevision.objects.filter(drive_document_id=OuterRef("pk"))
    visible = linked.filter(
        elaborato__in=organization_documents(profile=profile),
        state__in=("published", "signed", "superseded"),
    )
    return queryset.alias(
        _elaborato_linked=Exists(linked), _elaborato_visible=Exists(visible),
    ).filter(Q(_elaborato_linked=False) | Q(_elaborato_visible=True))


def require_drive_scope(*, profile, document_id):
    from edilcloud.modules.projects.models import ProjectDocument

    if not visible_drive_documents(
        profile=profile, queryset=ProjectDocument.objects.filter(pk=document_id),
    ).exists():
        # Project file handlers map ValueError to 404, without exposing metadata.
        raise ValueError("Documento non trovato.")
