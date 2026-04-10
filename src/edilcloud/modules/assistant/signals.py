from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from edilcloud.modules.assistant.models import ProjectAssistantState
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


def mark_project_assistant_states_dirty(project_id: int | None) -> None:
    if not project_id:
        return
    ProjectAssistantState.objects.filter(project_id=project_id).update(
        is_dirty=True,
        background_sync_scheduled=True,
    )


@receiver(post_save, sender=Project)
@receiver(post_delete, sender=Project)
def project_dirty_handler(sender, instance: Project, **kwargs):
    mark_project_assistant_states_dirty(instance.id)


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
