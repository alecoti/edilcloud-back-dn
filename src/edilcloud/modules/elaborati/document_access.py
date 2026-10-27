"""Document ACL for normalized querysets, before pagination and counts.

Input fields/aliases: project_id, document_id, content_type, object_id, data, kind.
The same predicate protects notifications, operational history and exports.
"""

from django.db.models import (
    BigIntegerField,
    Case,
    CharField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Lower, Replace

UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def visible_document_records(queryset, *, profile):
    from edilcloud.modules.elaborati.models import ElaboratoRevision
    from edilcloud.modules.elaborati.visibility import delivery_revisions
    from edilcloud.modules.projects.models import ProjectDocument
    from edilcloud.modules.projects.models import ProjectMember, ProjectMemberStatus

    queryset = queryset.alias(
        _notice_document_id=Coalesce(
            "document_id",
            Case(
                When(content_type="document", then=F("object_id")),
                default=Value(None),
                output_field=BigIntegerField(),
            ),
            output_field=BigIntegerField(),
        ),
        _notice_revision_key=Lower(
            Replace(KeyTextTransform("elaborato_revision_id", "data"), Value("-"), Value(""))
        ),
    )
    documents = ProjectDocument.objects.filter(pk=OuterRef("_notice_document_id"))
    queryset = queryset.alias(
        _notice_project_id=Coalesce(
            "project_id",
            Subquery(documents.values("project_id")[:1]),
            output_field=BigIntegerField(),
        )
    )
    linked = ElaboratoRevision.objects.filter(drive_document_id=OuterRef("_notice_document_id"))
    visible = delivery_revisions(profile=profile).filter(
        drive_document_id=OuterRef("_notice_document_id"),
        elaborato__project_id=OuterRef("_notice_project_id"),
    )
    marked = visible.alias(
        _revision_key=Lower(Replace(Cast("pk", CharField()), Value("-"), Value("")))
    ).filter(
        _revision_key=OuterRef("_notice_revision_key"),
    )
    ordinary = documents.filter(project_id=OuterRef("_notice_project_id")).exclude(
        document__startswith="elaborati/publications/",
    )
    members = ProjectMember.objects.filter(
        project_id=OuterRef("project_id"),
        profile=profile,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        profile__is_active=True,
        profile__workspace__is_active=True,
        profile__user__is_active=True,
    )
    queryset = queryset.alias(
        _notice_linked=Exists(linked),
        _notice_visible=Exists(visible),
        _notice_marked_visible=Exists(marked),
        _notice_ordinary=Exists(ordinary),
        _notice_member=Exists(members),
        _notice_target_exists=Exists(documents),
    )
    tagged = Q(data__has_key="elaborato_revision_id")
    document_notice = (
        Q(document_id__isnull=False)
        | Q(content_type="document")
        | Q(kind__startswith="project.document.")
    )
    ordinary_deleted = Q(
        kind="project.document.deleted",
        data__document_origin="ordinary_upload",
        _notice_member=True,
        _notice_target_exists=False,
        _notice_document_id__gt=0,
    )
    return queryset.filter(
        (
            tagged
            & Q(data__elaborato_revision_id__regex=UUID_PATTERN)
            & Q(_notice_marked_visible=True)
        )
        | (~tagged & Q(_notice_linked=True, _notice_visible=True))
        | (
            ~tagged
            & Q(_notice_linked=False)
            & (~document_notice | Q(_notice_ordinary=True) | ordinary_deleted)
        )
    )
