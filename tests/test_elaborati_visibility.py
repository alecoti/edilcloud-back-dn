"""Core company boundary. Raw media/search/events/sharing are separate gates."""
import uuid
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from ninja.errors import HttpError

from edilcloud.modules.elaborati import api, services
from edilcloud.modules.elaborati.models import ElaboratoOwnership
from edilcloud.modules.elaborati.visibility import organization_documents
from edilcloud.modules.projects.models import ProjectDocument, ProjectMember
from edilcloud.modules.projects.services import (
    delete_project_document, get_project_document_file_response, list_project_documents,
    update_project_document,
)
from tests import test_elaborati as baseline
from tests.test_notifications_api import create_workspace_user

site = baseline.site
pytestmark = pytest.mark.django_db


@pytest.fixture
def actors(site):
    project, owner, reader, outsider, _ = site
    ProjectMember.objects.create(project=project, profile=outsider, role="o")
    alias = type(owner).objects.create(
        user=owner.user, workspace=outsider.workspace, role="o", first_name="Alias", last_name="QA",
    )
    ProjectMember.objects.create(project=project, profile=alias, role="o")
    _, colleague = create_workspace_user(
        workspace=owner.workspace, email="elaborati.colleague@example.com", password="test123",
        first_name="Editor", last_name="QA", role="d",
    )
    ProjectMember.objects.create(project=project, profile=colleague, role="d")
    return {"owner": owner, "reader": reader, "outsider": outsider, "alias": alias, "colleague": colleague}


@pytest.mark.parametrize("assigned,state,expected", [
    (True, "draft", {"owner":200,"reader":403,"outsider":404,"alias":404,"colleague":200}),
    (True, "published", {"owner":200,"reader":200,"outsider":404,"alias":404,"colleague":200}),
    (False, "published", {"owner":200,"reader":404,"outsider":404,"alias":404,"colleague":404}),
])
def test_company_scope_is_additional_to_project_roles_and_exact_legacy_author(site, actors, assigned, state, expected):
    revision = baseline.create(site)
    revision.state = state
    revision.save(update_fields=["state"])
    if not assigned:
        ElaboratoOwnership.objects.filter(document=revision.elaborato).delete()
    for actor, status in expected.items():
        try:
            services.get_revision(profile=actors[actor], revision_id=revision.pk)
            actual = 200
        except HttpError as error:
            actual = error.status_code
        assert actual == status, actor
    for actor in ("outsider", "alias"):
        page = services.list_elaborati(profile=actors[actor], limit=1)
        assert page == {"items": [], "total":0, "offset":0, "has_more":False}
        assert api.options(SimpleNamespace(_elaborati_profile=actors[actor]))["authors"] == []


def test_company_filter_precedes_author_filters_count_and_pagination(site, actors):
    ours = baseline.create(site)
    from edilcloud.modules.elaborati.schemas import CreateRequest
    theirs = services.create_elaborato(profile=actors["outsider"], payload=CreateRequest(
        idempotency_key=uuid.uuid4(), project_id=site[0].pk, document_type="daily_report",
        period_start=ours.elaborato.period_start, period_end=ours.elaborato.period_end,
    ))
    for actor, visible in (("owner", ours), ("outsider", theirs), ("alias", theirs)):
        page = services.list_elaborati(profile=actors[actor], limit=1)
        assert page["total"] == 1 and not page["has_more"]
        assert page["items"][0]["revision_id"] == str(visible.pk)
        hidden = theirs if visible == ours else ours
        assert services.list_elaborati(profile=actors[actor], author_id=hidden.elaborato.created_by_id)["total"] == 0
        authors = api.options(SimpleNamespace(_elaborati_profile=actors[actor]))["authors"]
        assert [a["id"] for a in authors] == [visible.elaborato.created_by_id]
    # A reader must not learn authors from drafts they cannot read.
    assert api.options(SimpleNamespace(_elaborati_profile=actors["reader"]))["authors"] == []


@pytest.mark.parametrize("inactive", ["profile", "workspace", "user"])
def test_worker_or_stale_profile_cannot_bypass_deactivation(site, inactive):
    revision = baseline.create(site)
    profile = site[1]
    target = {"profile":profile, "workspace":profile.workspace, "user":profile.user}[inactive]
    type(target).objects.filter(pk=target.pk).update(is_active=False)
    assert not organization_documents(profile=profile).exists()
    with pytest.raises(HttpError) as failure:
        services.authorize_revision(profile=profile, revision=revision, edit=True)
    assert failure.value.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_drive_lists_files_and_mutations_use_same_boundary_without_changing_ordinary_uploads(site, actors):
    revision = baseline.create(site)
    drive = ProjectDocument.objects.create(project=site[0], uploaded_by=site[1], title="Private QA",
        document=ContentFile(b"%PDF-1.4\nSynthetic guard fixture", name="guard.pdf"))
    ordinary = ProjectDocument.objects.create(project=site[0], uploaded_by=site[1], title="Ordinary QA",
        document=ContentFile(b"ordinary", name="ordinary.txt"))
    revision.drive_document = drive
    revision.state = "published"
    revision.save(update_fields=["drive_document", "state"])
    for actor in ("owner", "reader", "outsider", "alias"):
        visible = {d["id"] for d in list_project_documents(profile=actors[actor], project_id=site[0].pk)}
        assert ordinary.pk in visible
        assert (drive.pk in visible) == (actor in ("owner", "reader"))
    for actor in ("outsider", "alias"):
        for action in (get_project_document_file_response, update_project_document, delete_project_document):
            with pytest.raises(ValueError, match="^Documento non trovato\\.$"):
                action(profile=actors[actor], document_id=drive.pk)
    response = get_project_document_file_response(profile=actors["reader"], document_id=drive.pk)
    assert b"".join(response.streaming_content).startswith(b"%PDF-1.4")
    response.close()
    revision.state = "deleted"
    revision.save(update_fields=["state"])
    assert drive.pk not in {d["id"] for d in list_project_documents(profile=actors["owner"], project_id=site[0].pk)}
