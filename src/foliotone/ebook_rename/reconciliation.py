"""Immutable reconciliation evidence for one bounded e-book rename."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from foliotone.core import EntityId

EBOOK_RENAME_RECONCILIATION_PROFILE: Final = "ebook-file-rename-reconciliation/v1"
_RECONCILIATION_DOMAIN: Final = b"foliotone:ebook-file-rename-reconciliation/v1\x00"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class EbookRenameReconciliationOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True, slots=True)
class EbookRenameReconciliationSnapshot:
    """One exact post-rename ScanRun and CollectionState binding.

    ``source_scan_event_id`` denotes ``MISSING`` for a forward outcome and
    ``UNCHANGED`` or ``REAPPEARED`` for a recovered outcome.  A missing file
    has no ``FileObservation`` in the index, so the immutable event identity is
    the canonical forward absence evidence.
    """

    run_id: EntityId
    authorization_id: EntityId
    authorization_content_hash: str = field(repr=False)
    preparation_id: EntityId
    preparation_content_hash: str = field(repr=False)
    outcome: EbookRenameReconciliationOutcome
    scan_run_id: EntityId
    source_file_id: EntityId
    source_before_observation_id: EntityId
    source_scan_event_id: EntityId
    source_observation_id: EntityId | None
    target_file_id: EntityId | None
    target_observation_id: EntityId | None
    target_scan_event_id: EntityId | None
    collection_state_snapshot_id: EntityId
    collection_state_content_digest: str = field(repr=False)
    expected_full_sha256: str = field(repr=False)
    expected_size_bytes: int
    target_absence_fingerprint: str = field(repr=False)
    physical_confirmation_digest: str = field(repr=False)
    reconciled_at: datetime
    content_hash: str = field(repr=False)
    profile: str = EBOOK_RENAME_RECONCILIATION_PROFILE

    def __post_init__(self) -> None:
        required_ids = (
            self.run_id,
            self.authorization_id,
            self.preparation_id,
            self.scan_run_id,
            self.source_file_id,
            self.source_before_observation_id,
            self.source_scan_event_id,
            self.collection_state_snapshot_id,
        )
        if (
            self.profile != EBOOK_RENAME_RECONCILIATION_PROFILE
            or not isinstance(self.outcome, EbookRenameReconciliationOutcome)
            or not all(isinstance(value, EntityId) for value in required_ids)
            or isinstance(self.expected_size_bytes, bool)
            or not isinstance(self.expected_size_bytes, int)
            or self.expected_size_bytes < 0
        ):
            raise ValueError("e-book rename reconciliation identity is invalid")
        optional_ids = (
            self.source_observation_id,
            self.target_file_id,
            self.target_observation_id,
            self.target_scan_event_id,
        )
        if any(value is not None and not isinstance(value, EntityId) for value in optional_ids):
            raise ValueError("e-book rename reconciliation identity is invalid")
        forward = self.outcome is EbookRenameReconciliationOutcome.VERIFIED
        if forward != (
            self.source_observation_id is None
            and self.target_file_id is not None
            and self.target_observation_id is not None
            and self.target_scan_event_id is not None
        ) or (not forward) != (
            self.source_observation_id is not None
            and self.target_file_id is None
            and self.target_observation_id is None
            and self.target_scan_event_id is None
        ):
            raise ValueError("e-book rename reconciliation outcome shape is invalid")
        if self.target_file_id == self.source_file_id:
            raise ValueError("e-book rename reconciliation file identities are invalid")
        for value in (
            self.authorization_content_hash,
            self.preparation_content_hash,
            self.collection_state_content_digest,
            self.expected_full_sha256,
            self.target_absence_fingerprint,
            self.physical_confirmation_digest,
            self.content_hash,
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("e-book rename reconciliation digest is invalid")
        if (
            not isinstance(self.reconciled_at, datetime)
            or self.reconciled_at.tzinfo is None
            or self.reconciled_at.utcoffset() is None
        ):
            raise ValueError("e-book rename reconciliation timestamp is invalid")
        object.__setattr__(self, "reconciled_at", self.reconciled_at.astimezone(UTC))
        if self.content_hash != _content_hash(self):
            raise ValueError("e-book rename reconciliation content hash differs")


def build_ebook_rename_reconciliation(
    *,
    run_id: EntityId,
    authorization_id: EntityId,
    authorization_content_hash: str,
    preparation_id: EntityId,
    preparation_content_hash: str,
    outcome: EbookRenameReconciliationOutcome,
    scan_run_id: EntityId,
    source_file_id: EntityId,
    source_before_observation_id: EntityId,
    source_scan_event_id: EntityId,
    source_observation_id: EntityId | None,
    target_file_id: EntityId | None,
    target_observation_id: EntityId | None,
    target_scan_event_id: EntityId | None,
    collection_state_snapshot_id: EntityId,
    collection_state_content_digest: str,
    expected_full_sha256: str,
    expected_size_bytes: int,
    target_absence_fingerprint: str,
    physical_confirmation_digest: str,
    reconciled_at: datetime,
) -> EbookRenameReconciliationSnapshot:
    material: dict[str, object] = {
        "run_id": run_id,
        "authorization_id": authorization_id,
        "authorization_content_hash": authorization_content_hash,
        "preparation_id": preparation_id,
        "preparation_content_hash": preparation_content_hash,
        "outcome": outcome,
        "scan_run_id": scan_run_id,
        "source_file_id": source_file_id,
        "source_before_observation_id": source_before_observation_id,
        "source_scan_event_id": source_scan_event_id,
        "source_observation_id": source_observation_id,
        "target_file_id": target_file_id,
        "target_observation_id": target_observation_id,
        "target_scan_event_id": target_scan_event_id,
        "collection_state_snapshot_id": collection_state_snapshot_id,
        "collection_state_content_digest": collection_state_content_digest,
        "expected_full_sha256": expected_full_sha256,
        "expected_size_bytes": expected_size_bytes,
        "target_absence_fingerprint": target_absence_fingerprint,
        "physical_confirmation_digest": physical_confirmation_digest,
        "reconciled_at": reconciled_at,
    }
    return EbookRenameReconciliationSnapshot(
        run_id=run_id,
        authorization_id=authorization_id,
        authorization_content_hash=authorization_content_hash,
        preparation_id=preparation_id,
        preparation_content_hash=preparation_content_hash,
        outcome=outcome,
        scan_run_id=scan_run_id,
        source_file_id=source_file_id,
        source_before_observation_id=source_before_observation_id,
        source_scan_event_id=source_scan_event_id,
        source_observation_id=source_observation_id,
        target_file_id=target_file_id,
        target_observation_id=target_observation_id,
        target_scan_event_id=target_scan_event_id,
        collection_state_snapshot_id=collection_state_snapshot_id,
        collection_state_content_digest=collection_state_content_digest,
        expected_full_sha256=expected_full_sha256,
        expected_size_bytes=expected_size_bytes,
        target_absence_fingerprint=target_absence_fingerprint,
        physical_confirmation_digest=physical_confirmation_digest,
        reconciled_at=reconciled_at,
        content_hash=_content_hash_from_material(material),
    )


def _content_hash(value: EbookRenameReconciliationSnapshot) -> str:
    return _content_hash_from_material(
        {
            "authorization_content_hash": value.authorization_content_hash,
            "authorization_id": value.authorization_id,
            "collection_state_content_digest": value.collection_state_content_digest,
            "collection_state_snapshot_id": value.collection_state_snapshot_id,
            "expected_full_sha256": value.expected_full_sha256,
            "expected_size_bytes": value.expected_size_bytes,
            "outcome": value.outcome,
            "physical_confirmation_digest": value.physical_confirmation_digest,
            "preparation_content_hash": value.preparation_content_hash,
            "preparation_id": value.preparation_id,
            "reconciled_at": value.reconciled_at,
            "run_id": value.run_id,
            "scan_run_id": value.scan_run_id,
            "source_before_observation_id": value.source_before_observation_id,
            "source_file_id": value.source_file_id,
            "source_observation_id": value.source_observation_id,
            "source_scan_event_id": value.source_scan_event_id,
            "target_absence_fingerprint": value.target_absence_fingerprint,
            "target_file_id": value.target_file_id,
            "target_observation_id": value.target_observation_id,
            "target_scan_event_id": value.target_scan_event_id,
        }
    )


def _content_hash_from_material(material: dict[str, object]) -> str:
    reconciled_at = material["reconciled_at"]
    outcome = material["outcome"]
    if not isinstance(reconciled_at, datetime) or not isinstance(
        outcome, EbookRenameReconciliationOutcome
    ):
        raise ValueError("e-book rename reconciliation material is invalid")
    canonical = {
        key: (
            value.value
            if isinstance(value, EbookRenameReconciliationOutcome)
            else value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, EntityId)
            else value
        )
        for key, value in material.items()
    }
    canonical["profile"] = EBOOK_RENAME_RECONCILIATION_PROFILE
    payload = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(_RECONCILIATION_DOMAIN + payload).hexdigest()


__all__ = [
    "EBOOK_RENAME_RECONCILIATION_PROFILE",
    "EbookRenameReconciliationOutcome",
    "EbookRenameReconciliationSnapshot",
    "build_ebook_rename_reconciliation",
]
