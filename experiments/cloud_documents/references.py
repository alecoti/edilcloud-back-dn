"""In-memory reference/synchronization spike. Deliberately stores no file bytes.

This proves domain transitions, not live synchronization. A production adapter
needs durable transactions, worker locks, provider calls, and active membership
checks before feeding this projection. All operations are disabled by default.
"""

from dataclasses import dataclass, replace
from hashlib import sha256
import json

from .access import AccessDenied, Binding, RemoteIdentity


class CheckpointConflict(ValueError):
    pass


@dataclass(frozen=True)
class FileMetadata:
    identity: RemoteIdentity
    name: str
    mime_type: str
    revision: str
    ancestors: tuple[RemoteIdentity, ...] = ()
    is_shortcut: bool = False
    can_edit: bool = False


@dataclass(frozen=True)
class Change:
    identity: RemoteIdentity
    metadata: FileMetadata | None = None
    unavailable_reason: str = "deleted"


@dataclass(frozen=True)
class Reference:
    project_id: int
    connection_id: str
    identity: RemoteIdentity
    name: str
    mime_type: str
    remote_revision: str
    bindings: frozenset[str]
    placement: str = "document"
    drawing_revision: str = ""
    availability: str = "available"
    can_edit: bool = False

    @property
    def reference_id(self) -> str:
        parts = [
            self.project_id,
            self.connection_id,
            self.identity.provider,
            self.identity.drive_id,
            self.identity.item_id,
        ]
        return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:32]

    @property
    def revision_changed(self) -> bool:
        return bool(self.drawing_revision and self.drawing_revision != self.remote_revision)

    def client_contract(self) -> dict:
        available = self.availability == "available" and bool(self.bindings)
        # No provider URL, credentials, download URL or remote item IDs in client data.
        return {
            "schema_version": 1,
            "reference_id": self.reference_id,
            "project_id": self.project_id,
            "source": self.identity.provider.value,
            "name": self.name if available else "",
            "mime_type": self.mime_type if available else "",
            "placement": self.placement,
            "availability": self.availability,
            "revision_changed": self.revision_changed,
            "can_open": available,
            "can_edit": available and self.can_edit,
        }


