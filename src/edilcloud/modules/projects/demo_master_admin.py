from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from edilcloud.modules.files.media_optimizer import optimize_media_content
from edilcloud.modules.notifications.models import Notification
from edilcloud.modules.projects.demo_master_assets import DEMO_ASSET_VERSION
from edilcloud.modules.projects.demo_master_snapshot import (
    BACKEND_ROOT,
    DEMO_SNAPSHOT_EXPORT_ROOT,
    DEMO_SNAPSHOT_SCHEMA_VERSION,
    build_demo_snapshot_record,
    normalize_path,
)
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import (
    DEMO_TARGET_PROGRESS,
    DEFAULT_VIEWER_EMAIL,
    DEFAULT_VIEWER_PASSWORD,
    PROJECT_BLUEPRINT,
    Seeder,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    DemoProjectSnapshot,
    DemoProjectSnapshotValidationStatus,
    PostAttachment,
    PostComment,
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectStatus,
    ProjectTask,
    TaskActivityStatus,
)
from edilcloud.modules.projects.services import (
    can_edit_project,
    create_task_post,
    delete_post,
    get_project_for_profile,
    list_project_feed,
    normalize_project_progress,
    project_member_effective_role,
    project_role_label,
)
from edilcloud.modules.workspaces.models import Profile, Workspace


def require_demo_master_superuser(*, user) -> None:
    if not getattr(user, "is_superuser", False):
        raise ValueError("Area riservata ai superuser.")


def get_canonical_demo_master_project_name() -> str:
    return PROJECT_BLUEPRINT["name"]


def get_demo_master_project() -> Project | None:
    return (
        Project.objects.select_related("workspace")
        .filter(name=get_canonical_demo_master_project_name())
        .order_by("-updated_at", "-id")
        .first()
    )


