from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from edilcloud.modules.assistant.models import (
    ProjectAssistantGraphSnapshot,
    ProjectAssistantState,
    ProjectAssistantWikiPage,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostComment,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)


def mark_project_assistant_states_dirty(project_id: int | None, *, ensure_state: bool = True) -> None:
    if not project_id:
        return

    def mark_after_commit() -> None:
        from edilcloud.modules.assistant.services import (
            assistant_rag_enabled,
            get_or_create_project_assistant_state,
        )

        should_schedule_sync = assistant_rag_enabled()
        updated_count = ProjectAssistantState.objects.filter(project_id=project_id).update(
            is_dirty=True,
            background_sync_scheduled=should_schedule_sync,
        )
        if ensure_state and updated_count == 0:
            project = Project.objects.filter(id=project_id).first()
            if project is not None:
                state = get_or_create_project_assistant_state(project)
                state.is_dirty = True
                state.background_sync_scheduled = should_schedule_sync
                state.save(update_fields=["is_dirty", "background_sync_scheduled"])
        ProjectAssistantWikiPage.objects.filter(project_id=project_id).update(is_stale=True)
        ProjectAssistantGraphSnapshot.objects.filter(project_id=project_id).update(is_stale=True)

    transaction.on_commit(mark_after_commit)


@receiver(post_save, sender=Project)
@receiver(post_delete, sender=Project)
def project_dirty_handler(sender, instance: Project, **kwargs):
    mark_project_assistant_states_dirty(instance.id, ensure_state=kwargs.get("signal") is post_save)


@receiver(post_save, sender=ProjectMember)
@receiver(post_delete, sender=ProjectMember)
def project_member_dirty_handler(sender, instance: ProjectMember, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=ProjectFolder)
@receiver(post_delete, sender=ProjectFolder)
def project_folder_dirty_handler(sender, instance: ProjectFolder, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=ProjectDocument)
@receiver(post_delete, sender=ProjectDocument)
def project_document_dirty_handler(sender, instance: ProjectDocument, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=ProjectPhoto)
@receiver(post_delete, sender=ProjectPhoto)
def project_photo_dirty_handler(sender, instance: ProjectPhoto, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=ProjectTask)
@receiver(post_delete, sender=ProjectTask)
def project_task_dirty_handler(sender, instance: ProjectTask, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=ProjectActivity)
@receiver(post_delete, sender=ProjectActivity)
def project_activity_dirty_handler(sender, instance: ProjectActivity, **kwargs):
    mark_project_assistant_states_dirty(instance.task.project_id)


@receiver(m2m_changed, sender=ProjectActivity.workers.through)
def project_activity_workers_dirty_handler(sender, instance: ProjectActivity, action: str, **kwargs):
    if action in {"post_add", "post_remove", "post_clear"}:
        mark_project_assistant_states_dirty(instance.task.project_id)


@receiver(post_save, sender=ProjectPost)
@receiver(post_delete, sender=ProjectPost)
def project_post_dirty_handler(sender, instance: ProjectPost, **kwargs):
    mark_project_assistant_states_dirty(instance.project_id)


@receiver(post_save, sender=PostAttachment)
@receiver(post_delete, sender=PostAttachment)
def post_attachment_dirty_handler(sender, instance: PostAttachment, **kwargs):
    mark_project_assistant_states_dirty(instance.post.project_id)


@receiver(post_save, sender=PostComment)
@receiver(post_delete, sender=PostComment)
def post_comment_dirty_handler(sender, instance: PostComment, **kwargs):
    mark_project_assistant_states_dirty(instance.post.project_id)


@receiver(post_save, sender=CommentAttachment)
@receiver(post_delete, sender=CommentAttachment)
def comment_attachment_dirty_handler(sender, instance: CommentAttachment, **kwargs):
    mark_project_assistant_states_dirty(instance.comment.post.project_id)
