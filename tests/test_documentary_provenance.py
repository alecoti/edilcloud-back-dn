import hashlib
from io import BytesIO
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image

from edilcloud.modules.projects.models import ProjectPost, PostAttachment
from edilcloud.modules.projects.provenance import capture_source, prepare_upload, enrich_source
from edilcloud.modules.projects.provenance_models import ProjectSource, ProjectSourceVersion
from edilcloud.modules.projects.participations import actor_snapshot
from edilcloud.modules.elaborati.evidence import resolve_evidence_file
from tests import test_elaborati as baseline
from django.test import Client
from django.core.management import call_command
from ninja.errors import HttpError
from edilcloud.modules.projects.participations import create_participation, close_participation
from edilcloud.modules.projects.provenance_schemas import ParticipationRequest
from edilcloud.modules.elaborati.renderer import render_html
from edilcloud.modules.elaborati.documentary_register import manifest, coverage, labels
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def post_source(post):
    return {
        "id": f"post:{post.pk}",
        "kind": "post",
        "record_id": str(post.pk),
        "data": {"text": post.text, "author": post.author.member_name},
        "at": post.published_date.isoformat(),
    }


def test_source_actor_remains_historical_after_person_company_and_role_changes(site):
    project, owner, _, _, _ = site
    member = project.members.get(profile=owner)
    owner.position = "Caposquadra"
    owner.save(update_fields=["position"])
    member.project_role_codes = ["rspp"]
    member.save(update_fields=["project_role_codes"])
    post = ProjectPost.objects.create(project=project, author=owner, text="Verifica aperta.")
    captured = enrich_source(project=project, source=post_source(post))
    assert captured["actor"]["person_name"] == "Laura Verdi"
    assert captured["actor"]["qualification"] == "Caposquadra"
    assert captured["actor"]["role_labels"] == ["RSPP"]
    old_company = captured["actor"]["company_name"]
    owner.first_name = "Laura aggiornata"
    owner.position = "Direttrice tecnica"
    owner.workspace.name = "Azienda rinominata"
    owner.workspace.save(update_fields=["name"])
    owner.save(update_fields=["first_name", "position"])
    member.project_role_codes = ["cse"]
    member.save(update_fields=["project_role_codes"])
    post.text = "Verifica aggiornata."
    post.save(update_fields=["text", "updated_at"])
    updated = enrich_source(project=project, source=post_source(post))
    assert updated["source_uuid"] == captured["source_uuid"]
    assert updated["reference"] == captured["reference"]
    assert updated["actor"] == captured["actor"]
    assert updated["actor"]["company_name"] == old_company
    assert updated["version_hash"] != captured["version_hash"]
    old = ProjectSourceVersion.objects.get(
        source_id=captured["source_uuid"], hash=captured["version_hash"]
    )
    assert old.snapshot["object"]["text"] == "Verifica aperta."
    old.snapshot = {}
    with pytest.raises(ValidationError, match="immutabile"):
        old.save()


def test_reconstructed_identity_does_not_claim_historical_roles(site):
    project, owner, _, _, post = site
    ProjectSource.objects.filter(project=project, kind="post", record_key=str(post.pk)).delete()
    past = timezone.now() - timedelta(days=60)
    ProjectPost.objects.filter(pk=post.pk).update(created_at=past)
    post.refresh_from_db()
    source, version = capture_source(post, reconstructed=True)
    again, same_version = capture_source(post, reconstructed=True)
    assert source.pk == again.pk and version.pk == same_version.pk
    assert source.identity_state == "reconstructed"
    assert source.actor_snapshot["historical_roles_known"] is False
    assert source.actor_snapshot["roles"] == []
    unknown = actor_snapshot(project=project, profile=None, at=past)
    assert unknown["identity_state"] == "unavailable" and not unknown["person_name"]


def test_received_photo_original_survives_optimization_and_later_file_replacement(site, settings):
    project, owner, _, _, post = site
    settings.MEDIA_IMAGE_MAX_DIMENSION = 480
    settings.MEDIA_OPTIMIZATION_ENABLED = True
    raw = BytesIO()
    Image.new("RGB", (1800, 1200), "#d59a20").save(raw, format="JPEG", quality=100)
    original_bytes = raw.getvalue()
    received = SimpleUploadedFile("foto-originale.jpg", original_bytes, content_type="image/jpeg")
    prepared = prepare_upload(project, received)
    attachment = PostAttachment.objects.create(
        post=post, uploaded_by=owner, file=prepared, content_type=prepared.content_type
    )
    source, version = capture_source(attachment)
    assert version.original_state == "received_original"
    assert version.original_blob.sha256 == hashlib.sha256(original_bytes).hexdigest()
    with version.original_blob.file.open("rb") as incoming:
        assert incoming.read() == original_bytes
    with version.file_blob.file.open("rb") as incoming:
        assert max(Image.open(incoming).size) <= 480
    frozen = {
        "source_uuid": str(source.pk),
        "version_hash": version.hash,
        "file_sha256": version.file_blob.sha256,
    }
    attachment.file = SimpleUploadedFile(
        "sostituzione.jpg", b"replacement", content_type="image/jpeg"
    )
    attachment.save()
    field = resolve_evidence_file(profile=owner, project_id=project.pk, source=frozen)
    with field.open("rb") as incoming:
        assert hashlib.sha256(incoming.read()).hexdigest() == frozen["file_sha256"]
    assert source.versions.count() == 2


