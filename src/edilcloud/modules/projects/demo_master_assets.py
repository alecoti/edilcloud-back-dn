from __future__ import annotations

from pathlib import Path


DEMO_ASSET_VERSION = "v2026.04"
BACKEND_ROOT = Path(__file__).resolve().parents[4]
DEMO_ASSET_SOURCE_ROOT = BACKEND_ROOT / "demo-assets" / "demo-master" / DEMO_ASSET_VERSION

DRAWING_FILENAME_PREFIXES = ("ar-", "st-", "fa-", "im-", "el-", "fn-")
IMAGE_SOURCE_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif")
DOCUMENT_SOURCE_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".zip")
LOGO_SOURCE_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif")
AVATAR_SOURCE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif")


def file_stem(value: str) -> str:
    return Path(value).stem.lower()


def visual_source_dir_for_filename(filename: str) -> str:
    stem = file_stem(filename)
    if stem.startswith(DRAWING_FILENAME_PREFIXES):
        return "drawings"
    return "photos"


def asset_code_for_filename(filename: str, *, category: str | None = None) -> str:
    stem = file_stem(filename)
    if category:
        return f"{category}-{stem}"
    if visual_source_dir_for_filename(filename) == "drawings":
        return f"drawing-{stem}"
    return f"photo-{stem}"


def asset_placeholder_kind(filename: str, *, category: str | None = None) -> str:
    if category:
        return f"{category} placeholder"
    if visual_source_dir_for_filename(filename) == "drawings":
        return "drawing placeholder"
    return "photo placeholder"


def expected_source_pattern(relative_dir: str, preferred_filename: str) -> str:
    stem = Path(preferred_filename).stem
    return str((DEMO_ASSET_SOURCE_ROOT / relative_dir / f"{stem}.*").relative_to(BACKEND_ROOT)).replace("\\", "/")


def find_demo_source_file(
    *,
    relative_dir: str,
    preferred_filename: str,
    extensions: tuple[str, ...],
) -> Path | None:
    base_dir = DEMO_ASSET_SOURCE_ROOT / relative_dir
    preferred_name = Path(preferred_filename).name
    preferred_path = base_dir / preferred_name
    if preferred_path.exists():
        return preferred_path

    stem = Path(preferred_filename).stem
    suffixes: list[str] = []
    preferred_suffix = Path(preferred_filename).suffix.lower()
    if preferred_suffix:
        suffixes.append(preferred_suffix)
    for ext in extensions:
        if ext not in suffixes:
            suffixes.append(ext)
    for suffix in suffixes:
        candidate = base_dir / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None
