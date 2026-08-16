"""Provider entry points for synthetic structured book knowledge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from foliotone.core import EntityId, EntityKind
from foliotone.enrichment.contracts import (
    DEFAULT_KNOWLEDGE_PROVIDER_VERSION,
    BookKnowledgeDTO,
    BookKnowledgeQuery,
    BookKnowledgeResponse,
    KnowledgeProviderDescriptor,
    KnowledgeProviderMode,
    StructuredKnowledgeBookResult,
)


class SyntheticKnowledgeBookRecord(TypedDict):
    title: str
    aliases: tuple[str, ...]
    authors: tuple[str, ...]
    author: str
    identifiers: tuple[tuple[str, str], ...]


class SyntheticBookKnowledgeProvider:
    """Structured book provider backed by synthetic fixtures only."""

    def __init__(self, *, mode: KnowledgeProviderMode = KnowledgeProviderMode.OFFLINE) -> None:
        self.descriptor = KnowledgeProviderDescriptor(
            provider_id="synthetic-book-knowledge",
            display_name="Synthetic Book Knowledge Provider",
            source_version=DEFAULT_KNOWLEDGE_PROVIDER_VERSION,
            default_mode=mode,
        )

    def fetch(
        self,
        query: BookKnowledgeQuery,
        *,
        observed_at: datetime | None = None,
    ) -> BookKnowledgeResponse:
        now = observed_at or datetime.now(tz=UTC)
        fingerprint = query.fingerprint()
        matches = tuple(_iter_matches(query))
        results = tuple(
            StructuredKnowledgeBookResult(
                query_fingerprint=fingerprint,
                provider_id=self.descriptor.provider_id,
                source_version=self.descriptor.source_version,
                target_kind=EntityKind.WORK,
                target_id=str(EntityId.new()),
                dtos=tuple(_to_dtos(match)),
                confidence=0.9,
                evidence_count=2,
                observed_at=now,
            )
            for match in matches
        )

        return BookKnowledgeResponse(
            query=query,
            mode=self.descriptor.default_mode,
            descriptor=self.descriptor,
            results=results,
        )


def _iter_matches(
    query: BookKnowledgeQuery,
) -> tuple[SyntheticKnowledgeBookRecord, ...]:
    normalized_title = query.normalized_title
    identifier_keys = {
        f"{namespace}:{value}" for namespace, value in query.identifiers
    }
    matches: list[SyntheticKnowledgeBookRecord] = []
    for dataset in _SYNTHETIC_BOOKS:
        if _matches_identifier(dataset, identifier_keys):
            matches.append(dataset)
            continue
        if _matches_title_and_authors(
            dataset,
            normalized_title,
            query.authors,
        ):
            matches.append(dataset)
    return tuple(matches)


def _matches_identifier(
    dataset: SyntheticKnowledgeBookRecord,
    identifier_keys: set[str],
) -> bool:
    if not identifier_keys:
        return False
    return any(
        f"{namespace}:{value}" in identifier_keys
        for namespace, value in dataset["identifiers"]
    )


def _matches_title_and_authors(
    dataset: SyntheticKnowledgeBookRecord,
    normalized_title: str,
    normalized_authors: tuple[str, ...],
) -> bool:
    if normalized_title not in dataset["aliases"]:
        return False
    if not normalized_authors:
        return True
    return any(author in dataset["authors"] for author in normalized_authors)


def _to_dtos(
    dataset: SyntheticKnowledgeBookRecord,
) -> tuple[BookKnowledgeDTO, ...]:
    return (
        BookKnowledgeDTO(
            key="work.title",
            value=dataset["title"],
            source_field="title",
            confidence=0.95,
            score=0.95,
        ),
        BookKnowledgeDTO(
            key="agent.name",
            value=dataset["author"],
            source_field="creator",
            confidence=0.91,
            score=0.91,
        ),
    )


_SYNTHETIC_BOOKS: tuple[SyntheticKnowledgeBookRecord, ...] = (
    {
        "title": "Project Babel",
        "aliases": ("project babel", "babel"),
        "authors": ("alice walker", "jane doe"),
        "author": "Jane Doe",
        "identifiers": (("isbn", "9783161484100"),),
    },
    {
        "title": "The Great Tale",
        "aliases": ("the great tale", "great tale"),
        "authors": ("john doe", "bert old"),
        "author": "John Doe",
        "identifiers": (("isbn", "9780007117116"),),
    },
)
