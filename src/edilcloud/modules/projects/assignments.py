"""Company-scoped staffing, shared by Gantt and phase detail."""
from django.db import transaction
from django.db.models import Q
from ninja.errors import HttpError

from edilcloud.modules.projects.models import ProjectMember, ProjectMemberStatus, ProjectTask
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole

ADMIN_ROLES = (WorkspaceRole.OWNER, WorkspaceRole.DELEGATE)


def can_assign_company(profile, project):
    return profile.is_active and profile.workspace_id == project.workspace_id and profile.role in ADMIN_ROLES


def can_assign_people(profile, task):
    return bool(profile.is_active and task.assigned_company_id and profile.workspace_id == task.assigned_company_id and profile.role in ADMIN_ROLES)


def eligible_companies(project):
    return Workspace.objects.filter(is_active=True).filter(
        Q(id=project.workspace_id) | Q(profiles__project_memberships__project=project,
            profiles__project_memberships__status=ProjectMemberStatus.ACTIVE,
            profiles__project_memberships__disabled=False, profiles__is_active=True)
    ).distinct().order_by("name", "id")


def validate_company(profile, project, company_id):
    if not can_assign_company(profile, project):
        raise HttpError(403, "Solo owner e delegate dell'impresa proprietaria possono assegnare l'impresa.")
    if company_id is None:
        return None
    company = eligible_companies(project).filter(id=company_id).first()
    if company is None:
        raise HttpError(400, "Seleziona un'impresa attiva nel progetto.")
    return company


def active_company_profiles(company_id):
    return Profile.objects.select_related("workspace", "user").filter(
        workspace_id=company_id, is_active=True, workspace__is_active=True,
    ).filter(Q(user__isnull=True) | Q(user__is_active=True))


def ensure_member(project, target, actor):
    from edilcloud.modules.projects import services as s
    member, created = ProjectMember.objects.get_or_create(project=project, profile=target, defaults={
        # Workspace authority does not grant project-wide administration.
        "role": target.role if target.workspace_id == project.workspace_id else WorkspaceRole.WORKER,
        "status": ProjectMemberStatus.ACTIVE, "is_external": target.workspace_id != project.workspace_id,
    })
    if member.disabled or member.status == ProjectMemberStatus.REFUSED:
        raise HttpError(403, "Una persona selezionata è stata disabilitata o rimossa dal progetto.")
    joined = created or member.status != ProjectMemberStatus.ACTIVE
    if member.status != ProjectMemberStatus.ACTIVE:
        member.status = ProjectMemberStatus.ACTIVE
        member.save(update_fields=["status", "updated_at"])
    if joined:
        from edilcloud.modules.notifications.catalog import build_project_member_added_notification
        s.emit_project_realtime_event(event_type="team.member.added", project_id=project.id,
            actor_profile=actor, data={"category": "team", "member_name": s.profile_display_name(target)})
        s.create_project_notification_from_blueprint(recipient_profile=target, actor_profile=actor,
            blueprint=build_project_member_added_notification(project=project, member=member,
                target_profile=target, actor_profile=actor, role_label=s.project_role_label(member.role)))
    return member


def company_changed(task, actor, *, notify=True):
    """Never carry staff from the previous company across a reassignment."""
    from edilcloud.modules.projects import services as s
    from edilcloud.modules.notifications.catalog import build_project_task_notification
    task.workers.clear()
    for activity in task.activities.all():
        activity.workers.clear()
        activity.inherit_workers = True
        activity.save(update_fields=["inherit_workers", "updated_at"])
    if not task.assigned_company_id:
        return
    admins = list(active_company_profiles(task.assigned_company_id).filter(role__in=ADMIN_ROLES))
    recipients = []
    for admin in admins:
        existing = ProjectMember.objects.filter(project=task.project, profile=admin).first()
        if existing and (existing.disabled or existing.status == ProjectMemberStatus.REFUSED):
            continue
        ensure_member(task.project, admin, actor)
        if admin.id != actor.id:
            recipients.append(admin)
    if recipients and notify:
        s.notify_profiles_with_blueprint(recipients=recipients, actor_profile=actor,
            blueprint=build_project_task_notification(task=task, actor_profile=actor, action="updated", audience="assigned"))


