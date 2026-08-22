from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.quarantine import capabilities
from foliotone.quarantine.capabilities import (
    CAPABILITIES_FILE_ENV,
    QuarantineCapabilityResolver,
    QuarantineCapabilityUnavailable,
)


def _write_config(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _document(
    capability_id: EntityId,
    scan_root_id: EntityId,
    root: Path,
    quarantine: Path,
) -> dict[str, object]:
    return {
        "capabilities": [
            {
                "quarantine_capability_id": str(capability_id),
                "scan_root_id": str(scan_root_id),
                "scan_root_directory": str(root),
                "quarantine_directory": str(quarantine),
            }
        ]
    }


def _resolve(monkeypatch: pytest.MonkeyPatch, config: Path, capability_id: EntityId):
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))
    return QuarantineCapabilityResolver().resolve(capability_id)


def test_resolves_a_private_valid_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    quarantine.mkdir()
    capability_id = EntityId.new()
    scan_root_id = EntityId.new()
    config = _write_config(tmp_path, _document(capability_id, scan_root_id, root, quarantine))
    if os.name == "nt":
        monkeypatch.setattr(capabilities, "_verify_configuration_protection", lambda _: None)

    value = _resolve(monkeypatch, config, capability_id)

    assert value.quarantine_capability_id == capability_id
    assert value.scan_root_id == scan_root_id
    assert str(root) not in repr(value)
    assert str(quarantine) not in repr(value)


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"capabilities": []},
        {"capabilities": [{"unknown": "field"}]},
    ],
)
def test_rejects_invalid_json_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(EntityId.new())


def test_rejects_malformed_json_and_invalid_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "capabilities.json"
    config.write_text("{", encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(EntityId.new())

    root = tmp_path / "source"
    root.mkdir()
    capability_id = EntityId.new()
    config = _write_config(
        tmp_path,
        _document(capability_id, EntityId.new(), root, tmp_path / "missing-quarantine"),
    )
    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(capability_id)


def test_rejects_missing_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CAPABILITIES_FILE_ENV, raising=False)

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(EntityId.new())


def test_rejects_duplicate_capability_ids_and_overlapping_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    nested = root / "nested"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    nested.mkdir()
    quarantine.mkdir()
    capability_id = EntityId.new()
    document = _document(capability_id, EntityId.new(), root, quarantine)
    duplicate = dict(document["capabilities"][0])  # type: ignore[index]
    duplicate["scan_root_id"] = str(EntityId.new())
    duplicate["scan_root_directory"] = str(nested)
    document["capabilities"].append(duplicate)  # type: ignore[index]
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(capability_id)


def test_rejects_duplicate_scan_root_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    other_root = tmp_path / "other-source"
    other_quarantine = tmp_path / "other-quarantine"
    for directory in (root, quarantine, other_root, other_quarantine):
        directory.mkdir()
    scan_root_id = EntityId.new()
    document = _document(EntityId.new(), scan_root_id, root, quarantine)
    duplicate_document = _document(
        EntityId.new(), scan_root_id, other_root, other_quarantine
    )
    duplicate = duplicate_document["capabilities"][0]
    document["capabilities"].append(duplicate)  # type: ignore[index]
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(EntityId.new())


def test_rejects_relative_paths_symlinks_and_unsafe_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    quarantine.mkdir()
    capability_id = EntityId.new()
    config = _write_config(tmp_path, _document(capability_id, EntityId.new(), root, quarantine))
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["capabilities"][0]["scan_root_directory"] = "relative"
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(capability_id)

    payload["capabilities"][0]["scan_root_directory"] = str(root)
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o644)
    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(capability_id)


def test_rejects_a_symlinked_configuration_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation needs host-specific privileges")
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    quarantine.mkdir()
    target = _write_config(tmp_path, _document(EntityId.new(), EntityId.new(), root, quarantine))
    config = tmp_path / "linked.json"
    config.symlink_to(target)
    monkeypatch.setenv(CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(QuarantineCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        QuarantineCapabilityResolver().resolve(EntityId.new())
