from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.metadata_write import capabilities
from foliotone.metadata_write.capabilities import (
    METADATA_WRITE_CAPABILITIES_FILE_ENV,
    MetadataWriteCapabilityResolver,
    MetadataWriteCapabilityUnavailable,
)
from foliotone.metadata_write.contracts import EPUB_TITLE_WRITE_PROFILE


def _write_config(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "metadata-write-capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _entry(
    capability_id: EntityId,
    scan_root_id: EntityId,
    scan_root: Path,
    recovery: Path,
) -> dict[str, object]:
    return {
        "metadata_write_capability_id": str(capability_id),
        "scan_root_id": str(scan_root_id),
        "scan_root_directory": str(scan_root),
        "recovery_directory": str(recovery),
        "writer_profile": EPUB_TITLE_WRITE_PROFILE,
    }


def _document(entry: dict[str, object]) -> dict[str, object]:
    return {"capabilities": [entry]}


def _permit_windows_test_config(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setattr(capabilities, "_verify_configuration_protection", lambda _: None)


def test_resolves_exact_private_same_filesystem_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    recovery = tmp_path / "recovery"
    scan_root.mkdir()
    recovery.mkdir()
    capability_id = EntityId.new()
    scan_root_id = EntityId.new()
    config = _write_config(
        tmp_path,
        _document(_entry(capability_id, scan_root_id, scan_root, recovery)),
    )
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)

    resolved = MetadataWriteCapabilityResolver().resolve(capability_id)

    assert resolved.metadata_write_capability_id == capability_id
    assert resolved.scan_root_id == scan_root_id
    assert resolved.writer_profile == EPUB_TITLE_WRITE_PROFILE
    assert str(scan_root) not in repr(resolved)
    assert str(recovery) not in repr(resolved)


@pytest.mark.parametrize(
    "document",
    (
        {},
        {"capabilities": []},
        {"capabilities": [{"unknown": "field"}]},
    ),
)
def test_rejects_invalid_schema_with_one_fixed_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: object,
) -> None:
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(EntityId.new())


def test_rejects_missing_config_directory_and_writer_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, raising=False)
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(EntityId.new())

    scan_root = tmp_path / "source"
    recovery = tmp_path / "recovery"
    scan_root.mkdir()
    capability_id = EntityId.new()
    entry = _entry(capability_id, EntityId.new(), scan_root, recovery)
    entry["writer_profile"] = "write-all"
    config = _write_config(tmp_path, _document(entry))
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(capability_id)


def test_rejects_duplicate_ids_and_overlapping_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    nested = scan_root / "nested"
    recovery = tmp_path / "recovery"
    other_recovery = tmp_path / "other-recovery"
    for directory in (scan_root, nested, recovery, other_recovery):
        directory.mkdir()
    capability_id = EntityId.new()
    document = {
        "capabilities": [
            _entry(capability_id, EntityId.new(), scan_root, recovery),
            _entry(capability_id, EntityId.new(), nested, other_recovery),
        ]
    }
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)

    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(capability_id)


def test_rejects_relative_missing_or_overlapping_recovery_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    scan_root.mkdir()
    capability_id = EntityId.new()
    entry = _entry(capability_id, EntityId.new(), scan_root, tmp_path / "missing")
    config = _write_config(tmp_path, _document(entry))
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_test_config(monkeypatch)
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(capability_id)

    nested = scan_root / "recovery"
    nested.mkdir()
    entry["recovery_directory"] = str(nested)
    config.write_text(json.dumps(_document(entry)), encoding="utf-8")
    config.chmod(0o600)
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(capability_id)

    entry["scan_root_directory"] = "relative"
    config.write_text(json.dumps(_document(entry)), encoding="utf-8")
    config.chmod(0o600)
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(capability_id)


def test_rejects_unprotected_or_symlinked_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    recovery = tmp_path / "recovery"
    scan_root.mkdir()
    recovery.mkdir()
    target = _write_config(
        tmp_path,
        _document(_entry(EntityId.new(), EntityId.new(), scan_root, recovery)),
    )
    if os.name == "nt":
        target.chmod(0o644)
        monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(target))
        with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
            MetadataWriteCapabilityResolver().resolve(EntityId.new())
        return

    target.chmod(0o644)
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(target))
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(EntityId.new())

    target.chmod(0o600)
    linked = tmp_path / "linked-capabilities.json"
    linked.symlink_to(target)
    monkeypatch.setenv(METADATA_WRITE_CAPABILITIES_FILE_ENV, str(linked))
    with pytest.raises(MetadataWriteCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        MetadataWriteCapabilityResolver().resolve(EntityId.new())
