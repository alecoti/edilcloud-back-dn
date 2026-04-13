from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
VECTOR_IMAGE_EXTENSIONS = {".svg", ".svgz"}
ANIMATED_IMAGE_EXTENSIONS = {".gif"}
AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wave",
    ".webm",
}
VIDEO_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}


class TemporaryOptimizedFile(File):
    """A temp-backed file that cleans itself up after Django persists it."""

    def __init__(self, *, temp_path: str | Path, storage_name: str, content_type: str = "") -> None:
        self._temp_path = Path(temp_path)
        self._temp_dir = self._temp_path.parent
        self._cleaned = False
        self._size = self._temp_path.stat().st_size
        handle = self._temp_path.open("rb")
        super().__init__(handle, name=storage_name)
        self.content_type = content_type

    @property
    def size(self) -> int:
        return self._size

    def open(self, mode: str | None = None):
        requested_mode = mode or "rb"
        if getattr(self, "file", None) is None or self.file.closed:
            self.file = self._temp_path.open(requested_mode)
        else:
            self.file.seek(0)
        return self

    def temporary_file_path(self) -> str:
        return str(self._temp_path)

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            self._temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            self._temp_dir.rmdir()
        except Exception:
            pass

    def __del__(self) -> None:
        self._cleanup()


def optimize_media_for_storage(uploaded_file):
    if uploaded_file is None or not getattr(settings, "MEDIA_OPTIMIZATION_ENABLED", True):
        return uploaded_file

    original_name = Path(getattr(uploaded_file, "name", "") or "upload").name
    suffix = Path(original_name).suffix.lower()
    content_type = _guess_content_type(uploaded_file, fallback_name=original_name)
    media_kind = _classify_media(content_type=content_type, suffix=suffix)

    if media_kind == "image":
        return _optimize_image(uploaded_file, original_name=original_name, content_type=content_type)
    if media_kind == "audio":
        return _optimize_audio(uploaded_file, original_name=original_name, content_type=content_type)
    if media_kind == "video":
        return _optimize_video(uploaded_file, original_name=original_name, content_type=content_type)

    _rewind(uploaded_file)
    return uploaded_file


def optimize_media_content(*, filename: str, content: bytes, content_type: str = ""):
    uploaded_file = SimpleUploadedFile(
        filename or "upload",
        content,
        content_type=content_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream",
    )
    return optimize_media_for_storage(uploaded_file)


def _optimize_image(uploaded_file, *, original_name: str, content_type: str):
    suffix = Path(original_name).suffix.lower()
    if suffix in VECTOR_IMAGE_EXTENSIONS or suffix in ANIMATED_IMAGE_EXTENSIONS:
        _rewind(uploaded_file)
        return uploaded_file
    if content_type in {"image/svg+xml", "image/gif"}:
        _rewind(uploaded_file)
        return uploaded_file

    original_size = _file_size(uploaded_file)
    if original_size <= 0:
        _rewind(uploaded_file)
        return uploaded_file

    _rewind(uploaded_file)
    try:
        with Image.open(uploaded_file) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            working = image.copy()
            source_format = (opened.format or "").upper()
            icc_profile = opened.info.get("icc_profile")
            dpi = opened.info.get("dpi")
    except (UnidentifiedImageError, OSError, ValueError):
        _rewind(uploaded_file)
        return uploaded_file

    max_dimension = int(getattr(settings, "MEDIA_IMAGE_MAX_DIMENSION", 0) or 0)
    if max_dimension > 0 and max(working.size) > max_dimension:
        working.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    save_name = Path(original_name).stem or "image"
    save_kwargs: dict[str, object]
    target_suffix: str
    target_content_type: str

    if source_format in {"JPEG", "JPG"} or suffix in {".jpg", ".jpeg"}:
        if working.mode not in {"RGB", "L"}:
            working = working.convert("RGB")
        target_suffix = ".jpg"
        target_content_type = "image/jpeg"
        save_kwargs = {
            "format": "JPEG",
            "quality": int(getattr(settings, "MEDIA_IMAGE_JPEG_QUALITY", 92)),
            "optimize": True,
            "progressive": True,
            "subsampling": 0,
        }
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        if dpi:
            save_kwargs["dpi"] = dpi
    elif source_format == "PNG" or suffix == ".png":
        target_suffix = ".png"
        target_content_type = "image/png"
        save_kwargs = {"format": "PNG", "optimize": True}
    elif source_format == "WEBP" or suffix == ".webp":
        target_suffix = ".webp"
        target_content_type = "image/webp"
        save_kwargs = {"format": "WEBP", "lossless": True, "method": 6}
    else:
        _rewind(uploaded_file)
        return uploaded_file

    temp_dir = Path(tempfile.mkdtemp(prefix="edilcloud-media-"))
    output_path = temp_dir / f"{save_name}{target_suffix}"
    try:
        with output_path.open("wb") as handle:
            working.save(handle, **save_kwargs)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    optimized_size = output_path.stat().st_size if output_path.exists() else 0
    if optimized_size <= 0 or optimized_size >= original_size:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    return TemporaryOptimizedFile(
        temp_path=output_path,
        storage_name=f"{save_name}{target_suffix}",
        content_type=target_content_type,
    )


