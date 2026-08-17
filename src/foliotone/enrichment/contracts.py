"""Structured contracts for book-oriented external knowledge providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Final

from foliotone.core import EntityKind
from foliotone.core._validation import require_confidence, require_non_empty

DEFAULT_KNOWLEDGE_PROVIDER_VERSION: Final = "knowledge-provider/v1"


class KnowledgeProviderMode(Enum):
    """Execution mode used by a structured knowledge provider."""

    OFFLINE = "offline"
    ONLINE = "online"
    CACHE = "cache"


@dataclass(frozen=True, slots=True)
class KnowledgeProviderDescriptor:
    """Stable provider identity and policy."""

    provider_id: str
    display_name: str
    source_version: str
    default_mode: KnowledgeProviderMode
    supports_cache: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", require_non_empty(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "display_name", require_non_empty(self.display_name, "display_name")
        )
        object.__setattr__(
            self, "source_version", require_non_empty(self.source_version, "source_version")
        )
        if not isinstance(self.default_mode, KnowledgeProviderMode):
            raise ValueError("default_mode must be a KnowledgeProviderMode")


@dataclass(frozen=True, slots=True)
class BookKnowledgeQuery:
    """Minimal, privacy-safe query contract for book enrichment providers."""

    title: str
    authors: tuple[str, ...] = ()
    identifiers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", require_non_empty(self.title, "title"))
        object.__setattr__(
            self, "authors", tuple(_normalize_text(author) for author in self.authors)
        )
        object.__setattr__(
            self, "identifiers", tuple(_normalize_identifier(*pair) for pair in self.identifiers)
        )

    @property
    def normalized_title(self) -> str:
        return _normalize_text(self.title)

    def fingerprint(self) -> str:
        payload = "|".join(
            (
                self.normalized_title,
                ",".join(self.authors),
                "|".join(f"{namespace}:{value}" for namespace, value in self.identifiers),
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BookKnowledgeDTO:
    """Privacy-minimised structured evidence for one claim."""

    key: str
    value: str
    confidence: float
    score: float
    source_field: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "key", require_non_empty(self.key, "key")
        )
        object.__setattr__(
            self, "value", require_non_empty(self.value, "value")
        )
        object.__setattr__(
            self, "source_field", require_non_empty(self.source_field, "source_field")
        )
        require_confidence(self.confidence, "confidence")
        require_confidence(self.score, "score")

    def as_privacy_dto(self) -> dict[str, str | float]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "score": self.score,
            "source_field": self.source_field,
        }


@dataclass(frozen=True, slots=True)
class StructuredKnowledgeBookResult:
    """Resolved knowledge row tied to a query fingerprint."""

    query_fingerprint: str
    provider_id: str
    source_version: str
    target_kind: EntityKind
    target_id: str
    dtos: tuple[BookKnowledgeDTO, ...]
    confidence: float
    evidence_count: int
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query_fingerprint",
            require_non_empty(self.query_fingerprint, "query_fingerprint"),
        )
        object.__setattr__(self, "provider_id", require_non_empty(self.provider_id, "provider_id"))
        object.__setattr__(
            self, "source_version", require_non_empty(self.source_version, "source_version")
        )
        object.__setattr__(self, "target_id", require_non_empty(self.target_id, "target_id"))
        if not self.dtos:
            raise ValueError("StructuredKnowledgeBookResult requires at least one DTO")
        if self.evidence_count < 1:
            raise ValueError("evidence_count must be greater than zero")
        require_confidence(self.confidence, "confidence")

    def as_privacy_dto(self) -> dict[str, object]:
        return {
            "query_fingerprint": self.query_fingerprint,
            "provider_id": self.provider_id,
            "source_version": self.source_version,
            "target_kind": self.target_kind.name,
            "target_id": self.target_id,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "dtos": tuple(dto.as_privacy_dto() for dto in self.dtos),
        }


@dataclass(frozen=True, slots=True)
class BookKnowledgeResponse:
    """Privacy-first envelope for one query round-trip."""

    query: BookKnowledgeQuery
    mode: KnowledgeProviderMode
    descriptor: KnowledgeProviderDescriptor
    results: tuple[StructuredKnowledgeBookResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, KnowledgeProviderMode):
            raise ValueError("mode must be a KnowledgeProviderMode")

    @property
    def query_fingerprint(self) -> str:
        return self.query.fingerprint()

    def as_privacy_dto(self) -> dict[str, object]:
        return {
            "provider_id": self.descriptor.provider_id,
            "source_version": self.descriptor.source_version,
            "query_fingerprint": self.query_fingerprint,
            "mode": self.mode.value,
            "result_count": len(self.results),
            "results": tuple(result.as_privacy_dto() for result in self.results),
        }


def _normalize_text(value: str) -> str:
    return require_non_empty(value, "text").strip().casefold()


def _normalize_identifier(namespace: str, value: str) -> tuple[str, str]:
    return _normalize_text(namespace), "".join(ch for ch in _normalize_text(value) if ch.isalnum())
