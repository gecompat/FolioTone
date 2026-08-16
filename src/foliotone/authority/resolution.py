"""Local authority and bibliographic normalization helpers.

This module intentionally stays read-only and synthetic-data focused. It provides
versioned normalization primitives and deterministic candidate materialization for
book-oriented local authority work before any provider or persistence coupling.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from foliotone.core._validation import require_non_empty
from foliotone.core.common import Provenance
from foliotone.parsing.contracts import FieldCandidate

DEFAULT_AUTHOR_RESOLUTION_VERSION: Final = "authority-resolution/v1"
DEFAULT_TITLE_RESOLUTION_VERSION: Final = "title-resolution/v1"
DEFAULT_IDENTIFIER_RESOLUTION_VERSION: Final = "identifier-resolution/v1"
DEFAULT_METADATA_RESOLUTION_VERSION: Final = "metadata-resolution/v1"
DEFAULT_AGENT_NAME_CONFIDENCE: Final = 0.55
DEFAULT_TITLE_CONFIDENCE: Final = 0.5
DEFAULT_IDENTIFIER_CONFIDENCE: Final = 0.75


@dataclass(frozen=True, slots=True)
class AuthorityNameProfile:
    """Versioned normalization profile for local author/agent names."""

    version: str
    keep_particles: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))


@dataclass(frozen=True, slots=True)
class TitleProfile:
    """Versioned normalization profile for book/work/edition/series titles."""

    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))


@dataclass(frozen=True, slots=True)
class BibliographicEntityProfile:
    """Versioned profile for metadata-derived bibliographic candidate materialization."""

    version: str
    include_identifiers: bool = True
    include_translator_as_agent: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))


def normalize_agent_name(name: str) -> str:
    """Return a deterministic normalized author name for matching keys."""

    raw = _normalized_text(name)
    if "," in raw:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) == 2 and all(parts):
            return f"{parts[1]} {parts[0]}".strip()
    return raw


def normalize_identifier(value: str) -> str:
    """Normalize external identifiers to a stable canonical form."""

    return re.sub(r"\W+", "", _normalized_text(value))


def canonicalize_title(title: str) -> str:
    """Return a minimal title normalization that avoids path-like noise."""

    return _normalized_text(title)


def normalize_identifier_for_profile(namespace: str, value: str) -> str:
    normalized_value = normalize_identifier(value)
    if not normalized_value:
        raise ValueError("value must contain at least one identifier character")
    return f"{require_non_empty(namespace, 'namespace')}:{normalized_value}"


def generate_agent_name_candidates(
    raw_name: str,
    *,
    observed_at: datetime,
    profile: AuthorityNameProfile | None = None,
) -> tuple[FieldCandidate, ...]:
    """
    Generate local authority candidates for an agent name.

    The output is intentionally non-authoritative and versioned:

    - canonical form from source spelling,
    - normalized canonical form for deterministic matching,
    - sort-name when comma syntax is present,
    - alias/pseudonym/credited-as candidates when structure suggests variants.
    """

    profile = profile or AuthorityNameProfile(version=DEFAULT_AUTHOR_RESOLUTION_VERSION)
    base_name = require_non_empty(raw_name, "raw_name")
    credited_as = _extract_credited_as(base_name)
    stripped_name = _strip_annotations(base_name, credited_as=credited_as)
    normalized_name = normalize_agent_name(stripped_name)

    candidates: list[FieldCandidate] = []
    source_stamp = f"authority-profile:{profile.version}"

    candidates.append(
        _candidate(
            field_name="agent.name.canonical",
            value=_normalized_text(stripped_name, preserve_case=True).strip(),
            source_location=f"{source_stamp}.canonical",
            observed_at=observed_at,
            profile_version=profile.version,
            confidence=DEFAULT_AGENT_NAME_CONFIDENCE,
        ),
    )

    candidates.append(
        _candidate(
            field_name="agent.name.normalized",
            value=normalized_name,
            source_location=f"{source_stamp}.normalized",
            observed_at=observed_at,
            profile_version=profile.version,
            confidence=DEFAULT_AGENT_NAME_CONFIDENCE + 0.1,
        ),
    )

    if "," in stripped_name and "," in base_name:
        raw_sort = _swap_comma_name(stripped_name)
        if raw_sort.strip():
            candidates.append(
                _candidate(
                    field_name="agent.name.sort_name",
                    value=raw_sort.strip(),
                    source_location=f"{source_stamp}.sort_name",
                    observed_at=observed_at,
                    profile_version=profile.version,
                    confidence=DEFAULT_AGENT_NAME_CONFIDENCE + 0.15,
                ),
            )
            normalized_sort = normalize_agent_name(raw_sort)
            if normalized_sort and normalized_sort != normalized_name:
                candidates.append(
                    _candidate(
                        field_name="agent.name.alias",
                        value=normalized_sort,
                        source_location=f"{source_stamp}.alias",
                        observed_at=observed_at,
                        profile_version=profile.version,
                        confidence=DEFAULT_AGENT_NAME_CONFIDENCE - 0.1,
                    ),
                )

    pseudonym = _extract_parenthesized(base_name)
    if pseudonym is not None:
        candidates.append(
            _candidate(
                field_name="agent.name.pseudonym",
                value=pseudonym,
                source_location=f"{source_stamp}.pseudonym",
                observed_at=observed_at,
                profile_version=profile.version,
                confidence=DEFAULT_AGENT_NAME_CONFIDENCE - 0.05,
            ),
        )

    if credited_as is not None:
        candidates.append(
            _candidate(
                field_name="agent.name.credited_as",
                value=credited_as,
                source_location=f"{source_stamp}.credited_as",
                observed_at=observed_at,
                profile_version=profile.version,
                confidence=DEFAULT_AGENT_NAME_CONFIDENCE - 0.05,
            ),
        )

    return tuple(candidates)


def generate_work_candidates(
    title: str,
    *,
    observed_at: datetime,
    profile: TitleProfile | None = None,
) -> tuple[FieldCandidate, ...]:
    """Generate local candidates for book work identity."""

    return _generate_title_candidates(
        title=title,
        target_kind="work",
        observed_at=observed_at,
        profile=profile or TitleProfile(version=DEFAULT_TITLE_RESOLUTION_VERSION),
    )


def generate_edition_candidates(
    title: str,
    *,
    observed_at: datetime,
    profile: TitleProfile | None = None,
) -> tuple[FieldCandidate, ...]:
    """Generate local candidates for a book edition identity."""

    return _generate_title_candidates(
        title=title,
        target_kind="edition",
        observed_at=observed_at,
        profile=profile or TitleProfile(version=DEFAULT_TITLE_RESOLUTION_VERSION),
    )


def generate_series_candidates(
    name: str,
    *,
    observed_at: datetime,
    profile: TitleProfile | None = None,
) -> tuple[FieldCandidate, ...]:
    """Generate local candidates for a series identity."""

    return _generate_title_candidates(
        title=name,
        target_kind="series",
        observed_at=observed_at,
        profile=profile or TitleProfile(version=DEFAULT_TITLE_RESOLUTION_VERSION),
    )


def is_homonym_free_merge(
    left_normalized: str,
    right_normalized: str,
    *,
    disambiguation: str | None = None,
) -> bool:
    """
    Conservative match gate for local merges.

    Equal normalized names alone never trigger auto-merge.
    """

    left_key = require_non_empty(left_normalized, "left_normalized").casefold()
    right_key = require_non_empty(right_normalized, "right_normalized").casefold()
    if left_key != right_key:
        return False
    if disambiguation is None or not disambiguation.strip():
        return False
    return disambiguate(left_key, disambiguation).startswith("ok:")


def disambiguate(name: str, disambiguation: str) -> str:
    """Return a deterministic merge key for an optional explicit disambiguation."""

    name_key = normalize_agent_name(disambiguation)
    if not name_key:
        return f"reject:{require_non_empty(disambiguation, 'disambiguation')}"
    return f"ok:{name_key}"


def normalize_agent_name_key(value: str) -> str:
    """Return a stable agent-name normalization key for matching."""

    return normalize_agent_name(value)


def normalize_identifier_key(value: str) -> str:
    """Return a stable identifier normalization key for matching."""

    return normalize_identifier(value)


def generate_metadata_entity_candidates(
    *,
    work_title: str | None = None,
    edition_title: str | None = None,
    series_name: str | None = None,
    language: str | None = None,
    translator: str | None = None,
    contributor_names: tuple[str, ...] = (),
    identifiers: tuple[tuple[str, str], ...] = (),
    profile: BibliographicEntityProfile | None = None,
    title_profile: TitleProfile | None = None,
    author_profile: AuthorityNameProfile | None = None,
    observed_at: datetime,
) -> tuple[FieldCandidate, ...]:
    """
    Generate local bibliographic/authority candidates from synthetic metadata values.

    The candidates are intentionally non-authoritative and designed for
    deterministic local resolution steps in W5A.
    """

    profile = profile or BibliographicEntityProfile(version=DEFAULT_METADATA_RESOLUTION_VERSION)
    title_profile = title_profile or TitleProfile(version=DEFAULT_TITLE_RESOLUTION_VERSION)
    author_profile = author_profile or AuthorityNameProfile(
        version=DEFAULT_AUTHOR_RESOLUTION_VERSION
    )

    candidates: list[FieldCandidate] = []

    if work_title is not None:
        candidates.extend(
            generate_work_candidates(
                work_title, observed_at=observed_at, profile=title_profile
            )
        )
    if edition_title is not None:
        candidates.extend(
            generate_edition_candidates(
                edition_title, observed_at=observed_at, profile=title_profile
            )
        )
    if series_name is not None:
        candidates.extend(
            generate_series_candidates(
                series_name, observed_at=observed_at, profile=title_profile
            )
        )

    for name in contributor_names:
        candidates.extend(
            generate_agent_name_candidates(name, observed_at=observed_at, profile=author_profile)
        )
    if profile.include_translator_as_agent and translator is not None and translator.strip():
        candidates.extend(
            generate_agent_name_candidates(
                translator, observed_at=observed_at, profile=author_profile
            )
        )

    if language is not None:
        normalized_language = _collapse_spaces(language.strip().lower())
        if normalized_language:
            candidates.append(
                _candidate(
                    field_name="edition.language",
                    value=normalized_language,
                    source_location=f"metadata-profile:{profile.version}.language",
                    observed_at=observed_at,
                    profile_version=profile.version,
                    confidence=0.5,
                ),
            )

    if profile.include_identifiers:
        for namespace, raw_identifier in identifiers:
            normalized = normalize_identifier_for_profile(namespace, raw_identifier)
            namespace_key, normalized_value = normalized.split(":", 1)
            candidates.append(
                _candidate(
                    field_name=f"identifier.{namespace_key}",
                    value=normalized_value,
                    source_location=f"metadata-profile:{profile.version}.identifier",
                    observed_at=observed_at,
                    profile_version=DEFAULT_IDENTIFIER_RESOLUTION_VERSION,
                    confidence=DEFAULT_IDENTIFIER_CONFIDENCE,
                ),
            )
            candidates.append(
                _candidate(
                    field_name=f"identifier.{namespace_key}.normalized",
                    value=normalized,
                    source_location=f"metadata-profile:{profile.version}.identifier.normalized",
                    observed_at=observed_at,
                    profile_version=DEFAULT_IDENTIFIER_RESOLUTION_VERSION,
                    confidence=DEFAULT_IDENTIFIER_CONFIDENCE + 0.05,
                ),
            )

    # Keep this function deterministic when duplicate metadata appears.
    seen: set[tuple[str, str, str]] = set()
    deduped_candidates = []
    for candidate in candidates:
        key = (candidate.field_name, candidate.value, candidate.source_location)
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(candidate)

    return tuple(deduped_candidates)


def generate_bibliographic_entity_candidates(
    *,
    work_title: str | None = None,
    edition_title: str | None = None,
    series_name: str | None = None,
    language: str | None = None,
    translator: str | None = None,
    contributor_names: tuple[str, ...] = (),
    identifiers: tuple[tuple[str, str], ...] = (),
    observed_at: datetime,
    profile: BibliographicEntityProfile | None = None,
    title_profile: TitleProfile | None = None,
    author_profile: AuthorityNameProfile | None = None,
) -> tuple[FieldCandidate, ...]:
    """Compatibility alias for local metadata candidate materialization."""

    return generate_metadata_entity_candidates(
        work_title=work_title,
        edition_title=edition_title,
        series_name=series_name,
        language=language,
        translator=translator,
        contributor_names=contributor_names,
        identifiers=identifiers,
        profile=profile,
        title_profile=title_profile,
        author_profile=author_profile,
        observed_at=observed_at,
    )


def _generate_title_candidates(
    *,
    title: str,
    target_kind: str,
    observed_at: datetime,
    profile: TitleProfile,
) -> tuple[FieldCandidate, ...]:
    canonical = require_non_empty(title, f"{target_kind}_title")
    normalized = canonicalize_title(canonical)

    candidates: list[FieldCandidate] = [
        _candidate(
            field_name=f"{target_kind}.title.canonical",
            value=canonical,
            source_location=f"{target_kind}-profile:{profile.version}.canonical",
            observed_at=observed_at,
            profile_version=profile.version,
            confidence=DEFAULT_TITLE_CONFIDENCE,
        ),
    ]

    if normalized != canonical:
        candidates.append(
            _candidate(
                field_name=f"{target_kind}.title.normalized",
                value=normalized,
                source_location=f"{target_kind}-profile:{profile.version}.normalized",
                observed_at=observed_at,
                profile_version=profile.version,
                confidence=DEFAULT_TITLE_CONFIDENCE + 0.1,
            ),
        )

    # For title continuity checks, a short alias preserves a version-stable
    # deterministic shape without pretending to decide canonical truth.
    alias = _title_alias(canonical)
    if alias != canonical:
        candidates.append(
            _candidate(
                field_name=f"{target_kind}.title.alias",
                value=alias,
                source_location=f"{target_kind}-profile:{profile.version}.alias",
                observed_at=observed_at,
                profile_version=profile.version,
                confidence=DEFAULT_TITLE_CONFIDENCE - 0.1,
            ),
        )

    return tuple(candidates)


def _candidate(
    *,
    field_name: str,
    value: str,
    source_location: str,
    observed_at: datetime,
    profile_version: str,
    confidence: float,
) -> FieldCandidate:
    return FieldCandidate(
        field_name=field_name,
        value=value,
        source_location=source_location,
        provenance=Provenance(
            source_kind="derived",
            source_name="authority-resolution",
            observed_at=observed_at,
            source_version=profile_version,
        ),
        confidence=confidence,
    )


def _normalized_text(value: str, *, preserve_case: bool = False) -> str:
    stripped = require_non_empty(value, "value").strip()
    folded = stripped if preserve_case else stripped.casefold()
    nfd = unicodedata.normalize("NFKD", folded)
    without_accents = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    sanitized = re.sub(r"[^0-9a-zA-Z\s\-'.&]+", " ", without_accents, flags=re.ASCII)
    return _collapse_spaces(sanitized)


def _collapse_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def _swap_comma_name(value: str) -> str:
    left, right = value.split(",", 1)
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return value.strip()
    return f"{right} {left}"


def _extract_parenthesized(value: str) -> str | None:
    match = re.search(r"\(([^)]+)\)", value)
    if not match:
        return None
    extracted = _collapse_spaces(match.group(1))
    return extracted if extracted else None


def _strip_annotations(value: str, credited_as: str | None) -> str:
    stripped = value
    if "(" in stripped and ")" in stripped:
        stripped = re.sub(r"\([^)]*\)", "", stripped)
    if credited_as is not None and "as" in stripped.lower():
        stripped = re.split(r"\bas|also known as", stripped, flags=re.IGNORECASE)[0]
    return _collapse_spaces(stripped)


def _extract_credited_as(value: str) -> str | None:
    match = re.search(r"\b(?:as|also known as)\s+([^;,\[]+)", value, flags=re.IGNORECASE)
    if not match:
        return None
    extracted = _collapse_spaces(match.group(1))
    return extracted if extracted else None


def _title_alias(value: str) -> str:
    prefixless = re.sub(r"^(?:The|A|An)\s+", "", value, flags=re.IGNORECASE)
    normalized_prefixless = _collapse_spaces(prefixless)
    return normalized_prefixless
