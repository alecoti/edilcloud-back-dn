import json
import struct
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from edilcloud.modules.projects.model3d import inspect_glb
from edilcloud.modules.projects.models import (
    PostKind, Project, ProjectDocument, ProjectDocumentKind, ProjectDrawingPin,
    ProjectMember, ProjectMemberStatus, ProjectModel3D, ProjectModelPin, ProjectPost,
    ProjectTask,
)
from edilcloud.modules.workspaces.models import WorkspaceRole
from tests.test_projects_api import auth_headers, create_workspace_profile


def sample_glb(*, external_resource=False, vertex_count=3):
    binary = struct.pack("<9f3H", 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 1, 2) + b"\0\0"
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": vertex_count, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    if external_resource:
        gltf["images"] = [{"uri": "https://example.com/texture.png"}]
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
        + struct.pack("<II", len(binary), 0x004E4942) + binary
    )


def test_model_glb_validation_rejects_external_and_unbounded_geometry():
    assert inspect_glb(SimpleUploadedFile("sample.glb", sample_glb())) == (3, 1)
    with pytest.raises(ValueError, match="risorse"):
        inspect_glb(SimpleUploadedFile("external.glb", sample_glb(external_resource=True)))
    with pytest.raises(ValueError, match="alleggerita"):
        inspect_glb(SimpleUploadedFile("huge.glb", sample_glb(vertex_count=350_001)))
    with pytest.raises(ValueError, match="GLB 2.0"):
        inspect_glb(SimpleUploadedFile("broken.glb", b"not-a-glb" + b"\0" * 40))


@pytest.mark.django_db(transaction=True)
def test_model3d_pins_persist_and_deleting_trial_preserves_2d(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="project.model3d@example.com", password="devpass123",
    )
    project = Project.objects.create(
        workspace=profile.workspace, created_by=profile, name="Prova modello",
        date_start=date.today(), date_end=date.today() + timedelta(days=10),
    )
    ProjectMember.objects.create(
        project=project, profile=profile, role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    task = ProjectTask.objects.create(
        project=project, name="Copertura", date_start=date.today(),
        date_end=date.today() + timedelta(days=2),
    )
    post = ProjectPost.objects.create(
        project=project, task=task, author=profile, text="Problema sul solaio",
        post_kind=PostKind.ISSUE, alert=True,
    )
    drawing = ProjectDocument.objects.create(
        project=project, title="Tavola 2D", document="drawings/2d.png",
        document_kind=ProjectDocumentKind.DRAWING,
    )
    drawing_pin = ProjectDrawingPin.objects.create(
        project=project, drawing_document=drawing, post=post,
        created_by=profile, x=0.2, y=0.4,
    )
    headers = auth_headers(client, email="project.model3d@example.com", password="devpass123")
    assert client.get(f"/api/v1/projects/{project.id}/models-3d").status_code == 401

    uploaded = client.post(
        f"/api/v1/projects/{project.id}/models-3d",
        {"model": SimpleUploadedFile("sample.glb", sample_glb(), content_type="model/gltf-binary"),
         "title": "Prova 3D eliminabile"}, **headers,
    )
    assert uploaded.status_code == 201, uploaded.content
    model_id = uploaded.json()["id"]
    model = ProjectModel3D.objects.get(id=model_id)
    file_name = model.file.name
    assert model.file.storage.exists(file_name)
    assert uploaded.json()["triangle_count"] == 1

    file_response = client.get(
        f"/api/v1/projects/{project.id}/models-3d/{model_id}/file", **headers,
    )
    assert file_response.status_code == 200
    assert b"".join(file_response.streaming_content) == sample_glb()

    created = client.post(
        f"/api/v1/projects/{project.id}/model-pins",
        data=json.dumps({"model": model_id, "post": post.id, "x": 0.4, "y": 1.2, "z": 0.0,
                         "label": "Nodo solaio"}),
        content_type="application/json", **headers,
    )
    assert created.status_code == 201, created.content
    pin_id = created.json()["id"]
    assert ProjectModelPin.objects.get(id=pin_id).model_id == model_id
    listed = client.get(f"/api/v1/projects/{project.id}/model-pins", **headers)
    assert listed.status_code == 200
    assert listed.json()[0]["post"]["model_pin_tags"][0]["id"] == pin_id
    assert listed.json()[0]["status"] == "open"

    bad_coordinates = client.post(
        f"/api/v1/projects/{project.id}/model-pins",
        data=json.dumps({"model": model_id, "post": post.id, "x": 1e8, "y": 0, "z": 0}),
        content_type="application/json", **headers,
    )
    assert bad_coordinates.status_code == 400

    deleted = client.delete(f"/api/v1/projects/{project.id}/models-3d/{model_id}", **headers)
    assert deleted.status_code == 204
    assert not ProjectModel3D.objects.filter(id=model_id).exists()
    assert not ProjectModelPin.objects.filter(id=pin_id).exists()
    assert not model.file.storage.exists(file_name)
    assert ProjectDrawingPin.objects.filter(id=drawing_pin.id).exists()
    assert ProjectPost.objects.filter(id=post.id).exists()
