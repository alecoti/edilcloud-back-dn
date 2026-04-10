import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone

from edilcloud.modules.projects.models import (
    PostComment,
    PostKind,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.projects.services import get_current_profile, project_access_queryset


SECTION_KEYS = (
    "projects",
    "tasks",
    "activities",
    "updates",
    "documents",
    "drawings",
    "people",
)

SECTION_BASE_SCORES = {
    "projects": 12.0,
    "tasks": 11.0,
    "activities": 10.0,
    "updates": 10.5,
    "documents": 10.5,
    "drawings": 9.0,
    "people": 8.5,
}

KIND_BASE_SCORES = {
    "project": 4.0,
    "task": 4.5,
    "activity": 4.0,
    "post": 3.5,
    "comment": 3.0,
    "issue_open": 6.0,
    "issue_resolved": 3.0,
    "document": 4.5,
    "drawing": 3.5,
    "person": 2.5,
}


def empty_sections() -> dict[str, list[dict]]:
    return {section: [] for section in SECTION_KEYS}


def normalize_category(value: str | None) -> str:
    if value in SECTION_KEYS:
        return value
    return "all"


def active_sections(category: str) -> tuple[str, ...]:
    if category == "all":
        return SECTION_KEYS
    return (category,)


def normalize_text(value: str | None) -> str:
    ascii_value = unicodedata.normalize("NFKD", value or "")
    ascii_value = ascii_value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value).strip().lower()


def split_query_tokens(value: str) -> list[str]:
    return [token for token in normalize_text(value).split(" ") if token]


def build_token_filter(tokens: list[str], fields: tuple[str, ...]) -> Q:
    query = Q()
    for token in tokens:
        token_query = Q()
        for field in fields:
            token_query |= Q(**{f"{field}__icontains": token})
        query &= token_query
    return query


def to_timestamp(value) -> float:
    if isinstance(value, datetime):
        aware = value
    elif isinstance(value, date):
        aware = datetime.combine(value, datetime.min.time(), tzinfo=timezone.get_current_timezone())
    else:
        return 0.0
    if timezone.is_naive(aware):
        aware = timezone.make_aware(aware, timezone.get_current_timezone())
    return aware.timestamp()


def format_date(value) -> str:
    if isinstance(value, datetime):
        value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return "Senza data"


def compact_text(value: str | None, limit: int = 84) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)].rstrip()}…"


def extract_match_snippet(value: str | None, *, tokens: list[str], limit: int = 132) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    if not tokens:
        return compact_text(text, limit)

    lowered = text.lower()
    token_positions = [lowered.find(token.lower()) for token in tokens if token]
    valid_positions = [position for position in token_positions if position >= 0]
    if not valid_positions:
        return compact_text(text, limit)

    first_hit = min(valid_positions)
    start = max(0, first_hit - 36)
    end = min(len(text), start + limit)
    if end - start < limit and start > 0:
        start = max(0, end - limit)

    snippet = text[start:end].strip()
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(text):
        snippet = f"{snippet}…"
    return snippet


def build_item_snippet(
    *sources: str | None,
    tokens: list[str],
    fallback: str | None = None,
    limit: int = 132,
) -> str | None:
    seen: set[str] = set()
    for source in sources:
        normalized = re.sub(r"\s+", " ", (source or "").strip())
        if not normalized:
            continue
        normalized_key = normalize_text(normalized)
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        snippet = extract_match_snippet(normalized, tokens=tokens, limit=limit)
        if snippet:
            return snippet

    fallback_text = compact_text(fallback, limit)
    return fallback_text or None


def build_project_path(project_id: int, tab_slug: str, **params) -> str:
    normalized = {key: value for key, value in params.items() if value not in (None, "", 0)}
    query = urlencode(normalized)
    base = f"/dashboard/cantieri/{project_id}/{tab_slug}"
    return f"{base}?{query}" if query else base


def build_project_actions(project_id: int) -> list[dict]:
    return [
        {
            "id": "project_overview",
            "href": build_project_path(project_id, "overview"),
            "label": "Dashboard",
            "external": False,
        },
        {
            "id": "project_drawings",
            "href": build_project_path(project_id, "drawings"),
            "label": "Planimetrie",
            "external": False,
        },
        {
            "id": "project_gantt",
            "href": build_project_path(project_id, "gantt"),
            "label": "Cronoprogramma",
            "external": False,
        },
    ]


