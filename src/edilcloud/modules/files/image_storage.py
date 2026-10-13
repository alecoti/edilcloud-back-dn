"""Precomputed, versioned image previews; originals remain downloadable unchanged."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from threading import RLock
from io import BytesIO

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
PREVIEW_DIMENSIONS = (320, 640, 960, 1920)
PREVIEW_ROOT = "image-previews/v1"
_manifest_cache_lock = RLock()


def metadata_variants(metadata):
    return sorted([*metadata.get("variants", []), *metadata.get("extra_variants", [])], key=lambda item: item["width"])


class OptimizedImageStorage(FileSystemStorage):
    """All image upload paths share this pipeline, including avatars and demo imports."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._image_manifests: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()

    def _manifest_name(self, name: str) -> str:
        key = hashlib.sha256(name.encode()).hexdigest()
        return f"{PREVIEW_ROOT}/{key}/manifest.json"

    @staticmethod
    def _valid_metadata(metadata: object, name: str) -> bool:
        if not isinstance(metadata, dict) or metadata.get("source") != name:
            return False
        version = metadata.get("version")
        variants = metadata.get("variants")
        extra = metadata.get("extra_variants", [])
        if not isinstance(version, str) or len(version) != 24 or any(c not in "0123456789abcdef" for c in version):
            return False
        if not isinstance(variants, list) or len(variants) > 3 or not isinstance(extra, list) or len(extra) > 1:
            return False
        return all(isinstance(v, dict) and isinstance(v.get("name"), str)
                   and v["name"].startswith(PREVIEW_ROOT + "/")
                   and ".." not in Path(v["name"]).parts
                   and all(isinstance(v.get(k), int) and v[k] > 0 for k in ("width", "height", "size"))
                   for v in [*variants, *extra])

    def _remember(self, name: str, metadata: dict) -> dict:
        key = (self.location, name)
        with _manifest_cache_lock:
            self._image_manifests[key] = (time.monotonic() + (3600 if metadata else 30), metadata)
            self._image_manifests.move_to_end(key)
            while len(self._image_manifests) > 512:
                self._image_manifests.popitem(last=False)
        return metadata

    def image_metadata(self, name: str) -> dict:
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            return {}
        key = (self.location, name)
        with _manifest_cache_lock:
            cached = self._image_manifests.get(key)
            if cached and cached[0] > time.monotonic():
                self._image_manifests.move_to_end(key)
                return cached[1]
        try:
            with open(self.path(self._manifest_name(name)), encoding="utf-8") as handle:
                metadata = json.load(handle)
            if not self._valid_metadata(metadata, name):
                return self._remember(name, {})
        except (OSError, ValueError):
            metadata = {}
        return self._remember(name, metadata)

    def _save(self, name, content):
        saved_name = super()._save(name, content)
        if getattr(settings, "MEDIA_OPTIMIZATION_ENABLED", True) and getattr(settings, "MEDIA_IMAGE_PREVIEWS_ENABLED", True):
            try:
                self.prepare_image_previews(saved_name)
            except Exception:
                # A failed preview must never lose or reject a successful original upload.
                logger.exception("image.preview.failed", extra={"event": "image.preview.failed"})
        return saved_name

    def prepare_image_previews(self, name: str, *, force: bool = False) -> dict:
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES or name.startswith(PREVIEW_ROOT + "/"):
            return {}
        previous = self.image_metadata(name)
        if previous and not force:
            self._share_content(previous)
            return previous
        source_path = Path(self.path(name))
        source_bytes = source_path.stat().st_size
        digest = hashlib.sha256()
        with source_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        version = digest.hexdigest()[:24]
        folder = Path(self.path(self._manifest_name(name))).parent
        content_folder = Path(self.path(f"{PREVIEW_ROOT}/content/{version}"))
        if not force:
            try:
                shared = json.loads((content_folder / "manifest.json").read_text(encoding="utf-8"))
                metadata = {**shared, "source": name} if isinstance(shared, dict) else {}
                if self._valid_metadata(metadata, name) and metadata.get("version") == version and metadata.get("source_bytes") == source_bytes:
                    folder.mkdir(parents=True, exist_ok=True)
                    self._atomic_write(folder / "manifest.json", json.dumps(metadata).encode())
                    return self._remember(name, metadata)
            except (OSError, ValueError):
                pass
        # Bound work for malformed/decompression-bomb input; upload itself remains intact.
        try:
            opened = Image.open(source_path)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            return {}
        with opened as source:
            if getattr(source, "n_frames", 1) > 1 or source.width * source.height > 40_000_000:
                return {}
            source.draft("RGB", (1920, 1920))
            image = ImageOps.exif_transpose(source)
            image.load()
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        folder.mkdir(parents=True, exist_ok=True)
        content_folder.mkdir(parents=True, exist_ok=True)
        variants = []
        previous_dimensions = None
        for dimension in PREVIEW_DIMENSIONS:
            if dimension == 640 and max(image.size) <= 640:
                continue
            preview = image.copy()
            preview.thumbnail((dimension, dimension), Image.Resampling.LANCZOS)
            if preview.size == previous_dimensions:
                continue
            if dimension != 640:
                previous_dimensions = preview.size
            output = BytesIO()
            preview.save(output, "WEBP", quality=82, method=4)
            data = output.getvalue()
            if len(data) >= source_bytes:
                continue
            filename = f"{dimension}.webp"
            self._atomic_write(content_folder / filename, data)
            relative = str((content_folder / filename).relative_to(Path(self.location))).replace(os.sep, "/")
            variants.append({"name": relative, "width": preview.width, "height": preview.height, "size": len(data)})
        # Existing readers accept at most three variants; the extension remains
        # separate so a rollback still serves all original previews correctly.
        metadata = {"source": name, "source_bytes": source_bytes, "version": version,
                    "variants": [v for v in variants if Path(v["name"]).name != "640.webp"],
                    "extra_variants": [v for v in variants if Path(v["name"]).name == "640.webp"]}
        self._atomic_write(folder / "manifest.json", json.dumps(metadata).encode())
        self._share_content(metadata)
        return self._remember(name, metadata)

    def _share_content(self, metadata: dict) -> None:
        folder = Path(self.path(f"{PREVIEW_ROOT}/content/{metadata['version']}"))
        if (folder / "manifest.json").exists():
            try:
                existing = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                if existing.get("extra_variants") or not metadata.get("extra_variants"):
                    return
            except (OSError, ValueError):
                pass
        folder.mkdir(parents=True, exist_ok=True)
        shared = {key: value for key, value in metadata.items() if key != "source"}
        self._atomic_write(folder / "manifest.json", json.dumps(shared).encode())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".preview-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def extend_image_previews(self, name: str) -> dict:
        """Add 640px bytes without rewriting originals or existing preview URLs."""
        metadata = self.image_metadata(name)
        if not metadata or metadata.get("extra_variants") or not metadata.get("variants"):
            return metadata
        if max(max(v["width"], v["height"]) for v in metadata["variants"]) <= 640:
            return metadata
        path = Path(self.path(name))
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()[:24]
        if digest != metadata["version"] or path.stat().st_size != metadata.get("source_bytes"):
            raise ValueError("Preview source changed; regenerate its manifest before extending it.")
        folder = Path(self.path(f"{PREVIEW_ROOT}/content/{digest}"))
        try:
            shared = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            shared = {}
        extra = shared.get("extra_variants", [])
        if extra and all(Path(self.path(v["name"])).is_file() for v in extra):
            metadata = {**metadata, "extra_variants": extra}
        else:
            with Image.open(path) as source:
                source.draft("RGB", (1280, 1280))
                image = ImageOps.exif_transpose(source)
                image.load()
                image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, "WEBP", quality=82, method=4)
            data = output.getvalue()
            if len(data) >= metadata["source_bytes"]:
                return metadata
            folder.mkdir(parents=True, exist_ok=True)
            preview = folder / "640.webp"
            self._atomic_write(preview, data)
            extra = [{"name": preview.relative_to(Path(self.location)).as_posix(),
                      "width": image.width, "height": image.height, "size": len(data)}]
            metadata = {**metadata, "extra_variants": extra}
            self._share_content(metadata)
        self._atomic_write(Path(self.path(self._manifest_name(name))), json.dumps(metadata).encode())
        return self._remember(name, metadata)


def image_variant_payload(file_field) -> dict:
    if not file_field or not callable(getattr(file_field.storage, "image_metadata", None)):
        return {}
    metadata = file_field.storage.image_metadata(file_field.name)
    variants = [
        {"url": file_field.storage.url(item["name"]), "width": item["width"],
         "height": item["height"], "size": item["size"]}
        for item in metadata_variants(metadata)
    ]
    return {"image_variants": variants} if variants else {}
