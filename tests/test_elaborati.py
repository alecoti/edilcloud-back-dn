import hashlib
import json
import uuid
from datetime import date, timedelta

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.content import (
    Composition,
    QualityResult,
    ReasoningResult,
    digest,
    editor_equivalent,
    local_quality,
    validate_editor,
)
from edilcloud.modules.elaborati.evidence import build_evidence
from edilcloud.modules.elaborati.jobs import expire_jobs, process_job
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentJob, Elaborato
from edilcloud.modules.elaborati.publication import publish_revision
from edilcloud.modules.elaborati.schemas import ActionRequest, CreateRequest, SaveRequest
from edilcloud.modules.projects.models import (
    Project,
    ProjectMember,
    ProjectOperationalEvent,
    ProjectPost,
)
from edilcloud.modules.workspaces.models import Workspace
from tests.test_notifications_api import auth_header, create_workspace_user, login_and_get_token

pytestmark = pytest.mark.django_db


@pytest.fixture
def site(settings, tmp_path):
    settings.AI_TOKEN_QUOTA_ENFORCED = False
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "private"
    settings.MEDIA_ROOT = tmp_path / "media"
    workspace = Workspace.objects.create(name="Impresa documento")
    _, owner = create_workspace_user(
        workspace=workspace,
        email="elaborati.owner@example.com",
        password="test123",
        first_name="Laura",
        last_name="Verdi",
        role="o",
    )
    _, worker = create_workspace_user(
        workspace=workspace,
        email="elaborati.worker@example.com",
        password="test123",
        first_name="Mario",
        last_name="Rossi",
        role="w",
    )
    other = Workspace.objects.create(name="Azienda separata")
    _, outsider = create_workspace_user(
        workspace=other,
        email="elaborati.other@example.com",
        password="test123",
        first_name="Altro",
        last_name="Utente",
        role="o",
    )
    project = Project.objects.create(
        workspace=workspace, name="Residenza prova", date_start=date.today(), created_by=owner
    )
    ProjectMember.objects.create(project=project, profile=owner, role="o")
    ProjectMember.objects.create(project=project, profile=worker, role="w")
    post = ProjectPost.objects.create(
        project=project,
        author=owner,
        text="È stata proposta una verifica del bagno B203. Nessuna verifica conclusiva ancora registrata.",
    )
    ProjectOperationalEvent.objects.create(
        project=project, event_type="post.created", post_id_snapshot=post.pk
    )
    return project, owner, worker, outsider, post


def create(site, **kwargs):
    project, owner, *_ = site
    return services.create_elaborato(
        profile=owner,
        payload=CreateRequest(
            idempotency_key=uuid.uuid4(),
            project_id=project.pk,
            document_type="daily_report",
            period_start=date.today(),
            period_end=date.today(),
            **kwargs,
        ),
    )


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def invoke(*, job, stage, schema, data, instructions, **kwargs):
        calls.append((stage, kwargs))
        if schema is ReasoningResult:
            return ReasoningResult(
                facts=[],
                duplicates=[],
                contradictions=[],
                missing_data=["Presenze non documentate"],
            )
        if schema is QualityResult:
            return QualityResult(issues=[], missing_data=["Presenze non documentate"])
        if schema is Composition:
            source = next(s["id"] for s in data["evidence"]["sources"] if s["kind"] == "post")
            return Composition(
                title="Rapporto prova",
                sections=[
                    {
                        "key": s["key"],
                        "paragraphs": [
                            {
                                "text": "È stata proposta una verifica, non ancora documentata come conclusa.",
                                "source_ids": [source],
                                "nature": "proposed",
                            }
                        ],
                    }
                    for s in data["template"]["sections"]
                ],
                photographs=[],
            )
        raise AssertionError(stage)

    monkeypatch.setattr("edilcloud.modules.elaborati.engine.structured_response", invoke)
    return calls


def generate(site):
    revision = create(site)
    assert process_job(revision.jobs.get().pk)
    revision.refresh_from_db()
    return revision


