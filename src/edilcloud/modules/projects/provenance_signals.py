"""Capture identity at registration for writes through existing app/admin APIs."""

from django.db import transaction
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver

from edilcloud.modules.workspaces.models import Profile, Workspace
from .models import (
    ProjectPost,
    PostComment,
    PostAttachment,
    CommentAttachment,
    ProjectDocument,
    ProjectPhoto,
    ProjectDrawingPin,
    ProjectModelPin,
    ProjectModel3D,
    ProjectMember,
)
from .participations import sync_member
from .provenance_models import ProjectParticipation, EvidenceBlob
from .provenance import capture_source, object_context


@receiver(post_delete, sender=EvidenceBlob, dispatch_uid="delete_project_evidence_bytes")
def delete_evidence_bytes(sender, instance, **kwargs):
    # Deleting a post never reaches this hook: evidence belongs to its project.
    # A project/account purge removes the private bytes after DB commit only.
    storage, name = instance.file.storage, instance.file.name
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(post_save, sender=ProjectMember, dispatch_uid="project_participation_capture")
def member_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_member(instance)


@receiver(pre_save, sender=Profile, dispatch_uid="profile_documentary_identity_before")
def before_profile_change(sender, instance, raw=False, update_fields=None, **kwargs):
    instance._documentary_identity_changed = False
    keys = {"workspace_id", "first_name", "last_name", "position"}
    if (
        raw
        or not instance.pk
        or (update_fields and not (keys | {"workspace"}).intersection(update_fields))
    ):
        return
    previous = sender.objects.filter(pk=instance.pk).values(*keys).first()
    instance._documentary_identity_changed = previous and any(
        previous[key] != getattr(instance, key) for key in keys
    )


@receiver(post_save, sender=Profile, dispatch_uid="profile_documentary_identity_after")
def after_profile_change(sender, instance, raw=False, **kwargs):
    if not raw and getattr(instance, "_documentary_identity_changed", False):
        for member in instance.project_memberships.select_related("project", "profile__workspace"):
            sync_member(member)
        instance._documentary_identity_changed = False


@receiver(pre_save, sender=Workspace, dispatch_uid="company_documentary_name_before")
def before_company_change(sender, instance, raw=False, update_fields=None, **kwargs):
    instance._documentary_name_changed = False
    if raw or not instance.pk or (update_fields and "name" not in update_fields):
        return
    previous = sender.objects.filter(pk=instance.pk).values_list("name", flat=True).first()
    instance._documentary_name_changed = previous is not None and previous != instance.name


@receiver(post_save, sender=Workspace, dispatch_uid="company_documentary_name_after")
def after_company_change(sender, instance, raw=False, **kwargs):
    if not raw and getattr(instance, "_documentary_name_changed", False):
        for member in ProjectMember.objects.filter(profile__workspace=instance).select_related(
            "project", "profile__workspace"
        ):
            sync_member(member)
        instance._documentary_name_changed = False


def source_saved(sender, instance, created=False, raw=False, **kwargs):
    if not raw:
        capture_source(instance, reconstructed=not created)


def observe_actor_before_creation(sender, instance, raw=False, **kwargs):
    if raw or not instance._state.adding:
        return
    project, _, profile, _ = object_context(instance)
    if profile:
        member = (
            ProjectMember.objects.filter(project=project, profile=profile)
            .select_related("project", "profile__workspace")
            .first()
        )
        if member:
            sync_member(member)


for model in (
    ProjectPost,
    PostComment,
    PostAttachment,
    CommentAttachment,
    ProjectDocument,
    ProjectPhoto,
    ProjectDrawingPin,
    ProjectModelPin,
    ProjectModel3D,
    ProjectMember,
    ProjectParticipation,
):
    post_save.connect(
        source_saved,
        sender=model,
        weak=False,
        dispatch_uid="source_capture_" + model._meta.model_name,
    )
    if model not in {ProjectMember, ProjectParticipation}:
        pre_save.connect(
            observe_actor_before_creation,
            sender=model,
            weak=False,
            dispatch_uid="source_actor_before_" + model._meta.model_name,
        )
