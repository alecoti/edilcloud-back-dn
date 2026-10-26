"""Attribution foundation only; these tests do not attest end-to-end privacy."""
from pathlib import Path
from copy import deepcopy
import uuid

import pytest
from django.db.models.deletion import ProtectedError
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.ownership import confirm_legacy, ownership_view
from edilcloud.modules.elaborati.models import Elaborato, ElaboratoOwnership
from edilcloud.modules.elaborati.schemas import CreateRequest
from edilcloud.modules.projects.models import ProjectMember
from tests import test_elaborati as baseline

site = baseline.site
pytestmark = pytest.mark.django_db


def test_creator_workspace_owns_document_even_in_another_company_project(site):
    project, owner, _, outsider, _ = site
    ProjectMember.objects.create(project=project, profile=outsider, role="o")
    original = baseline.create(site)
    payload = CreateRequest(
        idempotency_key=uuid.uuid4(), project_id=project.pk, document_type="daily_report",
        period_start=original.elaborato.period_start, period_end=original.elaborato.period_end,
    )
    revision = services.create_elaborato(profile=outsider, payload=payload)
    attribution = revision.elaborato.ownership
    assert attribution.workspace_id == outsider.workspace_id != project.workspace_id
    assert attribution.assigned_by_id == outsider.pk
    assert attribution.assigned_at == revision.elaborato.created_at
    assert attribution.basis == "creation"
    assert attribution.assignment_snapshot == {
        "schema_version": 1, "basis": "creation", "workspace_id": outsider.workspace_id,
        "workspace_name": outsider.workspace.name, "actor_profile_id": outsider.pk,
        "actor_user_id": outsider.user_id,
    }
    assert original.elaborato.ownership.workspace_id == owner.workspace_id
    assert revision.jobs.get().state == "queued"  # No worker/provider is run.


def test_idempotency_and_company_rename_do_not_change_ownership_receipt(site):
    revision = baseline.create(site)
    document = revision.elaborato
    before = deepcopy(document.ownership.assignment_snapshot)
    assigned = document.ownership.assigned_at
    workspace = site[1].workspace
    workspace.name = "Renamed organization"
    workspace.save(update_fields=["name"])
    payload = CreateRequest(
        idempotency_key=document.creation_key, project_id=document.project_id,
        document_type=document.document_type, period_start=document.period_start,
        period_end=document.period_end,
    )
    retried = services.create_elaborato(profile=site[1], payload=payload)
    assert retried.pk == revision.pk
    assert ElaboratoOwnership.objects.count() == 1
    assert retried.elaborato.ownership.assignment_snapshot == before
    assert retried.elaborato.ownership.assigned_at == assigned


def test_queue_failure_rolls_back_document_revision_and_ownership(site, monkeypatch):
    def reject(**kwargs):
        raise HttpError(402, "Synthetic quota rejection")

    monkeypatch.setattr(services, "queue_job", reject)
    with pytest.raises(HttpError) as failure:
        baseline.create(site)
    assert failure.value.status_code == 402
    assert Elaborato.objects.count() == ElaboratoOwnership.objects.count() == 0


def test_legacy_document_is_not_automatically_owned_by_project_or_current_author(site):
    original = baseline.create(site).elaborato
    legacy = Elaborato.objects.create(
        project=original.project, created_by=site[1], author_snapshot=original.author_snapshot,
        document_type=original.document_type, title="Synthetic legacy record",
        period_start=original.period_start, period_end=original.period_end,
        number=original.number + 1, creation_key=uuid.uuid4(), creation_hash="legacy",
    )
    assert not ElaboratoOwnership.objects.filter(document=legacy).exists()


def test_deleting_profile_keeps_company_ownership_and_actor_snapshot(site):
    revision = baseline.create(site)
    attribution = revision.elaborato.ownership
    snapshot = deepcopy(attribution.assignment_snapshot)
    workspace = attribution.workspace
    site[1].delete()
    attribution.refresh_from_db()
    assert attribution.assigned_by_id is None and attribution.workspace_id == workspace.pk
    assert attribution.assignment_snapshot == snapshot
    with pytest.raises(ProtectedError):
        workspace.delete()


def test_native_and_django_ownership_sql_are_identical():
    repo = Path(__file__).resolve().parents[1]
    django_sql = repo / "src/edilcloud/modules/elaborati/migrations/0013_company_ownership.sql"
    native_sql = repo.parent / "rust/resources/migrations/2026102602_elaborati_company_ownership.sql"
    # Standalone Django CI need not contain the separate Rust repository.
    if not native_sql.exists():
        pytest.skip("The separate native repository is not part of standalone Django CI.")
    assert django_sql.read_bytes() == native_sql.read_bytes()


def test_author_confirmation_is_explicit_atomic_and_idempotent_without_content_changes(site):
    revision = baseline.create(site)
    ElaboratoOwnership.objects.filter(document=revision.elaborato).delete()
    before = {key: deepcopy(getattr(revision, key)) for key in ('version','state','editor_doc','evidence','preview_hash','pdf_hash','signature_audit')}
    view = ownership_view(revision.elaborato, profile=site[1], can_edit=True)
    assert view['state'] == 'unassigned' and view['can_confirm']
    assert view['confirmation_workspace_id'] == site[1].workspace_id
    for _ in range(2):
        result = confirm_legacy(profile=site[1], revision_id=revision.pk, version=revision.version,
            confirmed=True, reason='Documento redatto per la nostra impresa.')
        assert {key: getattr(result,key) for key in before} == before
    assert revision.audit.filter(action='ownership.confirmed').count() == 1
    assert ElaboratoOwnership.objects.get(document=revision.elaborato).basis == 'author_confirmation'
    assert revision.jobs.count() == 1 and revision.jobs.get().state == 'queued'


@pytest.mark.parametrize('case,status', [('unconfirmed',400),('blank_reason',400),('stale',409),('other_editor',403),('outsider',404)])
def test_legacy_confirmation_rejects_invalid_or_unauthorized_assignments(site,case,status):
    revision = baseline.create(site)
    ElaboratoOwnership.objects.filter(document=revision.elaborato).delete()
    profile=site[3] if case in ('other_editor','outsider') else site[1]
    if case == 'other_editor':
        ProjectMember.objects.create(project=site[0],profile=profile,role='o')
    with pytest.raises(HttpError) as error:
        confirm_legacy(profile=profile,revision_id=revision.pk,version=revision.version+int(case=='stale'),
            confirmed=case!='unconfirmed',reason=' '*20 if case=='blank_reason' else 'Attribuzione storica documentata.')
    assert error.value.status_code == status
    assert not ElaboratoOwnership.objects.filter(document=revision.elaborato).exists()
