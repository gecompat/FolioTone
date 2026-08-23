"""Immutable path-free reconciliation evidence for one metadata-write run."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from foliotone.core import EntityId

METADATA_WRITE_RECONCILIATION_PROFILE: Final = "metadata-write-reconciliation/v1"
_RECONCILIATION_DOMAIN: Final = b"foliotone:metadata-write-reconciliation/v1\x00"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class MetadataWriteReconciliationOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True, slots=True)
class MetadataWriteReconciliationSnapshot:
    """One exact ScanRun/Observation/CollectionState binding."""

    run_id: EntityId
    authorization_id: EntityId
    authorization_content_hash: str = field(repr=False)
    outcome: MetadataWriteReconciliationOutcome
    scan_run_id: EntityId
    observation_id: EntityId
    collection_state_snapshot_id: EntityId
    collection_state_content_digest: str = field(repr=False)
    physical_confirmation_digest: str = field(repr=False)
    reconciled_at: datetime
    content_hash: str = field(repr=False)
    profile: str = METADATA_WRITE_RECONCILIATION_PROFILE

    def __post_init__(self) -> None:
        if self.profile != METADATA_WRITE_RECONCILIATION_PROFILE:
            raise ValueError("metadata write reconciliation profile is invalid")
        if not all(
            isinstance(value, EntityId)
            for value in (
                self.run_id,
                self.authorization_id,
                self.scan_run_id,
                self.observation_id,
                self.collection_state_snapshot_id,
            )
        ) or not isinstance(self.outcome, MetadataWriteReconciliationOutcome):
            raise ValueError("metadata write reconciliation identity is invalid")
        for value in (
            self.authorization_content_hash,
            self.collection_state_content_digest,
            self.physical_confirmation_digest,
            self.content_hash,
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("metadata write reconciliation digest is invalid")
        if (
            not isinstance(self.reconciled_at, datetime)
            or self.reconciled_at.tzinfo is None
            or self.reconciled_at.utcoffset() is None
        ):
            raise ValueError("metadata write reconciliation timestamp is invalid")
        object.__setattr__(self, "reconciled_at", self.reconciled_at.astimezone(UTC))
        if self.content_hash != _content_hash(self):
            raise ValueError("metadata write reconciliation content hash differs")


def build_metadata_write_reconciliation(
    *,
    run_id: EntityId,
    authorization_id: EntityId,
    authorization_content_hash: str,
    outcome: MetadataWriteReconciliationOutcome,
    scan_run_id: EntityId,
    observation_id: EntityId,
    collection_state_snapshot_id: EntityId,
    collection_state_content_digest: str,
    physical_confirmation_digest: str,
    reconciled_at: datetime,
) -> MetadataWriteReconciliationSnapshot:
    """Build content-addressed evidence without Source Media access."""

    material: dict[str, object] = {
        "run_id": run_id,
        "authorization_id": authorization_id,
        "authorization_content_hash": authorization_content_hash,
        "outcome": outcome,
        "scan_run_id": scan_run_id,
        "observation_id": observation_id,
        "collection_state_snapshot_id": collection_state_snapshot_id,
        "collection_state_content_digest": collection_state_content_digest,
        "physical_confirmation_digest": physical_confirmation_digest,
        "reconciled_at": reconciled_at,
    }
    return MetadataWriteReconciliationSnapshot(
        run_id=run_id,
        authorization_id=authorization_id,
        authorization_content_hash=authorization_content_hash,
        outcome=outcome,
        scan_run_id=scan_run_id,
        observation_id=observation_id,
        collection_state_snapshot_id=collection_state_snapshot_id,
        collection_state_content_digest=collection_state_content_digest,
        physical_confirmation_digest=physical_confirmation_digest,
        reconciled_at=reconciled_at,
        content_hash=_content_hash_from_material(material),
    )


def _content_hash(value: MetadataWriteReconciliationSnapshot) -> str:
    return _content_hash_from_material(
        {
            "authorization_content_hash": value.authorization_content_hash,
            "authorization_id": value.authorization_id,
            "collection_state_content_digest": value.collection_state_content_digest,
            "collection_state_snapshot_id": value.collection_state_snapshot_id,
            "observation_id": value.observation_id,
            "outcome": value.outcome,
            "physical_confirmation_digest": value.physical_confirmation_digest,
            "reconciled_at": value.reconciled_at,
            "run_id": value.run_id,
            "scan_run_id": value.scan_run_id,
        }
    )


def _content_hash_from_material(material: dict[str, object]) -> str:
    reconciled_at = material["reconciled_at"]
    outcome = material["outcome"]
    if not isinstance(reconciled_at, datetime) or not isinstance(
        outcome, MetadataWriteReconciliationOutcome
    ):
        raise ValueError("metadata write reconciliation material is invalid")
    canonical = {
        "authorization_content_hash": material["authorization_content_hash"],
        "authorization_id": str(material["authorization_id"]),
        "collection_state_content_digest": material["collection_state_content_digest"],
        "collection_state_snapshot_id": str(material["collection_state_snapshot_id"]),
        "observation_id": str(material["observation_id"]),
        "outcome": outcome.value,
        "physical_confirmation_digest": material["physical_confirmation_digest"],
        "profile": METADATA_WRITE_RECONCILIATION_PROFILE,
        "reconciled_at": reconciled_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "run_id": str(material["run_id"]),
        "scan_run_id": str(material["scan_run_id"]),
    }
    payload = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(_RECONCILIATION_DOMAIN + payload).hexdigest()


__all__ = [
    "METADATA_WRITE_RECONCILIATION_PROFILE",
    "MetadataWriteReconciliationOutcome",
    "MetadataWriteReconciliationSnapshot",
    "build_metadata_write_reconciliation",
]
