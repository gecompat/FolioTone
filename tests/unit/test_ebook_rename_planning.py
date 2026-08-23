from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import EbookOperationDependencyKind
from foliotone.ebook_rename import dependency_scopes
from foliotone.ebook_rename.dependency_scopes import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV,
    EbookRenameDependencyScopeMode,
    EbookRenameDependencyScopeResolver,
    EbookRenameDependencyScopeUnavailable,
    EbookRenameDependencySnapshotKind,
)
from foliotone.ebook_rename.target import (
    EbookRenameTargetError,
    build_ebook_rename_target_locator,
)


def test_target_policy_builds_only_same_parent_byte_distinct_locator() -> None:
    target, format_label = build_ebook_rename_target_locator(
        "private/library/source.epub",
        "renamed.epub",
    )

    assert target == "private/library/renamed.epub"
    assert format_label == "EPUB"


@pytest.mark.parametrize(
    ("source", "target", "code"),
    (
        (
            "private/Caf\N{LATIN SMALL LETTER E WITH ACUTE}.epub",
            "Cafe\u0301.epub",
            "LOCATOR_NOT_NFC",
        ),
        ("private/source.epub", "SOURCE.EPUB", "TARGET_SUFFIX_MISMATCH"),
        ("private/Source.epub", "source.epub", "TARGET_CASE_ONLY"),
        ("private/source.epub", "CON.epub", "TARGET_BASENAME_INVALID"),
        ("private/source.epub", "other.pdf", "TARGET_SUFFIX_MISMATCH"),
        ("private/source.epub", "../other.epub", "TARGET_BASENAME_INVALID"),
        ("private/source.epub", " trailing.epub", "TARGET_BASENAME_INVALID"),
        ("private/source.epub", "source.epub", "TARGET_UNCHANGED"),
        ("private/source.txt", "renamed.txt", "SOURCE_FORMAT_UNSUPPORTED"),
    ),
)
def test_target_policy_rejects_each_bounded_boundary(
    source: str,
    target: str,
    code: str,
) -> None:
    with pytest.raises(EbookRenameTargetError, match=f"^{code}$"):
        build_ebook_rename_target_locator(source, target)


def test_target_policy_rejects_non_nfc_source_without_rewriting_it() -> None:
    source = (
        "private/"
        + unicodedata.normalize("NFD", "Caf\N{LATIN SMALL LETTER E WITH ACUTE}")
        + ".epub"
    )

    with pytest.raises(EbookRenameTargetError, match="^LOCATOR_NOT_NFC$"):
        build_ebook_rename_target_locator(source, "renamed.epub")


def _axis(mode: str = "NOT_APPLICABLE") -> dict[str, object]:
    if mode == "NOT_APPLICABLE":
        return {"mode": mode}
    return {
        "mode": mode,
        "snapshot_kind": "TOOL_RESULT",
        "snapshot_id": str(EntityId.new()),
    }


def _entry(scope_id: EntityId, root_id: EntityId) -> dict[str, object]:
    return {
        "dependency_scope_id": str(scope_id),
        "scan_root_id": str(root_id),
        "profile": EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
        "version": 1,
        "axes": {kind.value: _axis() for kind in EbookOperationDependencyKind},
    }


def _write_config(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "ebook-rename-dependency-scopes.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _permit_windows_test_config(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setattr(
            dependency_scopes,
            "_verify_configuration_protection",
            lambda _: None,
        )


def test_dependency_scope_requires_all_five_explicit_axes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_id = EntityId.new()
    root_id = EntityId.new()
    entry = _entry(scope_id, root_id)
    entry["axes"]["CALIBRE"] = _axis("MANAGED")  # type: ignore[index]
    config = _write_config(tmp_path, {"dependency_scopes": [entry]})
    monkeypatch.setenv(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)

    resolved = EbookRenameDependencyScopeResolver().resolve(scope_id)

    assert resolved.scan_root_id == root_id
    assert tuple(axis.kind for axis in resolved.axes) == tuple(
        EbookOperationDependencyKind
    )
    assert resolved.axes[0].mode is EbookRenameDependencyScopeMode.MANAGED
    assert (
        resolved.axes[0].snapshot_kind
        is EbookRenameDependencySnapshotKind.TOOL_RESULT
    )

    del entry["axes"]["SIDECAR"]  # type: ignore[index]
    config.write_text(
        json.dumps({"dependency_scopes": [entry]}),
        encoding="utf-8",
    )
    config.chmod(0o600)
    with pytest.raises(
        EbookRenameDependencyScopeUnavailable,
        match="^DEPENDENCY_SCOPE_UNAVAILABLE$",
    ):
        EbookRenameDependencyScopeResolver().resolve(scope_id)


@pytest.mark.parametrize(
    "document",
    (
        {},
        {"dependency_scopes": []},
        {"dependency_scopes": [{"unexpected": "value"}]},
    ),
)
def test_dependency_scope_fails_closed_with_one_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: object,
) -> None:
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)

    with pytest.raises(
        EbookRenameDependencyScopeUnavailable,
        match="^DEPENDENCY_SCOPE_UNAVAILABLE$",
    ):
        EbookRenameDependencyScopeResolver().resolve(EntityId.new())


def test_dependency_scope_rejects_duplicate_scope_and_root_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_id = EntityId.new()
    root_id = EntityId.new()
    document = {
        "dependency_scopes": [
            _entry(scope_id, root_id),
            _entry(scope_id, root_id),
        ]
    }
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)

    with pytest.raises(
        EbookRenameDependencyScopeUnavailable,
        match="^DEPENDENCY_SCOPE_UNAVAILABLE$",
    ):
        EbookRenameDependencyScopeResolver().resolve(scope_id)


def test_dependency_scope_is_linux_owner_only_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_id = EntityId.new()
    config = _write_config(
        tmp_path,
        {"dependency_scopes": [_entry(scope_id, EntityId.new())]},
    )
    monkeypatch.setenv(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV, str(config))
    if os.name == "nt":
        with pytest.raises(
            EbookRenameDependencyScopeUnavailable,
            match="^DEPENDENCY_SCOPE_UNAVAILABLE$",
        ):
            EbookRenameDependencyScopeResolver().resolve(scope_id)
    else:
        assert EbookRenameDependencyScopeResolver().resolve(scope_id)
