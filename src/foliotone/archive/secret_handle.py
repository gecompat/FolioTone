"""Opaque SecretHandle and non-secret archive password attempt metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from foliotone.archive.secret_candidates import (
    MAX_ATTEMPTS_PER_ARCHIVE,
    ArchiveSecretCandidateSource,
)

ARCHIVE_PASSWORD_ATTEMPT_PROFILE: Final = "archive-password-attempt/v1"
MAX_OPAQUE_ID_CODEPOINTS: Final = 256
MAX_OPAQUE_ID_UTF8_BYTES: Final = 1_024
MAX_CANDIDATE_RANK: Final = 64


class ArchivePasswordAttemptStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SECURE_CHANNEL_UNAVAILABLE = "SECURE_CHANNEL_UNAVAILABLE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TOOL_ERROR = "TOOL_ERROR"


@dataclass(frozen=True, slots=True)
class SecretHandle:
    """A public, versioned reference; it never contains secret bytes."""

    provider_id: str
    handle_id: str
    secret_version: str

    def __post_init__(self) -> None:
        _require_opaque("provider_id", self.provider_id)
        _require_opaque("handle_id", self.handle_id)
        _require_opaque("secret_version", self.secret_version)

    def cache_key(self) -> tuple[str, str, str]:
        """Return only the opaque identity and version, never material."""

        return (self.provider_id, self.handle_id, self.secret_version)

    def to_persistable_payload(self) -> dict[str, str]:
        """Return the complete public representation permitted by ADR-0038."""

        return {
            "provider_id": self.provider_id,
            "handle_id": self.handle_id,
            "secret_version": self.secret_version,
        }


@dataclass(frozen=True, slots=True)
class ArchivePasswordAttemptMetadata:
    """Insert-only metadata for one bounded attempt; no candidate value field exists."""

    archive_identity: str
    observation_profile: str
    tool_provider_id: str
    tool_version: str
    adapter_version: str
    status: ArchivePasswordAttemptStatus
    attempt_count: int
    observed_at: datetime
    secret_handle: SecretHandle | None = None
    candidate_source: ArchiveSecretCandidateSource | None = None
    candidate_rank: int | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("archive_identity", self.archive_identity),
            ("observation_profile", self.observation_profile),
            ("tool_provider_id", self.tool_provider_id),
            ("tool_version", self.tool_version),
            ("adapter_version", self.adapter_version),
        ):
            _require_opaque(
                field_name,
                value,
                allow_slash=field_name in {"observation_profile", "adapter_version"},
            )
        if not isinstance(self.status, ArchivePasswordAttemptStatus):
            raise ValueError("status must be ArchivePasswordAttemptStatus")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or not 0 <= self.attempt_count <= MAX_ATTEMPTS_PER_ARCHIVE
        ):
            raise ValueError("attempt_count exceeds the archive attempt bound")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must have a UTC offset")
        if self.secret_handle is not None and not isinstance(self.secret_handle, SecretHandle):
            raise ValueError("secret_handle must be SecretHandle or None")
        if self.candidate_source is not None and not isinstance(
            self.candidate_source, ArchiveSecretCandidateSource
        ):
            raise ValueError("candidate_source must be ArchiveSecretCandidateSource or None")
        if self.candidate_rank is not None and (
            isinstance(self.candidate_rank, bool)
            or not isinstance(self.candidate_rank, int)
            or not 0 <= self.candidate_rank < MAX_CANDIDATE_RANK
        ):
            raise ValueError("candidate_rank exceeds the candidate bound")
        if (self.candidate_rank is None) is not (self.candidate_source is None):
            raise ValueError("candidate_source and candidate_rank must be present together")

    def to_persistable_payload(self) -> dict[str, object]:
        """Serialize only the ADR-0038-approved opaque metadata."""

        payload: dict[str, object] = {
            "profile": ARCHIVE_PASSWORD_ATTEMPT_PROFILE,
            "archive_identity": self.archive_identity,
            "observation_profile": self.observation_profile,
            "tool_provider_id": self.tool_provider_id,
            "tool_version": self.tool_version,
            "adapter_version": self.adapter_version,
            "status": self.status.value,
            "attempt_count": self.attempt_count,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
        }
        if self.secret_handle is not None:
            payload["secret_handle"] = self.secret_handle.to_persistable_payload()
        if self.candidate_source is not None:
            payload["candidate_source"] = self.candidate_source.value
        if self.candidate_rank is not None:
            payload["candidate_rank"] = self.candidate_rank
        return payload

    def cache_key(self) -> tuple[object, ...]:
        """Build a cache key solely from opaque versions and fixed metadata."""

        handle_key = self.secret_handle.cache_key() if self.secret_handle is not None else None
        return (
            ARCHIVE_PASSWORD_ATTEMPT_PROFILE,
            self.archive_identity,
            self.observation_profile,
            self.tool_provider_id,
            self.tool_version,
            self.adapter_version,
            self.status.value,
            self.attempt_count,
            self.candidate_source.value if self.candidate_source is not None else None,
            self.candidate_rank,
            handle_key,
        )


def _require_opaque(field_name: str, value: str, *, allow_slash: bool = False) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_OPAQUE_ID_CODEPOINTS:
        raise ValueError(f"{field_name} must be a bounded opaque string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} contains a control character")
    if (not allow_slash and "/" in value) or "\\" in value or ":" in value:
        raise ValueError(f"{field_name} must not contain a path")
    if allow_slash and (
        value.startswith("/")
        or "//" in value
        or any(part in {".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"{field_name} must not contain a path")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} is not valid UTF-8") from error
    if len(encoded) > MAX_OPAQUE_ID_UTF8_BYTES:
        raise ValueError(f"{field_name} exceeds the UTF-8 bound")