def test_create_idempotency_does_not_duplicate_document_or_paid_job(site):
    project, owner, *_ = site
    request = CreateRequest(
        idempotency_key=uuid.uuid4(),
        project_id=project.pk,
        document_type="daily_report",
        period_start=date.today(),
        period_end=date.today(),
    )
    a = services.create_elaborato(profile=owner, payload=request)
    b = services.create_elaborato(profile=owner, payload=request)
    assert a.pk == b.pk and Elaborato.objects.count() == 1 and DocumentJob.objects.count() == 1
    request.context = "Richiesta differente"
    with pytest.raises(HttpError) as exc:
        services.create_elaborato(profile=owner, payload=request)
    assert exc.value.status_code == 409


def test_membership_role_and_workspace_isolation(site):
    project, owner, worker, outsider, _ = site
    revision = create(site)
    for profile in (worker, outsider):
        with pytest.raises(HttpError):
            services.get_revision(profile=profile, revision_id=revision.pk, edit=True)
        assert services.list_elaborati(profile=profile)["total"] == 0
    assert services.list_elaborati(profile=owner)["total"] == 1
    ProjectMember.objects.filter(project=project, profile=owner).update(disabled=True)
    assert services.list_elaborati(profile=owner)["total"] == 0
    assert process_job(revision.jobs.get().pk)
    assert revision.jobs.get().state == "failed"


def test_evidence_has_stable_source_hashes_context_and_no_cross_project_data(site):
    project, owner, _, outsider, post = site
    secret = Project.objects.create(
        workspace=outsider.workspace, name="Segreto", date_start=date.today(), created_by=outsider
    )
    ProjectPost.objects.create(
        project=secret, author=outsider, text="DATO PRIVATO DI ALTRA AZIENDA"
    )
    revision = create(site)
    a = build_evidence(profile=owner, elaborato=revision.elaborato)
    b = build_evidence(profile=owner, elaborato=revision.elaborato)
    assert [s["hash"] for s in a["sources"]] == [s["hash"] for s in b["sources"]]
    assert f"post:{post.pk}" in {s["id"] for s in a["sources"]}
    assert "DATO PRIVATO" not in json.dumps(a)
    assert all(s["data"]["presence"] == "unknown" for s in a["sources"] if s["kind"] == "member")
    assert any(s["data"].get("post_id") == post.pk for s in a["sources"] if s["kind"] == "event")


def test_generation_has_three_separate_passes_and_quality_hash(site, provider):
    revision = generate(site)
    assert revision.editor_doc["type"] == "doc" and revision.version == 2
    assert revision.quality["passed"] and revision.quality["content_hash"] == digest(
        revision.editor_doc
    )
    assert [stage for stage, _ in provider] == [
        "document_reasoning",
        "document_composition",
        "document_quality",
    ]
    assert revision.jobs.get().state == "completed"
    assert not process_job(revision.jobs.get().pk), (
        "Completed jobs must never generate a second paid request"
    )


def test_editor_rejects_unknown_sources_html_external_images_and_scripts(site, provider):
    revision = generate(site)
    for node in [
        {"type": "image", "attrs": {"src": "http://127.0.0.1/secrets"}},
        {"type": "paragraph", "attrs": {"sourceIds": ["post:999999"]}},
        {"type": "paragraph", "attrs": {"onclick": "alert(1)"}},
        {
            "type": "text",
            "text": "link",
            "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
        },
    ]:
        with pytest.raises(ValueError):
            validate_editor(
                {"type": "doc", "content": [node]}, revision.evidence, revision.template_snapshot
            )
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"sectionKey": "section_1"},
                "content": [{"type": "text", "text": "Bianchi era presente"}],
            }
        ],
    }
    assert any(
        i["severity"] == "blocking"
        for i in local_quality(doc, revision.evidence, revision.template_snapshot)
    )


def test_edit_uses_optimistic_lock_and_invalidates_quality(site, provider):
    revision = generate(site)
    owner = site[1]
    revision.editor_doc["content"][1]["content"][0]["text"] += " Esito da confermare."
    changed = services.save_revision(
        profile=owner,
        revision_id=revision.pk,
        payload=SaveRequest(version=2, editor_doc=revision.editor_doc),
    )
    assert changed.version == 3 and changed.quality["needs_verification"]
    with pytest.raises(HttpError) as exc:
        services.save_revision(
            profile=owner,
            revision_id=revision.pk,
            payload=SaveRequest(version=2, editor_doc=revision.editor_doc),
        )
    assert exc.value.status_code == 409