def build_task_thread_path(project_id: int, activity_id: int | None = None, post_id: int | None = None, comment_id: int | None = None) -> str:
    return build_project_path(
        project_id,
        "tasks",
        activity=activity_id,
        post=post_id,
        comment=comment_id,
    )


def make_item(
    *,
    item_id: str,
    kind: str,
    section: str,
    title: str,
    subtitle: str,
    href: str,
    actions: list[dict],
    search_text: str,
    timestamp,
    snippet: str | None = None,
    external: bool = False,
) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "section": section,
        "title": title,
        "subtitle": subtitle,
        "snippet": snippet,
        "href": href,
        "external": external,
        "actions": actions,
        "_search_text": normalize_text(search_text),
        "_title_text": normalize_text(title),
        "_subtitle_text": normalize_text(subtitle),
        "_snippet_text": normalize_text(snippet),
        "_timestamp": to_timestamp(timestamp),
    }


def score_item(tokens: list[str], item: dict) -> float | None:
    title_text = item["_title_text"]
    subtitle_text = item["_subtitle_text"]
    snippet_text = item["_snippet_text"]
    search_text = item["_search_text"]
    section_weight = SECTION_BASE_SCORES.get(item["section"], 0.0)
    kind_weight = KIND_BASE_SCORES.get(item["kind"], 0.0)

    if not tokens:
        return item["_timestamp"] + section_weight + kind_weight

    full_query = " ".join(tokens)
    score = section_weight + kind_weight

    for token in tokens:
        if title_text.startswith(token):
            score += 52
            continue
        if re.search(rf"\b{re.escape(token)}", title_text):
            score += 40
            continue
        if token in title_text:
            score += 28
            continue
        if token in subtitle_text:
            score += 16
            continue
        if token in snippet_text:
            score += 13
            continue
        if token in search_text:
            score += 8
            continue
        return None

    if full_query:
        if title_text == full_query:
            score += 120
        elif title_text.startswith(full_query):
            score += 92
        elif full_query in title_text:
            score += 68
        elif full_query in subtitle_text:
            score += 34
        elif full_query in snippet_text:
            score += 28
        elif full_query in search_text:
            score += 20

    score += sum(search_text.count(token) for token in tokens) * 1.4

    score += min(item["_timestamp"] / 100000000000.0, 25.0)
    return score


def finalize_sections(items: list[dict], *, query: str, limit_per_section: int, category: str) -> dict:
    sections = empty_sections()
    allowed = set(active_sections(category))
    tokens = split_query_tokens(query)

    scored_items = []
    for item in items:
        if item["section"] not in allowed:
            continue
        score = score_item(tokens, item)
        if score is None:
            continue
        scored_items.append((score, item))

    scored_items.sort(key=lambda entry: (entry[0], entry[1]["_timestamp"]), reverse=True)

    for _, item in scored_items:
        target = sections[item["section"]]
        if len(target) >= limit_per_section:
            continue
        target.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "title": item["title"],
                "subtitle": item["subtitle"],
                "snippet": item["snippet"],
                "href": item["href"],
                "external": item["external"],
                "actions": item["actions"],
            }
        )

    total = sum(len(entries) for entries in sections.values())
    return {
        "query": query.strip(),
        "sections": sections,
        "total": total,
    }


