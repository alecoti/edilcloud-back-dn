from datetime import date
import math
from io import BytesIO
import shutil
import struct
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from edilcloud.modules.files.media_optimizer import optimize_media_for_storage
from edilcloud.modules.projects.models import Project, ProjectMember, ProjectMemberStatus
from edilcloud.modules.workspaces.models import WorkspaceRole
from tests.test_projects_api import auth_headers, create_workspace_profile


def build_noisy_jpeg_bytes(*, width: int = 1600, height: int = 900) -> bytes:
    image = Image.effect_noise((width, height), 96).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=100, subsampling=0)
    return buffer.getvalue()


def build_wav_bytes(*, seconds: int = 2, sample_rate: int = 44100) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(seconds * sample_rate):
            sample = int(32767 * math.sin(2 * math.pi * 440 * (index / sample_rate)))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def test_optimize_media_for_storage_reduces_valid_jpeg_size():
    original_bytes = build_noisy_jpeg_bytes()
    uploaded = SimpleUploadedFile("cantiere.jpg", original_bytes, content_type="image/jpeg")

    optimized = optimize_media_for_storage(uploaded)

    assert optimized is not uploaded
    assert optimized.size < len(original_bytes)
    assert getattr(optimized, "content_type", "") == "image/jpeg"
    optimized.open()
    try:
        assert optimized.read(2) == b"\xff\xd8"
    finally:
        optimized.close()


def test_optimize_media_for_storage_leaves_invalid_fake_images_untouched():
    original_bytes = b"fake-image-content"
    uploaded = SimpleUploadedFile("avatar.png", original_bytes, content_type="image/png")

    optimized = optimize_media_for_storage(uploaded)

    assert optimized is uploaded
    optimized.seek(0)
    assert optimized.read() == original_bytes


def test_optimize_media_for_storage_transcodes_raw_wav_to_flac_when_ffmpeg_is_available():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg non disponibile in questo ambiente.")

    original_bytes = build_wav_bytes()
    uploaded = SimpleUploadedFile("nota-vocale.wav", original_bytes, content_type="audio/wav")

    optimized = optimize_media_for_storage(uploaded)

    assert optimized is not uploaded
    assert optimized.size < len(original_bytes)
    assert getattr(optimized, "content_type", "") == "audio/flac"
    assert str(getattr(optimized, "name", "")).endswith(".flac")
    optimized.close()


@pytest.mark.django_db
def test_project_document_upload_optimizes_image_documents_before_storage():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="media.optimizer@example.com",
        password="devpass123",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Media Optimizer",
        date_start=date(2026, 4, 1),
        date_end=date(2026, 5, 1),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="media.optimizer@example.com", password="devpass123")
    original_bytes = build_noisy_jpeg_bytes(width=1800, height=1200)

    response = client.post(
        f"/api/v1/projects/{project.id}/documents",
        data={
            "title": "Foto avanzamento",
            "description": "Upload foto di cantiere",
            "document": SimpleUploadedFile("avanzamento.jpg", original_bytes, content_type="image/jpeg"),
        },
        **headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["extension"] == "jpg"
    assert payload["size"] < len(original_bytes)
