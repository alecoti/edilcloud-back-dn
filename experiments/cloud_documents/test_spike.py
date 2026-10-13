from dataclasses import replace

import pytest

from .access import AccessDenied, AccessMode, Binding, ConnectionPolicy, Provider, RemoteIdentity
from .references import Change, CheckpointConflict, FileMetadata, ReferenceIndex


ROOT = RemoteIdentity(Provider.GOOGLE, "selected-root")
OTHER_ROOT = RemoteIdentity(Provider.GOOGLE, "other-root")
FILE = RemoteIdentity(Provider.GOOGLE, "drawing-file")
PROJECTS = frozenset({7})


def policy(**overrides):
    return replace(
        ConnectionPolicy(
            connection_id="external-account-independent-of-login",
            provider=Provider.GOOGLE,
            account_kind="service_account",
            mode=AccessMode.SHARED_FOLDERS,
            scopes=frozenset({"https://www.googleapis.com/auth/drive.readonly"}),
            folders=frozenset({ROOT, OTHER_ROOT}),
            dedicated_principal=True,
            provider_grants_verified=True,
        ),
        **overrides,
    )


def binding(**overrides):
    return replace(Binding("folder-binding", 7, policy(), ROOT), **overrides)


def metadata(**overrides):
    return replace(
        FileMetadata(FILE, "Tavola A.pdf", "application/pdf", "revision-1", (ROOT,)), **overrides
    )


def apply(index, *, bind=None, meta=None, expected=None, cursor="checkpoint-1", changes=None):
    index.apply_batch(
        binding=bind or binding(),
        changes=changes if changes is not None else (Change(FILE, meta or metadata()),),
        expected_cursor=expected,
        next_cursor=cursor,
        actor_projects=PROJECTS,
    )


def only_reference(index):
    return index.references(project_id=7, actor_projects=PROJECTS)[0]


def draw(index):
    return index.link_to_drawings(
        project_id=7,
        connection_id=policy().connection_id,
        identity=FILE,
        actor_projects=PROJECTS,
        can_manage=True,
    )


def test_experiment_is_disabled_by_default():
    with pytest.raises(AccessDenied, match="disabled"):
        apply(ReferenceIndex())


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_kind": "personal"},
        {"dedicated_principal": False},
        {"provider_grants_verified": False},
        {"domain_wide_delegation": True},
        {"scopes": frozenset({"https://www.googleapis.com/auth/drive"})},
    ],
)
def test_folder_permissions_cannot_be_replaced_by_wide_user_oauth_or_unverified_claims(overrides):
    with pytest.raises(AccessDenied):
        policy(**overrides).validate()


def test_google_picked_folder_does_not_grant_access_to_child_files():
    picked = policy(
        account_kind="personal",
        mode=AccessMode.PICKED_FILES,
        scopes=frozenset({"https://www.googleapis.com/auth/drive.file"}),
        folders=frozenset(),
        picked_files=frozenset({ROOT}),
    )
    index = ReferenceIndex(enabled=True)
    with pytest.raises(AccessDenied, match="boundary"):
        apply(index, bind=binding(connection=picked, root=None))
    assert index.checkpoint("folder-binding") is None
    assert index.references(project_id=7, actor_projects=PROJECTS) == ()


def test_selected_google_file_does_not_need_broad_drive_permissions():
    picked = policy(
        account_kind="personal",
        mode=AccessMode.PICKED_FILES,
        scopes=frozenset({"https://www.googleapis.com/auth/drive.file"}),
        folders=frozenset(),
        picked_files=frozenset({FILE}),
    )
    index = ReferenceIndex(enabled=True)
    apply(index, bind=binding(connection=picked, root=None))
    assert only_reference(index).identity == FILE


@pytest.mark.parametrize(
    "account_kind,scope,allowed",
    [
        ("business", "Files.SelectedOperations.Selected", True),
        ("personal", "Files.SelectedOperations.Selected", False),
        ("business", "Files.Read", False),
        ("business", "Files.Read.All", False),
        ("business", "Files.ReadWrite.All", False),
        ("business", "Files.ReadWrite.Selected", False),
    ],
)
def test_microsoft_folder_boundary_requires_business_selected_resource_grants(
    account_kind, scope, allowed
):
    microsoft = policy(
        provider=Provider.MICROSOFT,
        account_kind=account_kind,
        mode=AccessMode.SELECTED_FOLDERS,
        scopes=frozenset({scope}),
        folders=frozenset({RemoteIdentity(Provider.MICROSOFT, "root", "drive")}),
    )
    if allowed:
        microsoft.validate()
    else:
        with pytest.raises(AccessDenied):
            microsoft.validate()


def test_batch_rejection_preserves_existing_data_and_checkpoint_atomically():
    index = ReferenceIndex(enabled=True)
    apply(index)
    before = only_reference(index)
    outside = RemoteIdentity(Provider.GOOGLE, "private-outside-file")
    invalid = FileMetadata(outside, "Private.pdf", "application/pdf", "1", ())
    with pytest.raises(AccessDenied):
        apply(
            index,
            expected="checkpoint-1",
            cursor="checkpoint-2",
            changes=(
                Change(FILE, metadata(revision="revision-2")),
                Change(outside, invalid),
            ),
        )
    assert only_reference(index) == before
    assert index.checkpoint("folder-binding") == "checkpoint-1"


