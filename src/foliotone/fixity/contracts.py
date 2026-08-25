"""Immutable contracts for the book-only fixity baseline slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath

from foliotone.core._validation import require_aware_datetime
from foliotone.core.ids import EntityId

EBOOK_FIXITY_BASELINE_PROFILE = "ebook-fixity-baseline/v1"
EBOOK_FIXITY_BASELINE_SERIALIZER = "canonical-json/v1"
EBOOK_FIXITY_BASELINE_TTL = timedelta(minutes=15)
EBOOK_FIXITY_HASH_ALGORITHM = "sha256"
EBOOK_FIXITY_HASH_ALGORITHM_VERSION = "1"
MAX_EBOOK_FIXITY_LOCATOR_BYTES = 4096
MAX_EBOOK_FIXITY_COMPONENT_BYTES = 255


class EbookFixityBaselineBuildEventKind(StrEnum):
    """Append-only lifecycle facts for one baseline build attempt."""

    STARTED = "STARTED"
    FAILED = "FAILED"
    MANIFEST_READY = "MANIFEST_READY"


class EbookFixityBaselineBuildStatus(StrEnum):
    """Path-free status derived from the latest append-only build event."""

    BUILDING = "BUILDING"
    FAILED = "FAILED"
    READY = "READY"
    ACTIVE = "ACTIVE"


def canonical_json_bytes(value: object) -> bytes:
    """Encode internal baseline material deterministically."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_digest(value: object) -> str:
    """Hash one canonical internal baseline value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def require_sha256(value: str, field_name: str) -> str:
    """Require one lowercase full SHA-256 value."""

    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def require_private_relative_locator(value: str) -> str:
    """Require the exact private POSIX locator without normalizing it."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("relative_locator is invalid")
    path = PurePosixPath(value)
    parts = tuple(path.parts)
    try:
        encoded_length = len(value.encode("utf-8"))
        component_lengths = tuple(len(part.encode("utf-8")) for part in parts)
    except UnicodeError as error:
        raise ValueError("relative_locator is invalid") from error
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or encoded_length > MAX_EBOOK_FIXITY_LOCATOR_BYTES
        or any(length > MAX_EBOOK_FIXITY_COMPONENT_BYTES for length in component_lengths)
    ):
        raise ValueError("relative_locator is invalid")
    return value


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineSourceEntry:
    """Private read-only projection of one latest-scan source observation."""

    file_id: EntityId
    observation_id: EntityId
    relative_locator: str = field(repr=False)
    expected_size_bytes: int
    expected_modified_at: datetime = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("fixity source IDs are invalid")
        object.__setattr__(
            self,
            "relative_locator",
            require_private_relative_locator(self.relative_locator),
        )
        if (
            isinstance(self.expected_size_bytes, bool)
            or not isinstance(self.expected_size_bytes, int)
            or self.expected_size_bytes < 0
        ):
            raise ValueError("expected_size_bytes must be a nonnegative integer")
        require_aware_datetime(self.expected_modified_at, "expected_modified_at")


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineEntry:
    """One immutable private byte expectation in a sealed manifest."""

    ordinal: int
    file_id: EntityId
    observation_id: EntityId
    expected_size_bytes: int
    relative_locator: str = field(repr=False)
    expected_sha256: str = field(repr=False)
    entry_digest: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a nonnegative integer")
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("fixity entry IDs are invalid")
        if (
            isinstance(self.expected_size_bytes, bool)
            or not isinstance(self.expected_size_bytes, int)
            or self.expected_size_bytes < 0
        ):
            raise ValueError("expected_size_bytes must be a nonnegative integer")
        object.__setattr__(
            self,
            "relative_locator",
            require_private_relative_locator(self.relative_locator),
        )
        object.__setattr__(
            self,
            "expected_sha256",
            require_sha256(self.expected_sha256, "expected_sha256"),
        )
        expected_digest = sha256_digest(self.material_payload())
        if not self.entry_digest:
            object.__setattr__(self, "entry_digest", expected_digest)
        require_sha256(self.entry_digest, "entry_digest")
        if self.entry_digest != expected_digest:
            raise ValueError("entry_digest does not match canonical entry data")

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "file_id": str(self.file_id),
            "observation_id": str(self.observation_id),
            "expected_size_bytes": self.expected_size_bytes,
            "relative_locator": self.relative_locator,
            "hash_algorithm": EBOOK_FIXITY_HASH_ALGORITHM,
            "hash_algorithm_version": EBOOK_FIXITY_HASH_ALGORITHM_VERSION,
            "expected_sha256": self.expected_sha256,
        }