def search_workspace_index(*, user, claims: dict, query: str, limit_per_section: int = 6, category: str = "all") -> dict:
    profile = get_current_profile(user=user, claims=claims)
    normalized_category = normalize_category(category)
    bounded_limit = max(1, min(limit_per_section, 12))
    raw_tokens = [token for token in query.strip().split() if token]
    allowed = set(active_sections(normalized_category))
    scan_limit = max(bounded_limit * 4, 16)

    project_queryset = project_access_queryset(profile)
    project_ids = list(project_queryset.values_list("id", flat=True))

    if not project_ids:
        return {
            "query": query.strip(),
            "sections": empty_sections(),
            "total": 0,
        }

    items: list[dict] = []

    if "projects" in allowed:
        projects = project_queryset
        if raw_tokens:
            projects = projects.filter(build_token_filter(raw_tokens, ("name", "description", "address")))
        for project in projects.order_by("-updated_at", "-id")[:scan_limit]:
            items.append(
                make_item(
                    item_id=f"project:{project.id}",
                    kind="project",
                    section="projects",
                    title=project.name,
                    subtitle=" • ".join(
                        filter(
                            None,
                            [
                                project.address.strip() if project.address else "Indirizzo non disponibile",
                                project.workspace.name if project.workspace_id else "",
                            ],
                        )
                    ),
                    href=build_project_path(project.id, "overview"),
                    actions=build_project_actions(project.id),
                    search_text=" ".join([project.name, project.description, project.address, project.workspace.name]),
                    timestamp=project.updated_at or project.created_at,
                    snippet=build_item_snippet(
                        project.description,
                        project.address,
                        tokens=raw_tokens,
                        fallback=project.description or project.address,
                    ),
                )
            )

    if "tasks" in allowed:
        tasks = ProjectTask.objects.select_related("project", "assigned_company").filter(project_id__in=project_ids)
        if raw_tokens:
            tasks = tasks.filter(
                build_token_filter(raw_tokens, ("name", "note", "project__name", "assigned_company__name"))
            )
        for task in tasks.order_by("-updated_at", "-id")[:scan_limit]:
            first_activity_id = (
                ProjectActivity.objects.filter(task=task).order_by("datetime_start", "id").values_list("id", flat=True).first()
            )
            status_bits = []
            if task.alert:
                status_bits.append("Critica")
            elif task.progress >= 100:
                status_bits.append("Completata")
            else:
                status_bits.append(f"Avanzamento {task.progress}%")
            if task.assigned_company_id:
                status_bits.append(task.assigned_company.name)
            items.append(
                make_item(
                    item_id=f"task:{task.id}",
                    kind="task",
                    section="tasks",
                    title=task.name,
                    subtitle=" • ".join([task.project.name, *status_bits]),
                    href=build_task_thread_path(task.project_id, first_activity_id),
                    actions=[
                        {
                            "id": "task_thread",
                            "href": build_task_thread_path(task.project_id, first_activity_id),
                            "label": "Task",
                            "external": False,
                        },
                        {
                            "id": "task_gantt",
                            "href": build_project_path(task.project_id, "gantt"),
                            "label": "Cronoprogramma",
                            "external": False,
                        },
                    ],
                    search_text=" ".join(
                        filter(None, [task.name, task.note, task.project.name, task.assigned_company.name if task.assigned_company_id else ""])
                    ),
                    timestamp=task.updated_at or task.created_at,
                    snippet=build_item_snippet(
                        task.note,
                        " ".join(status_bits),
                        tokens=raw_tokens,
                        fallback=task.note,
                    ),
                )
            )

    if "activities" in allowed:
        activities = ProjectActivity.objects.select_related("task", "task__project").filter(
            task__project_id__in=project_ids
        )
        if raw_tokens:
            activities = activities.filter(
                build_token_filter(raw_tokens, ("title", "description", "note", "task__name", "task__project__name"))
            )
        for activity in activities.order_by("-updated_at", "-id")[:scan_limit]:
            items.append(
                make_item(
                    item_id=f"activity:{activity.id}",
                    kind="activity",
                    section="activities",
                    title=activity.title or "Attività",
                    subtitle=" • ".join(
                        filter(
                            None,
                            [
                                activity.task.project.name,
                                activity.task.name,
                                format_date(activity.datetime_start),
                            ],
                        )
                    ),
                    href=build_task_thread_path(activity.task.project_id, activity.id),
                    actions=[
                        {
                            "id": "task_thread",
                            "href": build_task_thread_path(activity.task.project_id, activity.id),
                            "label": "Attività",
                            "external": False,
                        },
                        {
                            "id": "task_drawings",
                            "href": build_project_path(activity.task.project_id, "drawings", activity=activity.id),
                            "label": "Planimetrie",
                            "external": False,
                        },
                    ],
                    search_text=" ".join(
                        [activity.title, activity.description, activity.note, activity.task.name, activity.task.project.name]
                    ),
                    timestamp=activity.updated_at or activity.created_at,
                    snippet=build_item_snippet(
                        activity.description,
                        activity.note,
                        tokens=raw_tokens,
                        fallback=activity.description or activity.note,
                    ),
                )
            )

    if "updates" in allowed:
        posts = ProjectPost.objects.select_related(
            "project",
            "task",
            "activity",
            "author",
            "author__workspace",
        ).filter(project_id__in=project_ids, is_deleted=False)
        if raw_tokens:
            posts = posts.filter(
                build_token_filter(
                    raw_tokens,
                    ("text", "original_text", "task__name", "activity__title", "project__name", "author__first_name", "author__last_name"),
                )
            )
        for post in posts.order_by("-published_date", "-id")[:scan_limit]:
            activity_id = post.activity_id
            kind = "post"
            if post.post_kind == PostKind.ISSUE:
                kind = "issue_open" if post.alert else "issue_resolved"
            author_name = post.author.member_name
            title = compact_text(post.text or post.original_text or "Aggiornamento", 84) or "Aggiornamento"
            items.append(
                make_item(
                    item_id=f"post:{post.id}",
                    kind=kind,
                    section="updates",
                    title=title,
                    subtitle=" • ".join(
                        filter(
                            None,
                            [
                                post.project.name,
                                f"Post di {author_name}",
                                post.activity.title if post.activity_id else post.task.name if post.task_id else "",
                            ],
                        )
                    ),
                    href=build_task_thread_path(post.project_id, activity_id, post.id),
                    actions=[
                        {
                            "id": "task_thread",
                            "href": build_task_thread_path(post.project_id, activity_id, post.id),
                            "label": "Discussione",
                            "external": False,
                        }
                    ]
                    + (
                        [
                            {
                                "id": "task_drawings",
                                "href": build_project_path(post.project_id, "drawings", activity=activity_id),
                                "label": "Planimetrie",
                                "external": False,
                            }
                        ]
                        if activity_id
                        else []
                    ),
                    search_text=" ".join(
                        filter(
                            None,
                            [
                                post.text,
                                post.original_text,
                                post.project.name,
                                post.task.name if post.task_id else "",
                                post.activity.title if post.activity_id else "",
                                author_name,
                            ],
                        )
                    ),
                    timestamp=post.published_date or post.updated_at or post.created_at,
                    snippet=build_item_snippet(
                        post.text,
                        post.original_text,
                        post.activity.title if post.activity_id else None,
                        post.task.name if post.task_id else None,
                        tokens=raw_tokens,
                        fallback=post.text or post.original_text,
                    ),
                )
            )

        comments = PostComment.objects.select_related(
            "post",
            "post__project",
            "post__task",
            "post__activity",
            "author",
            "author__workspace",
        ).filter(post__project_id__in=project_ids, is_deleted=False)
        if raw_tokens:
            comments = comments.filter(
                build_token_filter(
                    raw_tokens,
                    (
                        "text",
                        "original_text",
                        "post__project__name",
                        "post__task__name",
                        "post__activity__title",
                        "author__first_name",
                        "author__last_name",
                    ),
                )
            )
        for comment in comments.order_by("-updated_at", "-id")[:scan_limit]:
            activity_id = comment.post.activity_id
            author_name = comment.author.member_name
            title = compact_text(comment.text or comment.original_text or "Commento", 84) or "Commento"
            items.append(
                make_item(
                    item_id=f"comment:{comment.id}",
                    kind="comment",
                    section="updates",
                    title=title,
                    subtitle=" • ".join(
                        filter(
                            None,
                            [
                                comment.post.project.name,
                                f"Commento di {author_name}",
                                comment.post.activity.title if comment.post.activity_id else comment.post.task.name if comment.post.task_id else "",
                            ],
                        )
                    ),
                    href=build_task_thread_path(comment.post.project_id, activity_id, comment.post_id, comment.id),
                    actions=[
                        {
                            "id": "task_thread",
                            "href": build_task_thread_path(comment.post.project_id, activity_id, comment.post_id, comment.id),
                            "label": "Discussione",
                            "external": False,
                        }
                    ]
                    + (
                        [
                            {
                                "id": "task_drawings",
                                "href": build_project_path(comment.post.project_id, "drawings", activity=activity_id),
                                "label": "Planimetrie",
                                "external": False,
                            }
                        ]
                        if activity_id
                        else []
                    ),
                    search_text=" ".join(
                        filter(
                            None,
                            [
                                comment.text,
                                comment.original_text,
                                author_name,
                                comment.post.project.name,
                                comment.post.task.name if comment.post.task_id else "",
                                comment.post.activity.title if comment.post.activity_id else "",
                            ],
                        )
                    ),
                    timestamp=comment.updated_at or comment.created_at,
                    snippet=build_item_snippet(
                        comment.text,
                        comment.original_text,
                        comment.post.text,
                        tokens=raw_tokens,
                        fallback=comment.text or comment.original_text,
                    ),
                )
            )

    if "documents" in allowed:
        documents = ProjectDocument.objects.select_related("project", "folder").filter(project_id__in=project_ids)
        if raw_tokens:
            documents = documents.filter(
                build_token_filter(raw_tokens, ("title", "description", "folder__name", "project__name", "document"))
            )
        for document in documents.order_by("-updated_at", "-id")[:scan_limit]:
            file_name = Path(document.document.name).name if document.document.name else ""
            subtitle = " • ".join(
                filter(
                    None,
                    [
                        document.project.name,
                        document.folder.path if document.folder_id else "",
                        f"Aggiornato {format_date(document.updated_at or document.created_at)}",
                    ],
                )
            )
            items.append(
                make_item(
                    item_id=f"document:{document.id}",
                    kind="document",
                    section="documents",
                    title=document.title or file_name or "Documento",
                    subtitle=subtitle,
                    href=build_project_path(document.project_id, "documents", doc=document.id),
                    actions=[
                        {
                            "id": "project_documents",
                            "href": build_project_path(document.project_id, "documents", doc=document.id),
                            "label": "Archivio documenti",
                            "external": False,
                        }
                    ],
                    search_text=" ".join(
                        filter(None, [document.title, document.description, file_name, document.project.name, document.folder.path if document.folder_id else ""])
                    ),
                    timestamp=document.updated_at or document.created_at,
                    snippet=build_item_snippet(
                        document.description,
                        file_name,
                        document.folder.path if document.folder_id else None,
                        tokens=raw_tokens,
                        fallback=document.description or file_name,
                    ),
                )
            )

    if "drawings" in allowed:
        photos = ProjectPhoto.objects.select_related("project").filter(project_id__in=project_ids)
        if raw_tokens:
            photos = photos.filter(build_token_filter(raw_tokens, ("title", "project__name", "photo")))
        for photo in photos.order_by("-updated_at", "-id")[:scan_limit]:
            file_name = Path(photo.photo.name).name if photo.photo.name else ""
            items.append(
                make_item(
                    item_id=f"drawing:{photo.id}",
                    kind="drawing",
                    section="drawings",
                    title=photo.title or file_name or "Disegno",
                    subtitle=" • ".join(
                        filter(
                            None,
                            [
                                photo.project.name,
                                f"Aggiornato {format_date(photo.updated_at or photo.created_at)}",
                            ],
                        )
                    ),
                    href=build_project_path(photo.project_id, "drawings"),
                    actions=[
                        {
                            "id": "project_drawings",
                            "href": build_project_path(photo.project_id, "drawings"),
                            "label": "Apri disegni",
                            "external": False,
                        }
                    ],
                    search_text=" ".join(filter(None, [photo.title, file_name, photo.project.name])),
                    timestamp=photo.updated_at or photo.created_at,
                    snippet=build_item_snippet(
                        photo.title,
                        file_name,
                        tokens=raw_tokens,
                        fallback=file_name,
                    ),
                )
            )

    if "people" in allowed:
        members = ProjectMember.objects.select_related(
            "project",
            "profile",
            "profile__workspace",
        ).filter(
            project_id__in=project_ids,
            status=ProjectMemberStatus.ACTIVE,
            disabled=False,
        )
        if raw_tokens:
            members = members.filter(
                build_token_filter(
                    raw_tokens,
                    (
                        "project__name",
                        "profile__first_name",
                        "profile__last_name",
                        "profile__email",
                        "profile__phone",
                        "profile__position",
                        "profile__workspace__name",
                    ),
                )
            )
        for member in members.order_by("-updated_at", "-id")[:scan_limit]:
            person_name = member.profile.member_name
            position = member.profile.position or member.profile.workspace.name or "Membro team"
            items.append(
                make_item(
                    item_id=f"person:{member.project_id}:{member.profile_id}",
                    kind="person",
                    section="people",
                    title=person_name,
                    subtitle=" • ".join(filter(None, [position, member.project.name])),
                    href=build_project_path(member.project_id, "team"),
                    actions=[
                        {
                            "id": "project_team",
                            "href": build_project_path(member.project_id, "team"),
                            "label": "Apri team",
                            "external": False,
                        }
                    ],
                    search_text=" ".join(
                        filter(
                            None,
                            [
                                person_name,
                                member.profile.email,
                                member.profile.phone,
                                member.profile.position,
                                member.profile.workspace.name,
                                member.project.name,
                            ],
                        )
                    ),
                    timestamp=member.updated_at or member.created_at,
                    snippet=build_item_snippet(
                        member.profile.position,
                        member.profile.workspace.name,
                        member.profile.email,
                        member.profile.phone,
                        tokens=raw_tokens,
                        fallback=member.profile.position or member.profile.workspace.name,
                    ),
                )
            )

    return finalize_sections(
        items,
        query=query,
        limit_per_section=bounded_limit,
        category=normalized_category,
    )
