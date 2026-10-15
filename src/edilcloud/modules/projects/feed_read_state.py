"""Authoritative unread counts and versioned, monotone read receipts."""

from datetime import datetime
import uuid

from django.db import transaction
from django.db.models import Case, Count, DateTimeField, F, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Greatest
from django.utils import timezone

from edilcloud.modules.projects.models import PostComment, ProjectPost, ProjectPostSeenState
from edilcloud.platform.realtime.services import publish_notification_event


def readable_feed_posts(profile):
    from edilcloud.modules.projects.services import project_access_queryset

    comments = PostComment.objects.filter(post_id=OuterRef("pk")).order_by("-updated_at", "-id")
    seen = ProjectPostSeenState.objects.filter(post_id=OuterRef("pk"), profile=profile)
    return ProjectPost.objects.filter(
        project_id__in=project_access_queryset(profile).filter(workspace__is_active=True).values("id"),
        is_deleted=False,
    ).annotate(
        latest_comment_activity=Subquery(comments.values("updated_at")[:1]),
        viewer_seen_at=Subquery(seen.values("seen_at")[:1]),
    ).annotate(
        effective_last_activity_at=Case(
            When(latest_comment_activity__gt=F("updated_at"), then=F("latest_comment_activity")),
            default=F("updated_at"), output_field=DateTimeField(),
        ),
    )


def feed_unread_counts(profile) -> dict:
    counts = {
        str(row["project_id"]): row["total"]
        for row in readable_feed_posts(profile).filter(
            Q(viewer_seen_at__isnull=True) | Q(viewer_seen_at__lt=F("effective_last_activity_at"))
        ).order_by().values("project_id").annotate(total=Count("pk"))
    }
    return {"unread_count": sum(counts.values()), "unread_by_project": counts}


@transaction.atomic
def record_feed_receipts(*, profile, post_ids=None, receipts=None) -> dict:
    versions: dict[int, datetime | None] = {}
    for value in post_ids or []:
        try:
            post_id = int(value)
        except (TypeError, ValueError):
            continue
        if post_id > 0:
            versions[post_id] = None
    for receipt in receipts or []:
        post_id = int(receipt["post_id"])
        through = receipt["seen_through"]
        if timezone.is_naive(through):
            raise ValueError("La versione visualizzata deve includere il fuso orario.")
        previous = versions.get(post_id)
        versions[post_id] = max(previous, through) if previous is not None else through
    if len(versions) > 250:
        raise ValueError("Massimo 250 ricevute per richiesta.")

    posts = list(readable_feed_posts(profile).filter(id__in=versions))
    order = {post_id: index for index, post_id in enumerate(versions)}
    posts.sort(key=lambda post: order[post.id])
    observed = {post.id: min(versions[post.id] or post.effective_last_activity_at, post.effective_last_activity_at) for post in posts}
    if posts:
        ProjectPostSeenState.objects.bulk_create([
            ProjectPostSeenState(post_id=post.id, profile=profile, seen_at=observed[post.id]) for post in posts
        ], ignore_conflicts=True)
        through = Case(*[When(post_id=post_id, then=Value(timestamp)) for post_id, timestamp in observed.items()], output_field=DateTimeField())
        ProjectPostSeenState.objects.filter(profile=profile, post_id__in=observed).update(
            seen_at=Greatest(F("seen_at"), through), updated_at=timezone.now(),
        )
    states = dict(ProjectPostSeenState.objects.filter(profile=profile, post_id__in=observed).values_list("post_id", "seen_at"))
    items = [{"post_id": post.id, "seen_at": states[post.id].isoformat(), "is_unread": states[post.id] < post.effective_last_activity_at} for post in posts]
    result = {"count": len(items), "items": items, **feed_unread_counts(profile)}
    if items:
        payload = {
            "eventId": str(uuid.uuid4()), "type": "feed.seen", "channel": "feed",
            "timestamp": timezone.now().isoformat(), "profileId": profile.id,
            "data": result,
        }
        transaction.on_commit(lambda: publish_notification_event(profile_id=profile.id, payload=payload))
    return result