def test_tiptap_numbered_list_can_save_preview_and_publish(site, provider, monkeypatch):
    from copy import deepcopy

    from edilcloud.modules.elaborati.renderer import render_html

    revision = generate(site)
    item = deepcopy(revision.editor_doc["content"][1])
    listing = {
        "type": "orderedList",
        "attrs": {"start": 3, "type": None},
        "content": [{"type": "listItem", "content": [item]}],
    }
    revision.editor_doc["content"].append(listing)
    before_open = deepcopy(revision.editor_doc)
    del before_open["content"][-1]["attrs"]["type"]
    assert editor_equivalent(before_open, revision.editor_doc)

    owner = site[1]
    client = Client()
    token = login_and_get_token(email=owner.user.email, password="test123")
    response = client.patch(
        f"/api/v1/elaborati/revisions/{revision.pk}",
        data=json.dumps({"version": revision.version, "editor_doc": revision.editor_doc}),
        content_type="application/json",
        **auth_header(token),
    )
    assert response.status_code == 200, response.content
    revision.refresh_from_db()
    assert revision.editor_doc["content"][-1]["attrs"] == {"start": 3, "type": None}
    assert '<ol start="3">' in render_html(revision=revision, profile=owner)

    # Exercise preview and exact-byte Drive publication using the saved editor
    # document; no provider/network/rendering dependency is needed for this gate.
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-list-regression"
    )
    revision = prepare(site, revision)
    frozen = publish_revision(
        profile=owner,
        revision_id=revision.pk,
        version=revision.version,
        preview_hash=revision.preview_hash,
    )
    assert frozen.state == "published"
    with frozen.drive_document.document.open("rb") as stream:
        assert stream.read() == b"%PDF-list-regression"


def test_numbered_list_types_preserve_formatting_and_reject_unsafe_attributes(site, provider):
    from edilcloud.modules.elaborati.renderer import render_html

    revision = generate(site)
    listing = {"type": "orderedList", "attrs": {"start": 2}, "content": []}
    revision.editor_doc["content"].append(listing)
    for style in (None, "1", "a", "A", "i", "I"):
        listing["attrs"]["type"] = style
        validate_editor(revision.editor_doc, revision.evidence, revision.template_snapshot)
        expected = f'<ol start="2" type="{style}">' if style else '<ol start="2">'
        assert expected in render_html(revision=revision, profile=site[1])
    for invalid in ([], {}, True, 1, "", 'a" onclick="alert(1)', "javascript:alert(1)"):
        listing["attrs"]["type"] = invalid
        with pytest.raises(ValueError):
            validate_editor(revision.editor_doc, revision.evidence, revision.template_snapshot)
    listing["attrs"] = {"start": 2, "type": None, "onclick": "alert(1)"}
    with pytest.raises(ValueError):
        validate_editor(revision.editor_doc, revision.evidence, revision.template_snapshot)


def test_editor_proposal_requires_acceptance_and_cannot_apply_after_later_edit(site, provider):
    revision = generate(site)
    owner = site[1]
    request = ActionRequest(
        idempotency_key=uuid.uuid4(),
        version=revision.version,
        action="rewrite",
        section_key="section_1",
    )
    job = services.request_action(profile=owner, revision_id=revision.pk, payload=request)
    process_job(job.pk)
    job.refresh_from_db()
    revision.refresh_from_db()
    assert job.result["requires_acceptance"] and revision.version == 2
    accepted = services.accept_proposal(
        profile=owner, revision_id=revision.pk, version=2, job_id=job.pk
    )
    assert accepted.version == 3 and not accepted.quality["passed"]
    with pytest.raises(HttpError):
        services.accept_proposal(profile=owner, revision_id=revision.pk, version=3, job_id=job.pk)


def test_expired_worker_is_failed_without_automatically_replaying_provider(site):
    revision = create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() - timedelta(minutes=1)
    job.save()
    assert expire_jobs() == 1
    assert not process_job(job.pk)
    job.refresh_from_db()
    assert job.error_code == "WORKER_INTERRUPTED"


def test_missing_provider_fails_without_fake_document(site):
    revision = create(site)
    process_job(revision.jobs.get().pk)
    revision.refresh_from_db()
    assert not revision.editor_doc
    assert revision.jobs.get().state == "failed"