def test_external_professional_appointments_do_not_grant_access_and_preserve_history(site):
    project, owner, worker, outsider, _ = site
    before = project.members.count()
    payload = ParticipationRequest(
        person_name="Stefano Riva",
        company_name="Riva Impianti S.r.l.",
        qualification="Caposquadra",
        role_codes=["rspp"],
        valid_from="2026-01-01",
        status="verified",
        appointment_reference="Nomina RSPP 01/2026",
    )
    row = create_participation(profile=owner, project_id=project.pk, payload=payload)
    assert row["external"] and row["role_labels"] == ["RSPP"]
    assert project.members.count() == before
    for denied in (worker, outsider):
        with pytest.raises(HttpError):
            create_participation(profile=denied, project_id=project.pk, payload=payload)
    closed = close_participation(
        profile=owner, project_id=project.pk, participation_id=row["id"], valid_to="2026-10-01"
    )
    assert closed["valid_to"].startswith("2026-10-01")
    with pytest.raises(HttpError):
        close_participation(
            profile=owner, project_id=project.pk, participation_id=row["id"], valid_to="2026-10-02"
        )
    new = create_participation(
        profile=owner,
        project_id=project.pk,
        payload=ParticipationRequest(
            **{
                **payload.model_dump(),
                "person_id": row["person_id"],
                "company_name": "Nuova Impresa",
                "valid_from": "2026-10-01",
                "role_codes": ["cse"],
            }
        ),
    )
    assert new["person_id"] == row["person_id"] and new["id"] != row["id"]
    assert project.participations.get(pk=row["id"]).company_name == "Riva Impianti S.r.l."


def test_appointment_validation_rejects_unknown_roles_dates_and_unverified_nomina(site):
    project, owner, *_ = site
    for patch in (
        {"role_codes": ["owner"]},
        {"valid_from": "2026-01-02", "valid_to": "2026-01-01"},
        {"status": "verified"},
        {"valid_from": "not-a-date"},
    ):
        with pytest.raises(HttpError):
            create_participation(
                profile=owner,
                project_id=project.pk,
                payload=ParticipationRequest(
                    **{"person_name": "Esterno", "company_name": "Impresa", **patch}
                ),
            )


def test_human_pdf_register_and_frozen_manifest_include_professional_roles(site, provider):
    project, owner, *_ = site
    create_participation(
        profile=owner,
        project_id=project.pk,
        payload=ParticipationRequest(
            person_name="Stefano Riva",
            company_name="Riva Impianti S.r.l.",
            qualification="Caposquadra",
            role_codes=["rspp"],
            valid_from="2020-01-01",
        ),
    )
    revision = baseline.generate(site)
    markup = render_html(revision=revision, profile=owner)
    assert "Stefano Riva" in markup and "Riva Impianti" in markup and "RSPP" in markup
    assert "non attestano la presenza" in markup and "Copertura delle fonti" in markup
    assert "post:" not in markup and "member:" not in markup
    assert "/evidenze/" in markup and "?version=" in markup
    frozen = manifest(revision, pdf_hash="a" * 64)
    assert frozen["sources"] and len(frozen["manifest_hash"]) == 64
    assert all(source["source_uuid"] and source["version_hash"] for source in frozen["sources"])
    role = next(s for s in revision.evidence["sources"] if s["data"].get("name") == "Stefano Riva")
    assert role["id"] in {s["id"] for s in frozen["sources"]}


def test_evidence_http_authorization_original_and_metadata_versioning(site):
    import json

    project, owner, _, outsider, post = site
    client = Client()
    token = login_and_get_token(email=owner.user.email, password="test123")
    headers = auth_header(token)
    received = SimpleUploadedFile("prova.txt", b"original bytes", content_type="text/plain")
    prepared = prepare_upload(project, received)
    attachment = PostAttachment.objects.create(
        post=post, uploaded_by=owner, file=prepared, content_type="text/plain"
    )
    source, version = capture_source(attachment)
    endpoint = f"/api/v1/projects/evidence/{source.pk}"
    response = client.get(endpoint, {"version": version.hash}, **headers)
    assert response.status_code == 200, response.content
    assert response.json()["original_sha256"] == hashlib.sha256(b"original bytes").hexdigest()
    assert client.get(endpoint, {"version": "0" * 64}, **headers).status_code == 404
    binary = client.get(
        endpoint + "/file", {"version": version.hash, "original": "true"}, **headers
    )
    assert binary.status_code == 200 and b"".join(binary.streaming_content) == b"original bytes"
    amended = client.post(
        endpoint + "/metadata",
        data=json.dumps(
            {"version": version.hash, "declared_content_date": "2026-05-18", "area": "Piano primo"}
        ),
        content_type="application/json",
        **headers,
    )
    assert amended.status_code == 200, amended.content
    assert amended.json()["version_hash"] != version.hash
    old = client.get(endpoint, {"version": version.hash}, **headers).json()
    assert old["capture_metadata"].get("area") is None
    assert old["is_latest"] is False
    assert old["latest_version_hash"] == amended.json()["version_hash"]
    stale = client.post(
        endpoint + "/metadata",
        data=json.dumps({"version": version.hash, "area": "stale"}),
        content_type="application/json",
        **headers,
    )
    assert stale.status_code == 409
    outsider_token = login_and_get_token(email=outsider.user.email, password="test123")
    assert client.get(
        endpoint, {"version": version.hash}, **auth_header(outsider_token)
    ).status_code in (403, 404)


