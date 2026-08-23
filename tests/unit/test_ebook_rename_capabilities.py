from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.ebook_rename import capabilities
from foliotone.ebook_rename.capabilities import (
    EBOOK_RENAME_CAPABILITIES_FILE_ENV,
    EBOOK_RENAME_CAPABILITY_PROFILE,
    EbookRenameCapabilityResolver,
    EbookRenameCapabilityUnavailable,
)
from foliotone.ebook_rename.target import EBOOK_RENAME_PROCESSOR_PROFILE


def _write_config(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "ebook-rename-capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _entry(
    capability_id: EntityId,
    scan_root_id: EntityId,
    scan_root: Path,
    probe: Path,
) -> dict[str, object]:
    return {
        "ebook_rename_capability_id": str(capability_id),
        "scan_root_id": str(scan_root_id),
        "scan_root_directory": str(scan_root),
        "probe_directory": str(probe),
        "capability_profile": EBOOK_RENAME_CAPABILITY_PROFILE,
        "writer_profile": EBOOK_RENAME_PROCESSOR_PROFILE,
        "version": 1,
    }


def _permit_windows_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setattr(
            capabilities,
            "_verify_configuration_protection",
            lambda _: None,
        )
        monkeypatch.setattr(
            capabilities,
            "_verify_probe_directory_protection",
            lambda _: None,
        )


def test_resolves_exact_private_nonoverlapping_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    probe = tmp_path / "probe"
    scan_root.mkdir()
    probe.mkdir(mode=0o700)
    capability_id = EntityId.new()
    scan_root_id = EntityId.new()
    config = _write_config(
        tmp_path,
        {"capabilities": [_entry(capability_id, scan_root_id, scan_root, probe)]},
    )
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_fixture(monkeypatch)

    first = EbookRenameCapabilityResolver().resolve(capability_id)
    second = EbookRenameCapabilityResolver().resolve(capability_id)

    assert first == second
    assert first.scan_root_id == scan_root_id
    assert first.writer_profile == EBOOK_RENAME_PROCESSOR_PROFILE
    assert len(first.configuration_fingerprint) == 64
    assert str(scan_root) not in repr(first)
    assert str(probe) not in repr(first)


@pytest.mark.parametrize(
    "document",
    (
        {},
        {"capabilities": []},
        {"capabilities": [{"unexpected": "value"}]},
    ),
)
def test_invalid_schema_fails_with_one_fixed_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: object,
) -> None:
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))

    with pytest.raises(EbookRenameCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        EbookRenameCapabilityResolver().resolve(EntityId.new())


def test_rejects_wrong_profile_version_and_missing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    probe = tmp_path / "probe"
    scan_root.mkdir()
    capability_id = EntityId.new()
    entry = _entry(capability_id, EntityId.new(), scan_root, probe)
    entry["writer_profile"] = "unbounded-writer/v1"
    entry["version"] = 0
    config = _write_config(tmp_path, {"capabilities": [entry]})
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_fixture(monkeypatch)

    with pytest.raises(EbookRenameCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        EbookRenameCapabilityResolver().resolve(capability_id)


def test_rejects_root_probe_and_cross_capability_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first-root"
    nested_probe = first_root / "probe"
    second_root = tmp_path / "second-root"
    second_probe = tmp_path / "second-probe"
    for directory in (first_root, nested_probe, second_root, second_probe):
        directory.mkdir()
    first_id = EntityId.new()
    document = {
        "capabilities": [
            _entry(first_id, EntityId.new(), first_root, nested_probe),
            _entry(EntityId.new(), EntityId.new(), second_root, second_probe),
        ]
    }
    config = _write_config(tmp_path, document)
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_fixture(monkeypatch)

    with pytest.raises(EbookRenameCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        EbookRenameCapabilityResolver().resolve(first_id)


def test_rejects_explicit_protected_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    probe = tmp_path / "probe"
    protected = scan_root / "protected"
    for directory in (scan_root, probe, protected):
        directory.mkdir()
    capability_id = EntityId.new()
    config = _write_config(
        tmp_path,
        {
            "capabilities": [
                _entry(capability_id, EntityId.new(), scan_root, probe)
            ]
        },
    )
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))
    _permit_windows_fixture(monkeypatch)

    with pytest.raises(EbookRenameCapabilityUnavailable, match="^TOOL_UNAVAILABLE$"):
        EbookRenameCapabilityResolver(protected_paths=(protected,)).resolve(
            capability_id
        )


def test_owner_protection_is_fail_closed_without_windows_fixture_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_root = tmp_path / "source"
    probe = tmp_path / "probe"
    scan_root.mkdir()
    probe.mkdir(mode=0o700)
    capability_id = EntityId.new()
    config = _write_config(
        tmp_path,
        {
            "capabilities": [
                _entry(capability_id, EntityId.new(), scan_root, probe)
            ]
        },
    )
    monkeypatch.setenv(EBOOK_RENAME_CAPABILITIES_FILE_ENV, str(config))

    if os.name == "nt":
        with pytest.raises(
            EbookRenameCapabilityUnavailable,
            match="^TOOL_UNAVAILABLE$",
        ):
            EbookRenameCapabilityResolver().resolve(capability_id)
    else:
        assert EbookRenameCapabilityResolver().resolve(capability_id)