def test_explicit_declaration_retains_author_and_source(site, provider):
    revision = generate(site)
    revision = services.add_declaration(
        profile=site[1],
        revision_id=revision.pk,
        version=2,
        text="Dichiaro di aver verificato il locale tecnico con Bianchi.",
    )
    declaration = next(s for s in revision.evidence["sources"] if s["kind"] == "declaration")
    assert declaration["data"]["declared_by"] == "Laura Verdi"
    assert declaration["data"]["nature"] == "reported" and revision.version == 3


def prepare(site, revision, *, signed=False):
    if signed:
        services.save_signature(
            user=site[1].user, strokes=[[[0.1, 0.1], [0.3, 0.6], [0.6, 0.2], [0.9, 0.8]]]
        )
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(),
            version=revision.version,
            action="preview",
            apply_signature=signed,
            signature_confirmation=signed,
        ),
    )
    process_job(job.pk)
    revision.refresh_from_db()
    job.refresh_from_db()
    assert job.state == "completed", job.error_message
    return revision


def test_publication_preserves_exact_pdf_signature_confirmation_and_revision_history(
    site, provider, monkeypatch
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf",
        lambda **kwargs: b"%PDF-test-exact-server-render",
    )
    revision = prepare(site, generate(site), signed=True)
    owner = site[1]
    with pytest.raises(HttpError):
        publish_revision(
            profile=owner, revision_id=revision.pk, version=2, preview_hash=revision.preview_hash
        )
    frozen = publish_revision(
        profile=owner,
        revision_id=revision.pk,
        version=2,
        preview_hash=revision.preview_hash,
        confirm_signature=True,
    )
    assert frozen.state == "signed" and frozen.signature_audit["user_id"] == owner.user_id
    assert frozen.pdf_hash == hashlib.sha256(b"%PDF-test-exact-server-render").hexdigest()
    with frozen.drive_document.document.open("rb") as stream:
        assert stream.read() == b"%PDF-test-exact-server-render"
    assert "Elaborati pubblicati" in frozen.drive_document.folder.path
    with pytest.raises(HttpError):
        services.save_revision(
            profile=owner,
            revision_id=frozen.pk,
            payload=SaveRequest(version=2, editor_doc=frozen.editor_doc),
        )
    assert services.list_elaborati(profile=site[2])["total"] == 1, (
        "Active workers can read the publication"
    )
    next_revision = services.new_revision(profile=owner, revision_id=frozen.pk)
    assert (
        next_revision.number == 1
        and not next_revision.signature_audit
        and not next_revision.preview_file
    )
    assert not next_revision.published_at and next_revision.state == "draft"
    assert services.new_revision(profile=owner, revision_id=frozen.pk).pk == next_revision.pk
    next_revision = prepare(site, next_revision)
    publish_revision(
        profile=owner,
        revision_id=next_revision.pk,
        version=1,
        preview_hash=next_revision.preview_hash,
    )
    frozen.refresh_from_db()
    assert frozen.state == "superseded" and frozen.signature_audit
    assert "Storico" in frozen.drive_document.folder.path
    assert frozen.pdf_hash == hashlib.sha256(b"%PDF-test-exact-server-render").hexdigest()


def test_signature_coordinates_are_private_bounded_and_transparent(site):
    with pytest.raises(HttpError):
        services.save_signature(user=site[1].user, strokes=[[[0, 0], [float("nan"), 1]]])
    signature = services.save_signature(
        user=site[1].user, strokes=[[[0, 0], [0.2, 0.3], [0.4, 0.2], [0.9, 0.7]]]
    )
    with pytest.raises(ValueError):
        signature.image.url
    from PIL import Image

    with signature.image.open("rb") as stream:
        image = Image.open(stream)
        assert image.mode == "RGBA"
        assert image.getpixel((1199, 399))[3] == 0


