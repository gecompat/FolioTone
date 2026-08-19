"""Deterministic, provider-local projection of normalized Open Library data."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from foliotone.core import EntityKind, ValueState

from .source import (
    AuthorSourceRecord,
    EditionSourceRecord,
    SearchSourceRecord,
    SourceRecord,
    WorkSourceRecord,
)

PROVIDER_ID: Final = "openlibrary"
PROVIDER_ADAPTER_VERSION: Final = "openlibrary-book-adapter/v2"
PROVIDER_SOURCE_VERSION: Final = "openlibrary-web-api-docs-2026-08-20"
MAPPING_PROFILE_VERSION: Final = "openlibrary-book-mapping/v2"
SOURCE_PROFILE_VERSION: Final = "openlibrary-source-record/v2"
_OLID = re.compile(r"^OL[0-9]+([MWA])$")
_ISBN10 = re.compile(r"^[0-9]{9}[0-9X]$")
_ISBN13 = re.compile(r"^[0-9]{13}$")
_OCLC = re.compile(r"^[0-9]{1,16}$")
_LCCN = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_FIELDS: Final = {
    EntityKind.WORK: frozenset(("title", "first_publish_year", "subjects")),
    EntityKind.EDITION: frozenset(("title", "subtitle", "publish_date", "publishers", "languages")),
    EntityKind.AGENT: frozenset(("name", "alternate_names", "birth_date", "death_date")),
}
_NAMESPACES: Final = {
    "openlibrary.work": (EntityKind.WORK, "W"),
    "openlibrary.edition": (EntityKind.EDITION, "M"),
    "openlibrary.author": (EntityKind.AGENT, "A"),
    "isbn10": (EntityKind.EDITION, None),
    "isbn13": (EntityKind.EDITION, None),
    "oclc": (EntityKind.EDITION, None),
    "lccn": (EntityKind.EDITION, None),
}
_SOURCE_REF_CATEGORIES: Final = (
    "openlibrary.work:",
    "openlibrary.edition:",
    "isbn10:",
    "isbn13:",
)


def _sorted_source_record_refs(values: Iterable[str]) -> tuple[str, ...]:
    refs = tuple(values)
    if any(
        not isinstance(ref, str)
        or not ref
        or not any(ref.startswith(prefix) for prefix in _SOURCE_REF_CATEGORIES)
        for ref in refs
    ):
        raise ValueError("invalid source record ref")
    for ref in refs:
        if ref.startswith("openlibrary.work:"):
            _olid(ref[len("openlibrary.work:") :], "W")
        elif ref.startswith("openlibrary.edition:"):
            _olid(ref[len("openlibrary.edition:") :], "M")
        elif ref.startswith("isbn10:"):
            _identifier("isbn10", ref[7:], EntityKind.EDITION)
        elif ref.startswith("isbn13:"):
            _identifier("isbn13", ref[7:], EntityKind.EDITION)
    unique = set(refs)
    return tuple(
        ref
        for prefix in _SOURCE_REF_CATEGORIES
        for ref in sorted(unique)
        if ref.startswith(prefix)
    )


def _canonical_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{name} must be a bounded non-empty string")
    if value != unicodedata.normalize("NFC", value) or value != value.strip():
        raise ValueError(f"{name} must be NFC and canonical")
    if any(character in value for character in "\x00\r\n"):
        raise ValueError(f"{name} contains a forbidden control character")
    return value


def _safe_ref(value: object, name: str, limit: int) -> str:
    value = _canonical_text(value, name, limit)
    folded = value.casefold()
    if (
        "\\" in value
        or "/" in value
        or ".." in value
        or "://" in value
        or folded.startswith("file:")
        or _DRIVE.match(value)
    ):
        raise ValueError(f"{name} must be path- and private-data-safe")
    return value


def _target_ref(value: object, name: str) -> str:
    return _safe_ref(value, name, 256)


def _olid(value: object, kind: str) -> str:
    value = _canonical_text(value, "Open Library identifier", 64)
    match = _OLID.fullmatch(value)
    if match is None or match.group(1) != kind:
        raise ValueError("invalid Open Library identifier")
    return value


def _identifier(namespace: str, value: object, kind: EntityKind) -> str:
    expected = _NAMESPACES.get(namespace)
    if expected is None or expected[0] is not kind:
        raise ValueError("invalid Open Library identifier namespace")
    if expected[1] is not None:
        return _olid(value, expected[1])
    value = _canonical_text(value, "identifier value", 64)
    valid = {
        "isbn10": bool(_ISBN10.fullmatch(value))
        and sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(value)) % 11 == 0,
        "isbn13": bool(_ISBN13.fullmatch(value))
        and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0,
        "oclc": bool(_OCLC.fullmatch(value)),
        "lccn": bool(_LCCN.fullmatch(value)),
    }
    if not valid[namespace]:
        raise ValueError("invalid identifier value")
    return value


@dataclass(frozen=True, slots=True)
class OpenLibraryMappingProvenance:
    provider_id: str
    provider_source_version: str
    provider_adapter_version: str
    source_profile_version: str
    mapping_profile_version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            self.provider_id,
            self.provider_source_version,
            self.provider_adapter_version,
            self.source_profile_version,
            self.mapping_profile_version,
        ) != (
            PROVIDER_ID,
            PROVIDER_SOURCE_VERSION,
            PROVIDER_ADAPTER_VERSION,
            SOURCE_PROFILE_VERSION,
            MAPPING_PROFILE_VERSION,
        ):
            raise ValueError("Open Library provenance constants do not match")
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")

    def __repr__(self) -> str:
        return "OpenLibraryMappingProvenance(<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryEvidenceProjection:
    target_kind: EntityKind
    target_ref: str
    source_field: str
    value: str
    state: ValueState
    provenance: OpenLibraryMappingProvenance
    confidence: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target_kind, EntityKind) or self.target_kind not in _FIELDS:
            raise ValueError("unsupported target_kind")
        _target_ref(self.target_ref, "target_ref")
        if self.source_field not in _FIELDS[self.target_kind]:
            raise ValueError("source_field is not allowed for target_kind")
        _canonical_text(self.value, "value", 512)
        if self.state is not ValueState.EXTERNAL or self.confidence is not None:
            raise ValueError("provider projections are EXTERNAL and have no confidence")
        if not isinstance(self.provenance, OpenLibraryMappingProvenance):
            raise ValueError("invalid provenance")

    @property
    def field(self) -> str:
        return self.source_field

    def __repr__(self) -> str:
        return "OpenLibraryEvidenceProjection(<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryIdentifierProjection:
    target_kind: EntityKind
    target_ref: str
    namespace: str
    value: str
    provenance: OpenLibraryMappingProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.target_kind, EntityKind):
            raise ValueError("target_kind must be EntityKind")
        _target_ref(self.target_ref, "target_ref")
        _identifier(self.namespace, self.value, self.target_kind)
        if not isinstance(self.provenance, OpenLibraryMappingProvenance):
            raise ValueError("invalid provenance")

    def __repr__(self) -> str:
        return "OpenLibraryIdentifierProjection(<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryWorkCandidate:
    target_ref: str
    work_olid: str
    provenance: OpenLibraryMappingProvenance

    def __post_init__(self) -> None:
        _target_ref(self.target_ref, "target_ref")
        _olid(self.work_olid, "W")
        if not isinstance(self.provenance, OpenLibraryMappingProvenance):
            raise ValueError("invalid provenance")

    def __repr__(self) -> str:
        return "OpenLibraryWorkCandidate(<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryAgentCandidate:
    target_ref: str | None
    author_olid: str | None
    values: tuple[OpenLibraryEvidenceProjection, ...]
    provenance: OpenLibraryMappingProvenance
    candidate_kind: EntityKind = EntityKind.AGENT
    source_field: str | None = None
    value: str | None = None
    state: ValueState = ValueState.EXTERNAL
    confidence: None = None
    source_record_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate_kind is not EntityKind.AGENT:
            raise ValueError("agent candidate kind must be AGENT")
        if self.state is not ValueState.EXTERNAL or self.confidence is not None:
            raise ValueError("provider candidates are EXTERNAL and have no confidence")
        if (
            not isinstance(self.values, tuple)
            or any(not isinstance(v, OpenLibraryEvidenceProjection) for v in self.values)
            or self.values != _sorted_unique(self.values)
        ):
            raise ValueError("agent candidate values must be typed tuple")
        if not isinstance(self.provenance, OpenLibraryMappingProvenance):
            raise ValueError("invalid provenance")
        if not isinstance(self.source_record_refs, tuple):
            raise ValueError("source_record_refs must be a tuple")
        refs = self.source_record_refs
        if self.target_ref is None and self.author_olid is None:
            if self.values or self.source_field != "author_name" or self.value is None:
                raise ValueError("name-only agent candidate shape")
            _canonical_text(self.value, "candidate value", 512)
            if not refs or refs != _sorted_source_record_refs(refs):
                raise ValueError("name-only source refs must be non-empty and ordered")
        else:
            if self.target_ref is None or self.author_olid is None:
                raise ValueError("bound agent candidate requires target and OLID")
            _target_ref(self.target_ref, "target_ref")
            _olid(self.author_olid, "A")
            if self.source_field is not None or self.value is not None or refs:
                raise ValueError("bound agent candidate cannot carry name-only fields")
            if any(
                v.target_kind is not EntityKind.AGENT
                or v.target_ref != self.target_ref
                or v.provenance != self.provenance
                for v in self.values
            ):
                raise ValueError("agent candidate values must cross-bind")
        object.__setattr__(self, "source_record_refs", refs)

    def __repr__(self) -> str:
        return "OpenLibraryAgentCandidate(<redacted>)"


def _projection_key(value: object) -> tuple[object, ...]:
    if isinstance(value, OpenLibraryIdentifierProjection):
        return (
            "identifier",
            value.target_kind.value,
            value.target_ref,
            value.namespace,
            value.value,
        )
    if isinstance(value, OpenLibraryEvidenceProjection):
        return (
            "evidence",
            value.target_kind.value,
            value.target_ref,
            value.source_field,
            value.value,
        )
    if isinstance(value, OpenLibraryWorkCandidate):
        return ("work-candidate", value.target_ref, value.work_olid)
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


def _sorted_unique[T](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(sorted(set(values), key=_projection_key))


@dataclass(frozen=True, slots=True)
class OpenLibraryMappingResult:
    identifiers: tuple[OpenLibraryIdentifierProjection, ...]
    values: tuple[OpenLibraryEvidenceProjection, ...]
    work_candidates: tuple[OpenLibraryWorkCandidate, ...]
    agent_candidates: tuple[OpenLibraryAgentCandidate, ...]
    provenance: OpenLibraryMappingProvenance

    @property
    def knowledge(self) -> tuple[OpenLibraryEvidenceProjection, ...]:
        return self.values

    @property
    def dtos(self) -> tuple[OpenLibraryEvidenceProjection, ...]:
        return self.values

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, OpenLibraryMappingProvenance):
            raise ValueError("invalid provenance")
        for values, expected in (
            (self.identifiers, OpenLibraryIdentifierProjection),
            (self.values, OpenLibraryEvidenceProjection),
            (self.work_candidates, OpenLibraryWorkCandidate),
            (self.agent_candidates, OpenLibraryAgentCandidate),
        ):
            if not isinstance(values, tuple) or any(not isinstance(v, expected) for v in values):
                raise ValueError("mapping collections must be typed tuples")
            if values != _sorted_unique(values):
                raise ValueError("mapping collections must be sorted and deduplicated")
            if any(v.provenance != self.provenance for v in values):
                raise ValueError("all projections must carry result provenance")

    def __repr__(self) -> str:
        return "OpenLibraryMappingResult(<redacted>)"


def map_openlibrary_record(
    record: SourceRecord,
    *,
    observed_at: datetime,
    target_id: str | None = None,
    target_bindings: Mapping[str, str] | None = None,
) -> OpenLibraryMappingResult:
    """Map source records; caller-owned bindings prevent invented FolioTone IDs."""
    p = OpenLibraryMappingProvenance(
        PROVIDER_ID,
        PROVIDER_SOURCE_VERSION,
        PROVIDER_ADAPTER_VERSION,
        SOURCE_PROFILE_VERSION,
        MAPPING_PROFILE_VERSION,
        observed_at,
    )
    if target_bindings is not None and not isinstance(target_bindings, Mapping):
        raise TypeError("target_bindings must be a mapping")
    bindings = {
        _binding_key(key): _target_ref(value, "target binding")
        for key, value in (target_bindings or {}).items()
    }
    if target_id is not None:
        bindings.setdefault(_record_key(record), _target_ref(target_id, "target_id"))
    if isinstance(record, SearchSourceRecord):
        children = tuple(child for child in (record.work, *record.editions) if child is not None)
        if any(_record_key(child) not in bindings for child in children):
            raise ValueError("Search mapping requires explicit target bindings for every child")
        mapped = _merge(
            (
                map_openlibrary_record(child, observed_at=observed_at, target_bindings=bindings)
                for child in children
            ),
            p,
        )
        return _merge((mapped, _search_agents(record, p)), p)
    ref = bindings.get(_record_key(record))
    if ref is None:
        raise ValueError("missing caller-supplied target binding")
    if isinstance(record, WorkSourceRecord):
        return _work(record, ref, p, bindings)
    if isinstance(record, EditionSourceRecord):
        return _edition(record, ref, p, bindings)
    if isinstance(record, AuthorSourceRecord):
        return _author(record, ref, p)
    raise TypeError("record must be a normalized Open Library source record")


def map_openlibrary_source(
    record: SourceRecord,
    *,
    observed_at: datetime,
    target_id: str | None = None,
    target_bindings: Mapping[str, str] | None = None,
) -> OpenLibraryMappingResult:
    return map_openlibrary_record(
        record, observed_at=observed_at, target_id=target_id, target_bindings=target_bindings
    )


def _record_key(record: SourceRecord) -> str:
    if isinstance(record, WorkSourceRecord):
        return f"openlibrary.work:{record.work_olid}"
    if isinstance(record, EditionSourceRecord):
        return f"openlibrary.edition:{record.edition_olid or (record.isbn10 + record.isbn13)[0]}"
    if isinstance(record, AuthorSourceRecord):
        return f"openlibrary.author:{record.author_olid}"
    raise TypeError("Search records do not have a target key")


def _binding_key(value: object) -> str:
    value = _safe_ref(value, "target binding key", 128)
    match = re.fullmatch(r"openlibrary\.(work|edition|author):(OL[0-9]+[MWA])", value)
    expected_kind = {"work": "W", "edition": "M", "author": "A"}
    if match is None or match.group(2)[-1] != expected_kind[match.group(1)]:
        raise ValueError("invalid target binding key")
    return value


def _values(
    kind: EntityKind,
    ref: str,
    fields: Iterable[tuple[str, object]],
    p: OpenLibraryMappingProvenance,
) -> tuple[OpenLibraryEvidenceProjection, ...]:
    values: list[OpenLibraryEvidenceProjection] = []
    for field, source in fields:
        entries = (
            (source,) if isinstance(source, str) else source if isinstance(source, tuple) else ()
        )
        values.extend(
            OpenLibraryEvidenceProjection(kind, ref, field, value, ValueState.EXTERNAL, p)
            for value in entries
            if isinstance(value, str) and value
        )
    return _sorted_unique(values)


def _work(
    record: WorkSourceRecord,
    ref: str,
    p: OpenLibraryMappingProvenance,
    bindings: Mapping[str, str],
) -> OpenLibraryMappingResult:
    ids = (
        OpenLibraryIdentifierProjection(
            EntityKind.WORK, ref, "openlibrary.work", record.work_olid, p
        ),
    )
    agents = _agent_candidates(record.author_refs, bindings, p)
    return OpenLibraryMappingResult(
        ids,
        _values(
            EntityKind.WORK,
            ref,
            (
                ("title", record.title),
                ("first_publish_year", record.first_publish_year),
                ("subjects", record.subjects),
            ),
            p,
        ),
        (),
        agents,
        p,
    )


def _edition(
    record: EditionSourceRecord,
    ref: str,
    p: OpenLibraryMappingProvenance,
    bindings: Mapping[str, str],
) -> OpenLibraryMappingResult:
    ids: list[OpenLibraryIdentifierProjection] = []
    if record.edition_olid:
        ids.append(
            OpenLibraryIdentifierProjection(
                EntityKind.EDITION, ref, "openlibrary.edition", record.edition_olid, p
            )
        )
    ids.extend(
        OpenLibraryIdentifierProjection(EntityKind.EDITION, ref, namespace, value, p)
        for namespace, values in (
            ("isbn10", record.isbn10),
            ("isbn13", record.isbn13),
            ("oclc", record.oclc),
            ("lccn", record.lccn),
        )
        for value in values
    )
    candidates = _sorted_unique(
        OpenLibraryWorkCandidate(_binding(bindings, f"openlibrary.work:{olid}"), olid, p)
        for olid in record.work_refs
    )
    values = _values(
        EntityKind.EDITION,
        ref,
        (
            ("title", record.title),
            ("subtitle", record.subtitle),
            ("publish_date", record.publish_date),
            ("publishers", record.publishers),
            ("languages", record.languages),
        ),
        p,
    )
    agents = _agent_candidates(record.author_refs, bindings, p)
    return OpenLibraryMappingResult(_sorted_unique(ids), values, candidates, agents, p)


def _binding(bindings: Mapping[str, str], key: str) -> str:
    value = bindings.get(key)
    if value is None:
        raise ValueError("referenced candidate requires explicit target binding")
    return _target_ref(value, "referenced target binding")


def _agent_candidates(
    author_olids: Iterable[str],
    bindings: Mapping[str, str],
    provenance: OpenLibraryMappingProvenance,
) -> tuple[OpenLibraryAgentCandidate, ...]:
    return _sorted_unique(
        OpenLibraryAgentCandidate(
            _binding(bindings, f"openlibrary.author:{author_olid}"),
            author_olid,
            (),
            provenance,
        )
        for author_olid in author_olids
    )


def _search_record_refs(record: SearchSourceRecord) -> tuple[str, ...]:
    refs: list[str] = []
    if record.work is not None:
        refs.append(f"openlibrary.work:{record.work.work_olid}")
    for edition in record.editions:
        if edition.edition_olid:
            refs.append(f"openlibrary.edition:{edition.edition_olid}")
        refs.extend(f"isbn10:{value}" for value in edition.isbn10)
        refs.extend(f"isbn13:{value}" for value in edition.isbn13)
    return _sorted_source_record_refs(refs)


def _search_agents(
    record: SearchSourceRecord, p: OpenLibraryMappingProvenance
) -> OpenLibraryMappingResult:
    refs = _search_record_refs(record)
    if record.contributor_names and not refs:
        raise ValueError("Search contributor requires source record refs")
    return OpenLibraryMappingResult(
        (),
        (),
        (),
        tuple(
            OpenLibraryAgentCandidate(
                None,
                None,
                (),
                p,
                source_field="author_name",
                value=name,
                source_record_refs=refs,
            )
            for name in record.contributor_names
        ),
        p,
    )


def _author(
    record: AuthorSourceRecord, ref: str, p: OpenLibraryMappingProvenance
) -> OpenLibraryMappingResult:
    values = _values(
        EntityKind.AGENT,
        ref,
        (
            ("name", record.name),
            ("alternate_names", record.alternate_names),
            ("birth_date", record.birth_date),
            ("death_date", record.death_date),
        ),
        p,
    )
    return OpenLibraryMappingResult(
        (
            OpenLibraryIdentifierProjection(
                EntityKind.AGENT, ref, "openlibrary.author", record.author_olid, p
            ),
        ),
        values,
        (),
        (OpenLibraryAgentCandidate(ref, record.author_olid, values, p),),
        p,
    )


def _merge(
    parts: Iterable[OpenLibraryMappingResult], p: OpenLibraryMappingProvenance
) -> OpenLibraryMappingResult:
    items = tuple(parts)
    return OpenLibraryMappingResult(
        _sorted_unique(x for item in items for x in item.identifiers),
        _sorted_unique(x for item in items for x in item.values),
        _sorted_unique(x for item in items for x in item.work_candidates),
        _sorted_unique(x for item in items for x in item.agent_candidates),
        p,
    )


__all__ = [
    "MAPPING_PROFILE_VERSION",
    "OpenLibraryAgentCandidate",
    "OpenLibraryEvidenceProjection",
    "OpenLibraryIdentifierProjection",
    "OpenLibraryMappingProvenance",
    "OpenLibraryMappingResult",
    "OpenLibraryWorkCandidate",
    "PROVIDER_ADAPTER_VERSION",
    "PROVIDER_ID",
    "PROVIDER_SOURCE_VERSION",
    "SOURCE_PROFILE_VERSION",
    "map_openlibrary_record",
    "map_openlibrary_source",
]
