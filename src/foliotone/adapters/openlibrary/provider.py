"""Bounded Open Library provider vertical slice (ADR-0035/0036)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Final

from foliotone.enrichment import (
    BookKnowledgeQuery,
    KnowledgeProviderDescriptor,
    ProviderAccessMode,
    ProviderCacheContentSlot,
    ProviderCacheFailureSlot,
    ProviderCacheMappedRuntimeResult,
    ProviderCacheMappingRuntime,
    ProviderCachePayloadKind,
    ProviderCachePolicy,
    ProviderCachePort,
    ProviderCacheResultStatus,
    ProviderCacheRuntime,
    ProviderCacheSlots,
    ProviderCacheTransportResult,
    provider_source_cache_key,
)

from .mapping import (
    MAPPING_PROFILE_VERSION,
    PROVIDER_ADAPTER_VERSION,
    PROVIDER_ID,
    PROVIDER_SOURCE_VERSION,
    OpenLibraryAgentCandidate,
    OpenLibraryEvidenceProjection,
    OpenLibraryIdentifierProjection,
    OpenLibraryMappingResult,
    OpenLibraryWorkCandidate,
    map_openlibrary_source,
)
from .query import (
    OpenLibraryQueryBuilder,
    OpenLibraryQueryRoute,
    OpenLibraryRequest,
    OpenLibraryResolvedAuthorQuery,
    OpenLibraryRouteKind,
)
from .source import (
    MAX_NORMALIZED_BYTES,
    PAYLOAD_CODEC,
    PROFILE,
    AuthorSourceRecord,
    EditionSourceRecord,
    OpenLibrarySourceEnvelope,
    OpenLibrarySourceStatus,
    SearchSourceRecord,
    SourceRecord,
    WorkSourceRecord,
    parse_openlibrary_source,
)
from .transport import OpenLibraryTransport

POSITIVE_FRESH_TTL: Final = timedelta(days=30)
POSITIVE_RETENTION_TTL: Final = timedelta(days=180)
NOT_FOUND_FRESH_TTL: Final = timedelta(hours=6)
NOT_FOUND_RETENTION_TTL: Final = timedelta(hours=24)
RATE_LIMIT_MAX_TTL: Final = timedelta(hours=24)
FAILURE_TTLS: Final = {
    ProviderCacheResultStatus.RATE_LIMITED: timedelta(hours=1),
    ProviderCacheResultStatus.TEMPORARY_FAILURE: timedelta(minutes=5),
    ProviderCacheResultStatus.PERMANENT_FAILURE: timedelta(hours=24),
    ProviderCacheResultStatus.INVALID_RESPONSE: timedelta(hours=1),
}
_ENVELOPE_KEYS: Final = frozenset(
    {
        "profile",
        "endpoint_kind",
        "records",
        "result_count",
        "pagination_offset",
        "pagination_complete",
    }
)
_RECORD_KEYS: Final = {
    "WORK": frozenset(
        {"work_olid", "title", "first_publish_year", "author_refs", "subjects", "truncated"}
    ),
    "EDITION": frozenset(
        {
            "edition_olid",
            "work_refs",
            "title",
            "subtitle",
            "publish_date",
            "publishers",
            "languages",
            "isbn10",
            "isbn13",
            "oclc",
            "lccn",
            "author_refs",
            "truncated",
        }
    ),
    "AUTHOR": frozenset(
        {"author_olid", "name", "alternate_names", "birth_date", "death_date", "truncated"}
    ),
    "SEARCH": frozenset({"work", "editions", "contributor_names", "truncated"}),
}


@dataclass(frozen=True, slots=True)
class OpenLibraryProviderResult:
    """Redacted provider outcome; normalized source DTOs remain private."""

    status: ProviderCacheResultStatus | None
    source_cache_key: str | None
    mapping_input_key: str | None
    mapping: OpenLibraryMappingResult | None
    bulk_dataset_required: bool = False
    source_cache_keys: tuple[str, ...] = ()
    mapping_input_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is not None and not isinstance(self.status, ProviderCacheResultStatus):
            raise TypeError("status must be a ProviderCacheResultStatus or None")
        if type(self.bulk_dataset_required) is not bool:
            raise TypeError("bulk_dataset_required must be bool")
        if not isinstance(self.source_cache_keys, tuple) or not isinstance(
            self.mapping_input_keys, tuple
        ):
            raise TypeError("provider result keys must be tuples")
        for value in (
            self.source_cache_key,
            self.mapping_input_key,
            *self.source_cache_keys,
            *self.mapping_input_keys,
        ):
            if value is not None and (
                type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError("provider result keys must be lowercase SHA-256 digests")
        if self.source_cache_key is not None and (
            not self.source_cache_keys or self.source_cache_keys[0] != self.source_cache_key
        ):
            raise ValueError("source_cache_key must be the first source_cache_keys entry")
        if self.mapping_input_key is not None and (
            not self.mapping_input_keys or self.mapping_input_keys[0] != self.mapping_input_key
        ):
            raise ValueError("mapping_input_key must be the first mapping_input_keys entry")
        if self.bulk_dataset_required and any(
            value is not None
            for value in (self.status, self.source_cache_key, self.mapping_input_key, self.mapping)
        ):
            raise ValueError("bulk result may not contain provider output")

    def __repr__(self) -> str:
        return "OpenLibraryProviderResult(<redacted>)"


class OpenLibraryBookProvider:
    """Resolve one explicit low-volume route through the shared cache runtime."""

    def __init__(
        self,
        *,
        access_mode: ProviderAccessMode,
        cache_policy: ProviderCachePolicy,
        transport: OpenLibraryTransport,
        cache: ProviderCachePort | None = None,
        cache_factory: Callable[[str], ProviderCachePort | None] | None = None,
    ) -> None:
        self.descriptor = KnowledgeProviderDescriptor(
            PROVIDER_ID, "Open Library", PROVIDER_SOURCE_VERSION, access_mode, cache_policy
        )
        self._transport = transport
        self._cache = cache
        if cache is not None and cache_factory is not None:
            raise ValueError("cache and cache_factory are mutually exclusive")
        if cache_factory is not None and not callable(cache_factory):
            raise TypeError("cache_factory must be callable")
        self._cache_factory = cache_factory
        self._mapped_runtime = ProviderCacheMappingRuntime(
            runtime=ProviderCacheRuntime(access_mode=access_mode, cache_policy=cache_policy)
        )

    def fetch(
        self,
        query: BookKnowledgeQuery,
        *,
        observed_at: datetime,
        target_bindings: Mapping[str, str],
        resolved_author: OpenLibraryResolvedAuthorQuery | None = None,
        referenced_author_olid: str | None = None,
        planned_lookup_count: int = 1,
        unresolved_record_count: int = 0,
    ) -> OpenLibraryProviderResult:
        """Fetch or reuse one route; caller supplies every deterministic target binding."""

        if not isinstance(query, BookKnowledgeQuery):
            raise TypeError("query must be a BookKnowledgeQuery")
        if not isinstance(target_bindings, Mapping):
            raise TypeError("target_bindings must be a mapping")
        _require_count(planned_lookup_count, "planned_lookup_count", minimum=1)
        _require_count(unresolved_record_count, "unresolved_record_count", minimum=0)
        if planned_lookup_count > 100 or unresolved_record_count > 1_000:
            return OpenLibraryProviderResult(None, None, None, None, True)

        route = OpenLibraryQueryBuilder().build(
            query,
            identifiers=query.identifiers,
            resolved_author=resolved_author,
            referenced_author_olid=referenced_author_olid,
        )
        if route is None:
            return OpenLibraryProviderResult(ProviderCacheResultStatus.NOT_FOUND, None, None, None)
        fingerprint = query.fingerprint()
        key = provider_source_cache_key(
            PROVIDER_ID, PROVIDER_ADAPTER_VERSION, fingerprint, PROVIDER_SOURCE_VERSION
        )
        mapped = self._resolve_source(
            source_cache_key=key,
            query_fingerprint=fingerprint,
            observed_at=observed_at,
            target_bindings=target_bindings,
            fetcher=lambda: _fetch_route(self._transport, route, observed_at),
        )
        source_keys = [key]
        mapping_keys = [mapped.mapping_input_key] if mapped.mapping_input_key is not None else []
        mappings = (
            [mapped.mapped_payload]
            if isinstance(mapped.mapped_payload, OpenLibraryMappingResult)
            else []
        )
        status = mapped.source_status

        if (
            status is ProviderCacheResultStatus.SUCCESS
            and route.route_kind is not OpenLibraryRouteKind.SEARCH
            and len(route.requests) == 2
        ):
            author_request = route.requests[1]
            author_fingerprint = _supplemental_query_fingerprint(fingerprint, author_request)
            author_key = provider_source_cache_key(
                PROVIDER_ID,
                PROVIDER_ADAPTER_VERSION,
                author_fingerprint,
                PROVIDER_SOURCE_VERSION,
            )
            author = self._resolve_source(
                source_cache_key=author_key,
                query_fingerprint=author_fingerprint,
                observed_at=observed_at,
                target_bindings=target_bindings,
                fetcher=lambda: _fetch_single(self._transport, author_request, observed_at),
            )
            source_keys.append(author_key)
            if author.mapping_input_key is not None:
                mapping_keys.append(author.mapping_input_key)
            if isinstance(author.mapped_payload, OpenLibraryMappingResult):
                mappings.append(author.mapped_payload)
            if author.source_status not in {
                ProviderCacheResultStatus.SUCCESS,
                ProviderCacheResultStatus.NOT_FOUND,
            }:
                status = author.source_status
                mappings = []

        mapping = _merge_mappings(mappings) if mappings else None
        return OpenLibraryProviderResult(
            status=status,
            source_cache_key=key,
            mapping_input_key=mapped.mapping_input_key,
            mapping=mapping,
            source_cache_keys=tuple(source_keys),
            mapping_input_keys=tuple(mapping_keys),
        )

    def _resolve_source(
        self,
        *,
        source_cache_key: str,
        query_fingerprint: str,
        observed_at: datetime,
        target_bindings: Mapping[str, str],
        fetcher: Callable[[], ProviderCacheTransportResult],
    ) -> ProviderCacheMappedRuntimeResult:
        return self._mapped_runtime.resolve(
            source_cache_key=source_cache_key,
            now=observed_at,
            cache=(
                self._cache_factory(query_fingerprint)
                if self._cache_factory is not None
                else self._cache
            ),
            transport=_CallableTransport(fetcher),
            provider_id=PROVIDER_ID,
            provider_adapter_version=PROVIDER_ADAPTER_VERSION,
            provider_source_version=PROVIDER_SOURCE_VERSION,
            query_fingerprint=query_fingerprint,
            mapping_profile_version=MAPPING_PROFILE_VERSION,
            mapper=lambda payload: _map_payload(payload, observed_at, target_bindings),
        )


class _CallableTransport:
    def __init__(self, callback: Callable[[], ProviderCacheTransportResult]) -> None:
        self._callback = callback

    def fetch(self) -> ProviderCacheTransportResult:
        return self._callback()


def _require_count(value: object, name: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        qualifier = "nonnegative" if minimum == 0 else "positive"
        raise ValueError(f"{name} must be a {qualifier} int")
    return value


def _fetch_route(
    transport: OpenLibraryTransport, route: OpenLibraryQueryRoute, now: datetime
) -> ProviderCacheTransportResult:
    """Execute the ADR route dynamically after parsing request one."""

    first = _fetch_and_parse(transport, route.requests[0], now)
    if isinstance(first, ProviderCacheTransportResult):
        return first
    envelopes = [first]
    if route.route_kind is OpenLibraryRouteKind.SEARCH:
        expanded = route.with_search_page_two(
            num_found=first.result_count,
            page_one_has_strong_doc=_has_strong_search_doc(first),
        )
        if len(expanded.requests) == 2:
            second = _fetch_and_parse(transport, expanded.requests[1], now)
            if isinstance(second, ProviderCacheTransportResult):
                return second
            if (
                second.endpoint_kind != "SEARCH"
                or second.pagination_offset != 10
                or second.result_count != first.result_count
            ):
                return _failure(ProviderCacheResultStatus.INVALID_RESPONSE, now, None, None)
            envelopes.append(second)
        return _success(_combine_search_envelopes(envelopes), now, 200)

    return _success(envelopes[0], now, 200)


def _fetch_single(
    transport: OpenLibraryTransport, request: OpenLibraryRequest, now: datetime
) -> ProviderCacheTransportResult:
    parsed = _fetch_and_parse(transport, request, now)
    return (
        parsed if isinstance(parsed, ProviderCacheTransportResult) else _success(parsed, now, 200)
    )


def _supplemental_query_fingerprint(parent_fingerprint: str, request: OpenLibraryRequest) -> str:
    payload = json.dumps(
        {
            "domain": "foliotone:openlibrary-supplemental-query/v1",
            "parent_query_fingerprint": parent_fingerprint,
            "route_kind": request.route_kind.value,
            "path": request.path,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _fetch_and_parse(
    transport: OpenLibraryTransport, request: OpenLibraryRequest, now: datetime
) -> OpenLibrarySourceEnvelope | ProviderCacheTransportResult:
    result = transport.fetch(request)
    if result.status is ProviderCacheResultStatus.NOT_FOUND:
        return _not_found(now, result.http_status)
    if result.status is not ProviderCacheResultStatus.SUCCESS:
        return _failure(result.status, now, result.http_status, result.retry_after_at)
    parsed = parse_openlibrary_source(result.body or b"", request)
    if parsed.status is OpenLibrarySourceStatus.SUCCESS:
        assert parsed.payload is not None
        return parsed.payload
    if parsed.status is OpenLibrarySourceStatus.NOT_FOUND:
        return _not_found(now, result.http_status)
    return _failure(ProviderCacheResultStatus.INVALID_RESPONSE, now, result.http_status, None)


def _canonical_bytes(value: OpenLibrarySourceEnvelope) -> bytes:
    payload = value.as_payload()
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if not raw or len(raw) > MAX_NORMALIZED_BYTES:
        raise ValueError("normalized Open Library source DTO exceeds bounded size")
    return raw


def _success(
    envelope: OpenLibrarySourceEnvelope,
    now: datetime,
    http_status: int | None,
) -> ProviderCacheTransportResult:
    payload = _canonical_bytes(envelope)
    return ProviderCacheTransportResult(
        ProviderCacheResultStatus.SUCCESS,
        ProviderCacheSlots(
            content_slot=ProviderCacheContentSlot(
                content_status=ProviderCacheResultStatus.SUCCESS,
                payload_kind=ProviderCachePayloadKind.NORMALIZED_SOURCE_DTO,
                payload_codec=PAYLOAD_CODEC,
                payload_bytes=payload,
                payload_bytes_sha256=sha256(payload).hexdigest(),
                content_http_status=http_status,
                content_fetched_at=now,
                content_fresh_until_at=now + POSITIVE_FRESH_TTL,
                content_expires_at=now + POSITIVE_RETENTION_TTL,
            )
        ),
        payload,
    )


def _not_found(now: datetime, http_status: int | None) -> ProviderCacheTransportResult:
    return ProviderCacheTransportResult(
        ProviderCacheResultStatus.NOT_FOUND,
        ProviderCacheSlots(
            content_slot=ProviderCacheContentSlot(
                content_status=ProviderCacheResultStatus.NOT_FOUND,
                content_http_status=http_status,
                content_fetched_at=now,
                content_fresh_until_at=now + NOT_FOUND_FRESH_TTL,
                content_expires_at=now + NOT_FOUND_RETENTION_TTL,
            )
        ),
        None,
    )


def _failure(
    status: ProviderCacheResultStatus,
    now: datetime,
    http_status: int | None,
    retry: datetime | None,
) -> ProviderCacheTransportResult:
    expiry = now + FAILURE_TTLS[status]
    retry_at = retry
    if status is ProviderCacheResultStatus.RATE_LIMITED:
        cap = now + RATE_LIMIT_MAX_TTL
        retry_at = min(max(retry or now, now), cap)
        expiry = min(max(expiry, retry_at), cap)
    return ProviderCacheTransportResult(
        status,
        ProviderCacheSlots(
            failure_slot=ProviderCacheFailureSlot(
                failure_status=status,
                failure_http_status=http_status,
                failure_at=now,
                failure_retry_after_at=retry_at
                if status is ProviderCacheResultStatus.RATE_LIMITED
                else None,
                failure_expires_at=expiry,
            )
        ),
        None,
    )


def _has_strong_search_doc(envelope: OpenLibrarySourceEnvelope) -> bool:
    return any(
        isinstance(record, SearchSourceRecord)
        and record.work is not None
        and any(
            edition.edition_olid is not None or bool(edition.isbn10 or edition.isbn13)
            for edition in record.editions
        )
        for record in envelope.records
    )


def _source_record_key(record: SourceRecord) -> tuple[str, str]:
    if isinstance(record, WorkSourceRecord):
        return "W", record.work_olid
    if isinstance(record, EditionSourceRecord):
        return "M", record.edition_olid or "|".join(record.isbn10 + record.isbn13)
    if isinstance(record, AuthorSourceRecord):
        return "A", record.author_olid
    if record.work is not None:
        return "S", record.work.work_olid
    return "S", "|".join(
        edition.edition_olid or "|".join(edition.isbn10 + edition.isbn13)
        for edition in record.editions
    )


def _canonical_record_bytes(record: SourceRecord) -> bytes:
    return json.dumps(
        record.as_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _stable_records(records: Iterable[SourceRecord]) -> tuple[SourceRecord, ...]:
    selected: dict[tuple[str, str], SourceRecord] = {}
    for record in records:
        key = _source_record_key(record)
        old = selected.get(key)
        if old is None or _canonical_record_bytes(record) < _canonical_record_bytes(old):
            selected[key] = record
    return tuple(selected[key] for key in sorted(selected))


def _combine_search_envelopes(
    envelopes: Sequence[OpenLibrarySourceEnvelope],
) -> OpenLibrarySourceEnvelope:
    first = envelopes[0]
    records = _stable_records(record for item in envelopes for record in item.records)
    if len(records) > 20:
        raise ValueError("combined Search source exceeds record bound")
    return OpenLibrarySourceEnvelope(
        "SEARCH", records, first.result_count, 0, envelopes[-1].pagination_complete
    )


def _map_payload(
    payload: object, observed_at: datetime, bindings: Mapping[str, str]
) -> OpenLibraryMappingResult:
    mapped = tuple(
        map_openlibrary_source(record, observed_at=observed_at, target_bindings=bindings)
        for envelope in decode_openlibrary_source_dtos(payload)
        for record in envelope.records
    )
    if not mapped:
        raise ValueError("normalized Open Library source contains no records")
    return _merge_mappings(mapped)


def _merge_mappings(parts: Iterable[OpenLibraryMappingResult]) -> OpenLibraryMappingResult:
    items = tuple(parts)
    provenance = items[0].provenance
    if any(item.provenance != provenance for item in items):
        raise ValueError("Open Library mapping provenance mismatch")
    return OpenLibraryMappingResult(
        _sorted_unique(value for item in items for value in item.identifiers),
        _sorted_unique(value for item in items for value in item.values),
        _sorted_unique(value for item in items for value in item.work_candidates),
        _sorted_unique(value for item in items for value in item.agent_candidates),
        provenance,
    )


def _sorted_unique[T](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(sorted(set(values), key=_projection_key))


def _projection_key(value: object) -> tuple[object, ...]:
    if isinstance(value, OpenLibraryIdentifierProjection):
        return "identifier", value.target_kind.value, value.target_ref, value.namespace, value.value
    if isinstance(value, OpenLibraryEvidenceProjection):
        return (
            "evidence",
            value.target_kind.value,
            value.target_ref,
            value.source_field,
            value.value,
        )
    if isinstance(value, OpenLibraryWorkCandidate):
        return "work-candidate", value.target_ref, value.work_olid
    if isinstance(value, OpenLibraryAgentCandidate):
        return (
            "agent-candidate",
            value.candidate_kind.value,
            value.source_record_refs,
            value.target_ref,
            value.author_olid,
            value.source_field,
            value.value,
            tuple(_projection_key(item) for item in value.values),
        )
    raise TypeError("unsupported Open Library projection")


def decode_openlibrary_source_dto(payload: object) -> OpenLibrarySourceEnvelope:
    """Losslessly decode one canonical v2 cache DTO."""

    envelopes = decode_openlibrary_source_dtos(payload)
    if len(envelopes) != 1:
        raise ValueError("cached Open Library source contains multiple endpoint envelopes")
    return envelopes[0]


def decode_openlibrary_source_dtos(payload: object) -> tuple[OpenLibrarySourceEnvelope, ...]:
    """Losslessly decode one canonical v2 source envelope."""

    if type(payload) is not bytes or not payload or len(payload) > MAX_NORMALIZED_BYTES:
        raise ValueError("invalid cached Open Library source DTO")
    try:
        data = json.loads(payload.decode("utf-8"), parse_constant=_reject_json_constant)
        envelopes = (_decode_envelope(data),)
        canonical = _canonical_bytes(envelopes[0])
        if canonical != payload:
            raise ValueError("noncanonical")
        return envelopes
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid cached Open Library source DTO") from exc


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON value")


def _decode_envelope(value: object) -> OpenLibrarySourceEnvelope:
    data = _exact_dict(value, _ENVELOPE_KEYS, "envelope")
    if data["profile"] != PROFILE or type(data["endpoint_kind"]) is not str:
        raise ValueError("profile")
    records = data["records"]
    if not isinstance(records, list):
        raise ValueError("records")
    if type(data["result_count"]) is not int or type(data["pagination_offset"]) is not int:
        raise ValueError("counts")
    if type(data["pagination_complete"]) is not bool:
        raise ValueError("pagination_complete")
    kind = data["endpoint_kind"]
    return OpenLibrarySourceEnvelope(
        kind,
        tuple(_decode_record(kind, item) for item in records),
        data["result_count"],
        data["pagination_offset"],
        data["pagination_complete"],
    )


def _exact_dict(value: object, keys: frozenset[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(name)
    return value


def _tuple_field(data: Mapping[str, object], field: str) -> tuple[object, ...]:
    value = data[field]
    if not isinstance(value, list):
        raise ValueError(field)
    return tuple(value)


def _strings_field(data: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = _tuple_field(data, field)
    if any(type(value) is not str for value in values):
        raise ValueError(field)
    return tuple(value for value in values if isinstance(value, str))


def _string(value: object, field: str) -> str:
    if type(value) is not str:
        raise ValueError(field)
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is not None and type(value) is not str:
        raise ValueError(field)
    return value if isinstance(value, str) else None


def _bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(field)
    return value


def _decode_record(kind: object, value: object) -> SourceRecord:
    record_kind = "EDITION" if kind == "LEGACY_IDENTIFIER" else kind
    if not isinstance(record_kind, str) or record_kind not in _RECORD_KEYS:
        raise ValueError("endpoint")
    data = _exact_dict(value, _RECORD_KEYS[record_kind], "record")
    if record_kind == "WORK":
        return WorkSourceRecord(
            _string(data["work_olid"], "work_olid"),
            _optional_string(data["title"], "title"),
            _optional_string(data["first_publish_year"], "first_publish_year"),
            _strings_field(data, "author_refs"),
            _strings_field(data, "subjects"),
            _bool(data["truncated"], "truncated"),
        )
    if record_kind == "EDITION":
        return EditionSourceRecord(
            _optional_string(data["edition_olid"], "edition_olid"),
            _strings_field(data, "work_refs"),
            _optional_string(data["title"], "title"),
            _optional_string(data["subtitle"], "subtitle"),
            _optional_string(data["publish_date"], "publish_date"),
            _strings_field(data, "publishers"),
            _strings_field(data, "languages"),
            _strings_field(data, "isbn10"),
            _strings_field(data, "isbn13"),
            _strings_field(data, "oclc"),
            _strings_field(data, "lccn"),
            _strings_field(data, "author_refs"),
            _bool(data["truncated"], "truncated"),
        )
    if record_kind == "AUTHOR":
        return AuthorSourceRecord(
            _string(data["author_olid"], "author_olid"),
            _optional_string(data["name"], "name"),
            _strings_field(data, "alternate_names"),
            _optional_string(data["birth_date"], "birth_date"),
            _optional_string(data["death_date"], "death_date"),
            _bool(data["truncated"], "truncated"),
        )
    work = _decode_record("WORK", data["work"]) if data["work"] is not None else None
    editions = tuple(_decode_record("EDITION", item) for item in _tuple_field(data, "editions"))
    if (work is not None and not isinstance(work, WorkSourceRecord)) or any(
        not isinstance(item, EditionSourceRecord) for item in editions
    ):
        raise ValueError("search record")
    return SearchSourceRecord(
        work,
        tuple(item for item in editions if isinstance(item, EditionSourceRecord)),
        _bool(data["truncated"], "truncated"),
        _strings_field(data, "contributor_names"),
    )


__all__ = [
    "OpenLibraryBookProvider",
    "OpenLibraryProviderResult",
    "decode_openlibrary_source_dto",
    "decode_openlibrary_source_dtos",
]
