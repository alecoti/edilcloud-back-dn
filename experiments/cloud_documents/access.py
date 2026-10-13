"""Strict permission policies for the cloud-document feasibility spike.

Policy inputs must come from a trusted provider adapter, never a browser request.
The flags below are assertions to prove against a real account before activation;
they do not grant provider permissions or replace EdilCloud membership checks.
"""

from dataclasses import dataclass
from enum import StrEnum


class AccessDenied(ValueError):
    pass


class Provider(StrEnum):
    GOOGLE = "google_drive"
    MICROSOFT = "onedrive"


class AccessMode(StrEnum):
    PICKED_FILES = "picked_files"
    SHARED_FOLDERS = "shared_folders"
    SELECTED_FOLDERS = "selected_folders"


@dataclass(frozen=True)
class RemoteIdentity:
    provider: Provider
    item_id: str
    drive_id: str = ""

    def __post_init__(self):
        if not isinstance(self.provider, Provider) or not self.item_id.strip():
            raise AccessDenied("Invalid remote identity.")
        if self.provider == Provider.MICROSOFT and not self.drive_id.strip():
            raise AccessDenied("A Microsoft item requires its drive ID.")
        if self.provider == Provider.GOOGLE and self.drive_id:
            # Google file IDs are globally stable; a drive move must not duplicate the item.
            raise AccessDenied("Google identity uses the file ID, not its current drive.")


@dataclass(frozen=True)
class ConnectionPolicy:
    connection_id: str
    provider: Provider
    account_kind: str
    mode: AccessMode
    scopes: frozenset[str]
    folders: frozenset[RemoteIdentity] = frozenset()
    picked_files: frozenset[RemoteIdentity] = frozenset()
    dedicated_principal: bool = False
    provider_grants_verified: bool = False
    domain_wide_delegation: bool = False

    def validate(self):
        if not self.connection_id.strip() or self.domain_wide_delegation:
            raise AccessDenied("An independent, limited connection is required.")
        if any(item.provider != self.provider for item in self.folders | self.picked_files):
            raise AccessDenied("The permission boundary cannot cross providers.")
        if self.provider == Provider.GOOGLE and self.mode == AccessMode.PICKED_FILES:
            if self.account_kind not in {"personal", "workspace"} or self.scopes != frozenset(
                {"https://www.googleapis.com/auth/drive.file"}
            ):
                raise AccessDenied("Google user OAuth must use only drive.file.")
            if self.folders or not self.picked_files or not self.provider_grants_verified:
                raise AccessDenied("A picked folder does not authorize its child files.")
            return
        if self.provider == Provider.GOOGLE and self.mode == AccessMode.SHARED_FOLDERS:
            if self.account_kind != "service_account" or not self.dedicated_principal:
                raise AccessDenied("Folder sharing requires a dedicated service identity.")
            if self.scopes != frozenset({"https://www.googleapis.com/auth/drive.readonly"}):
                raise AccessDenied("The folder spike supports read-only service access.")
        elif self.provider == Provider.MICROSOFT and self.mode == AccessMode.SELECTED_FOLDERS:
            identity_scopes = {"openid", "profile", "offline_access", "User.Read"}
            if self.account_kind != "business" or self.scopes - identity_scopes != frozenset(
                {"Files.SelectedOperations.Selected"}
            ):
                raise AccessDenied("Microsoft folders require business Selected permissions.")
        else:
            raise AccessDenied("This account/mode cannot guarantee the requested boundary.")
        if not self.folders or self.picked_files or not self.provider_grants_verified:
            raise AccessDenied("Explicit provider folder grants must be verified first.")


@dataclass(frozen=True)
class Binding:
    binding_id: str
    project_id: int
    connection: ConnectionPolicy
    root: RemoteIdentity | None = None

    def validate(self):
        self.connection.validate()
        if not self.binding_id.strip() or self.project_id <= 0:
            raise AccessDenied("Invalid project folder binding.")
        if self.connection.mode == AccessMode.PICKED_FILES:
            if self.root is not None:
                raise AccessDenied("Picked-file access cannot become recursive folder access.")
        elif self.root not in self.connection.folders:
            raise AccessDenied("The folder has no verified provider grant.")

    def authorizes(self, item: RemoteIdentity, ancestors: tuple[RemoteIdentity, ...]) -> bool:
        if item.provider != self.connection.provider:
            return False
        if self.connection.mode == AccessMode.PICKED_FILES:
            return item in self.connection.picked_files
        # Ancestors must be resolved by a trusted adapter from provider responses.
        # Paths, display names and shortcuts are not permission evidence.
        return self.root in ancestors and all(
            parent.provider == item.provider and parent.drive_id == item.drive_id
            for parent in ancestors
        )
