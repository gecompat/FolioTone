"""Immutable and deterministic contracts for book-only CollectionState v1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from foliotone.core._validation import require_aware_datetime, require_non_empty
from foliotone.core.ids import EntityId

COLLECTION_STATE_PROFILE: Final = "collection-state/v1"
COLLECTION_STATE_SERIALIZER: Final = "canonical-json/v1"
COLLECTION_STATE_NAMESPACE: Final = UUID("6c9e9c49-84ac-5bf6-9c02-0a1a3a604b70")
MAX_COLLECTION_STATE_PROFILE_VERSIONS: Final = 256
MAX_COLLECTION_STATE_PROFILE_VERSION_LENGTH: Final = 512


class CollectionStateComponentName(StrEnum):
    ANALYSIS = "ANALYSIS"
    RESOLUTION = "RESOLUTION"
    CLASSIFICATION = "CLASSIFICATION"
    MATCHING = "MATCHING"
    REVIEW = "REVIEW"
    CALIBRE = "CALIBRE"
    ARCHIVE = "ARCHIVE"
    CONSOLIDATION = "CONSOLIDATION"
    QUARANTINE = "QUARANTINE"


COLLECTION_STATE_COMPONENT_ORDER: Final = tuple(CollectionStateComponentName)
COLLECTION_STATE_COUNT_PREFIXES: Final = {
    CollectionStateComponentName.ANALYSIS: "analysis",
    CollectionStateComponentName.RESOLUTION: "resolver",
    CollectionStateComponentName.CLASSIFICATION: "classification",
    CollectionStateComponentName.MATCHING: "matcher",
    CollectionStateComponentName.REVIEW: "review",
    CollectionStateComponentName.CALIBRE: "calibre",
    CollectionStateComponentName.ARCHIVE: "archive",
    CollectionStateComponentName.CONSOLIDATION: "consolidation",
    CollectionStateComponentName.QUARANTINE: "quarantine",
}
COLLECTION_STATE_FORMAT_NAMES: Final = ("AZW", "AZW3", "EPUB", "MOBI", "OTHER", "PDF")


class CollectionStateCoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class CollectionStateFreshnessState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class CollectionStateConflictState(StrEnum):
    NONE = "NONE"
    PRESENT = "PRESENT"


class CollectionStateTruncationState(StrEnum):
    NONE = "NONE"
    PROFILE_VERSIONS = "PROFILE_VERSIONS"


class CollectionStateItemState(StrEnum):
    CURRENT = "CURRENT"
    CURRENT_CONFLICT = "CURRENT_CONFLICT"
    STALE = "STALE"
    STALE_CONFLICT = "STALE_CONFLICT"
    UNSCOPED = "UNSCOPED"
    UNSCOPED_CONFLICT = "UNSCOPED_CONFLICT"
    MISSING = "MISSING"


def _sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CollectionStateComponentSummary:
    component: CollectionStateComponentName
    profile_versions: tuple[str, ...]
    evidence_count: int
    current_item_count: int
    stale_item_count: int
    unscoped_item_count: int
    missing_item_count: int
    conflict_item_count: int
    coverage_state: CollectionStateCoverageState
    freshness_state: CollectionStateFreshnessState
    conflict_state: CollectionStateConflictState
    truncation_state: CollectionStateTruncationState
    evidence_digest: str

    def __post_init__(self) -> None:
        profiles = tuple(self.profile_versions)
        if profiles != tuple(sorted(set(profiles))):
            raise ValueError("profile_versions must be sorted and unique")
        if len(profiles) > MAX_COLLECTION_STATE_PROFILE_VERSIONS:
            raise ValueError("profile_versions exceeds the bounded contract")
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_COLLECTION_STATE_PROFILE_VERSION_LENGTH
            for value in profiles
        ):
            raise ValueError("profile_versions must contain non-empty strings")
        for field_name in (
            "evidence_count",
            "current_item_count",
            "stale_item_count",
            "unscoped_item_count",
            "missing_item_count",
            "conflict_item_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        _sha256(self.evidence_digest, "evidence_digest")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "component": self.component.value,
            "profile_versions": list(self.profile_versions),
            "evidence_count": self.evidence_count,
            "current_item_count": self.current_item_count,
            "stale_item_count": self.stale_item_count,
            "unscoped_item_count": self.unscoped_item_count,
            "missing_item_count": self.missing_item_count,
            "conflict_item_count": self.conflict_item_count,
            "coverage_state": self.coverage_state.value,
            "freshness_state": self.freshness_state.value,
            "conflict_state": self.conflict_state.value,
            "truncation_state": self.truncation_state.value,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class CollectionStateCount:
    key: str
    value: int

    def __post_init__(self) -> None:
        key = require_non_empty(self.key, "key")
        if len(key) > 128 or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in key
        ):
            raise ValueError("count key must be a bounded lowercase technical key")
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0:
            raise ValueError("count value must be a nonnegative integer")
        object.__setattr__(self, "key", key)

    def canonical_payload(self) -> dict[str, object]:
        return {"key": self.key, "value": self.value}


@dataclass(frozen=True, slots=True)
class CollectionStateItem:
    ordinal: int
    file_id: EntityId
    observation_id: EntityId
    format_name: str
    size_bytes: int
    technical_digest: str
    analysis_state: CollectionStateItemState
    analysis_digest: str | None
    resolution_state: CollectionStateItemState
    resolution_digest: str | None
    classification_state: CollectionStateItemState
    classification_digest: str | None
    matching_state: CollectionStateItemState
    matching_digest: str | None
    review_state: CollectionStateItemState
    review_digest: str | None
    calibre_state: CollectionStateItemState
    calibre_digest: str | None
    archive_state: CollectionStateItemState
    archive_digest: str | None
    consolidation_state: CollectionStateItemState
    consolidation_digest: str | None
    quarantine_state: CollectionStateItemState
    quarantine_digest: str | None
    item_digest: str

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a nonnegative integer")
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("CollectionState item IDs are invalid")
        if self.format_name not in {"EPUB", "MOBI", "AZW", "AZW3", "PDF", "OTHER"}:
            raise ValueError("format_name is outside the book-only allowlist")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must not be negative")
        _sha256(self.technical_digest, "technical_digest")
        for component in CollectionStateComponentName:
            state = getattr(self, f"{component.value.casefold()}_state")
            digest = getattr(self, f"{component.value.casefold()}_digest")
            if state is CollectionStateItemState.MISSING:
                if digest is not None:
                    raise ValueError("missing component state cannot have a digest")
            elif digest is None:
                raise ValueError("present component state requires a digest")
            else:
                _sha256(digest, f"{component.value.casefold()}_digest")
        expected_item_digest = self.compute_item_digest()
        if not self.item_digest:
            object.__setattr__(self, "item_digest", expected_item_digest)
        _sha256(self.item_digest, "item_digest")
        if self.item_digest != expected_item_digest:
            raise ValueError("item_digest does not match canonical item data")

    def material_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "ordinal": self.ordinal,
            "file_id": str(self.file_id),
            "observation_id": str(self.observation_id),
            "format_name": self.format_name,
            "size_bytes": self.size_bytes,
            "technical_digest": self.technical_digest,
        }
        for component in CollectionStateComponentName:
            key = component.value.casefold()
            payload[f"{key}_state"] = getattr(self, f"{key}_state").value
            payload[f"{key}_digest"] = getattr(self, f"{key}_digest")
        return payload

    def canonical_payload(self) -> dict[str, object]:
        return {**self.material_payload(), "item_digest": self.item_digest}

    def compute_item_digest(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.material_payload())).hexdigest()


class CollectionStateItemsHasher:
    """Stream a deterministic digest over canonical item rows."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256(b"foliotone:collection-state-items/v1\x00")
        self._next_ordinal = 0

    def update(self, item: CollectionStateItem) -> None:
        if item.ordinal != self._next_ordinal:
            raise ValueError("CollectionState items must be contiguous and ordered")
        payload = _canonical_bytes(item.canonical_payload())
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        self._next_ordinal += 1

    @property
    def count(self) -> int:
        return self._next_ordinal

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CollectionStateSnapshot:
    id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    created_at: datetime
    item_count: int
    total_size_bytes: int
    items_digest: str
    components: tuple[CollectionStateComponentSummary, ...]
    counts: tuple[CollectionStateCount, ...]
    content_digest: str
    profile: str = COLLECTION_STATE_PROFILE
    serializer: str = COLLECTION_STATE_SERIALIZER

    def __post_init__(self) -> None:
        if self.profile != COLLECTION_STATE_PROFILE:
            raise ValueError("CollectionState profile is invalid")
        if self.serializer != COLLECTION_STATE_SERIALIZER:
            raise ValueError("CollectionState serializer is invalid")
        if (
            not isinstance(self.id, EntityId)
            or not isinstance(self.scan_root_id, EntityId)
            or not isinstance(self.source_scan_run_id, EntityId)
        ):
            raise ValueError("CollectionState IDs are invalid")
        require_aware_datetime(self.created_at, "created_at")
        for field_name in ("item_count", "total_size_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        _sha256(self.items_digest, "items_digest")
        components = tuple(self.components)
        if tuple(item.component for item in components) != COLLECTION_STATE_COMPONENT_ORDER:
            raise ValueError("CollectionState components must be complete and ordered")
        for component in components:
            covered_items = (
                component.current_item_count
                + component.stale_item_count
                + component.unscoped_item_count
                + component.missing_item_count
            )
            if covered_items != self.item_count:
                raise ValueError("CollectionState component item counts are incomplete")
            if component.conflict_item_count > self.item_count - component.missing_item_count:
                raise ValueError("CollectionState component conflict count is invalid")
        counts = tuple(self.counts)
        if tuple(item.key for item in counts) != tuple(sorted({item.key for item in counts})):
            raise ValueError("CollectionState counts must be sorted and unique")
        count_values = {item.key: item.value for item in counts}
        expected_count_keys = {
            "physical.byte_count",
            "physical.item_count",
            *(f"physical.format.{name.casefold()}" for name in COLLECTION_STATE_FORMAT_NAMES),
        }
        for prefix in COLLECTION_STATE_COUNT_PREFIXES.values():
            expected_count_keys.update(
                {
                    f"{prefix}.conflict_items",
                    f"{prefix}.current_items",
                    f"{prefix}.evidence_links",
                    f"{prefix}.missing_items",
                    f"{prefix}.stale_items",
                    f"{prefix}.unscoped_items",
                }
            )
        if set(count_values) != expected_count_keys:
            raise ValueError("CollectionState counts are incomplete")
        if (
            count_values["physical.item_count"] != self.item_count
            or count_values["physical.byte_count"] != self.total_size_bytes
            or sum(
                count_values[f"physical.format.{name.casefold()}"]
                for name in COLLECTION_STATE_FORMAT_NAMES
            )
            != self.item_count
        ):
            raise ValueError("CollectionState physical counts do not match the snapshot")
        for component in components:
            prefix = COLLECTION_STATE_COUNT_PREFIXES[component.component]
            mirrors = {
                f"{prefix}.conflict_items": component.conflict_item_count,
                f"{prefix}.current_items": component.current_item_count,
                f"{prefix}.evidence_links": component.evidence_count,
                f"{prefix}.missing_items": component.missing_item_count,
                f"{prefix}.stale_items": component.stale_item_count,
                f"{prefix}.unscoped_items": component.unscoped_item_count,
            }
            if any(count_values[key] != value for key, value in mirrors.items()):
                raise ValueError("CollectionState component counts do not match the snapshot")
        _sha256(self.content_digest, "content_digest")
        if self.content_digest != collection_state_content_digest(self):
            raise ValueError("content_digest does not match canonical snapshot data")
        if self.id != collection_state_snapshot_id(self.content_digest):
            raise ValueError("CollectionState snapshot ID does not match content_digest")

    def material_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "serializer": self.serializer,
            "scan_root_id": str(self.scan_root_id),
            "source_scan_run_id": str(self.source_scan_run_id),
            "item_count": self.item_count,
            "total_size_bytes": self.total_size_bytes,
            "items_digest": self.items_digest,
            "components": [item.canonical_payload() for item in self.components],
            "counts": [item.canonical_payload() for item in self.counts],
        }


def collection_state_content_digest(snapshot: CollectionStateSnapshot) -> str:
    return hashlib.sha256(_canonical_bytes(snapshot.material_payload())).hexdigest()


def collection_state_snapshot_id(content_digest: str) -> EntityId:
    _sha256(content_digest, "content_digest")
    return EntityId(uuid5(COLLECTION_STATE_NAMESPACE, content_digest))


def canonical_json_bytes(value: object) -> bytes:
    """Encode bounded internal evidence material deterministically."""

    return _canonical_bytes(value)


def sha256_digest(value: object) -> str:
    """Digest one canonical internal evidence value."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()
