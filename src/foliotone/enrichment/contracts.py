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


class ProviderAccessMode(Enum):
    """Sources that an external knowledge provider may access."""

    OFFLINE = "offline"
    LOCAL_DATASETS = "local_datasets"
    ONLINE_STRUCTURED = "online_structured"
    ONLINE_WEB_RESEARCH = "online_web_research"


class ProviderCachePolicy(Enum):
    """Cache behavior for an external knowledge provider request."""

    USE_IF_FRESH = "use_if_fresh"
    REFRESH_IF_STALE = "refresh_if_stale"
    FORCE_REFRESH = "force_refresh"
    NO_CACHE = "no_cache"


class KnowledgeProviderMode(Enum):
    """Execution mode used by a structured knowledge provider."""

    OFFLINE = "offline"
    ONLINE = "online"
    CACHE = "cache"


def provider_policy_from_legacy(
    mode: KnowledgeProviderMode,
) -> tuple[ProviderAccessMode, ProviderCachePolicy]:
    """Map one deprecated provider mode to its canonical policy pair."""

    if not isinstance(mode, KnowledgeProviderMode):
        raise ValueError("mode must be a KnowledgeProviderMode")
    return {
        KnowledgeProviderMode.OFFLINE: (
            ProviderAccessMode.OFFLINE,
            ProviderCachePolicy.NO_CACHE,
        ),
        KnowledgeProviderMode.ONLINE: (
            ProviderAccessMode.ONLINE_STRUCTURED,
            ProviderCachePolicy.NO_CACHE,
        ),
        KnowledgeProviderMode.CACHE: (
            ProviderAccessMode.OFFLINE,
            ProviderCachePolicy.USE_IF_FRESH,
        ),
    }[mode]


def validate_provider_policy(
    access_mode: ProviderAccessMode,
    cache_policy: ProviderCachePolicy,
) -> None:
    """Validate one provider access and cache-policy combination."""

    if not isinstance(access_mode, ProviderAccessMode):
        raise ValueError("access_mode must be a ProviderAccessMode")
    if not isinstance(cache_policy, ProviderCachePolicy):
        raise ValueError("cache_policy must be a ProviderCachePolicy")
    if access_mode is ProviderAccessMode.OFFLINE and cache_policy in {
        ProviderCachePolicy.REFRESH_IF_STALE,
        ProviderCachePolicy.FORCE_REFRESH,
    }:
        raise ValueError("offline access cannot request a source refresh")


@dataclass(frozen=True, slots=True)
class KnowledgeProviderDescriptor:
    """Stable provider identity and policy."""

    provider_id: str
    display_name: str
    source_version: str
    default_access_mode: ProviderAccessMode
    default_cache_policy: ProviderCachePolicy
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
        validate_provider_policy(
            self.default_access_mode,
            self.default_cache_policy,
        )


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
    access_mode: ProviderAccessMode
    cache_policy: ProviderCachePolicy
    descriptor: KnowledgeProviderDescriptor
    results: tuple[StructuredKnowledgeBookResult, ...]

    def __post_init__(self) -> None:
        validate_provider_policy(self.access_mode, self.cache_policy)

    @property
    def query_fingerprint(self) -> str:
        return self.query.fingerprint()

    def as_privacy_dto(self) -> dict[str, object]:
        return {
            "provider_id": self.descriptor.provider_id,
            "source_version": self.descriptor.source_version,
            "query_fingerprint": self.query_fingerprint,
            "access_mode": self.access_mode.value,
            "cache_policy": self.cache_policy.value,
            "result_count": len(self.results),
            "results": tuple(result.as_privacy_dto() for result in self.results),
        }


def _normalize_text(value: str) -> str:
    return require_non_empty(value, "text").strip().casefold()


def _normalize_identifier(namespace: str, value: str) -> tuple[str, str]:
    return _normalize_text(namespace), "".join(ch for ch in _normalize_text(value) if ch.isalnum())