def test_overlapping_folders_duplicate_notifications_and_drawings_reuse_one_reference():
    index = ReferenceIndex(enabled=True)
    apply(index)
    original_id = only_reference(index).reference_id
    apply(index, expected="checkpoint-1", cursor="checkpoint-2")
    second = binding(binding_id="second-binding", root=OTHER_ROOT)
    apply(index, bind=second, meta=metadata(ancestors=(OTHER_ROOT,)))
    drawing = draw(index)
    assert draw(index) == drawing
    assert len(index.references(project_id=7, actor_projects=PROJECTS)) == 1
    assert drawing.reference_id == original_id
    assert drawing.bindings == frozenset({"folder-binding", "second-binding"})
    assert drawing.drawing_revision == "revision-1"


def test_remote_updates_never_silently_rebind_drawing_coordinates_to_new_content():
    index = ReferenceIndex(enabled=True)
    apply(index)
    drawing = draw(index)
    apply(
        index,
        meta=metadata(name="Renamed.pdf", revision="revision-2"),
        expected="checkpoint-1",
        cursor="checkpoint-2",
    )
    updated = draw(index)
    assert updated.reference_id == drawing.reference_id
    assert updated.placement == "drawing"
    assert updated.drawing_revision == "revision-1"
    assert updated.remote_revision == "revision-2"
    assert updated.client_contract()["revision_changed"] is True


@pytest.mark.parametrize("reason", ["deleted", "outside_scope", "access_revoked"])
def test_lost_access_retains_drawing_reference_but_removes_open_edit_and_visible_metadata(reason):
    index = ReferenceIndex(enabled=True)
    apply(index, meta=metadata(can_edit=True))
    drawing = draw(index)
    apply(
        index,
        expected="checkpoint-1",
        cursor="checkpoint-2",
        changes=(Change(FILE, unavailable_reason=reason),),
    )
    ref = only_reference(index)
    contract = ref.client_contract()
    assert ref.reference_id == drawing.reference_id
    assert ref.drawing_revision == "revision-1"
    assert contract["availability"] == reason
    assert not contract["can_open"] and not contract["can_edit"]
    assert contract["name"] == contract["mime_type"] == ""
    with pytest.raises(AccessDenied):
        draw(index)


def test_removing_one_overlapping_folder_keeps_the_other_authorized_link():
    index = ReferenceIndex(enabled=True)
    apply(index)
    apply(
        index,
        bind=binding(binding_id="second-binding", root=OTHER_ROOT),
        meta=metadata(ancestors=(OTHER_ROOT,)),
    )
    index.unlink_folder(binding_id="folder-binding", actor_projects=PROJECTS, can_manage=True)
    assert only_reference(index).client_contract()["can_open"] is True
    index.unlink_folder(binding_id="second-binding", actor_projects=PROJECTS, can_manage=True)
    assert only_reference(index).availability == "unlinked"
    assert only_reference(index).client_contract()["can_open"] is False


def test_disconnect_is_owner_only_blocks_stale_workers_and_retains_drawing_history():
    index = ReferenceIndex(enabled=True)
    apply(index)
    drawing = draw(index)
    with pytest.raises(AccessDenied):
        index.disconnect(connection_id=policy().connection_id, owns_connection=False)
    index.disconnect(connection_id=policy().connection_id, owns_connection=True)
    assert only_reference(index).drawing_revision == drawing.drawing_revision
    assert only_reference(index).availability == "access_revoked"
    with pytest.raises(AccessDenied, match="disconnected"):
        apply(index, cursor="after-disconnect")


def test_membership_edit_permissions_and_immutable_binding_prevent_cross_project_access():
    index = ReferenceIndex(enabled=True)
    apply(index)
    with pytest.raises(AccessDenied):
        index.references(project_id=7, actor_projects=frozenset())
    with pytest.raises(AccessDenied):
        index.link_to_drawings(
            project_id=7,
            connection_id=policy().connection_id,
            identity=FILE,
            actor_projects=PROJECTS,
            can_manage=False,
        )
    with pytest.raises(AccessDenied):
        index.apply_batch(
            binding=binding(project_id=8),
            changes=(),
            expected_cursor="checkpoint-1",
            next_cursor="checkpoint-2",
            actor_projects=frozenset({7, 8}),
        )


def test_shortcuts_and_stale_workers_cannot_expand_access_or_replace_newer_state():
    index = ReferenceIndex(enabled=True)
    with pytest.raises(AccessDenied):
        apply(index, meta=metadata(is_shortcut=True))
    apply(index)
    with pytest.raises(CheckpointConflict):
        apply(index, meta=metadata(revision="stale"), expected=None, cursor="checkpoint-2")
    assert only_reference(index).remote_revision == "revision-1"


def test_contract_has_no_provider_credentials_or_download_urls():
    index = ReferenceIndex(enabled=True)
    apply(index)
    contract = only_reference(index).client_contract()
    assert set(contract) == {
        "schema_version",
        "reference_id",
        "project_id",
        "source",
        "name",
        "mime_type",
        "placement",
        "availability",
        "revision_changed",
        "can_open",
        "can_edit",
    }
    assert contract["reference_id"] != FILE.item_id
