import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from edilcloud.modules.projects.models import (
    PostComment,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole


def auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


def login_and_get_token(*, email: str, password: str) -> str:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": email,
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()["token"]


@pytest.mark.django_db
def test_global_search_returns_workspace_results_without_legacy_dependency():
    user_model = get_user_model()
    owner = user_model.objects.create_user(
        email="search-owner@example.com",
        password="devpass123",
        username="search-owner",
        first_name="Elena",
        last_name="Conti",
        language="it",
    )
    teammate = user_model.objects.create_user(
        email="search-teammate@example.com",
        password="devpass123",
        username="search-teammate",
        first_name="Fabio",
        last_name="Riva",
        language="it",
    )
    outsider = user_model.objects.create_user(
        email="search-outsider@example.com",
        password="devpass123",
        username="search-outsider",
        first_name="Lia",
        last_name="Bianchi",
        language="it",
    )

    workspace = Workspace.objects.create(name="Impresa Naviglio")
    outsider_workspace = Workspace.objects.create(name="Impresa Esterna")
    owner_profile = Profile.objects.create(
        workspace=workspace,
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Elena",
        last_name="Conti",
        language="it",
        position="Direttrice lavori",
    )
    teammate_profile = Profile.objects.create(
        workspace=workspace,
        user=teammate,
        email=teammate.email,
        role=WorkspaceRole.MANAGER,
        first_name="Fabio",
        last_name="Riva",
        language="it",
        position="Capocantiere",
    )
    outsider_profile = Profile.objects.create(
        workspace=outsider_workspace,
        user=outsider,
        email=outsider.email,
        role=WorkspaceRole.OWNER,
        first_name="Lia",
        last_name="Bianchi",
        language="it",
        position="Owner",
    )

    project = Project.objects.create(
        workspace=workspace,
        created_by=owner_profile,
        name="Residenza Naviglio Ponte",
        description="Riqualificazione completa del lotto principale.",
        address="Via del Naviglio 24, Milano",
        date_start="2026-03-01",
    )
    hidden_project = Project.objects.create(
        workspace=outsider_workspace,
        created_by=outsider_profile,
        name="Cantiere Segreto Legacy",
        description="Non deve comparire nella search.",
        address="Via Riservata 1, Torino",
        date_start="2026-02-10",
    )

    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    ProjectMember.objects.create(
        project=project,
        profile=teammate_profile,
        role=WorkspaceRole.MANAGER,
        status=ProjectMemberStatus.ACTIVE,
    )
    ProjectMember.objects.create(
        project=hidden_project,
        profile=outsider_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )

    task = ProjectTask.objects.create(
        project=project,
        name="Consolidamento ponte nord",
        date_start="2026-03-04",
        date_end="2026-03-19",
        progress=42,
        note="Verificare il getto prima del collaudo.",
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Tracciamento ponte nord",
        description="Posizionamento quote e verifica allineamenti.",
        datetime_start="2026-03-05T08:00:00+01:00",
        datetime_end="2026-03-05T12:00:00+01:00",
        note="Serve laser aggiornato.",
    )
    post = ProjectPost.objects.create(
        project=project,
        task=task,
        activity=activity,
        author=owner_profile,
        text="Aggiornamento Naviglio: ponte nord pronto per la casseratura.",
        post_kind="work-progress",
    )
    comment = PostComment.objects.create(
        post=post,
        author=teammate_profile,
        text="Ricevuto. Porto il materiale in cantiere entro le 07:30.",
    )
    document = ProjectDocument.objects.create(
        project=project,
        title="Capitolato Naviglio ponte nord",
        description="Documento operativo per il getto del solaio.",
        document=SimpleUploadedFile(
            "capitolato-naviglio.pdf",
            b"%PDF-1.4 search test",
            content_type="application/pdf",
        ),
    )
    photo = ProjectPhoto.objects.create(
        project=project,
        title="Disegno esecutivo Naviglio",
        photo=SimpleUploadedFile(
            "naviglio-drawing.jpg",
            b"binary-image",
            content_type="image/jpeg",
        ),
    )

    token = login_and_get_token(email=owner.email, password="devpass123")
    client = Client()
    response = client.get("/api/v1/search/global?q=naviglio&limit=4", **auth_header(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "naviglio"
    assert any(item["id"] == f"project:{project.id}" for item in payload["sections"]["projects"])
    assert any(item["id"] == f"task:{task.id}" for item in payload["sections"]["tasks"])
    assert any(item["id"] == f"activity:{activity.id}" for item in payload["sections"]["activities"])
    assert any(item["id"] == f"post:{post.id}" for item in payload["sections"]["updates"])
    assert any(item["id"] == f"document:{document.id}" for item in payload["sections"]["documents"])
    assert any(item["id"] == f"drawing:{photo.id}" for item in payload["sections"]["drawings"])
    assert any(
        item["id"] == f"person:{project.id}:{teammate_profile.id}"
        for item in payload["sections"]["people"]
    )

    serialized = json.dumps(payload)
    assert "Cantiere Segreto Legacy" not in serialized
    assert f"/dashboard/cantieri/{project.id}/overview" in serialized
    assert f"/dashboard/cantieri/{project.id}/documents?doc={document.id}" in serialized
    assert f"/dashboard/cantieri/{project.id}/tasks?activity={activity.id}&post={post.id}" in serialized
    assert comment.id


@pytest.mark.django_db
def test_global_search_category_filter_returns_only_requested_section():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        email="search-docs@example.com",
        password="devpass123",
        username="search-docs",
        first_name="Sara",
        last_name="Greco",
        language="it",
    )
    workspace = Workspace.objects.create(name="Studio Capitolati")
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Sara",
        last_name="Greco",
        language="it",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Palazzina Capitolato",
        description="Documentazione generale.",
        address="Via Roma 10",
        date_start="2026-01-15",
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    document = ProjectDocument.objects.create(
        project=project,
        title="Capitolato strutturale definitivo",
        description="Versione finale approvata.",
        document=SimpleUploadedFile(
            "capitolato-finale.pdf",
            b"%PDF-1.4 docs only",
            content_type="application/pdf",
        ),
    )
    ProjectTask.objects.create(
        project=project,
        name="Task che non deve uscire nel filtro documenti",
        date_start="2026-01-16",
        date_end="2026-01-20",
        progress=10,
    )

    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()
    response = client.get(
        "/api/v1/search/global?q=capitolato&category=documents&limit=5",
        **auth_header(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"]["documents"][0]["id"] == f"document:{document.id}"
    assert payload["sections"]["projects"] == []
    assert payload["sections"]["tasks"] == []
    assert payload["sections"]["activities"] == []
    assert payload["sections"]["updates"] == []
    assert payload["sections"]["drawings"] == []
    assert payload["sections"]["people"] == []


@pytest.mark.django_db
def test_global_search_prioritizes_title_matches_and_returns_snippets():
    user_model = get_user_model()
    user = user_model.objects.create_user(
        email="search-ranking@example.com",
        password="devpass123",
        username="search-ranking",
        first_name="Andrea",
        last_name="Riva",
        language="it",
    )
    workspace = Workspace.objects.create(name="Impianti Naviglio")
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Andrea",
        last_name="Riva",
        language="it",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Residenza Bilanciamento",
        description="Interventi su circuito nord e collaudi finali.",
        address="Via Torino 42",
        date_start="2026-02-20",
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    title_match_document = ProjectDocument.objects.create(
        project=project,
        title="Valvole bilanciamento circuito nord",
        description="Scheda tecnica con taratura consigliata e sequenza di collaudo finale.",
        document=SimpleUploadedFile(
            "valvole-bilanciamento.pdf",
            b"%PDF-1.4 title match",
            content_type="application/pdf",
        ),
    )
    description_match_document = ProjectDocument.objects.create(
        project=project,
        title="Scheda tecnica impianto idronico",
        description="Nel corpo documento trovi bilanciamento circuito nord, prerequisiti e prove di taratura.",
        document=SimpleUploadedFile(
            "impianto-idronico.pdf",
            b"%PDF-1.4 description match",
            content_type="application/pdf",
        ),
    )

    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()
    response = client.get(
        "/api/v1/search/global?q=bilanciamento%20circuito&limit=4&category=documents",
        **auth_header(token),
    )

    assert response.status_code == 200
    payload = response.json()
    documents = payload["sections"]["documents"]
    assert [item["id"] for item in documents[:2]] == [
        f"document:{title_match_document.id}",
        f"document:{description_match_document.id}",
    ]
    assert "taratura" in (documents[0]["snippet"] or "").lower()
    assert "bilanciamento circuito nord" in (documents[1]["snippet"] or "").lower()