def assignment_state(*, profile, task_id, activity_id=None, query=""):
    from edilcloud.modules.projects import services as s
    task = ProjectTask.objects.select_related("project", "assigned_company").filter(id=task_id).first()
    if task is None:
        raise HttpError(404, "Fase non trovata.")
    try:
        s.get_project_membership(task.project, profile)
    except ValueError as exc:
        raise HttpError(403, str(exc)) from exc
    activity = None
    if activity_id is not None:
        activity = task.activities.filter(id=activity_id).first()
        if activity is None:
            raise HttpError(404, "Sottofase non trovata nella fase.")
    people_allowed = can_assign_people(profile, task)
    people = []
    if people_allowed:
        candidates = active_company_profiles(task.assigned_company_id)
        if query.strip():
            # Match each term across names, email and position, like post mentions.
            for term in query.strip().split()[:8]:
                candidates = candidates.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term)
                    | Q(email__icontains=term) | Q(position__icontains=term)
                    | Q(user__first_name__icontains=term) | Q(user__last_name__icontains=term))
        memberships = {m.profile_id: m for m in ProjectMember.objects.filter(project=task.project)}
        for person in candidates.order_by("first_name", "last_name", "id")[:100]:
            member = memberships.get(person.id)
            if member and (member.disabled or member.status == ProjectMemberStatus.REFUSED):
                continue
            people.append({"profile": s.serialize_project_profile(person),
                "in_project": bool(member and member.status == ProjectMemberStatus.ACTIVE)})
        people.sort(key=lambda item: not item["in_project"])
    workers = (activity.workers if activity else task.workers).select_related("workspace", "user")
    return {"task_id": task.id, "activity_id": activity.id if activity else None,
        "assigned_company": s.serialize_project_company(task.assigned_company),
        "companies": [s.serialize_project_company(c) for c in eligible_companies(task.project)] if can_assign_company(profile, task.project) else [],
        "can_assign_company": can_assign_company(profile, task.project) and activity is None,
        "can_assign_people": people_allowed,
        "disabled_reason": "Assegna prima l'impresa alla fase." if not task.assigned_company_id else
            "Solo owner e delegate dell'impresa assegnata possono gestire le persone." if not people_allowed else "",
        "inherit_workers": activity.inherit_workers if activity else False,
        "phase_workers": [s.serialize_project_profile(worker) for worker in task.workers.select_related("workspace", "user")],
        "workers": [s.serialize_project_profile(worker) for worker in workers], "people": people}


@transaction.atomic
def update_assignment(*, profile, task_id, activity_id=None, company_id=None, set_company=False,
                      worker_ids=None, inherit_workers=None):
    from edilcloud.modules.projects import services as s
    # Parent lock serializes phase updates with per-activity overrides.
    task = ProjectTask.objects.select_for_update(of=("self",)).select_related("project", "assigned_company").filter(id=task_id).first()
    if task is None:
        raise HttpError(404, "Fase non trovata.")
    s.get_project_membership(task.project, profile)
    if set_company:
        if activity_id is not None:
            raise HttpError(400, "L'impresa si assegna alla fase e viene ereditata dalle sottofasi.")
        company = validate_company(profile, task.project, company_id)
        if task.assigned_company_id != company_id:
            task.assigned_company = company
            task.save(update_fields=["assigned_company", "updated_at"])
            company_changed(task, profile)
    if worker_ids is not None or inherit_workers is not None:
        if not can_assign_people(profile, task):
            raise HttpError(403, "Solo owner e delegate dell'impresa assegnata possono gestire le persone.")
        activity = task.activities.select_for_update().filter(id=activity_id).first() if activity_id is not None else None
        if activity_id is not None and activity is None:
            raise HttpError(404, "Sottofase non trovata nella fase.")
        if inherit_workers and activity is None:
            raise HttpError(400, "Solo una sottofase può ereditare le persone.")
        ids = sorted(set(worker_ids or []))
        if inherit_workers:
            ids = list(task.workers.values_list("id", flat=True))
        selected = list(active_company_profiles(task.assigned_company_id).filter(id__in=ids))
        if len(selected) != len(ids):
            raise HttpError(400, "Puoi assegnare soltanto persone attive dell'impresa assegnata.")
        for person in selected:
            ensure_member(task.project, person, profile)
        target = activity or task
        previous = set(target.workers.values_list("id", flat=True))
        target.workers.set(selected)
        if activity:
            activity.inherit_workers = bool(inherit_workers)
            activity.save(update_fields=["inherit_workers", "updated_at"])
        else:
            for child in task.activities.filter(inherit_workers=True):
                child.workers.set(selected)
        from edilcloud.modules.notifications.catalog import build_project_activity_notification, build_project_task_notification
        new_people = [p for p in selected if p.id not in previous and p.id != profile.id]
        if new_people:
            blueprint = build_project_activity_notification(activity=activity, actor_profile=profile,
                action="updated", audience="assigned") if activity else build_project_task_notification(
                    task=task, actor_profile=profile, action="updated", audience="assigned")
            s.notify_profiles_with_blueprint(recipients=new_people, actor_profile=profile, blueprint=blueprint)
    s.emit_project_realtime_event(event_type="task.updated", project_id=task.project_id,
        actor_profile=profile, task_id=task.id, activity_id=activity_id,
        data={"category": "task", "task_name": task.name, "assignment_changed": True})
    return assignment_state(profile=profile, task_id=task.id, activity_id=activity_id)