def test_backfill_is_idempotent_and_does_not_rewrite_existing_revision(site):
    from io import StringIO

    project, _, _, _, post = site
    revision = baseline.create(site)
    initial = (revision.editor_doc, revision.evidence, revision.version)
    ProjectSource.objects.filter(project=project, kind="post", record_key=str(post.pk)).delete()
    call_command("backfill_documentary_sources", project=project.pk, stdout=StringIO())
    assert not ProjectSource.objects.filter(
        project=project, kind="post", record_key=str(post.pk)
    ).exists()
    call_command("backfill_documentary_sources", project=project.pk, apply=True, stdout=StringIO())
    counts = (
        project.evidence_sources.count(),
        ProjectSourceVersion.objects.filter(source__project=project).count(),
    )
    call_command("backfill_documentary_sources", project=project.pk, apply=True, stdout=StringIO())
    assert counts == (
        project.evidence_sources.count(),
        ProjectSourceVersion.objects.filter(source__project=project).count(),
    )
    revision.refresh_from_db()
    assert initial == (revision.editor_doc, revision.evidence, revision.version)


def test_coverage_counts_unexamined_and_unreadable_without_claiming_all_read():
    bundle = {
        "sources": [
            {"id": "a", "data": {}, "reading_state": "read"},
            {"id": "b", "data": {}, "reading_state": "unreadable"},
            {"id": "c", "data": {}, "reading_state": "pending"},
        ],
        "census": {"total": 10, "complete": True, "excluded_from_selection": 7},
    }
    counts = coverage(bundle, {"a"})
    assert {
        k: counts[k]
        for k in ("censused", "examined", "used", "excluded", "unreadable", "not_examined")
    } == {
        "censused": 10,
        "examined": 2,
        "used": 1,
        "excluded": 7,
        "unreadable": 1,
        "not_examined": 1,
    }
    assert all(labels(locale)["roles"] for locale in ("it", "en", "fr", "ro", "ru", "ar"))


def test_tampered_archived_file_is_rejected_even_when_version_metadata_is_valid(site):
    project, owner, _, _, post = site
    attachment = PostAttachment.objects.create(
        post=post,
        uploaded_by=owner,
        file=SimpleUploadedFile("retained.txt", b"retained bytes", content_type="text/plain"),
    )
    source, version = capture_source(attachment)
    field = version.file_blob.file
    with field.storage.open(field.name, "wb") as stream:
        stream.write(b"tampered bytes")
    with pytest.raises(ValueError, match="integrità"):
        resolve_evidence_file(
            profile=owner,
            project_id=project.pk,
            source={
                "source_uuid": str(source.pk),
                "version_hash": version.hash,
                "file_sha256": version.file_blob.sha256,
            },
        )


def test_person_and_company_uuid_from_another_workspace_cannot_be_attached(site):
    project, owner, _, outsider, _ = site
    from edilcloud.modules.projects.provenance_models import Person, Company

    alien_person = Person.objects.create(workspace=outsider.workspace, name="Riservato")
    alien_company = Company.objects.create(workspace=outsider.workspace, name="Altra azienda")
    for patch in ({"person_id": alien_person.pk}, {"company_id": alien_company.pk}):
        with pytest.raises(HttpError) as error:
            create_participation(
                profile=owner,
                project_id=project.pk,
                payload=ParticipationRequest(
                    person_name="Tentativo", company_name="Impresa", **patch
                ),
            )
        assert error.value.status_code == 404


def test_new_source_observes_current_legacy_team_roles_before_recording(site):
    project, owner, _, _, _ = site
    # Simulates an upgraded project whose memberships predate this schema.
    project.participations.all().delete()
    project.members.filter(profile=owner).update(project_role_codes=["rspp"])
    post = ProjectPost.objects.create(
        project=project, author=owner, text="Nuova registrazione con RSPP."
    )
    source, _ = capture_source(post)
    assert source.actor_snapshot["role_labels"] == ["RSPP"]
    assert source.actor_snapshot["historical_roles_known"] is True
    assert project.participations.get(person__profile=owner).valid_from <= post.created_at