def _optimize_audio(uploaded_file, *, original_name: str, content_type: str):
    del content_type
    mode = (getattr(settings, "MEDIA_AUDIO_TRANSCODE_MODE", "safe") or "safe").strip().lower()
    if mode == "off" or not _ffmpeg_available():
        _rewind(uploaded_file)
        return uploaded_file

    suffix = Path(original_name).suffix.lower()
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        _rewind(uploaded_file)
        return uploaded_file

    original_size = _file_size(uploaded_file)
    temp_dir, input_path = _copy_uploaded_file_to_temp(uploaded_file, preferred_suffix=suffix or ".bin")

    if suffix in {".wav", ".wave", ".aif", ".aiff"}:
        output_suffix = ".flac"
        output_content_type = "audio/flac"
        output_path = temp_dir / f"{Path(original_name).stem or 'audio'}{output_suffix}"
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-map_metadata",
            "-1",
            "-c:a",
            "flac",
            str(output_path),
        ]
    else:
        output_suffix = suffix or ".bin"
        output_content_type = mimetypes.guess_type(f"file{output_suffix}")[0] or "application/octet-stream"
        output_path = temp_dir / f"{Path(original_name).stem or 'audio'}{output_suffix}"
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-map_metadata",
            "-1",
            "-c",
            "copy",
        ]
        if output_suffix in {".m4a", ".mp4"}:
            command.extend(["-movflags", "+faststart"])
        command.append(str(output_path))

    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not output_path.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    optimized_size = output_path.stat().st_size
    if optimized_size <= 0 or optimized_size >= original_size:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    return TemporaryOptimizedFile(
        temp_path=output_path,
        storage_name=f"{Path(original_name).stem or 'audio'}{output_suffix}",
        content_type=output_content_type,
    )


def _optimize_video(uploaded_file, *, original_name: str, content_type: str):
    del content_type
    mode = (getattr(settings, "MEDIA_VIDEO_TRANSCODE_MODE", "safe") or "safe").strip().lower()
    if mode == "off" or not _ffmpeg_available():
        _rewind(uploaded_file)
        return uploaded_file

    suffix = Path(original_name).suffix.lower()
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        _rewind(uploaded_file)
        return uploaded_file

    original_size = _file_size(uploaded_file)
    temp_dir, input_path = _copy_uploaded_file_to_temp(uploaded_file, preferred_suffix=suffix or ".bin")

    if mode == "transparent":
        output_suffix = ".mp4"
        output_content_type = "video/mp4"
        output_path = temp_dir / f"{Path(original_name).stem or 'video'}{output_suffix}"
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            str(int(getattr(settings, "MEDIA_VIDEO_TRANSPARENT_CRF", 18))),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    elif suffix in {".mp4", ".mov", ".m4v"}:
        output_suffix = suffix
        output_content_type = mimetypes.guess_type(f"file{output_suffix}")[0] or "video/mp4"
        output_path = temp_dir / f"{Path(original_name).stem or 'video'}{output_suffix}"
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not output_path.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    optimized_size = output_path.stat().st_size
    if optimized_size <= 0 or optimized_size >= original_size:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _rewind(uploaded_file)
        return uploaded_file

    return TemporaryOptimizedFile(
        temp_path=output_path,
        storage_name=f"{Path(original_name).stem or 'video'}{output_suffix}",
        content_type=output_content_type,
    )


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _classify_media(*, content_type: str, suffix: str) -> str:
    lowered_type = (content_type or "").split(";", 1)[0].strip().lower()
    lowered_suffix = (suffix or "").lower()
    if lowered_type.startswith("image/") or lowered_suffix in IMAGE_EXTENSIONS | VECTOR_IMAGE_EXTENSIONS | ANIMATED_IMAGE_EXTENSIONS:
        return "image"
    if lowered_type.startswith("audio/") or lowered_suffix in AUDIO_EXTENSIONS:
        return "audio"
    if lowered_type.startswith("video/") or lowered_suffix in VIDEO_EXTENSIONS:
        return "video"
    return ""


def _guess_content_type(uploaded_file, *, fallback_name: str) -> str:
    explicit = (getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].strip().lower()
    if explicit:
        return explicit
    guessed, _encoding = mimetypes.guess_type(fallback_name)
    return guessed or "application/octet-stream"


def _copy_uploaded_file_to_temp(uploaded_file, *, preferred_suffix: str) -> tuple[Path, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="edilcloud-media-"))
    input_path = temp_dir / f"source{preferred_suffix}"
    _rewind(uploaded_file)
    with input_path.open("wb") as handle:
        if hasattr(uploaded_file, "chunks"):
            for chunk in uploaded_file.chunks():
                handle.write(chunk)
        else:
            handle.write(uploaded_file.read())
    _rewind(uploaded_file)
    return temp_dir, input_path


def _file_size(uploaded_file) -> int:
    explicit_size = getattr(uploaded_file, "size", None)
    if explicit_size is not None:
        return int(explicit_size)
    if hasattr(uploaded_file, "seek") and hasattr(uploaded_file, "tell"):
        try:
            position = uploaded_file.tell()
            uploaded_file.seek(0, os.SEEK_END)
            size = uploaded_file.tell()
            uploaded_file.seek(position)
            return int(size)
        except Exception:
            return 0
    return 0


def _rewind(uploaded_file) -> None:
    if hasattr(uploaded_file, "seek"):
        try:
            uploaded_file.seek(0)
        except Exception:
            return