def test_real_chromium_pdf_is_valid_and_escapes_untrusted_text(site, provider, settings):
    from pathlib import Path

    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if chrome.exists():
        settings.ELABORATI_CHROMIUM_EXECUTABLE = str(chrome)
    revision = generate(site)
    revision.editor_doc["content"][1]["content"][0]["text"] = (
        '<script>fetch("https://evil.example")</script>'
    )
    from edilcloud.modules.elaborati.renderer import render_html, render_pdf

    markup = render_html(revision=revision, profile=site[1])
    assert "&lt;script&gt;" in markup and "<script>fetch" not in markup
    output = render_pdf(revision=revision, profile=site[1])
    assert output.startswith(b"%PDF") and len(output) > 2000
    import pypdfium2

    with pypdfium2.PdfDocument(output) as pdf:
        # The reference layout flows sources into available space, without a
        # compulsory extra page for this deliberately short fixture.
        assert len(pdf) >= 1
        page = pdf[0]
        text = page.get_textpage().get_text_range()
        assert "Residenza" in text


def test_http_options_create_permissions_and_signature_isolation(site):
    from django.core.cache import cache

    cache.clear()
    client = Client()
    owner_token = login_and_get_token(email=site[1].email, password="test123")
    worker_token = login_and_get_token(email=site[2].email, password="test123")
    root = "/api/v1/elaborati"
    options = client.get(f"{root}/options", **auth_header(owner_token))
    assert options.status_code == 200 and len(options.json()["templates"]) == 6
    assert options.json()["projects"][0]["can_create"]
    assert not client.get(f"{root}/options", **auth_header(worker_token)).json()["projects"][0][
        "can_create"
    ]
    assert client.get(root).status_code == 401
    services.save_signature(
        user=site[1].user, strokes=[[[0, 0], [0.2, 0.3], [0.4, 0.2], [0.9, 0.7]]]
    )
    assert client.get(f"{root}/signature", **auth_header(owner_token)).json()["enrolled"]
    assert not client.get(f"{root}/signature", **auth_header(worker_token)).json()["enrolled"]


def test_action_retry_remains_idempotent_after_generation_changed_version(site, provider):
    revision = generate(site)
    request = ActionRequest(
        idempotency_key=uuid.uuid4(), version=revision.version, action="generate"
    )
    job = services.request_action(profile=site[1], revision_id=revision.pk, payload=request)
    process_job(job.pk)
    duplicate = services.request_action(profile=site[1], revision_id=revision.pk, payload=request)
    assert duplicate.pk == job.pk
    assert DocumentJob.objects.filter(idempotency_key=request.idempotency_key).count() == 1


def test_existing_drive_endpoints_cannot_overwrite_or_delete_published_pdf(
    site, provider, monkeypatch
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-frozen"
    )
    revision = prepare(site, generate(site))
    frozen = publish_revision(
        profile=site[1],
        revision_id=revision.pk,
        version=revision.version,
        preview_hash=revision.preview_hash,
    )
    from edilcloud.modules.projects.services import update_project_document, delete_project_document

    with pytest.raises(ValueError, match="immutabile"):
        update_project_document(
            profile=site[1],
            document_id=frozen.drive_document_id,
            uploaded_file=ContentFile(b"altered", name="other.pdf"),
        )
    with pytest.raises(ValueError, match="storico"):
        delete_project_document(profile=site[1], document_id=frozen.drive_document_id)


def test_provider_uses_exact_model_high_structured_schema_and_accounts_incomplete_response(
    site, settings, monkeypatch
):
    import httpx
    from edilcloud.modules.elaborati.provider import DocumentProviderError, structured_response

    settings.OPENAI_API_KEY = "test-private-key"
    revision = create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    captured = []
    original = httpx.Client

    def response(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-incomplete-test",
                "status": "incomplete",
                "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
            },
        )

    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(response)),
    )
    with pytest.raises(DocumentProviderError, match="interrotta"):
        structured_response(
            job=job,
            stage="document_reasoning",
            schema=ReasoningResult,
            instructions="Safe instructions",
            data={"synthetic": True},
        )
    assert captured[0]["model"] == "gpt-6-luna" and captured[0]["reasoning"]["effort"] == "high"
    assert captured[0]["store"] is False
    assert "max_output_tokens" not in captured[0]
    assert captured[0]["text"]["format"]["strict"] is True
    assert captured[0]["text"]["format"]["schema"]["additionalProperties"] is False
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 50
    job.refresh_from_db()
    assert job.consumed_tokens == 50
    from edilcloud.modules.billing.services import (
        get_workspace_billing_account,
        calculate_account_ai_usage,
    )

    assert (
        calculate_account_ai_usage(get_workspace_billing_account(site[0].workspace))["used"] == 50
    )


