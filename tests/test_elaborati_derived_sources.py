from datetime import date, timedelta
import uuid

import pytest
from django.core.files.base import ContentFile
from edilcloud.modules.elaborati.evidence import build_evidence
from edilcloud.modules.elaborati.models import ElaboratoRevision
from edilcloud.modules.elaborati.schemas import CreateRequest
from edilcloud.modules.elaborati.services import create_elaborato
from edilcloud.modules.projects.models import ProjectDocument
from tests import test_elaborati as baseline

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def test_published_pdf_is_secondary_once_and_never_reenters_as_primary_drive_evidence(
    site, provider
):
    prior = baseline.generate(site)
    drive = ProjectDocument.objects.create(
        project=site[0],
        title="Rapporto già generato",
        document=ContentFile(b"derived file", name="derived.pdf"),
    )
    ElaboratoRevision.objects.filter(pk=prior.pk).update(state="published", drive_document=drive)
    following = baseline.create(site)
    bundle = build_evidence(profile=site[1], elaborato=following.elaborato)
    assert f"document:{drive.pk}" not in {s["id"] for s in bundle["sources"]}
    secondary = [s for s in bundle["sources"] if s["kind"] == "previous_elaborato"]
    assert len(secondary) == 1 and secondary[0]["data"]["secondary_source"]
    assert secondary[0]["data"]["period_end"] == date.today().isoformat()


def test_later_period_report_cannot_supply_hindsight_to_an_earlier_day(site, provider):
    prior = baseline.generate(site)
    ElaboratoRevision.objects.filter(pk=prior.pk).update(state="published")
    before = date.today() - timedelta(days=10)
    following = create_elaborato(
        profile=site[1],
        payload=CreateRequest(
            idempotency_key=uuid.uuid4(),
            project_id=site[0].pk,
            document_type="daily_report",
            period_start=before,
            period_end=before,
        ),
    )
    bundle = build_evidence(profile=site[1], elaborato=following.elaborato)
    assert not any(s["kind"] == "previous_elaborato" for s in bundle["sources"])
