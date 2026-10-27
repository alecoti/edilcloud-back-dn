"""Organization boundary, independent of (and additional to) project roles.

Legacy documents stay quarantined to their exact creator until attribution.
Sharing grants are deliberately not inferred from project membership.
"""

from django.db.models import Exists, F, OuterRef, Q
from ninja.errors import HttpError

from .models import Elaborato, ElaboratoRevision


def organization_documents(*, profile, queryset=None):
    queryset = Elaborato.objects.all() if queryset is None else queryset
    # Workers can hold an old Profile instance: recheck activation in the DB.
    if (
        not type(profile)
        .objects.filter(
            pk=profile.pk,
            workspace_id=profile.workspace_id,
            is_active=True,
            workspace__is_active=True,
            user__is_active=True,
        )
        .exists()
    ):
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
        elaborato__project_id=OuterRef("project_id"),
        state__in=("published", "signed", "superseded"),
        drive_document__project_id=F("elaborato__project_id"),
    )
    return queryset.alias(
        _elaborato_linked=Exists(linked),
        _elaborato_visible=Exists(visible),
    ).filter(
        (Q(_elaborato_linked=False) & ~Q(document__startswith="elaborati/publications/"))
        | Q(_elaborato_visible=True)
    )


def delivery_revisions(*, profile):
    """Issued revisions available to an active project member, for delivery too."""
    from edilcloud.modules.projects.models import ProjectMember, ProjectMemberStatus

    memberships = ProjectMember.objects.filter(
        profile=profile,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
    ).values("project_id")
    return ElaboratoRevision.objects.filter(
        elaborato__in=organization_documents(profile=profile),
        elaborato__project_id__in=memberships,
        state__in=("published", "signed", "superseded"),
        drive_document__project_id=F("elaborato__project_id"),
    )


def publication_recipients(*, revision, candidates):
    from edilcloud.modules.workspaces.models import Profile

    if not candidates:
        return []
    owner = getattr(revision.elaborato, "ownership", None)
    queryset = Profile.objects.filter(
        pk__in=[profile.pk for profile in candidates],
        is_active=True,
        user__is_active=True,
        workspace__is_active=True,
        project_memberships__project_id=revision.elaborato.project_id,
        project_memberships__status=1,
        project_memberships__disabled=False,
    )
    queryset = (
        queryset.filter(workspace_id=owner.workspace_id)
        if owner
        else queryset.filter(pk=revision.elaborato.created_by_id)
    )
    ids = set(queryset.values_list("pk", flat=True))
    return [profile for profile in candidates if profile.pk in ids]


def publication_group(revision):
    project = revision.elaborato.project_id
    owner = getattr(revision.elaborato, "ownership", None)
    if owner:
        return f"projects.{project}.workspace.{owner.workspace_id}"
    creator = revision.elaborato.created_by_id
    return f"projects.{project}.profile.{creator}" if creator else None


def require_drive_scope(*, profile, document_id):
    from edilcloud.modules.projects.models import ProjectDocument

    if not visible_drive_documents(
        profile=profile,
        queryset=ProjectDocument.objects.filter(pk=document_id),
    ).exists():
        # Project file handlers map ValueError to 404, without exposing metadata.
        raise ValueError("Documento non trovato.")
