"""Isolated GLB pilot for project model pins."""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct

from django.db import transaction
from django.db.models import Count
from django.http import FileResponse

from edilcloud.modules.billing.services import assert_storage_quota_available
from edilcloud.modules.projects.models import ProjectModel3D, ProjectModelPin
from edilcloud.modules.projects.services import (
    can_edit_project,
    get_project_for_profile,
    get_project_with_team_context,
    project_posts_queryset,
    serialize_post_summary,
)
from edilcloud.modules.workspaces.models import Profile


MAX_GLB_BYTES = 25 * 1024 * 1024
MAX_VERTICES = 350_000
MAX_TRIANGLES = 500_000


def inspect_glb(uploaded_file) -> tuple[int, int]:
    if Path(uploaded_file.name).suffix.lower() != ".glb":
        raise ValueError("Per la prova 3D serve un file GLB autosufficiente.")
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size < 28 or size > MAX_GLB_BYTES:
        raise ValueError("Il modello GLB deve essere valido e non superare 25 MB.")
    uploaded_file.seek(0)
    header = uploaded_file.read(12)
    if len(header) != 12:
        raise ValueError("Intestazione GLB non valida.")
    magic, version, declared_size = struct.unpack("<4sII", header)
    if magic != b"glTF" or version != 2 or declared_size != size:
        raise ValueError("Serve un file GLB 2.0 valido.")
    chunk_header = uploaded_file.read(8)
    if len(chunk_header) != 8:
        raise ValueError("Struttura GLB incompleta.")
    json_size, chunk_type = struct.unpack("<II", chunk_header)
    if chunk_type != 0x4E4F534A or json_size > 2 * 1024 * 1024 or json_size + 20 > size:
        raise ValueError("Descrizione del modello GLB non valida.")
    try:
        gltf = json.loads(uploaded_file.read(json_size))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Descrizione del modello GLB non leggibile.") from exc
    finally:
        uploaded_file.seek(0)
    if not isinstance(gltf, dict) or not isinstance(gltf.get("asset"), dict) or gltf["asset"].get("version") != "2.0":
        raise ValueError("Serve un modello glTF 2.0.")
    if gltf.get("extensionsRequired"):
        raise ValueError("Questa prova non supporta estensioni GLB obbligatorie.")
    collections = ("nodes", "images", "buffers", "accessors", "meshes")
    if any(not isinstance(gltf.get(name, []), list) for name in collections):
        raise ValueError("Descrizione GLB non valida.")
    if any(not isinstance(item, dict) for name in collections for item in gltf.get(name, [])):
        raise ValueError("Descrizione GLB non valida.")
    if len(gltf.get("nodes", [])) > 2_000 or len(gltf.get("images", [])) > 100:
        raise ValueError("Modello troppo complesso per la prova 3D.")
    if any("uri" in item for item in gltf.get("buffers", [])) or any(
        "uri" in item and not str(item["uri"]).startswith("data:")
        for item in gltf.get("images", [])
    ):
        raise ValueError("Il GLB deve contenere tutte le risorse, senza file esterni.")
    accessors = gltf.get("accessors", [])
    vertex_count = triangle_count = 0
    try:
        for mesh in gltf.get("meshes", []):
            for primitive in mesh.get("primitives", []):
                if primitive.get("mode", 4) != 4:
                    continue
                positions = accessors[primitive["attributes"]["POSITION"]]["count"]
                indices = accessors[primitive["indices"]]["count"] if "indices" in primitive else positions
                vertex_count += int(positions)
                triangle_count += int(indices) // 3
    except (IndexError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Geometria GLB non valida.") from exc
    if vertex_count < 3 or triangle_count < 1:
        raise ValueError("Il modello deve contenere superfici triangolari selezionabili.")
    if vertex_count > MAX_VERTICES or triangle_count > MAX_TRIANGLES:
        raise ValueError("Modello troppo dettagliato: esporta una versione alleggerita.")
    return vertex_count, triangle_count


def serialize_model(model: ProjectModel3D, *, can_delete: bool) -> dict:
    return {
        "id": model.id,
        "project": model.project_id,
        "title": model.title,
        "format": "glb",
        "size": model.file_size,
        "vertex_count": model.vertex_count,
        "triangle_count": model.triangle_count,
        "pin_count": model.pin_count if hasattr(model, "pin_count") else model.pins.count(),
        "can_delete": can_delete,
        "created_at": model.created_at,
    }


def list_project_models(*, profile: Profile, project_id: int) -> list[dict]:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    models = project.models_3d.annotate(pin_count=Count("pins")).order_by("-created_at", "-id")
    return [serialize_model(model, can_delete=can_edit_project(membership)) for model in models]


def upload_project_model(*, profile: Profile, project_id: int, uploaded_file, title: str) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per caricare modelli 3D.")
    vertex_count, triangle_count = inspect_glb(uploaded_file)
    assert_storage_quota_available(project.workspace, incoming_bytes=uploaded_file.size)
    model = ProjectModel3D.objects.create(
        project=project,
        title=(title or Path(uploaded_file.name).stem).strip()[:255],
        file=uploaded_file,
        vertex_count=vertex_count,
        triangle_count=triangle_count,
        created_by=profile,
    )
    return serialize_model(model, can_delete=True)


def get_project_model_file(*, profile: Profile, project_id: int, model_id: int):
    project = get_project_for_profile(profile=profile, project_id=project_id)
    model = project.models_3d.filter(id=model_id).first()
    if model is None:
        raise ValueError("Modello 3D non trovato.")
    response = FileResponse(model.file.open("rb"), content_type="model/gltf-binary")
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def delete_project_model(*, profile: Profile, project_id: int, model_id: int) -> None:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    if not can_edit_project(membership):
        raise ValueError("Non hai permessi per eliminare modelli 3D.")
    model = project.models_3d.filter(id=model_id).first()
    if model is None:
        raise ValueError("Modello 3D non trovato.")
    storage, name = model.file.storage, model.file.name
    with transaction.atomic():
        model.delete()
        transaction.on_commit(lambda: storage.delete(name))


def normalize_world_coordinate(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Coordinata 3D {name} non valida.") from exc
    if not math.isfinite(number) or abs(number) > 10_000_000:
        raise ValueError(f"Coordinata 3D {name} non valida.")
    return number


def serialize_model_pin(pin: ProjectModelPin, *, membership) -> dict:
    status = "open" if pin.post.alert else "linked"
    return {
        "id": pin.id,
        "project": pin.project_id,
        "model": {"id": pin.model_id, "title": pin.model.title},
        "post": serialize_post_summary(post=pin.post, membership=membership),
        "x": pin.x,
        "y": pin.y,
        "z": pin.z,
        "label": pin.label,
        "status": status,
        "color_hex": "#b85b39" if status == "open" else "#355fc4",
        "created_at": pin.created_at,
    }


def model_pin_queryset():
    return ProjectModelPin.objects.select_related(
        "model", "post", "post__author", "post__author__workspace",
        "post__author__user", "post__project", "post__task", "post__activity",
    ).prefetch_related("post__attachments", "post__drawing_pins", "post__model_pins")


def list_project_model_pins(*, profile: Profile, project_id: int, model_id: int | None = None) -> list[dict]:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    pins = model_pin_queryset().filter(project=project)
    if model_id is not None:
        pins = pins.filter(model_id=model_id)
    return [serialize_model_pin(pin, membership=membership) for pin in pins]


def create_project_model_pin(
    *, profile: Profile, project_id: int, model_id: int, post_id: int,
    x: float, y: float, z: float, label: str = "",
) -> dict:
    project, membership, _members = get_project_with_team_context(
        profile=profile, project_id=project_id
    )
    model = project.models_3d.filter(id=model_id).first()
    if model is None:
        raise ValueError("Modello 3D non trovato nel progetto.")
    post = project_posts_queryset().filter(project=project, id=post_id, is_deleted=False).first()
    if post is None:
        raise ValueError("Post non trovato nel progetto.")
    pin = ProjectModelPin.objects.create(
        project=project,
        model=model,
        post=post,
        created_by=profile,
        x=normalize_world_coordinate(x, "x"),
        y=normalize_world_coordinate(y, "y"),
        z=normalize_world_coordinate(z, "z"),
        label=(label or "").strip()[:255],
    )
    return serialize_model_pin(model_pin_queryset().get(id=pin.id), membership=membership)


def delete_project_model_pin(*, profile: Profile, project_id: int, pin_id: int) -> None:
    project = get_project_for_profile(profile=profile, project_id=project_id)
    deleted, _ = ProjectModelPin.objects.filter(project=project, id=pin_id).delete()
    if not deleted:
        raise ValueError("Pin 3D non trovato.")
