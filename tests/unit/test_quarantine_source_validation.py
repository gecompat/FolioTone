"""Focused synthetic coverage for read-only quarantine source validation."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.consolidation.contracts import ConsolidationFileRole
from foliotone.core import EntityId
from foliotone.persistence.quarantine import QuarantineAuthorizationSourceSnapshot
from foliotone.quarantine.capabilities import ResolvedQuarantineCapability
from foliotone.quarantine.source_validation import (
    InterimQuarantineSourceVerifier,
    QuarantineSourceValidationError,
)

ROOT_ID = EntityId.parse("dc000000-0000-0000-0000-000000000001")
FILE_ID = EntityId.parse("dc000000-0000-0000-0000-000000000002")
OBSERVATION_ID = EntityId.parse("dc000000-0000-0000-0000-000000000003")
CAPABILITY_ID = EntityId.parse("dc000000-0000-0000-0000-000000000004")


def test_source_verifier_streams_one_stable_regular_file(tmp_path: Path) -> None:
    capability, source, _path = _source(tmp_path, b"synthetic ebook payload")

    InterimQuarantineSourceVerifier().verify(capability=capability, source=source)


def test_source_verifier_rejects_changed_content_without_exposing_material(
    tmp_path: Path,
) -> None:
    capability, source, path = _source(tmp_path, b"candidate")
    path.write_bytes(b"changed!!")

    with pytest.raises(QuarantineSourceValidationError) as captured:
        InterimQuarantineSourceVerifier().verify(capability=capability, source=source)

    assert str(captured.value) == "STALE"
    assert str(path) not in str(captured.value)
    assert source.relative_path not in repr(source)
    assert source.expected_full_sha256 not in repr(source)


def test_source_verifier_rejects_hardlink_multiple_reference(tmp_path: Path) -> None:
    capability, source, path = _source(tmp_path, b"synthetic hardlink")
    second = path.with_name("second.epub")
    try:
        os.link(path, second)
    except OSError:
        pytest.skip("hardlinks are unavailable on this test filesystem")

    with pytest.raises(QuarantineSourceValidationError, match="STALE"):
        InterimQuarantineSourceVerifier().verify(capability=capability, source=source)


def _source(
    tmp_path: Path,
    content: bytes,
) -> tuple[
    ResolvedQuarantineCapability,
    QuarantineAuthorizationSourceSnapshot,
    Path,
]:
    root = tmp_path / "root"
    quarantine = tmp_path / "quarantine"
    parent = root / "Synthetic"
    parent.mkdir(parents=True)
    quarantine.mkdir()
    path = parent / "candidate.epub"
    path.write_bytes(content)
    details = path.stat()
    capability = ResolvedQuarantineCapability(
        CAPABILITY_ID,
        ROOT_ID,
        root,
        quarantine,
    )
    source = QuarantineAuthorizationSourceSnapshot(
        role=ConsolidationFileRole.CANDIDATE,
        scan_root_id=ROOT_ID,
        file_id=FILE_ID,
        observation_id=OBSERVATION_ID,
        relative_path="Synthetic/candidate.epub",
        expected_full_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
        expected_modified_at=datetime.fromtimestamp(details.st_mtime, tz=UTC),
    )
    return capability, source, path
