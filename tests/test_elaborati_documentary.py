"""Regression cases derived from the documentary references, not wording snapshots."""

from copy import deepcopy
from datetime import date, timedelta
import io
from pathlib import Path
import uuid

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image
import pytest

from edilcloud.modules.elaborati.evidence import build_evidence
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.media_sources import enrich_media, VisualResult
from edilcloud.modules.elaborati.readiness import documentary_issues, require_documentary_material
from edilcloud.modules.elaborati.registry import template_for
from edilcloud.modules.elaborati.schemas import CreateRequest
from edilcloud.modules.elaborati.services import create_elaborato
from edilcloud.modules.projects.models import PostAttachment, ProjectDocument, ProjectPost
from tests import test_elaborati as baseline

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def running_job(revision):
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    return job


def test_wrong_year_is_rejected_before_any_paid_call_and_suggests_real_post_date(site, provider):
    project, owner, *_, post = site
    day = date.today() - timedelta(days=365)
    revision = create_elaborato(
        profile=owner,
        payload=CreateRequest(
            idempotency_key=uuid.uuid4(),
            project_id=project.pk,
            document_type="daily_report",
            period_start=day,
            period_end=day,
        ),
    )
    process_job(revision.jobs.get().pk)
    job = revision.jobs.get()
    assert job.state == "failed" and "periodo selezionato" in job.error_message
    assert timezone.localtime(post.published_date).date().isoformat() in job.error_message
    assert provider == [] and not revision.editor_doc


def test_photo_report_without_images_cannot_succeed_as_empty_prose(site, provider):
    revision = baseline.create(site)
    revision.elaborato.document_type = "photo_report"
    revision.elaborato.save()
    revision.template_snapshot = template_for("photo_report", "it")
    revision.save()
    process_job(revision.jobs.get().pk)
    assert revision.jobs.get().state == "failed"
    assert "fotografie" in revision.jobs.get().error_message and provider == []


def test_photo_report_quality_still_blocks_manual_removal_of_all_photographs(site, provider):
    revision = baseline.generate(site)
    issues = documentary_issues(revision.editor_doc, revision.evidence, "photo_report")
    assert any(
        i["severity"] == "blocking" and "fotografie effettive" in i["explanation"] for i in issues
    )


def test_internal_machine_label_is_blocking_even_if_provider_approves(site, provider):
    revision = baseline.generate(site)
    doc = deepcopy(revision.editor_doc)
    doc["content"][1]["content"][0]["text"] = "La presenza resta unverified."
    assert any(
        i["severity"] == "blocking" and "etichette tecniche" in i["explanation"]
        for i in documentary_issues(doc, revision.evidence, "daily_report")
    )


def test_dates_mentioned_inside_current_pdf_can_support_a_document_without_posts(site, tmp_path):
    raw = (
        Path(__file__).parents[1]
        / "demo-assets/demo-master/v2026.04/documents/rilievo-foro-cucina-2b.pdf"
    ).read_bytes()
    project, owner, *_ = site
    ProjectDocument.objects.create(
        project=project, title="Rilievo del foro", document=ContentFile(raw, name="rilievo.pdf")
    )
    revision = create_elaborato(
        profile=owner,
        payload=CreateRequest(
            idempotency_key=uuid.uuid4(),
            project_id=project.pk,
            document_type="inspection",
            period_start=date(2026, 4, 4),
            period_end=date(2026, 4, 4),
        ),
    )
    bundle = build_evidence(profile=owner, elaborato=revision.elaborato)
    summary = require_documentary_material(bundle, "inspection")
    assert summary["documents_mentioning_period_dates"]
    source = next(s for s in bundle["sources"] if s["kind"] == "document")
    assert "18 mm" in source["data"]["excerpts"][0]["text"]
    assert source["data"]["excerpts"][0]["extraction_method"] == "current_pdf_text"


def test_image_analysis_is_cached_by_bytes_but_storage_authorization_is_rechecked(
    site, monkeypatch
):
    project, owner, *_, post = site
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "green").save(out, "PNG")
    attachment = PostAttachment.objects.create(
        post=post, file=ContentFile(out.getvalue(), name="rilievo.png")
    )
    revision = baseline.create(site)
    job = running_job(revision)
    bundle = build_evidence(profile=owner, elaborato=revision.elaborato)
    calls = []

    def analyze(**kwargs):
        calls.append(kwargs)
        sid = kwargs["images"][0][0]
        return VisualResult(
            images=[
                {
                    "source_id": sid,
                    "description": "Superficie verde uniforme.",
                    "limitations": "Nessuna misura ricavabile.",
                }
            ]
        )

    monkeypatch.setattr("edilcloud.modules.elaborati.media_sources.structured_response", analyze)
    cache.clear()
    first = enrich_media(job=job, bundle=bundle)
    second = enrich_media(job=job, bundle=bundle)
    assert len(calls) == 1 and calls[0]["images"][0][1].startswith("data:image/")
    source = next(
        s
        for s in second["sources"]
        if s["record_id"] == str(attachment.pk) and s["kind"] == "image_attachment"
    )
    assert source["data"]["visual_analysis"]["human_verified"] is False
    assert source["data"]["visual_content_verified"] is False
    assert first["bundle_hash"] == second["bundle_hash"]
    attachment.delete()
    third = enrich_media(job=job, bundle=bundle)
    assert third["bundle_hash"] == second["bundle_hash"]
    # Removing the live attachment does not destroy an archived revision, but
    # revoking membership must still block even previously cached analyses.
    from edilcloud.modules.projects.models import ProjectMember
    ProjectMember.objects.filter(project=project, profile=owner).update(disabled=True)
    inaccessible = enrich_media(job=job, bundle=bundle)
    assert any(
        w["reason"] == "image_unavailable_or_unsupported"
        for w in inaccessible["media_analysis"]["warnings"]
    )
    assert len(calls) == 1


def test_media_upload_date_is_not_substituted_for_post_event_date(site):
    _, owner, *_, post = site
    PostAttachment.objects.create(post=post, file=ContentFile(b"audio", name="note.flac"))
    revision = baseline.create(site)
    bundle = build_evidence(profile=owner, elaborato=revision.elaborato)
    source = next(s for s in bundle["sources"] if s["kind"] == "attachment")
    assert source["data"]["media_kind"] == "audio"
    assert source["data"]["event_date_from_parent"] == post.published_date.isoformat()
    assert source["data"]["uploaded_at_is_not_event_date"]


def test_primary_decisions_survive_large_media_inventory(site):
    from edilcloud.modules.projects.models import PostComment

    project, owner, *_, post = site
    for i in range(31):
        p = ProjectPost.objects.create(project=project, author=owner, text=f"Aggiornamento {i}")
        for j in range(16):
            PostAttachment.objects.create(
                post=p, file=ContentFile(b"x", name=f"allegato-{i}-{j}.txt")
            )
    decision = PostComment.objects.create(
        post=post, author=owner, text="Verifica eseguita, punto chiuso con riscontro."
    )
    revision = baseline.create(site)
    bundle = build_evidence(profile=owner, elaborato=revision.elaborato)
    assert bundle["truncated"]
    assert f"comment:{decision.pk}" in {s["id"] for s in bundle["sources"]}