class EbookFixityBaselineEntriesHasher:
    """Build a bounded deterministic digest over gapless entry rows."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256(b"foliotone:ebook-fixity-baseline-entries/v1\x00")
        self._next_ordinal = 0

    def update(self, entry: EbookFixityBaselineEntry) -> None:
        if entry.ordinal != self._next_ordinal:
            raise ValueError("fixity baseline entries must be contiguous and ordered")
        payload = canonical_json_bytes(
            {**entry.material_payload(), "entry_digest": entry.entry_digest}
        )
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        self._next_ordinal += 1

    @property
    def count(self) -> int:
        return self._next_ordinal

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineManifest:
    """A completely built draft eligible for explicit activation."""

    manifest_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    prepared_at: datetime
    expires_at: datetime
    item_count: int
    total_size_bytes: int
    entries_digest: str
    content_digest: str = ""
    profile: str = EBOOK_FIXITY_BASELINE_PROFILE
    serializer: str = EBOOK_FIXITY_BASELINE_SERIALIZER

    def __post_init__(self) -> None:
        if self.profile != EBOOK_FIXITY_BASELINE_PROFILE:
            raise ValueError("fixity baseline profile is invalid")
        if self.serializer != EBOOK_FIXITY_BASELINE_SERIALIZER:
            raise ValueError("fixity baseline serializer is invalid")
        if not all(
            isinstance(value, EntityId)
            for value in (self.manifest_id, self.scan_root_id, self.source_scan_run_id)
        ):
            raise ValueError("fixity manifest IDs are invalid")
        require_aware_datetime(self.prepared_at, "prepared_at")
        require_aware_datetime(self.expires_at, "expires_at")
        if not self.prepared_at < self.expires_at:
            raise ValueError("fixity manifest must expire after preparation")
        if self.expires_at - self.prepared_at > EBOOK_FIXITY_BASELINE_TTL:
            raise ValueError("fixity manifest lifetime exceeds 15 minutes")
        for field_name in ("item_count", "total_size_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        require_sha256(self.entries_digest, "entries_digest")
        expected_digest = sha256_digest(self.material_payload())
        if not self.content_digest:
            object.__setattr__(self, "content_digest", expected_digest)
        require_sha256(self.content_digest, "content_digest")
        if self.content_digest != expected_digest:
            raise ValueError("content_digest does not match canonical manifest data")

    def material_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "serializer": self.serializer,
            "scan_root_id": str(self.scan_root_id),
            "source_scan_run_id": str(self.source_scan_run_id),
            "prepared_at": self.prepared_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "item_count": self.item_count,
            "total_size_bytes": self.total_size_bytes,
            "entries_digest": self.entries_digest,
        }


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineActivation:
    """Append-only activation of exactly one ready manifest."""

    activation_id: EntityId
    manifest_id: EntityId
    scan_root_id: EntityId
    activated_at: datetime
    manifest_content_digest: str
    confirmation_digest: str = field(repr=False)
    activation_digest: str = ""

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, EntityId)
            for value in (self.activation_id, self.manifest_id, self.scan_root_id)
        ):
            raise ValueError("fixity activation IDs are invalid")
        require_aware_datetime(self.activated_at, "activated_at")
        require_sha256(self.manifest_content_digest, "manifest_content_digest")
        require_sha256(self.confirmation_digest, "confirmation_digest")
        expected_digest = sha256_digest(self.material_payload())
        if not self.activation_digest:
            object.__setattr__(self, "activation_digest", expected_digest)
        require_sha256(self.activation_digest, "activation_digest")
        if self.activation_digest != expected_digest:
            raise ValueError("activation_digest does not match canonical activation data")

    def material_payload(self) -> dict[str, object]:
        return {
            "profile": EBOOK_FIXITY_BASELINE_PROFILE,
            "activation_id": str(self.activation_id),
            "manifest_id": str(self.manifest_id),
            "scan_root_id": str(self.scan_root_id),
            "activated_at": self.activated_at.isoformat(),
            "manifest_content_digest": self.manifest_content_digest,
            "confirmation_digest": self.confirmation_digest,
        }


@dataclass(frozen=True, slots=True)
class EbookFixityBaselineStatusSnapshot:
    """Path-, locator-, and hash-free status for later application adapters."""

    manifest_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    status: EbookFixityBaselineBuildStatus
    started_at: datetime
    prepared_at: datetime | None
    expires_at: datetime | None
    item_count: int | None
    total_size_bytes: int | None
    activated_at: datetime | None

    def __post_init__(self) -> None:
        require_aware_datetime(self.started_at, "started_at")
        for field_name in ("prepared_at", "expires_at", "activated_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware_datetime(value, field_name)
        if (self.prepared_at is None) != (self.expires_at is None):
            raise ValueError("prepared_at and expires_at must be set together")
        if (self.item_count is None) != (self.total_size_bytes is None):
            raise ValueError("fixity status counts must be set together")
        for field_name in ("item_count", "total_size_bytes"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} must be nonnegative when present")
