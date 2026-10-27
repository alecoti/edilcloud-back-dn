"""Normalize historical event targets without casting untrusted JSON to IDs."""
from django.db.models import BigIntegerField, CharField, Exists, F, JSONField, OuterRef, Q, Subquery, Value
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, Coalesce, Concat

from edilcloud.modules.elaborati.document_access import visible_document_records
from .models import ProjectDocument, ProjectMember


def visible_operational_events(queryset, *, profile):
    members = ProjectMember.objects.filter(
        project_id=OuterRef("project_id"), profile_id=profile.pk, status=1, disabled=False,
        profile__is_active=True, profile__workspace__is_active=True, profile__user__is_active=True,
        profile__workspace_id=profile.workspace_id,
    )
    queryset = queryset.alias(
        _event_member=Exists(members),
        _event_document_text=KeyTextTransform("documentId", "payload"),
        _event_project_text=KeyTextTransform("projectId", "payload"),
        _event_project_key=Cast("project_id", CharField()),
    ).filter(_event_member=True)
    targets = ProjectDocument.objects.alias(_event_target_key=Cast("pk", CharField())).filter(
        _event_target_key=OuterRef("_event_document_text")
    )
    queryset = queryset.alias(
        document_id=Coalesce(
            F("document_id_snapshot"), Subquery(targets.values("pk")[:1]),
            output_field=BigIntegerField(),
        ),
        content_type=Value("", output_field=CharField()),
        object_id=Cast(Value(None), BigIntegerField()),
        data=Coalesce(KeyTransform("data", "payload"), Value({}, output_field=JSONField())),
        kind=Concat(Value("project."), F("event_type")),
    ).alias(_event_resolved_document_text=Cast("document_id", CharField()))
    # A payload may carry historical IDs, but may not contradict the snapshot.
    queryset = queryset.filter(
        ~Q(payload__has_key="documentId")
        | Q(payload__documentId=None)
        | Q(_event_document_text=F("_event_resolved_document_text"))
    )
    queryset = queryset.filter(
        ~Q(payload__has_key="projectId") | Q(payload__projectId=None)
        | Q(_event_project_text=F("_event_project_key"))
    )
    return visible_document_records(queryset, profile=profile)