class ReferenceIndex:
    def __init__(self, *, enabled: bool = False):
        self.enabled = enabled
        self._references: dict[tuple[int, str, RemoteIdentity], Reference] = {}
        self._checkpoints: dict[str, str | None] = {}
        self._bindings: dict[str, Binding] = {}
        self._disconnected: set[str] = set()

    def _authorize(self, *, project_id: int, actor_projects: frozenset[int]):
        if not self.enabled:
            raise AccessDenied("The cloud-document experiment is disabled.")
        if project_id not in actor_projects:
            raise AccessDenied("No active project access.")

    def references(
        self, *, project_id: int, actor_projects: frozenset[int]
    ) -> tuple[Reference, ...]:
        self._authorize(project_id=project_id, actor_projects=actor_projects)
        return tuple(ref for ref in self._references.values() if ref.project_id == project_id)

    def checkpoint(self, binding_id: str) -> str | None:
        # Internal worker cursor. Must never be exposed by the client API.
        return self._checkpoints.get(binding_id)

    def apply_batch(
        self,
        *,
        binding: Binding,
        changes: tuple[Change, ...],
        expected_cursor: str | None,
        next_cursor: str,
        actor_projects: frozenset[int],
    ):
        self._authorize(project_id=binding.project_id, actor_projects=actor_projects)
        binding.validate()
        connection_id = binding.connection.connection_id
        if connection_id in self._disconnected:
            raise AccessDenied("The cloud account has been disconnected.")
        previous_binding = self._bindings.get(binding.binding_id)
        if previous_binding is not None and previous_binding != binding:
            raise AccessDenied("A binding cannot be reassigned to another project or grant.")
        if expected_cursor != self.checkpoint(binding.binding_id) or not next_cursor:
            raise CheckpointConflict("A stale worker cannot advance this checkpoint.")
        staged = self._references.copy()
        for change in changes:
            if change.identity.provider != binding.connection.provider:
                raise AccessDenied("A change cannot cross providers.")
            key = (binding.project_id, connection_id, change.identity)
            existing = staged.get(key)
            if change.metadata is None:
                if change.unavailable_reason not in {"deleted", "access_revoked", "outside_scope"}:
                    raise AccessDenied("Unknown removal reason.")
                if existing is not None and binding.binding_id in existing.bindings:
                    remaining = existing.bindings - {binding.binding_id}
                    staged[key] = replace(
                        existing,
                        bindings=frozenset(remaining),
                        availability="available" if remaining else change.unavailable_reason,
                    )
                continue
            meta = change.metadata
            if meta.identity != change.identity or meta.is_shortcut:
                raise AccessDenied("Shortcuts require separate target authorization.")
            if (
                not meta.name.strip()
                or not meta.revision
                or not binding.authorizes(meta.identity, meta.ancestors)
            ):
                raise AccessDenied("File is not inside the verified access boundary.")
            if existing is None:
                staged[key] = Reference(
                    binding.project_id,
                    connection_id,
                    meta.identity,
                    meta.name,
                    meta.mime_type,
                    meta.revision,
                    frozenset({binding.binding_id}),
                    can_edit=meta.can_edit,
                )
            else:
                staged[key] = replace(
                    existing,
                    name=meta.name,
                    mime_type=meta.mime_type,
                    remote_revision=meta.revision,
                    can_edit=meta.can_edit,
                    bindings=existing.bindings | {binding.binding_id},
                    availability="available",
                )
        # Commit only after every change has passed validation. Production: one DB transaction.
        self._references = staged
        self._bindings[binding.binding_id] = binding
        self._checkpoints[binding.binding_id] = next_cursor

    def link_to_drawings(
        self,
        *,
        project_id: int,
        connection_id: str,
        identity: RemoteIdentity,
        actor_projects: frozenset[int],
        can_manage: bool,
    ) -> Reference:
        self._authorize(project_id=project_id, actor_projects=actor_projects)
        if not can_manage:
            raise AccessDenied("Drawing changes require project edit permission.")
        key = (project_id, connection_id, identity)
        ref = self._references.get(key)
        if ref is None or ref.availability != "available" or not ref.bindings:
            raise AccessDenied("The original file is no longer accessible.")
        if ref.mime_type not in {"application/pdf", "image/png", "image/jpeg", "image/webp"}:
            raise AccessDenied("This file needs a supported drawing rendition first.")
        # Same reference, same source. Preserve the original revision on repeated actions.
        drawing = replace(
            ref, placement="drawing", drawing_revision=ref.drawing_revision or ref.remote_revision
        )
        self._references[key] = drawing
        return drawing

    def unlink_folder(self, *, binding_id: str, actor_projects: frozenset[int], can_manage: bool):
        binding = self._bindings.get(binding_id)
        if binding is None:
            return
        self._authorize(project_id=binding.project_id, actor_projects=actor_projects)
        if not can_manage:
            raise AccessDenied("Unlinking requires project edit permission.")
        for key, ref in tuple(self._references.items()):
            if (
                ref.project_id == binding.project_id
                and ref.connection_id == (binding.connection.connection_id)
                and binding_id in ref.bindings
            ):
                remaining = ref.bindings - {binding_id}
                self._references[key] = replace(
                    ref,
                    bindings=frozenset(remaining),
                    availability="available" if remaining else "unlinked",
                )
        self._bindings.pop(binding_id)
        self._checkpoints.pop(binding_id, None)

    def disconnect(self, *, connection_id: str, owns_connection: bool):
        # Production needs the connection owner's identity; project membership alone is insufficient.
        if not self.enabled or not owns_connection:
            raise AccessDenied("Only the connection owner may disconnect this account.")
        # The owner must be able to revoke the connection even after leaving a project.
        # Revocation can remove access; it cannot grant access or delete remote content.
        self._disconnected.add(connection_id)
        for key, ref in tuple(self._references.items()):
            if ref.connection_id == connection_id:
                self._references[key] = replace(
                    ref, bindings=frozenset(), availability="access_revoked", can_edit=False
                )
        for binding_id, binding in tuple(self._bindings.items()):
            if binding.connection.connection_id == connection_id:
                self._bindings.pop(binding_id)
                self._checkpoints.pop(binding_id, None)