def get_active_demo_master_snapshot() -> DemoProjectSnapshot | None:
    return (
        DemoProjectSnapshot.objects.select_related("created_by", "created_by__workspace")
        .filter(
            name=get_canonical_demo_master_project_name(),
            active_in_production=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def serialize_demo_master_snapshot(snapshot: DemoProjectSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    created_by = snapshot.created_by
    return {
        "id": snapshot.id,
        "version": snapshot.version,
        "name": snapshot.name,
        "business_date": snapshot.business_date,
        "schema_version": snapshot.schema_version,
        "seed_hash": snapshot.seed_hash or None,
        "asset_manifest_hash": snapshot.asset_manifest_hash or None,
        "payload_hash": snapshot.payload_hash or None,
        "validation_status": snapshot.validation_status,
        "validated_at": snapshot.validated_at,
        "active_in_production": snapshot.active_in_production,
        "notes": snapshot.notes or None,
        "export_relative_path": snapshot.export_relative_path or None,
        "created_at": snapshot.created_at,
        "created_by": (
            {
                "id": created_by.id,
                "name": created_by.member_name,
                "email": created_by.email,
                "workspace_name": created_by.workspace.name if created_by.workspace_id else None,
            }
            if created_by is not None
            else None
        ),
    }


def serialize_demo_master_project(project: Project | None) -> dict[str, Any] | None:
    if project is None:
        return None

    task_progress_values = list(project.tasks.values_list("progress", flat=True))
    progress = (
        normalize_project_progress(sum(task_progress_values) / len(task_progress_values))
        if task_progress_values
        else 0
    )

    return {
        "id": project.id,
        "name": project.name,
        "workspace_name": project.workspace.name if project.workspace_id else None,
        "is_demo_master": project.is_demo_master,
        "demo_snapshot_version": project.demo_snapshot_version or None,
        "progress_percentage": progress,
        "task_count": len(task_progress_values),
        "activity_count": ProjectActivity.objects.filter(task__project=project).count(),
        "document_count": project.documents.count(),
        "photo_count": project.photos.count(),
        "post_count": project.posts.filter(is_deleted=False).count(),
        "comment_count": PostComment.objects.filter(post__project=project, is_deleted=False).count(),
        "updated_at": project.updated_at,
    }


def build_demo_master_status_payload() -> dict[str, Any]:
    project_name = get_canonical_demo_master_project_name()
    project = get_demo_master_project()
    recent_snapshots = list(
        DemoProjectSnapshot.objects.select_related("created_by", "created_by__workspace")
        .filter(name=project_name)
        .order_by("-created_at", "-id")[:6]
    )
    active_snapshot = get_active_demo_master_snapshot()
    if active_snapshot is not None and all(item.id != active_snapshot.id for item in recent_snapshots):
        recent_snapshots = [active_snapshot, *recent_snapshots][:6]

    return {
        "canonical_project_name": project_name,
        "asset_version": DEMO_ASSET_VERSION,
        "snapshot_schema_version": DEMO_SNAPSHOT_SCHEMA_VERSION,
        "viewer_email": DEFAULT_VIEWER_EMAIL,
        "project": serialize_demo_master_project(project),
        "active_snapshot": serialize_demo_master_snapshot(active_snapshot),
        "recent_snapshots": [serialize_demo_master_snapshot(snapshot) for snapshot in recent_snapshots],
    }


def get_demo_master_admin_status(*, user) -> dict[str, Any]:
    require_demo_master_superuser(user=user)
    return build_demo_master_status_payload()


def build_demo_master_scenario_metric(label: str, value: Any) -> dict[str, Any]:
    return {
        "label": label,
        "value": "-" if value is None else str(value),
    }


def build_demo_master_scenario_record(
    *,
    scenario_id: str,
    label: str,
    status: str,
    actor: str,
    summary: str,
    prerequisites: list[str],
    expected: list[str],
    observed: list[str],
    notifications_expected: list[str],
    notifications_not_expected: list[str],
    feed_expected: list[str],
    permissions_expected: list[str],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "label": label,
        "status": status,
        "actor": actor,
        "summary": summary,
        "prerequisites": prerequisites,
        "expected": expected,
        "observed": observed,
        "notifications_expected": notifications_expected,
        "notifications_not_expected": notifications_not_expected,
        "feed_expected": feed_expected,
        "permissions_expected": permissions_expected,
        "metrics": metrics,
    }


def summarize_demo_master_scenarios(scenarios: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(scenarios),
        "passed": sum(1 for scenario in scenarios if scenario.get("status") == "pass"),
        "warned": sum(1 for scenario in scenarios if scenario.get("status") == "warn"),
        "failed": sum(1 for scenario in scenarios if scenario.get("status") == "fail"),
    }


def get_demo_master_scenarios_report(*, user) -> dict[str, Any]:
    require_demo_master_superuser(user=user)

    project = get_demo_master_project()
    if project is None:
        raise ValueError(
            f'Progetto demo "{get_canonical_demo_master_project_name()}" non trovato. Esegui prima il seed canonico.'
        )

    active_snapshot = get_active_demo_master_snapshot()
    progress = serialize_demo_master_project(project).get("progress_percentage", 0)  # type: ignore[union-attr]

    members = list(
        ProjectMember.objects.select_related("profile", "profile__workspace")
        .filter(project=project, status=ProjectMemberStatus.ACTIVE, disabled=False)
        .order_by("id")
    )
    posts_qs = ProjectPost.objects.filter(project=project, is_deleted=False)
    comments_qs = PostComment.objects.filter(post__project=project, is_deleted=False)

    task_count = ProjectTask.objects.filter(project=project).count()
    activity_count = ProjectActivity.objects.filter(task__project=project).count()
    document_count = ProjectDocument.objects.filter(project=project).count()
    photo_count = ProjectPhoto.objects.filter(project=project).count()
    folder_count = ProjectFolder.objects.filter(project=project).count()
    post_count = posts_qs.count()
    comment_count = comments_qs.count()
    post_attachment_count = PostAttachment.objects.filter(post__project=project).count()
    comment_attachment_count = CommentAttachment.objects.filter(comment__post__project=project).count()
    documentation_post_count = posts_qs.filter(post_kind=PostKind.DOCUMENTATION).count()
    open_issue_count = posts_qs.filter(post_kind=PostKind.ISSUE, alert=True).count()
    resolved_issue_count = posts_qs.filter(post_kind=PostKind.ISSUE, alert=False).count()
    mentioned_post_count = posts_qs.filter(text__contains="@").count()
    mentioned_comment_count = comments_qs.filter(text__contains="@").count()
    mention_total = mentioned_post_count + mentioned_comment_count
    mention_thread_ids = set(posts_qs.filter(text__contains="@").values_list("id", flat=True))
    mention_thread_ids.update(comments_qs.filter(text__contains="@").values_list("post_id", flat=True))
    mention_thread_count = len(mention_thread_ids)

    active_member_count = len(members)
    distinct_workspace_ids = {
        member.profile.workspace_id
        for member in members
        if member.profile_id and member.profile.workspace_id is not None
    }
    external_member_count = sum(1 for member in members if member.is_external)
    members_with_role_codes = sum(1 for member in members if member.project_role_codes)
    role_code_set = {
        code
        for member in members
        for code in (member.project_role_codes or [])
        if isinstance(code, str) and code.strip()
    }
    required_role_codes = [
        "committente",
        "responsabile_lavori",
        "cse",
        "csp",
        "datore_lavoro",
        "preposto",
        "lavoratore",
    ]
    missing_role_codes = [code for code in required_role_codes if code not in role_code_set]

    open_issue_posts = list(
        ProjectPost.objects.select_related("author", "author__workspace")
        .prefetch_related("comments__author__workspace")
        .filter(project=project, post_kind=PostKind.ISSUE, alert=True, is_deleted=False)
        .order_by("id")
    )
    mature_open_issue_threads = 0
    cross_workspace_issue_threads = 0
    open_issue_comment_count = 0
    for post in open_issue_posts:
        thread_comments = [comment for comment in post.comments.all() if not comment.is_deleted]
        open_issue_comment_count += len(thread_comments)
        participant_workspaces = {
            post.author.workspace_id
        }
        participant_workspaces.update(
            comment.author.workspace_id
            for comment in thread_comments
            if comment.author_id and comment.author.workspace_id is not None
        )
        if len(participant_workspaces) >= 2:
            cross_workspace_issue_threads += 1
        if len(thread_comments) >= 4 and len(participant_workspaces) >= 2:
            mature_open_issue_threads += 1

    total_attachment_count = post_attachment_count + comment_attachment_count

    issue_triage_status = (
        "pass"
        if open_issue_count >= 2 and mature_open_issue_threads >= 2 and open_issue_comment_count >= 10
        else ("warn" if open_issue_count >= 1 else "fail")
    )
    mention_loop_status = (
        "pass"
        if mention_total >= 12 and mention_thread_count >= 6 and mentioned_comment_count >= 8
        else ("warn" if mention_total >= 4 else "fail")
    )
    document_flow_status = (
        "pass"
        if document_count >= 12 and documentation_post_count >= 8 and total_attachment_count >= 10 and folder_count >= 3
        else ("warn" if document_count >= 8 and documentation_post_count >= 3 else "fail")
    )
    permissions_status = (
        "pass"
        if active_member_count >= 20
        and len(distinct_workspace_ids) >= 8
        and external_member_count >= 12
        and members_with_role_codes >= 20
        and not missing_role_codes
        else ("warn" if active_member_count >= 12 and len(distinct_workspace_ids) >= 4 else "fail")
    )

    scenarios = [
        build_demo_master_scenario_record(
            scenario_id="issue-triage",
            label="Triage segnalazioni aperte",
            status=issue_triage_status,
            actor="Direzione lavori + capocantiere",
            summary=(
                "Verifica che il Demo Master abbia thread issue credibili e abbastanza profondi da testare alert, risposte e presa in carico."
            ),
            prerequisites=[
                "Il progetto demo deve esistere e avere il seed canonico attivo.",
                "Devono esserci issue aperte con alert e partecipazione di piu aziende.",
            ],
            expected=[
                "Almeno 2 issue aperte con alert attivo.",
                "Almeno 2 thread issue aperti con 4 o piu commenti.",
                "Coinvolgimento di almeno 2 workspace per thread aperto.",
            ],
            observed=[
                f"Issue aperte trovate: {open_issue_count}.",
                f"Thread issue aperti maturi: {mature_open_issue_threads}.",
                f"Commenti totali sui thread issue aperti: {open_issue_comment_count}.",
                f"Thread issue aperti cross-workspace: {cross_workspace_issue_threads}.",
            ],
            notifications_expected=[
                "Alert su issue aperta.",
                "Risposta su thread gia seguito.",
                "Menzione nel thread quando la decisione viene assegnata.",
            ],
            notifications_not_expected=[
                "Nessuna auto-notifica ridondante per l'autore del messaggio.",
                "Nessun alert generico a chi non appartiene al progetto.",
            ],
            feed_expected=[
                "Presenza di post issue in evidenza nel feed operativo.",
                "Follow-up leggibili con presa in carico e chiusura del punto aperto.",
            ],
            permissions_expected=[
                "DL, impresa affidataria e specialisti coinvolti devono vedere il thread.",
                "Solo membri del progetto devono accedere alla conversazione.",
            ],
            metrics=[
                build_demo_master_scenario_metric("Issue aperte", open_issue_count),
                build_demo_master_scenario_metric("Issue risolte", resolved_issue_count),
                build_demo_master_scenario_metric("Thread maturi", mature_open_issue_threads),
                build_demo_master_scenario_metric("Commenti issue aperte", open_issue_comment_count),
            ],
        ),
        build_demo_master_scenario_record(
            scenario_id="mention-loop",
            label="Loop menzioni e risposte",
            status=mention_loop_status,
            actor="Referenti impresa + stakeholder chiamati in causa",
            summary=(
                "Misura se il Demo Master ha abbastanza menzioni operative per testare notifiche puntuali, handoff e rientro nel thread."
            ),
            prerequisites=[
                "I testi di post e commenti devono contenere richiami espliciti a persone del team.",
                "Le menzioni devono comparire in piu thread e non in un unico punto isolato.",
            ],
            expected=[
                "Almeno 12 menzioni complessive tra post e commenti.",
                "Almeno 6 thread con una menzione esplicita.",
                "Le menzioni devono stare soprattutto nei commenti di coordinamento.",
            ],
            observed=[
                f"Menzioni nei post: {mentioned_post_count}.",
                f"Menzioni nei commenti: {mentioned_comment_count}.",
                f"Thread con menzioni: {mention_thread_count}.",
            ],
            notifications_expected=[
                "Notifica di menzione diretta.",
                "Notifica di risposta nel thread dopo la menzione.",
                "Segnale di rientro nel thread per chi e stato chiamato in causa.",
            ],
            notifications_not_expected=[
                "Nessuna menzione a utenti esterni al progetto.",
                "Nessuna notifica multipla per lo stesso evento senza nuovo contenuto.",
            ],
            feed_expected=[
                "Il feed deve far emergere thread con handoff chiari e richieste puntuali.",
                "I thread menzionati devono avere un seguito leggibile.",
            ],
            permissions_expected=[
                "Le persone menzionate devono gia appartenere al progetto o al relativo workspace coinvolto.",
            ],
            metrics=[
                build_demo_master_scenario_metric("Menzioni totali", mention_total),
                build_demo_master_scenario_metric("Menzioni nei post", mentioned_post_count),
                build_demo_master_scenario_metric("Menzioni nei commenti", mentioned_comment_count),
                build_demo_master_scenario_metric("Thread con menzioni", mention_thread_count),
            ],
        ),
        build_demo_master_scenario_record(
            scenario_id="document-revision",
            label="Revisione documenti e allegati",
            status=document_flow_status,
            actor="DL + impresa + specialisti",
            summary=(
                "Controlla se il master ha materiale sufficiente per simulare upload, revisione, commento e chiusura di un documento tecnico."
            ),
            prerequisites=[
                "Devono esserci cartelle, documenti reali e media collegabili ai thread.",
                "Le discussioni documentali devono emergere anche nel feed.",
            ],
            expected=[
                "Almeno 12 documenti tecnici nel progetto.",
                "Almeno 8 post di tipo documentazione.",
                "Almeno 10 allegati complessivi tra post e commenti.",
                "Struttura cartelle con almeno 3 nodi utili.",
            ],
            observed=[
                f"Documenti trovati: {document_count}.",
                f"Post documentazione: {documentation_post_count}.",
                f"Cartelle progetto: {folder_count}.",
                f"Allegati totali post/commenti: {total_attachment_count}.",
                f"Foto e tavole disponibili: {photo_count}.",
            ],
            notifications_expected=[
                "Nuovo documento caricato.",
                "Nuovo commento su documento o thread collegato.",
                "Aggiornamento issue con allegato tecnico di supporto.",
            ],
            notifications_not_expected=[
                "Nessun invio a utenti senza accesso al progetto.",
                "Nessun documento privo di contesto operativo nel feed demo.",
            ],
            feed_expected=[
                "Post documentazione con allegati e risposte coerenti.",
                "Presenza di materiale utile per aprire modali, preview e thread di revisione.",
            ],
            permissions_expected=[
                "I documenti devono restare confinati al team di progetto.",
                "Le cartelle devono poter sostenere test di upload e revisione senza drift.",
            ],
            metrics=[
                build_demo_master_scenario_metric("Documenti", document_count),
                build_demo_master_scenario_metric("Cartelle", folder_count),
                build_demo_master_scenario_metric("Post documentazione", documentation_post_count),
                build_demo_master_scenario_metric("Allegati", total_attachment_count),
                build_demo_master_scenario_metric("Foto/tavole", photo_count),
            ],
        ),
        build_demo_master_scenario_record(
            scenario_id="permissions-matrix",
            label="Matrice permessi e ruoli",
            status=permissions_status,
            actor="Superuser + ruoli progetto",
            summary=(
                "Valuta se il Demo Master copre abbastanza aziende, ruoli e responsabilita per stressare la matrice permessi e la visibilita dei contenuti."
            ),
            prerequisites=[
                "Il progetto deve avere membri interni ed esterni da piu aziende.",
                "I `project_role_codes` devono coprire i profili chiave di cantiere.",
            ],
            expected=[
                "Almeno 20 membri attivi nel progetto.",
                "Almeno 8 workspace rappresentati.",
                "Almeno 12 membri esterni.",
                "Copertura dei ruoli chiave: committente, RL, CSE, CSP, datore lavoro, preposto, lavoratore.",
            ],
            observed=[
                f"Membri attivi: {active_member_count}.",
                f"Workspace coinvolti: {len(distinct_workspace_ids)}.",
                f"Membri esterni: {external_member_count}.",
                f"Membri con role codes: {members_with_role_codes}.",
                (
                    "Ruoli chiave mancanti: nessuno."
                    if not missing_role_codes
                    else f'Ruoli chiave mancanti: {", ".join(missing_role_codes)}.'
                ),
            ],
            notifications_expected=[
                "Notifiche visibili solo a chi ha titolo per vedere il contenuto.",
                "Possibilita di testare differenze tra attori interni, esterni e committente.",
            ],
            notifications_not_expected=[
                "Nessuna esposizione a workspace non coinvolti.",
                "Nessun contenuto operativo mostrato a ruoli senza accesso.",
            ],
            feed_expected=[
                "Autori e partecipanti del feed distribuiti su piu aziende.",
                "Thread utili per leggere il comportamento dei ruoli nel tempo.",
            ],
            permissions_expected=[
                "Il progetto deve sostenere prove su chi vede, chi commenta e chi allega.",
                "La demo deve permettere test realistici tra DL, impresa, specialisti e committente.",
            ],
            metrics=[
                build_demo_master_scenario_metric("Membri attivi", active_member_count),
                build_demo_master_scenario_metric("Workspace", len(distinct_workspace_ids)),
                build_demo_master_scenario_metric("Membri esterni", external_member_count),
                build_demo_master_scenario_metric("Role codes", members_with_role_codes),
                build_demo_master_scenario_metric("Progress target", f"{DEMO_TARGET_PROGRESS}%"),
                build_demo_master_scenario_metric("Progress attuale", f"{progress}%"),
            ],
        ),
    ]

    return {
        "generated_at": timezone.now(),
        "engine_kind": "readiness",
        "project_id": project.id,
        "project_name": project.name,
        "project_progress_percentage": progress,
        "snapshot_version": project.demo_snapshot_version or (active_snapshot.version if active_snapshot else None),
        "summary": summarize_demo_master_scenarios(scenarios),
        "scenarios": scenarios,
    }


def build_demo_master_active_check(
    *,
    check_id: str,
    label: str,
    status: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
    }


def summarize_demo_master_active_checks(checks: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "").strip().lower() for item in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def serialize_demo_master_profile_brief(
    *,
    membership: ProjectMember | None,
    profile: Profile,
) -> dict[str, Any]:
    effective_role = project_member_effective_role(membership) if membership is not None else profile.role
    return {
        "id": profile.id,
        "name": profile.member_name,
        "email": profile.email,
        "workspace_name": profile.workspace.name if profile.workspace_id else None,
        "role_label": project_role_label(effective_role),
    }


def serialize_demo_master_task_brief(task: ProjectTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "assigned_company_name": task.assigned_company.name if task.assigned_company_id else None,
    }


def select_demo_master_mention_scenario_context(
    *,
    project: Project,
) -> tuple[ProjectMember, ProjectMember, ProjectTask, Profile | None]:
    members = [
        ensure_project_member_role_alignment(member)
        for member in ProjectMember.objects.select_related(
            "project",
            "profile",
            "profile__workspace",
            "profile__user",
        )
        .filter(project=project, status=ProjectMemberStatus.ACTIVE, disabled=False, profile__is_active=True)
        .order_by("project_invitation_date", "id")
    ]
    if not members:
        raise ValueError("Nessun membro attivo disponibile per eseguire lo scenario demo.")

    actor_member = next(
        (
            member
            for member in members
            if member.profile_id == project.created_by_id and can_edit_project(member)
        ),
        None,
    )
    if actor_member is None:
        actor_member = next((member for member in members if can_edit_project(member)), None)
    if actor_member is None:
        raise ValueError("Nessun attore con permessi di scrittura disponibile nel Demo Master.")

    tasks = list(
        ProjectTask.objects.select_related("assigned_company")
        .filter(project=project)
        .order_by("date_start", "id")
    )
    if not tasks:
        raise ValueError("Nessuna task disponibile per lo scenario demo.")

    target_member: ProjectMember | None = None
    selected_task: ProjectTask | None = None
    for task in tasks:
        if task.assigned_company_id is None:
            continue
        candidate = next(
            (
                member
                for member in members
                if member.profile_id != actor_member.profile_id
                and member.profile.workspace_id == task.assigned_company_id
            ),
            None,
        )
        if candidate is not None:
            target_member = candidate
            selected_task = task
            break

    if target_member is None:
        target_member = next(
            (
                member
                for member in members
                if member.profile_id != actor_member.profile_id
                and member.profile.workspace_id != actor_member.profile.workspace_id
            ),
            None,
        )
    if target_member is None:
        target_member = next(
            (member for member in members if member.profile_id != actor_member.profile_id),
            None,
        )
    if target_member is None:
        raise ValueError("Nessun destinatario valido disponibile per lo scenario di menzione.")

    if selected_task is None:
        selected_task = next(
            (
                task
                for task in tasks
                if task.assigned_company_id == target_member.profile.workspace_id
            ),
            None,
        ) or tasks[0]

    outsider_profile = (
        Profile.objects.select_related("workspace", "user")
        .filter(email__iexact=DEFAULT_VIEWER_EMAIL, is_active=True, workspace__is_active=True)
        .exclude(
            project_memberships__project=project,
            project_memberships__status=ProjectMemberStatus.ACTIVE,
            project_memberships__disabled=False,
        )
        .first()
    )
    return actor_member, target_member, selected_task, outsider_profile


def run_demo_master_mention_post_scenario(*, user) -> dict[str, Any]:
    require_demo_master_superuser(user=user)

    project = (
        Project.objects.select_related("workspace", "created_by", "created_by__workspace")
        .filter(name=get_canonical_demo_master_project_name())
        .order_by("-updated_at", "-id")
        .first()
    )
    if project is None:
        raise ValueError(
            f'Progetto demo "{get_canonical_demo_master_project_name()}" non trovato. Esegui prima il seed canonico.'
        )

    actor_member, target_member, task, outsider_profile = select_demo_master_mention_scenario_context(
        project=project
    )
    actor_profile = actor_member.profile
    target_profile = target_member.profile

    checks: list[dict[str, Any]] = []
    observations: list[str] = []
    metrics: list[dict[str, Any]] = []
    cleanup_errors: list[str] = []
    cleanup_notes: list[str] = []
    cleanup_status = "completed"

    post_id: int | None = None
    actor_feed_item: dict[str, Any] | None = None
    target_feed_item: dict[str, Any] | None = None
    target_notification: Notification | None = None
    target_notification_count = 0
    generic_notification_count = 0
    actor_notification_count = 0
    total_notification_count = 0
    scenario_stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    text = (
        f"[admin-scenario {scenario_stamp}] @{target_profile.member_name} confermi oggi "
        f"quote posa, verifica finale e finestra operativa per {task.name}?"
    )

    try:
        created_post = create_task_post(
            profile=actor_profile,
            task_id=task.id,
            text=text,
            post_kind=PostKind.WORK_PROGRESS,
            is_public=False,
            alert=False,
            source_language="it",
            mentioned_profile_ids=[target_profile.id],
            target_language="it",
        )
        raw_post_id = created_post.get("id")
        post_id = int(raw_post_id) if str(raw_post_id).isdigit() else None
        if not post_id:
            checks.append(
                build_demo_master_active_check(
                    check_id="post.create",
                    label="Creazione post operativo",
                    status="fail",
                    detail="Il servizio ha risposto senza un post id valido.",
                )
            )
        else:
            checks.append(
                build_demo_master_active_check(
                    check_id="post.create",
                    label="Creazione post operativo",
                    status="pass",
                    detail=f"Post operativo creato sul task '{task.name}' con id {post_id}.",
                )
            )
            observations.append(
                f"Post di test creato da {actor_profile.member_name} con menzione esplicita verso {target_profile.member_name}."
            )

        if post_id:
            notifications = list(
                Notification.objects.select_related("recipient_profile", "recipient_profile__workspace")
                .filter(post_id=post_id)
                .order_by("recipient_profile_id", "id")
            )
            total_notification_count = len(notifications)
            target_notifications = [
                notification
                for notification in notifications
                if notification.recipient_profile_id == target_profile.id
            ]
            target_notification_count = len(target_notifications)
            target_notification = next(
                (
                    notification
                    for notification in target_notifications
                    if notification.kind == "project.mention.post"
                ),
                None,
            )
            generic_notification_count = sum(
                1
                for notification in notifications
                if notification.recipient_profile_id not in {actor_profile.id, target_profile.id}
            )
            actor_notification_count = sum(
                1
                for notification in notifications
                if notification.recipient_profile_id == actor_profile.id
            )

            checks.append(
                build_demo_master_active_check(
                    check_id="notification.mention",
                    label="Notifica di menzione",
                    status="pass" if target_notification is not None else "fail",
                    detail=(
                        f"Notifica '{target_notification.kind}' recapitata a {target_profile.member_name}."
                        if target_notification is not None
                        else f"Nessuna notifica di menzione trovata per {target_profile.member_name}."
                    ),
                )
            )
            checks.append(
                build_demo_master_active_check(
                    check_id="notification.self",
                    label="No self-notification per l'attore",
                    status="pass" if actor_notification_count == 0 else "fail",
                    detail=(
                        "L'attore non ha ricevuto notifiche sul proprio post di test."
                        if actor_notification_count == 0
                        else f"L'attore ha ricevuto {actor_notification_count} notifiche inattese sul post di test."
                    ),
                )
            )

            actor_feed = list_project_feed(
                profile=actor_profile,
                limit=25,
                target_language="it",
            )
            actor_feed_item = next(
                (
                    item
                    for item in actor_feed.get("items") or []
                    if int(item.get("id") or 0) == post_id
                ),
                None,
            )
            checks.append(
                build_demo_master_active_check(
                    check_id="feed.actor",
                    label="Feed autore",
                    status="pass" if actor_feed_item is not None else "fail",
                    detail=(
                        "Il post creato compare nel feed dell'autore."
                        if actor_feed_item is not None
                        else "Il post non compare nel feed dell'autore."
                    ),
                )
            )

            target_feed = list_project_feed(
                profile=target_profile,
                limit=25,
                target_language="it",
            )
            target_feed_item = next(
                (
                    item
                    for item in target_feed.get("items") or []
                    if int(item.get("id") or 0) == post_id
                ),
                None,
            )
            target_feed_unread = bool(target_feed_item and target_feed_item.get("feed_is_unread"))
            checks.append(
                build_demo_master_active_check(
                    check_id="feed.target",
                    label="Feed destinatario menzionato",
                    status="pass" if target_feed_item is not None and target_feed_unread else "fail",
                    detail=(
                        "Il post compare nel feed del destinatario e risulta non letto."
                        if target_feed_item is not None and target_feed_unread
                        else (
                            "Il post compare nel feed del destinatario ma non risulta non letto."
                            if target_feed_item is not None
                            else "Il post non compare nel feed del destinatario menzionato."
                        )
                    ),
                )
            )

            try:
                get_project_for_profile(profile=target_profile, project_id=project.id)
                checks.append(
                    build_demo_master_active_check(
                        check_id="permissions.target",
                        label="Accesso del destinatario",
                        status="pass",
                        detail=f"{target_profile.member_name} ha accesso corretto al progetto.",
                    )
                )
            except ValueError as exc:
                checks.append(
                    build_demo_master_active_check(
                        check_id="permissions.target",
                        label="Accesso del destinatario",
                        status="fail",
                        detail=str(exc),
                    )
                )

            if outsider_profile is None:
                checks.append(
                    build_demo_master_active_check(
                        check_id="permissions.outsider",
                        label="Blocco non membro",
                        status="warn",
                        detail="Profilo outsider demo non disponibile: impossibile verificare il blocco accesso.",
                    )
                )
            else:
                try:
                    get_project_for_profile(profile=outsider_profile, project_id=project.id)
                    checks.append(
                        build_demo_master_active_check(
                            check_id="permissions.outsider",
                            label="Blocco non membro",
                            status="fail",
                            detail=f"{outsider_profile.member_name} riesce ad accedere al progetto pur non essendo membro.",
                        )
                    )
                except ValueError:
                    checks.append(
                        build_demo_master_active_check(
                            check_id="permissions.outsider",
                            label="Blocco non membro",
                            status="pass",
                            detail=f"{outsider_profile.member_name} viene correttamente bloccato fuori dal progetto.",
                        )
                    )

            if target_notification is not None:
                observations.append(
                    f"Notifica recapitata con subject '{target_notification.subject}'."
                )
            if target_feed_item is not None:
                observations.append(
                    "Il destinatario vede il post nel feed operativo con stato non letto."
                )
            if generic_notification_count > 0:
                observations.append(
                    f"Il post ha generato anche {generic_notification_count} notifiche informative verso altri membri del progetto."
                )
    except Exception as exc:
        checks.append(
            build_demo_master_active_check(
                check_id="scenario.execution",
                label="Esecuzione scenario",
                status="fail",
                detail=f"Errore durante l'esecuzione dello scenario: {exc}",
            )
        )
    finally:
        if post_id is not None:
            try:
                delete_post(profile=actor_profile, post_id=post_id)
                cleanup_notes.append("Soft delete del post eseguita.")
            except Exception as exc:
                cleanup_errors.append(f"Soft delete non riuscita: {exc}")

            try:
                deleted_notifications = Notification.objects.filter(post_id=post_id).count()
                Notification.objects.filter(post_id=post_id).delete()
                cleanup_notes.append(f"Notifiche ripulite: {deleted_notifications}.")
            except Exception as exc:
                cleanup_errors.append(f"Pulizia notifiche non riuscita: {exc}")

            try:
                ProjectPost.objects.filter(id=post_id).delete()
                cleanup_notes.append("Post di test rimosso definitivamente.")
            except Exception as exc:
                cleanup_errors.append(f"Hard cleanup post non riuscita: {exc}")

        if cleanup_errors:
            cleanup_status = "partial" if post_id is not None else "failed"
        checks.append(
            build_demo_master_active_check(
                check_id="cleanup",
                label="Cleanup scenario",
                status="pass" if not cleanup_errors else "warn",
                detail=(
                    " | ".join(cleanup_notes) if not cleanup_errors else " | ".join([*cleanup_notes, *cleanup_errors])
                )
                or "Nessun cleanup necessario.",
            )
        )

    metrics = [
        build_demo_master_scenario_metric("Task usata", task.name),
        build_demo_master_scenario_metric("Notifiche totali", total_notification_count),
        build_demo_master_scenario_metric("Notifiche target", target_notification_count),
        build_demo_master_scenario_metric("Notifiche generiche", generic_notification_count),
        build_demo_master_scenario_metric("Self notifications attore", actor_notification_count),
        build_demo_master_scenario_metric(
            "Feed target unread",
            "si" if bool(target_feed_item and target_feed_item.get("feed_is_unread")) else "no",
        ),
    ]

    status = summarize_demo_master_active_checks(checks)
    detail = {
        "pass": "Scenario completato: menzione, feed e visibilita' risultano coerenti.",
        "warn": "Scenario completato con note da rivedere su cleanup o copertura del controllo.",
        "fail": "Scenario fallito: almeno un effetto atteso non si e' verificato correttamente.",
    }[status]

    return {
        "generated_at": timezone.now(),
        "scenario_id": "mention_post",
        "label": "Menzione in post operativo",
        "status": status,
        "detail": detail,
        "cleanup_status": cleanup_status,
        "project_id": project.id,
        "project_name": project.name,
        "snapshot_version": project.demo_snapshot_version or None,
        "actor": serialize_demo_master_profile_brief(membership=actor_member, profile=actor_profile),
        "mentioned_target": serialize_demo_master_profile_brief(
            membership=target_member,
            profile=target_profile,
        ),
        "outsider": (
            serialize_demo_master_profile_brief(membership=None, profile=outsider_profile)
            if outsider_profile is not None
            else None
        ),
        "task": serialize_demo_master_task_brief(task),
        "checks": checks,
        "observations": observations,
        "metrics": metrics,
    }


def run_demo_master_admin_scenario(*, user, scenario_id: str) -> dict[str, Any]:
    require_demo_master_superuser(user=user)
    normalized_scenario_id = (scenario_id or "").strip().lower()
    if normalized_scenario_id == "mention_post":
        return run_demo_master_mention_post_scenario(user=user)
    raise ValueError(f'Scenario "{scenario_id}" non supportato.')


def snapshot_asset_bundle_root(*, version: str) -> Path:
    return DEMO_SNAPSHOT_EXPORT_ROOT / version / "assets"


def iter_snapshot_relative_paths(payload: dict[str, Any]) -> list[str]:
    collected: list[str] = []

    def add(value: Any) -> None:
        normalized = normalize_path(value)
        if not normalized:
            return
        if normalized not in collected:
            collected.append(normalized)

    for item in payload.get("documents") or []:
        if isinstance(item, dict):
            add(item.get("relative_path"))
    for item in payload.get("photos") or []:
        if isinstance(item, dict):
            add(item.get("relative_path"))

    attachments = payload.get("attachments") or {}
    if isinstance(attachments, dict):
        for item in attachments.get("post") or []:
            if isinstance(item, dict):
                add(item.get("relative_path"))
        for item in attachments.get("comment") or []:
            if isinstance(item, dict):
                add(item.get("relative_path"))

    return collected


def export_snapshot_binary_assets(*, snapshot: DemoProjectSnapshot) -> dict[str, Any]:
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    asset_root = snapshot_asset_bundle_root(version=snapshot.version)
    exported = 0
    missing: list[str] = []

    for relative_path in iter_snapshot_relative_paths(payload):
        if not default_storage.exists(relative_path):
            missing.append(relative_path)
            continue
        target_path = asset_root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with default_storage.open(relative_path, "rb") as handle:
            target_path.write_bytes(handle.read())
        exported += 1

    return {
        "exported_count": exported,
        "missing_paths": missing,
    }


def load_snapshot_binary_assets(*, snapshot: DemoProjectSnapshot) -> tuple[dict[str, bytes], list[str]]:
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    asset_root = snapshot_asset_bundle_root(version=snapshot.version)
    binary_map: dict[str, bytes] = {}
    missing: list[str] = []

    for relative_path in iter_snapshot_relative_paths(payload):
        bundle_path = asset_root / relative_path
        if bundle_path.exists():
            binary_map[relative_path] = bundle_path.read_bytes()
            continue
        if default_storage.exists(relative_path):
            with default_storage.open(relative_path, "rb") as handle:
                binary_map[relative_path] = handle.read()
            continue
        missing.append(relative_path)

    return binary_map, missing


def parse_snapshot_date(value: Any, *, fallback: date | None = None) -> date | None:
    if value in {None, ""}:
        return fallback
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return fallback
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            try:
                return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
            except ValueError:
                return fallback
    return fallback


def parse_snapshot_datetime(value: Any, *, fallback: datetime | None = None) -> datetime | None:
    if value in {None, ""}:
        return fallback
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return fallback
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    else:
        return fallback

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def build_profile_lookup(*, profiles: list[Profile]) -> dict[str, dict[Any, Profile]]:
    by_email: dict[str, Profile] = {}
    by_workspace_and_name: dict[tuple[str, str], Profile] = {}
    by_name: dict[str, Profile] = {}

    for profile in profiles:
        email = (profile.email or "").strip().lower()
        if email:
            by_email[email] = profile
        member_name = (profile.member_name or "").strip().lower()
        workspace_name = (profile.workspace.name if profile.workspace_id else "").strip().lower()
        if member_name:
            by_name.setdefault(member_name, profile)
        if workspace_name and member_name:
            by_workspace_and_name[(workspace_name, member_name)] = profile

    return {
        "by_email": by_email,
        "by_workspace_and_name": by_workspace_and_name,
        "by_name": by_name,
    }


def resolve_snapshot_profile(
    lookup: dict[str, dict[Any, Profile]],
    *,
    email: str | None = None,
    workspace_name: str | None = None,
    member_name: str | None = None,
) -> Profile | None:
    normalized_email = (email or "").strip().lower()
    if normalized_email and normalized_email in lookup["by_email"]:
        return lookup["by_email"][normalized_email]

    normalized_workspace = (workspace_name or "").strip().lower()
    normalized_name = (member_name or "").strip().lower()
    if normalized_workspace and normalized_name:
        candidate = lookup["by_workspace_and_name"].get((normalized_workspace, normalized_name))
        if candidate is not None:
            return candidate

    if normalized_name:
        return lookup["by_name"].get(normalized_name)
    return None


def ensure_project_folder_from_path(
    *,
    project: Project,
    folders: dict[str, ProjectFolder],
    raw_path: str | None,
) -> ProjectFolder | None:
    normalized = (raw_path or "").strip().strip("/")
    if not normalized:
        return None
    if normalized in folders:
        return folders[normalized]

    parent = None
    chunks: list[str] = []
    for chunk in [item.strip() for item in normalized.split("/") if item.strip()]:
        chunks.append(chunk)
        current_path = "/".join(chunks)
        if current_path in folders:
            parent = folders[current_path]
            continue
        folder = ProjectFolder.objects.create(
            project=project,
            parent=parent,
            name=chunk,
            path=current_path,
            is_public=False,
            is_root=parent is None,
        )
        folders[current_path] = folder
        parent = folder
    return folders[normalized]

def write_demo_master_snapshot_export(*, snapshot: DemoProjectSnapshot, project_id: int) -> dict[str, Any]:
    DEMO_SNAPSHOT_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    export_path = DEMO_SNAPSHOT_EXPORT_ROOT / f"{snapshot.version}.json"
    export_payload = {
        "snapshot_id": snapshot.id,
        "version": snapshot.version,
        "project_id": project_id,
        "name": snapshot.name,
        "business_date": snapshot.business_date,
        "schema_version": snapshot.schema_version,
        "seed_hash": snapshot.seed_hash,
        "asset_manifest_hash": snapshot.asset_manifest_hash,
        "payload_hash": snapshot.payload_hash,
        "validation_status": snapshot.validation_status,
        "active_in_production": snapshot.active_in_production,
        "created_by_profile_id": snapshot.created_by_id,
        "created_at": snapshot.created_at,
        "validated_at": snapshot.validated_at,
        "notes": snapshot.notes,
        "payload": snapshot.payload,
    }
    export_path.write_text(
        json.dumps(export_payload, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    normalized_export_path = normalize_path(export_path.relative_to(BACKEND_ROOT)) or ""
    snapshot.export_relative_path = normalized_export_path
    snapshot.save(update_fields=["export_relative_path", "updated_at"])
    asset_export = export_snapshot_binary_assets(snapshot=snapshot)
    return {
        "export_relative_path": normalized_export_path,
        "asset_exported_count": asset_export["exported_count"],
        "asset_missing_paths": asset_export["missing_paths"],
    }


@transaction.atomic
def create_demo_master_snapshot(
    *,
    user,
    created_by_profile: Profile | None = None,
    snapshot_version: str | None = None,
    business_date: date | None = None,
    notes: str = "",
    validate: bool = False,
    activate: bool = False,
    write_json: bool = False,
) -> dict[str, Any]:
    require_demo_master_superuser(user=user)

    project = get_demo_master_project()
    if project is None:
        raise ValueError(
            f'Progetto demo "{get_canonical_demo_master_project_name()}" non trovato. Esegui prima il seed canonico.'
        )

    version = snapshot_version or timezone.now().strftime("demo-master-%Y%m%d-%H%M%S")
    effective_business_date = business_date or timezone.localdate()
    validation_status = (
        DemoProjectSnapshotValidationStatus.VALIDATED
        if validate
        else DemoProjectSnapshotValidationStatus.DRAFT
    )
    export_relative_path = ""
    if write_json:
        export_path = DEMO_SNAPSHOT_EXPORT_ROOT / f"{version}.json"
        export_relative_path = normalize_path(export_path.relative_to(BACKEND_ROOT)) or ""

    snapshot_defaults = build_demo_snapshot_record(
        project=project,
        version=version,
        business_date=effective_business_date,
        notes=(notes or "").strip(),
        validation_status=validation_status,
        active_in_production=activate,
        export_relative_path=export_relative_path,
    )
    snapshot, _created = DemoProjectSnapshot.objects.update_or_create(
        name=project.name,
        version=version,
        defaults={
            **snapshot_defaults,
            "project": project,
            "created_by": created_by_profile,
        },
    )

    if activate:
        DemoProjectSnapshot.objects.filter(name=project.name).exclude(id=snapshot.id).update(active_in_production=False)
        project.is_demo_master = True
        project.demo_snapshot_version = snapshot.version
        project.save(update_fields=["is_demo_master", "demo_snapshot_version", "updated_at"])
    elif not project.is_demo_master:
        project.is_demo_master = True
        project.save(update_fields=["is_demo_master", "updated_at"])

    export_meta: dict[str, Any] = {
        "asset_exported_count": 0,
        "asset_missing_paths": [],
    }
    if write_json:
        export_meta = write_demo_master_snapshot_export(snapshot=snapshot, project_id=project.id)

    return {
        "detail": (
            f'Freeze point "{snapshot.version}" salvato correttamente.'
            if not export_meta["asset_missing_paths"]
            else (
                f'Freeze point "{snapshot.version}" salvato con {len(export_meta["asset_missing_paths"])} asset non esportati.'
            )
        ),
        "action": "create_snapshot",
        "snapshot_export": export_meta,
        **build_demo_master_status_payload(),
    }


@transaction.atomic
def restore_demo_master_snapshot(
    *,
    user,
    snapshot_version: str,
    viewer_email: str = DEFAULT_VIEWER_EMAIL,
    viewer_password: str = DEFAULT_VIEWER_PASSWORD,
) -> dict[str, Any]:
    require_demo_master_superuser(user=user)

    normalized_version = (snapshot_version or "").strip()
    if not normalized_version:
        raise ValueError("Versione snapshot obbligatoria.")

    snapshot = (
        DemoProjectSnapshot.objects.select_related(
            "project",
            "project__workspace",
            "project__created_by",
            "created_by",
            "created_by__workspace",
        )
        .filter(
            name=get_canonical_demo_master_project_name(),
            version=normalized_version,
        )
        .first()
    )
    if snapshot is None:
        raise ValueError(f'Snapshot "{normalized_version}" non trovato.')

    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    project_payload = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    binary_assets, missing_assets = load_snapshot_binary_assets(snapshot=snapshot)

    seeder = Seeder(
        viewer_email=viewer_email,
        viewer_password=viewer_password,
    )
    seeder.ensure_viewer_profile()
    seeder.ensure_companies()

    owner_profile = (
        snapshot.project.created_by
        if snapshot.project is not None and snapshot.project.created_by_id
        else seeder.profiles["laura-ferretti"]
    )
    owner_workspace = (
        snapshot.project.workspace
        if snapshot.project is not None and snapshot.project.workspace_id
        else owner_profile.workspace
    )

    seeder.delete_existing_project()

    project = Project.objects.create(
        workspace=owner_workspace,
        created_by=owner_profile,
        name=(project_payload.get("name") or snapshot.name or get_canonical_demo_master_project_name()),
        description=(project_payload.get("description") or ""),
        address=(project_payload.get("address") or ""),
        google_place_id=(project_payload.get("google_place_id") or ""),
        latitude=project_payload.get("latitude"),
        longitude=project_payload.get("longitude"),
        date_start=parse_snapshot_date(project_payload.get("date_start"), fallback=timezone.localdate()) or timezone.localdate(),
        date_end=parse_snapshot_date(project_payload.get("date_end")),
        status=(
            int(project_payload.get("status"))
            if str(project_payload.get("status")).lstrip("-").isdigit()
            else ProjectStatus.ACTIVE
        ),
        is_demo_master=True,
        demo_snapshot_version=snapshot.version,
    )

    project_created_at = parse_snapshot_datetime(snapshot.created_at, fallback=None)
    if project_created_at is not None:
        Project.objects.filter(pk=project.pk).update(created_at=project_created_at, updated_at=timezone.now())

    seeder.project = project
    seeder.ensure_project_workspace_superuser_profiles()

    profile_lookup = build_profile_lookup(
        profiles=list(
            Profile.objects.select_related("workspace", "user").filter(
                id__in={profile.id for profile in [*seeder.profiles.values(), seeder.viewer_profile] if profile is not None}
            )
        )
    )

    membership_items = payload.get("members") if isinstance(payload.get("members"), list) else []
    membership_default_date = parse_snapshot_datetime(
        snapshot.created_at,
        fallback=timezone.make_aware(
            datetime.combine(project.date_start - timedelta(days=10), datetime.min.time().replace(hour=9)),
            timezone.get_current_timezone(),
        ),
    )
    if membership_items:
        for member_item in membership_items:
            if not isinstance(member_item, dict):
                continue
            profile = resolve_snapshot_profile(
                profile_lookup,
                email=member_item.get("email"),
                workspace_name=member_item.get("workspace"),
                member_name=member_item.get("name"),
            )
            if profile is None:
                raise ValueError(
                    f'Impossibile risolvere il membro snapshot "{member_item.get("name") or member_item.get("email") or "sconosciuto"}".'
                )
            member = ProjectMember.objects.create(
                project=project,
                profile=profile,
                role=(member_item.get("role") or profile.role or "w"),
                status=ProjectMemberStatus.ACTIVE,
                disabled=False,
                is_external=bool(member_item.get("is_external", profile.workspace_id != project.workspace_id)),
                project_role_codes=list(member_item.get("project_role_codes") or []),
            )
            ProjectMember.objects.filter(pk=member.pk).update(
                created_at=membership_default_date,
                updated_at=membership_default_date,
                project_invitation_date=membership_default_date,
            )
    else:
        seeder.attach_members()

    seeder.attach_workspace_superusers()

    folders: dict[str, ProjectFolder] = {}
    task_map: dict[int, ProjectTask] = {}
    activity_map: dict[int, ProjectActivity] = {}

    for task_item in payload.get("tasks") or []:
        if not isinstance(task_item, dict):
            continue
        assigned_company = None
        assigned_company_name = (task_item.get("assigned_company") or "").strip()
        if assigned_company_name:
            assigned_company = Workspace.objects.filter(name=assigned_company_name).order_by("id").first()

        task = ProjectTask.objects.create(
            project=project,
            name=(task_item.get("name") or "Task"),
            assigned_company=assigned_company,
            date_start=parse_snapshot_date(task_item.get("date_start"), fallback=project.date_start) or project.date_start,
            date_end=parse_snapshot_date(task_item.get("date_end"), fallback=project.date_end or project.date_start) or (project.date_end or project.date_start),
            date_completed=parse_snapshot_date(task_item.get("date_completed")),
            progress=normalize_project_progress(task_item.get("progress")),
            status=1,
            share_status=True,
            only_read=False,
            alert=bool(task_item.get("alert")),
            starred=bool(task_item.get("starred")),
            note=(task_item.get("note") or ""),
        )
        task_created_at = parse_snapshot_datetime(
            task_item.get("date_start"),
            fallback=timezone.make_aware(
                datetime.combine(task.date_start, datetime.min.time().replace(hour=8, minute=15)),
                timezone.get_current_timezone(),
            ),
        )
        ProjectTask.objects.filter(pk=task.pk).update(created_at=task_created_at, updated_at=task_created_at)
        if isinstance(task_item.get("id"), int):
            task_map[int(task_item["id"])] = task

        for activity_item in task_item.get("activities") or []:
            if not isinstance(activity_item, dict):
                continue
            activity_status = (
                activity_item.get("status")
                if activity_item.get("status") in set(TaskActivityStatus.values)
                else TaskActivityStatus.TODO
            )
            activity = ProjectActivity.objects.create(
                task=task,
                title=(activity_item.get("title") or "Attivita"),
                description=(activity_item.get("note") or ""),
                status=activity_status,
                progress=normalize_project_progress(activity_item.get("progress")),
                datetime_start=parse_snapshot_datetime(
                    activity_item.get("datetime_start"),
                    fallback=timezone.make_aware(
                        datetime.combine(task.date_start, datetime.min.time().replace(hour=7, minute=30)),
                        timezone.get_current_timezone(),
                    ),
                )
                or timezone.make_aware(
                    datetime.combine(task.date_start, datetime.min.time().replace(hour=7, minute=30)),
                    timezone.get_current_timezone(),
                ),
                datetime_end=parse_snapshot_datetime(
                    activity_item.get("datetime_end"),
                    fallback=timezone.make_aware(
                        datetime.combine(task.date_end, datetime.min.time().replace(hour=17, minute=30)),
                        timezone.get_current_timezone(),
                    ),
                )
                or timezone.make_aware(
                    datetime.combine(task.date_end, datetime.min.time().replace(hour=17, minute=30)),
                    timezone.get_current_timezone(),
                ),
                alert=bool(activity_item.get("alert")),
                starred=bool(activity_item.get("starred")),
                note=(activity_item.get("note") or ""),
            )
            resolved_workers: list[Profile] = []
            for worker_name in activity_item.get("workers") or []:
                worker = resolve_snapshot_profile(
                    profile_lookup,
                    member_name=str(worker_name),
                )
                if worker is not None:
                    resolved_workers.append(worker)
            if resolved_workers:
                activity.workers.set(resolved_workers)
            ProjectActivity.objects.filter(pk=activity.pk).update(
                created_at=activity.datetime_start,
                updated_at=activity.datetime_start,
            )
            if isinstance(activity_item.get("id"), int):
                activity_map[int(activity_item["id"])] = activity

    for document_item in payload.get("documents") or []:
        if not isinstance(document_item, dict):
            continue
        relative_path = normalize_path(document_item.get("relative_path"))
        if not relative_path:
            continue
        file_bytes = binary_assets.get(relative_path)
        if file_bytes is None:
            continue
        folder = ensure_project_folder_from_path(
            project=project,
            folders=folders,
            raw_path=document_item.get("folder"),
        )
        document = ProjectDocument(
            project=project,
            folder=folder,
            title=(document_item.get("title") or Path(relative_path).stem or "Documento"),
            description=(document_item.get("title") or ""),
            is_public=False,
        )
        optimized_file = optimize_media_content(filename=Path(relative_path).name, content=file_bytes)
        document.document.save(Path(getattr(optimized_file, "name", "") or relative_path).name, optimized_file, save=False)
        document.save()

    for photo_item in payload.get("photos") or []:
        if not isinstance(photo_item, dict):
            continue
        relative_path = normalize_path(photo_item.get("relative_path"))
        if not relative_path:
            continue
        file_bytes = binary_assets.get(relative_path)
        if file_bytes is None:
            continue
        photo = ProjectPhoto(
            project=project,
            title=(photo_item.get("title") or ""),
        )
        optimized_file = optimize_media_content(filename=Path(relative_path).name, content=file_bytes)
        photo.photo.save(Path(getattr(optimized_file, "name", "") or relative_path).name, optimized_file, save=False)
        photo.save()

    post_map: dict[int, ProjectPost] = {}
    for post_item in payload.get("posts") or []:
        if not isinstance(post_item, dict):
            continue
        author = resolve_snapshot_profile(
            profile_lookup,
            workspace_name=post_item.get("author_workspace"),
            member_name=post_item.get("author"),
        )
        if author is None:
            raise ValueError(f'Impossibile risolvere l\'autore post "{post_item.get("author")}".')
        published_at = parse_snapshot_datetime(post_item.get("published_date"), fallback=timezone.now()) or timezone.now()
        post = ProjectPost.objects.create(
            project=project,
            task=task_map.get(int(post_item["task_id"])) if str(post_item.get("task_id")).isdigit() else None,
            activity=activity_map.get(int(post_item["activity_id"])) if str(post_item.get("activity_id")).isdigit() else None,
            author=author,
            post_kind=(
                post_item.get("post_kind")
                if post_item.get("post_kind") in {"work-progress", "issue", "documentation"}
                else "work-progress"
            ),
            text=(post_item.get("text") or ""),
            original_text=(post_item.get("text") or ""),
            source_language="it",
            display_language="it",
            alert=bool(post_item.get("alert")),
            is_public=bool(post_item.get("is_public")),
            weather_snapshot={},
        )
        ProjectPost.objects.filter(pk=post.pk).update(
            created_at=published_at,
            updated_at=published_at,
            published_date=published_at,
        )
        if isinstance(post_item.get("id"), int):
            post_map[int(post_item["id"])] = post

    comment_map: dict[int, PostComment] = {}
    pending_parents: list[tuple[int, int]] = []
    for comment_item in payload.get("comments") or []:
        if not isinstance(comment_item, dict):
            continue
        original_post_id = comment_item.get("post_id")
        if not str(original_post_id).isdigit() or int(original_post_id) not in post_map:
            continue
        author = resolve_snapshot_profile(
            profile_lookup,
            workspace_name=comment_item.get("author_workspace"),
            member_name=comment_item.get("author"),
        )
        if author is None:
            raise ValueError(f'Impossibile risolvere l\'autore commento "{comment_item.get("author")}".')
        created_at = parse_snapshot_datetime(comment_item.get("created_at"), fallback=timezone.now()) or timezone.now()
        comment = PostComment.objects.create(
            post=post_map[int(original_post_id)],
            author=author,
            text=(comment_item.get("text") or ""),
            original_text=(comment_item.get("text") or ""),
            source_language="it",
            display_language="it",
        )
        ProjectPost.objects.filter(pk=comment.post_id).update(updated_at=created_at)
        PostComment.objects.filter(pk=comment.pk).update(
            created_at=created_at,
            updated_at=created_at,
        )
        if isinstance(comment_item.get("id"), int):
            comment_map[int(comment_item["id"])] = comment
        if str(comment_item.get("parent_id")).isdigit():
            pending_parents.append((comment.id, int(comment_item["parent_id"])))

    for comment_id, original_parent_id in pending_parents:
        parent = comment_map.get(original_parent_id)
        if parent is None:
            continue
        PostComment.objects.filter(pk=comment_id).update(parent=parent)

    attachments_payload = payload.get("attachments") if isinstance(payload.get("attachments"), dict) else {}
    for attachment_item in attachments_payload.get("post") or []:
        if not isinstance(attachment_item, dict):
            continue
        original_post_id = attachment_item.get("post_id")
        relative_path = normalize_path(attachment_item.get("relative_path"))
        if not str(original_post_id).isdigit() or int(original_post_id) not in post_map or not relative_path:
            continue
        file_bytes = binary_assets.get(relative_path)
        if file_bytes is None:
            continue
        attachment = PostAttachment(post=post_map[int(original_post_id)])
        optimized_file = optimize_media_content(filename=Path(relative_path).name, content=file_bytes)
        attachment.file.save(Path(getattr(optimized_file, "name", "") or relative_path).name, optimized_file, save=False)
        attachment.save()

    for attachment_item in attachments_payload.get("comment") or []:
        if not isinstance(attachment_item, dict):
            continue
        original_comment_id = attachment_item.get("comment_id")
        relative_path = normalize_path(attachment_item.get("relative_path"))
        if not str(original_comment_id).isdigit() or int(original_comment_id) not in comment_map or not relative_path:
            continue
        file_bytes = binary_assets.get(relative_path)
        if file_bytes is None:
            continue
        attachment = CommentAttachment(comment=comment_map[int(original_comment_id)])
        optimized_file = optimize_media_content(filename=Path(relative_path).name, content=file_bytes)
        attachment.file.save(Path(getattr(optimized_file, "name", "") or relative_path).name, optimized_file, save=False)
        attachment.save()

    DemoProjectSnapshot.objects.filter(name=project.name).update(project=project)
    project.demo_snapshot_version = snapshot.version
    project.is_demo_master = True
    project.save(update_fields=["demo_snapshot_version", "is_demo_master", "updated_at"])

    return {
        "detail": (
            f'Snapshot "{snapshot.version}" ripristinato correttamente.'
            if not missing_assets
            else f'Snapshot "{snapshot.version}" ripristinato con {len(missing_assets)} asset mancanti.'
        ),
        "action": "restore_snapshot",
        "restore_summary": {
            "snapshot_version": snapshot.version,
            "task_count": ProjectTask.objects.filter(project=project).count(),
            "activity_count": ProjectActivity.objects.filter(task__project=project).count(),
            "document_count": ProjectDocument.objects.filter(project=project).count(),
            "photo_count": ProjectPhoto.objects.filter(project=project).count(),
            "post_count": ProjectPost.objects.filter(project=project, is_deleted=False).count(),
            "comment_count": PostComment.objects.filter(post__project=project, is_deleted=False).count(),
            "missing_asset_count": len(missing_assets),
            "missing_assets": missing_assets[:10],
        },
        **build_demo_master_status_payload(),
    }


@transaction.atomic
def reset_demo_master_project(
    *,
    user,
    viewer_email: str = DEFAULT_VIEWER_EMAIL,
    viewer_password: str = DEFAULT_VIEWER_PASSWORD,
    skip_active_snapshot_link: bool = False,
) -> dict[str, Any]:
    require_demo_master_superuser(user=user)

    active_snapshot = None
    if not skip_active_snapshot_link:
        active_snapshot = get_active_demo_master_snapshot()

    summary = Seeder(
        viewer_email=viewer_email,
        viewer_password=viewer_password,
    ).run()
    project = Project.objects.filter(id=summary["project_id"]).first()
    if project is not None:
        DemoProjectSnapshot.objects.filter(name=project.name).update(project=project)
        if active_snapshot is not None:
            project.is_demo_master = True
            project.demo_snapshot_version = active_snapshot.version
            project.save(update_fields=["is_demo_master", "demo_snapshot_version", "updated_at"])

    return {
        "detail": "Demo Master ripristinato dal seed canonico.",
        "action": "reset",
        "reset_summary": {
            "project_id": summary["project_id"],
            "project_name": summary["project_name"],
            "progress_percentage": summary["progress_percentage"],
            "documents": summary["documents"],
            "photos": summary["photos"],
            "posts": summary["posts"],
            "comments": summary["comments"],
            "reattached_snapshot_version": active_snapshot.version if active_snapshot is not None else None,
        },
        **build_demo_master_status_payload(),
    }
