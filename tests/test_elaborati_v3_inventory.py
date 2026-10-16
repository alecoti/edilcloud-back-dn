from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from edilcloud.modules.elaborati.inventory import build_inventory
from edilcloud.modules.elaborati.models import DocumentEvidenceItem
from edilcloud.modules.elaborati.policies import POLICIES, policy_for
from edilcloud.modules.elaborati.registry import template_for
from edilcloud.modules.elaborati.schemas import CreateRequest
from edilcloud.modules.projects.models import (
    CommentAttachment, PostAttachment, PostComment, ProjectDocument, ProjectPost,
)
from tests import test_elaborati as baseline

site = baseline.site
pytestmark = pytest.mark.django_db


def inventory_job(site, document_type="daily_report"):
    revision = baseline.create(site)
    if document_type != "daily_report":
        revision.elaborato.document_type = document_type
        revision.elaborato.save()
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    return job


def test_all_six_versioned_policies_and_legacy_type_aliases():
    assert len(POLICIES) == 6
    for key, policy in POLICIES.items():
        contract = policy.snapshot(template_for(key)["sections"])
        assert contract["version"] and contract["required_sections"]
        for field in ("required_fields", "allowed_sources", "forbidden_inferences", "critical_facts",
                      "completion_rules", "signature_rules", "layout", "fast_path_rules", "deep_path_rules"):
            assert contract[field]
    assert policy_for("inspection_report") is policy_for("inspection")
    assert policy_for("coordination_minutes") is policy_for("coordination")
    for canonical, stored in (("inspection_report", "inspection"), ("coordination_minutes", "coordination")):
        payload = CreateRequest(idempotency_key=uuid.uuid4(), project_id=1, document_type=canonical,
                                period_start="2026-10-16", period_end="2026-10-16")
        assert payload.document_type == stored


def test_inventory_exceeds_every_previous_communication_and_file_limit_without_truncation(site):
    project, owner, _, _, original = site
    posts = ProjectPost.objects.bulk_create([
        ProjectPost(project=project, author=owner, text=f"Comunicazione {i}") for i in range(185)
    ])
    comments = PostComment.objects.bulk_create([
        PostComment(post=original, author=owner, text=f"Riscontro {i}") for i in range(205)
    ])
    PostAttachment.objects.bulk_create([
        PostAttachment(post=posts[-1], file=f"posts/photo-{i}.jpg") for i in range(22)
    ])
    CommentAttachment.objects.bulk_create([
        CommentAttachment(comment=comments[-1], file=f"comments/audio-{i}.mp3") for i in range(65)
    ])
    ProjectDocument.objects.bulk_create([
        ProjectDocument(project=project, title=f"Documento {i}", document=f"documents/{i}.pdf")
        for i in range(67)
    ])
    job = inventory_job(site)
    counts = build_inventory(job, batch_size=19)
    assert counts["by_kind"]["post"] == 186
    assert counts["by_kind"]["comment"] == 205
    assert counts["by_kind"]["image_attachment"] == 22
    assert counts["by_kind"]["attachment"] == 65
    assert counts["by_kind"]["document"] == 67
    assert counts["total"] > 450
    assert counts["by_state"] == {"pending": counts["total"]}
    original_hashes = dict(job.evidence_items.values_list("source_id", "source_hash"))
    # A repeated dispatch after a completed census reuses the same snapshot.
    original.text = "Testo modificato dopo l'inventario"
    original.save()
    assert build_inventory(job, batch_size=7) == counts
    assert dict(job.evidence_items.values_list("source_id", "source_hash")) == original_hashes


def test_inventory_keeps_long_text_and_entire_thread_with_explicit_temporal_context(site):
    project, owner, _, _, original = site
    original.text = "Contenuto " * 20000 + "Esito conclusivo: controllo ancora condizionato."
    original.save()
    old = ProjectPost.objects.create(project=project, author=owner, text="Segnalazione storica")
    ProjectPost.objects.filter(pk=old.pk).update(published_date=timezone.now() - timedelta(days=10))
    early = PostComment.objects.create(post=old, author=owner, text="Condizione iniziale")
    PostComment.objects.filter(pk=early.pk).update(created_at=timezone.now() - timedelta(days=9))
    late = PostComment.objects.create(post=old, author=owner, text="Esito di oggi")
    job = inventory_job(site)
    build_inventory(job, batch_size=1)
    text = job.evidence_items.get(source_id=f"post:{original.pk}").payload["data"]["text"]
    assert text == original.text
    assert job.evidence_items.get(source_id=f"post:{old.pk}").payload["data"]["outside_period_context"]
    assert job.evidence_items.get(source_id=f"comment:{early.pk}").payload["data"]["outside_period_context"]
    assert not job.evidence_items.get(source_id=f"comment:{late.pk}").payload["data"]["outside_period_context"]


def test_issue_inventory_covers_prior_history_until_reference_end_and_is_permission_scoped(site):
    project, owner, _, outsider, _ = site
    old = ProjectPost.objects.create(project=project, author=owner, text="Origine del problema")
    ProjectPost.objects.filter(pk=old.pk).update(published_date=timezone.now() - timedelta(days=100))
    job = inventory_job(site, "issue_report")
    build_inventory(job)
    assert job.evidence_items.filter(source_id=f"post:{old.pk}").exists()
    job.requested_by = outsider
    # An unfinished run always reauthorizes the project before reading sources.
    job.workflow_state = {}
    job.save()
    with pytest.raises(ValueError):
        build_inventory(job)
    assert not DocumentEvidenceItem.objects.filter(job=job).exclude(
        payload__kind__in=POLICIES["issue_report"].allowed_sources
    ).exists()