def test_large_input_is_counted_before_a_billable_request_instead_of_guessing_bytes(
    site, settings, monkeypatch
):
    import httpx
    from edilcloud.modules.elaborati.provider import structured_response

    settings.OPENAI_API_KEY = "test-private-key"
    revision = create(site)
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.reserved_tokens = 128_500
    job.save()
    paths = []
    original = httpx.Client

    def reply(request):
        paths.append(request.url.path)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(
                200, json={"object": "response.input_tokens", "input_tokens": 100}
            )
        return httpx.Response(
            200,
            json={
                "id": "counted-result",
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "facts": [],
                                        "duplicates": [],
                                        "contradictions": [],
                                        "missing_data": [],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )
    structured_response(
        job=job,
        stage="document_reasoning",
        schema=ReasoningResult,
        instructions="test",
        data={"synthetic": "a" * 10000},
    )
    assert paths == ["/v1/responses/input_tokens", "/v1/responses"]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 120


def test_sources_reuse_only_current_document_excerpts_and_never_stale_replaced_files(site):
    from edilcloud.modules.projects.models import ProjectDocument
    from edilcloud.modules.assistant.models import (
        ProjectAssistantState,
        ProjectAssistantChunkSource,
        ProjectAssistantChunkMap,
    )
    from edilcloud.modules.elaborati.document_sources import document_excerpts

    project = site[0]
    document = ProjectDocument.objects.create(
        project=project,
        title="Verbale fonte",
        document=ContentFile(b"synthetic", name="source.txt"),
    )
    state = ProjectAssistantState.objects.create(
        project=project, container_tag="elaborati-source-test"
    )
    source = ProjectAssistantChunkSource.objects.create(
        project=project,
        assistant_state=state,
        source_key=f"document:{document.pk}",
        source_type="document",
        is_indexed=True,
        last_indexed_at=timezone.now(),
    )
    chunk = ProjectAssistantChunkMap.objects.create(
        project=project,
        assistant_state=state,
        chunk_source=source,
        source_key=source.source_key,
        source_type="document",
        point_id=str(uuid.uuid4()),
        document_id=document.pk,
        source_updated_at=document.updated_at,
        content="Decisione registrata nel verbale.",
        extracted_char_count=31,
        page_reference=2,
    )
    extracted = document_excerpts(project.pk, [document])
    assert extracted[document.pk][0]["page"] == 2
    assert "Decisione registrata" in extracted[document.pk][0]["text"]
    chunk.source_updated_at = document.updated_at - timedelta(seconds=1)
    chunk.save()
    assert not document_excerpts(project.pk, [document])


def test_published_project_can_follow_existing_purge_lifecycle(site, provider, monkeypatch):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-frozen"
    )
    revision = prepare(site, generate(site))
    publish_revision(
        profile=site[1],
        revision_id=revision.pk,
        version=revision.version,
        preview_hash=revision.preview_hash,
    )
    project_id = site[0].pk
    site[0].delete()
    assert not Project.objects.filter(pk=project_id).exists()


def test_private_storage_override_and_orphan_cleanup_preserve_active_and_recent_files(site):
    import os
    from edilcloud.modules.elaborati.storage import private_document_storage
    from edilcloud.modules.elaborati.maintenance import cleanup_orphans

    signature = services.save_signature(
        user=site[1].user, strokes=[[[0, 0], [0.2, 0.3], [0.4, 0.2], [0.9, 0.7]]]
    )
    storage = private_document_storage()
    old = storage.save("elaborati/previews/orphan.pdf", ContentFile(b"orphan"))
    recent = storage.save("elaborati/previews/recent.pdf", ContentFile(b"recent"))
    yesterday = (timezone.now() - timedelta(days=2)).timestamp()
    os.utime(storage.path(old), (yesterday, yesterday))
    os.utime(signature.image.path, (yesterday, yesterday))
    assert old in cleanup_orphans(dry_run=True) and storage.exists(old)
    assert old in cleanup_orphans(dry_run=False) and not storage.exists(old)
    assert storage.exists(recent) and storage.exists(signature.image.name)
    assert str(signature.image.path).startswith(str(storage.location))
