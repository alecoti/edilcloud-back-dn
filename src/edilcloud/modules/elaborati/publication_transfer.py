"""Offline, recoverable transfer. No deletion and no public-storage fallback."""

import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

MAX_PDF_BYTES = 45 * 1024 * 1024


class TransferBlocked(ValueError):
    pass


def sync_directory(path):
    # POSIX directory entries must be durable before committing their DB link.
    # Windows directory durability remains part of the deployment qualification.
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def checked_path(root, name):
    if (
        not name
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or any(p in ("", ".", "..") or p.rstrip(" .") != p for p in name.split("/"))
    ):
        raise TransferBlocked("invalid_path")
    target = root / name
    current = root
    for part in name.split("/"):
        current /= part
        if current.is_symlink() or current.is_junction():
            raise TransferBlocked("linked_path")
    if not target.resolve().is_relative_to(root):
        raise TransferBlocked("outside_root")
    return target


def fingerprint(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or path.is_junction():
        raise TransferBlocked("not_regular_file")
    if metadata.st_size > MAX_PDF_BYTES:
        raise TransferBlocked("oversized_pdf")
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as source:
        while chunk := source.read(65536):
            length += len(chunk)
            if length > MAX_PDF_BYTES:
                raise TransferBlocked("oversized_pdf")
            digest.update(chunk)
    if length != metadata.st_size:
        raise TransferBlocked("file_changed")
    return digest.hexdigest(), length


class PublicationTransfer:
    def __init__(self, public, private):
        self.public = Path(public).resolve()
        self.private = Path(private).resolve()
        if self.private.is_relative_to(self.public) or any(
            (self.private / folder).is_relative_to(self.public)
            for folder in ("elaborati/publications", "elaborati/public-retired")
        ):
            raise TransferBlocked("public_private_roots_overlap")

    def paths(self, old, new, retired):
        return (
            checked_path(self.public, old),
            checked_path(self.private, new),
            checked_path(self.private, retired),
        )

    def inspect(self, old, new, retired, expected_hash, recorded_size):
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise TransferBlocked("invalid_frozen_hash")
        source, target, archive = self.paths(old, new, retired)
        values = [fingerprint(p) for p in (source, target, archive)]
        existing = [value for value in values if value is not None]
        if not existing:
            raise TransferBlocked("missing_pdf")
        expected = existing[0]
        if expected[0] != expected_hash or any(value != expected for value in existing):
            raise TransferBlocked("pdf_hash_mismatch")
        if recorded_size != expected[1]:
            raise TransferBlocked("recorded_size_mismatch")
        if values[0] is not None and values[2] is not None:
            raise TransferBlocked("retirement_collision")
        if values[1] is None and values[0] is None:
            raise TransferBlocked("missing_active_copy")
        return {
            "public_present": values[0] is not None,
            "private_present": values[1] is not None,
            "retired_present": values[2] is not None,
            "byte_length": expected[1],
        }

    def prepare(self, old, new, retired, expected_hash, recorded_size):
        state = self.inspect(old, new, retired, expected_hash, recorded_size)
        if state["private_present"]:
            sync_directory(self.paths(old, new, retired)[1].parent)
            return
        source, target, _ = self.paths(old, new, retired)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after creating parents. A unique private staging file is never
        # published partially; link creates the final name without replacement.
        source, target, _ = self.paths(old, new, retired)
        temporary = target.with_name(f".{uuid.uuid4().hex}.transfer")
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            digest = hashlib.sha256()
            length = 0
            while chunk := incoming.read(65536):
                length += len(chunk)
                if length > MAX_PDF_BYTES:
                    raise TransferBlocked("oversized_pdf")
                digest.update(chunk)
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if (digest.hexdigest(), length) != (expected_hash, recorded_size):
            raise TransferBlocked("file_changed")
        try:
            os.link(temporary, target)
        except FileExistsError:
            if fingerprint(target) != (expected_hash, recorded_size):
                raise TransferBlocked("private_copy_collision") from None
        # Only our private staging alias is removed. Issued bytes remain at target.
        temporary.unlink()
        sync_directory(target.parent)
        if fingerprint(target) != (expected_hash, recorded_size):
            raise TransferBlocked("private_copy_verification_failed")

    def retire(self, old, new, retired, expected_hash, recorded_size):
        state = self.inspect(old, new, retired, expected_hash, recorded_size)
        if not state["private_present"]:
            raise TransferBlocked("missing_private_copy")
        if not state["public_present"]:
            return "retired" if state["retired_present"] else "public_absent"
        _, _, archive = self.paths(old, new, retired)
        archive.parent.mkdir(parents=True, exist_ok=True)
        source, _, archive = self.paths(old, new, retired)
        if archive.exists():
            raise TransferBlocked("retirement_collision")
        # Maintenance mode and the DB revision lock serialize application writers.
        # EXDEV is intentionally surfaced; no copy+delete fallback is permitted.
        source.rename(archive)
        sync_directory(archive.parent)
        sync_directory(source.parent)
        if fingerprint(archive) != (expected_hash, recorded_size):
            raise TransferBlocked("retirement_verification_failed")
        return "retired"
