"""Bounded background translation; HTTP reads never wait for the provider.

Redis leases deduplicate across web processes. A missed/dropped job is retried
on a subsequent read after lease expiry; no request queues unbounded work.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
from threading import BoundedSemaphore

from django.core.cache import cache
from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edilcloud-translation")
_slots = BoundedSemaphore(8)


def enqueue_translation(*, kind, entity_id, target_language, source_signature):
    transaction.on_commit(lambda: _enqueue(kind=kind, entity_id=entity_id,
        target_language=target_language, source_signature=source_signature))


def _enqueue(*, kind, entity_id, target_language, source_signature):
    lease = "content-translation-job:" + hashlib.sha256(
        f"{kind}:{entity_id}:{target_language}:{source_signature}".encode()
    ).hexdigest()
    if not _slots.acquire(blocking=False):
        return
    try:
        if not cache.add(lease, True, timeout=600):
            _slots.release()
            return
    except Exception:
        _slots.release()
        logger.exception("translation.enqueue.cache_unavailable")
        return

    def dispatch():
        try:
            _executor.submit(_run, lease, kind, entity_id, target_language, source_signature)
        except Exception:
            cache.delete(lease)
            _slots.release()
            logger.exception("translation.enqueue.failed")

    dispatch()


def _run(lease, kind, entity_id, target_language, source_signature):
    from edilcloud.modules.projects import services as s
    from edilcloud.modules.projects.models import ProjectPost, PostComment

    close_old_connections()
    failed = False
    try:
        model = ProjectPost if kind == "post" else PostComment
        entity = model.objects.filter(pk=entity_id, is_deleted=False).first()
        if entity is None:
            return
        text = s.project_content_source_text(text=entity.text, original_text=entity.original_text)
        language = s.project_content_source_language(source_language=entity.source_language, display_language=entity.display_language)
        if s.build_project_content_translation_signature(source_text=text, source_language=language) != source_signature:
            return
        # Identical content shared between posts/comments reuses the same result.
        content_key = f"content-translation-result:{source_signature}:{target_language}"
        text_lease = content_key + ":lock"
        translated = cache.get(content_key)
        if translated is None:
            if not cache.add(text_lease, True, timeout=120):
                return
            try:
                translated = s.generate_project_content_translation(source_text=text, source_language=language, target_language=target_language)
                cache.set(content_key, translated, timeout=86400)
            finally:
                cache.delete(text_lease)
        # Serialize against edits/deletes: an old job cannot store stale text.
        with transaction.atomic():
            current = model.objects.select_for_update().filter(pk=entity_id, is_deleted=False).first()
            if current is None:
                return
            current_text = s.project_content_source_text(text=current.text, original_text=current.original_text)
            current_language = s.project_content_source_language(source_language=current.source_language, display_language=current.display_language)
            if s.build_project_content_translation_signature(source_text=current_text, source_language=current_language) != source_signature:
                return
            save = s.upsert_post_translation_memory if kind == "post" else s.upsert_comment_translation_memory
            save(**{kind: current}, target_language=target_language, translated_text=translated,
                 source_language=language, source_signature=source_signature)
        post = current if kind == "post" else current.post
        s.emit_feed_refresh_for_post(post=post, actor_profile=None, action="translation.ready")
        s.publish_project_event(project_id=post.project_id, payload=s.build_project_realtime_event(
            project_id=post.project_id, actor_profile=None, event_type="post.updated",
            task_id=post.task_id, activity_id=post.activity_id, post_id=post.id,
            data={"action": "translation.ready", "language": target_language}))
    except Exception:
        failed = True
        # Keep a short lease on provider failure, so repeated reads do not storm it.
        cache.set(lease, True, timeout=30)
        logger.exception("translation.job.failed")
    finally:
        try:
            if not failed:
                cache.delete(lease)
        finally:
            close_old_connections()
            _slots.release()
