"""Pure synthetic physical-state tests for ADR-0056 recovery."""

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
from foliotone.quarantine.recovery import (
    QuarantineRecoveryPhysicalState,
    inspect_interim_quarantine_recovery,
)

NOW = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)
CONTENT = b"synthetic-recovery-ebook"
TARGET_TOKEN = "a" * 64


def test_classifies_exact_unmoved_source_without_mutation(tmp_path: Path) -> None:
    capability, source, source_path, target = _fixture(tmp_path)

    result = inspect_interim_quarantine_recovery(
        capability=capability,
        source=source,
        target_token=TARGET_TOKEN,
    )

    assert result is QuarantineRecoveryPhysicalState.SOURCE_EXACT_TARGET_ABSENT
    assert source_path.read_bytes() == CONTENT
    assert not target.exists()


def test_classifies_exact_bound_target_after_observed_move(tmp_path: Path) -> None:
    capability, source, source_path, target = _fixture(tmp_path)
    source_path.rename(target)

    result = inspect_interim_quarantine_recovery(
        capability=capability,
        source=source,
        target_token=TARGET_TOKEN,
    )

    assert result is QuarantineRecoveryPhysicalState.SOURCE_ABSENT_TARGET_EXACT
    assert not source_path.exists()
    assert target.read_bytes() == CONTENT


@pytest.mark.parametrize(
    "distribution",
    ("both-absent", "both-present", "foreign-target", "foreign-source"),
)
def test_every_nonexact_distribution_is_ambiguous(
    tmp_path: Path,
    distribution: str,
) -> None:
    capability, source, source_path, target = _fixture(tmp_path)
    if distribution == "both-absent":
        source_path.unlink()
    elif distribution == "both-present":
        target.write_bytes(CONTENT)
        os.utime(target, (NOW.timestamp(), NOW.timestamp()))
    elif distribution == "foreign-target":
        source_path.unlink()
        target.write_bytes(b"foreign")
        os.utime(target, (NOW.timestamp(), NOW.timestamp()))
    else:
        source_path.write_bytes(b"changed")
        os.utime(source_path, (NOW.timestamp(), NOW.timestamp()))

    result = inspect_interim_quarantine_recovery(
        capability=capability,
        source=source,
        target_token=TARGET_TOKEN,
    )

    assert result is QuarantineRecoveryPhysicalState.AMBIGUOUS


def _fixture(
    tmp_path: Path,
) -> tuple[
    ResolvedQuarantineCapability,
    QuarantineAuthorizationSourceSnapshot,
    Path,
    Path,
]:
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    relative = Path("Synthetic") / "Book.epub"
    source_path = root / relative
    source_path.parent.mkdir(parents=True)
    quarantine.mkdir()
    source_path.write_bytes(CONTENT)
    os.utime(source_path, (NOW.timestamp(), NOW.timestamp()))
    root_id = EntityId.new()
    source = QuarantineAuthorizationSourceSnapshot(
        ConsolidationFileRole.CANDIDATE,
        root_id,
        EntityId.new(),
        EntityId.new(),
        relative.as_posix(),
        hashlib.sha256(CONTENT).hexdigest(),
        len(CONTENT),
        NOW,
    )
    capability = ResolvedQuarantineCapability(
        EntityId.new(),
        root_id,
        root,
        quarantine,
    )
    return capability, source, source_path, quarantine / TARGET_TOKEN
