"""Personal project preferences. They never change access to the Feed itself."""
from .models import ProjectMember, ProjectMemberStatus

DEFAULT_NOTIFICATION_PREFERENCES = {
    "enabled": True, "push": True, "posts": True, "comments": True,
    "mentions": True, "issues": True, "tasks": True, "documents": True, "team": True,
}


def resolved_notification_preferences(member):
    return {**DEFAULT_NOTIFICATION_PREFERENCES, **{
        key: value for key, value in (member.notification_preferences or {}).items()
        if key in DEFAULT_NOTIFICATION_PREFERENCES and isinstance(value, bool)
    }}


def notification_category(kind):
    if kind.startswith("project.mention."): return "mentions"
    if kind.startswith("project.issue."): return "issues"
    if kind.startswith("project.comment."): return "comments"
    if kind.startswith("project.post."): return "posts"
    if kind.startswith(("project.task.", "project.activity.", "project.schedule.")): return "tasks"
    if kind.startswith(("project.document.", "project.folder.")): return "documents"
    return "team"


def project_notification_allowed(*, profile, project_id, kind, push=False):
    if kind == "project.invite.created":
        return True  # The invitation must be available before membership exists.
    member = ProjectMember.objects.filter(project_id=project_id, profile=profile,
        status=ProjectMemberStatus.ACTIVE, disabled=False, profile__is_active=True,
        profile__workspace__is_active=True).first()
    if member is None:
        return False
    if member.project.is_demo_master and profile.demo_project_hidden:
        return False
    preferences = resolved_notification_preferences(member)
    return preferences["enabled"] and preferences[notification_category(kind)] and (not push or preferences["push"])
