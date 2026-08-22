"""Deterministic book-only Library Health contracts and pure item rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from foliotone.collection_state.contracts import (
    COLLECTION_STATE_SERIALIZER,
    CollectionStateItemState,
    canonical_json_bytes,
    sha256_digest,
)
from foliotone.core._validation import require_aware_datetime
from foliotone.core.ids import EntityId

LIBRARY_HEALTH_PROFILE: Final = "library-health/v1"
LIBRARY_HEALTH_COMPARISON_PROFILE: Final = "library-health-comparison/v1"
LIBRARY_HEALTH_SERIALIZER: Final = COLLECTION_STATE_SERIALIZER
LIBRARY_HEALTH_NAMESPACE: Final = UUID("8fc5d1a3-e043-55d1-86f2-27189a9ff0a9")
MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING: Final = 64
DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT: Final = 20


class LibraryHealthDimension(StrEnum):
    SCAN_FIXITY = "SCAN_FIXITY"
    ANALYSIS_TOOL_COVERAGE = "ANALYSIS_TOOL_COVERAGE"
    METADATA_AUTHORITY_CLASSIFICATION = "METADATA_AUTHORITY_CLASSIFICATION"
    OPEN_REVIEWS = "OPEN_REVIEWS"
    DUPLICATE_VARIANT_EVIDENCE = "DUPLICATE_VARIANT_EVIDENCE"
    DEPENDENCIES = "DEPENDENCIES"
    BLOCKED_OPERATIONS = "BLOCKED_OPERATIONS"


LIBRARY_HEALTH_DIMENSION_ORDER: Final = tuple(LibraryHealthDimension)


class LibraryHealthCoverageState(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class LibraryHealthStatus(StrEnum):
    CLEAR = "CLEAR"
    OBSERVED = "OBSERVED"
    ATTENTION = "ATTENTION"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


class LibraryHealthSeverity(StrEnum):
    INFO = "INFO"
    ATTENTION = "ATTENTION"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


class LibraryHealthEvidenceCategory(StrEnum):
    COLLECTION_STATE = "COLLECTION_STATE"
    FIXITY_FINGERPRINT = "FIXITY_FINGERPRINT"
    TOOL_ANALYSIS = "TOOL_ANALYSIS"
    METADATA_CANDIDATE = "METADATA_CANDIDATE"
    AUTHORITY_RESOLUTION = "AUTHORITY_RESOLUTION"
    CLASSIFICATION = "CLASSIFICATION"
    REVIEW_QUEUE = "REVIEW_QUEUE"
    MATCHING = "MATCHING"
    CALIBRE = "CALIBRE"
    SIDECAR = "SIDECAR"
    ARCHIVE = "ARCHIVE"
    CONSOLIDATION = "CONSOLIDATION"
    QUARANTINE = "QUARANTINE"


class LibraryHealthFindingCode(StrEnum):
    FULL_FIXITY_MISSING = "FULL_FIXITY_MISSING"
    FULL_FIXITY_CONFLICT = "FULL_FIXITY_CONFLICT"
    ANALYSIS_MISSING = "ANALYSIS_MISSING"
    ANALYSIS_STALE_OR_UNSCOPED = "ANALYSIS_STALE_OR_UNSCOPED"
    ANALYSIS_CONFLICT = "ANALYSIS_CONFLICT"
    ANALYSIS_QUALITY_FINDING_PRESENT = "ANALYSIS_QUALITY_FINDING_PRESENT"
    TITLE_METADATA_MISSING = "TITLE_METADATA_MISSING"
    CONTRIBUTOR_METADATA_MISSING = "CONTRIBUTOR_METADATA_MISSING"
    IDENTIFIER_METADATA_MISSING = "IDENTIFIER_METADATA_MISSING"
    LANGUAGE_METADATA_MISSING = "LANGUAGE_METADATA_MISSING"
    PUBLISHER_METADATA_MISSING = "PUBLISHER_METADATA_MISSING"
    METADATA_INDEX_TRUNCATED = "METADATA_INDEX_TRUNCATED"
    AUTHORITY_RESOLUTION_COVERAGE_GAP = "AUTHORITY_RESOLUTION_COVERAGE_GAP"
    AUTHORITY_RESOLUTION_CONFLICT = "AUTHORITY_RESOLUTION_CONFLICT"
    CLASSIFICATION_COVERAGE_GAP = "CLASSIFICATION_COVERAGE_GAP"
    CLASSIFICATION_CONFLICT = "CLASSIFICATION_CONFLICT"
    PENDING_REVIEW = "PENDING_REVIEW"
    DEFERRED_REVIEW = "DEFERRED_REVIEW"
    DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT = "DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT"
    MATCHING_COVERAGE_GAP = "MATCHING_COVERAGE_GAP"
    MATCHING_CONFLICT = "MATCHING_CONFLICT"
    CALIBRE_DEPENDENCY_PRESENT = "CALIBRE_DEPENDENCY_PRESENT"
    SIDECAR_DEPENDENCY_PRESENT = "SIDECAR_DEPENDENCY_PRESENT"
    ARCHIVE_DEPENDENCY_PRESENT = "ARCHIVE_DEPENDENCY_PRESENT"
    DEPENDENCY_COVERAGE_GAP = "DEPENDENCY_COVERAGE_GAP"
    CALIBRE_CONFLICT = "CALIBRE_CONFLICT"
    ARCHIVE_CONFLICT = "ARCHIVE_CONFLICT"
    CONSOLIDATION_BLOCKED = "CONSOLIDATION_BLOCKED"
    QUARANTINE_BLOCKED = "QUARANTINE_BLOCKED"


LIBRARY_HEALTH_FINDING_ORDER: Final = tuple(LibraryHealthFindingCode)


@dataclass(frozen=True, slots=True)
class LibraryHealthFindingDefinition:
    dimension: LibraryHealthDimension
    severity: LibraryHealthSeverity
    evidence_categories: tuple[LibraryHealthEvidenceCategory, ...]


def _definition(
    dimension: LibraryHealthDimension,
    severity: LibraryHealthSeverity,
    *categories: LibraryHealthEvidenceCategory,
) -> LibraryHealthFindingDefinition:
    return LibraryHealthFindingDefinition(dimension, severity, tuple(categories))


_C = LibraryHealthEvidenceCategory
_D = LibraryHealthDimension
_S = LibraryHealthSeverity
LIBRARY_HEALTH_FINDING_DEFINITIONS: Final = {
    LibraryHealthFindingCode.FULL_FIXITY_MISSING: _definition(
        _D.SCAN_FIXITY, _S.INCOMPLETE, _C.COLLECTION_STATE, _C.FIXITY_FINGERPRINT
    ),
    LibraryHealthFindingCode.FULL_FIXITY_CONFLICT: _definition(
        _D.SCAN_FIXITY, _S.BLOCKED, _C.COLLECTION_STATE, _C.FIXITY_FINGERPRINT
    ),
    LibraryHealthFindingCode.ANALYSIS_MISSING: _definition(
        _D.ANALYSIS_TOOL_COVERAGE, _S.INCOMPLETE, _C.COLLECTION_STATE, _C.TOOL_ANALYSIS
    ),
    LibraryHealthFindingCode.ANALYSIS_STALE_OR_UNSCOPED: _definition(
        _D.ANALYSIS_TOOL_COVERAGE, _S.INCOMPLETE, _C.COLLECTION_STATE, _C.TOOL_ANALYSIS
    ),
    LibraryHealthFindingCode.ANALYSIS_CONFLICT: _definition(
        _D.ANALYSIS_TOOL_COVERAGE, _S.BLOCKED, _C.COLLECTION_STATE, _C.TOOL_ANALYSIS
    ),
    LibraryHealthFindingCode.ANALYSIS_QUALITY_FINDING_PRESENT: _definition(
        _D.ANALYSIS_TOOL_COVERAGE, _S.ATTENTION, _C.COLLECTION_STATE, _C.TOOL_ANALYSIS
    ),
    LibraryHealthFindingCode.TITLE_METADATA_MISSING: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.ATTENTION,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.CONTRIBUTOR_METADATA_MISSING: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.ATTENTION,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.IDENTIFIER_METADATA_MISSING: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INFO,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.LANGUAGE_METADATA_MISSING: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INFO,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.PUBLISHER_METADATA_MISSING: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INFO,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.METADATA_INDEX_TRUNCATED: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INCOMPLETE,
        _C.COLLECTION_STATE,
        _C.METADATA_CANDIDATE,
    ),
    LibraryHealthFindingCode.AUTHORITY_RESOLUTION_COVERAGE_GAP: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INCOMPLETE,
        _C.COLLECTION_STATE,
        _C.AUTHORITY_RESOLUTION,
    ),
    LibraryHealthFindingCode.AUTHORITY_RESOLUTION_CONFLICT: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.ATTENTION,
        _C.COLLECTION_STATE,
        _C.AUTHORITY_RESOLUTION,
    ),
    LibraryHealthFindingCode.CLASSIFICATION_COVERAGE_GAP: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.INCOMPLETE,
        _C.COLLECTION_STATE,
        _C.CLASSIFICATION,
    ),
    LibraryHealthFindingCode.CLASSIFICATION_CONFLICT: _definition(
        _D.METADATA_AUTHORITY_CLASSIFICATION,
        _S.ATTENTION,
        _C.COLLECTION_STATE,
        _C.CLASSIFICATION,
    ),
    LibraryHealthFindingCode.PENDING_REVIEW: _definition(
        _D.OPEN_REVIEWS, _S.ATTENTION, _C.COLLECTION_STATE, _C.REVIEW_QUEUE
    ),
    LibraryHealthFindingCode.DEFERRED_REVIEW: _definition(
        _D.OPEN_REVIEWS, _S.ATTENTION, _C.COLLECTION_STATE, _C.REVIEW_QUEUE
    ),
    LibraryHealthFindingCode.DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT: _definition(
        _D.DUPLICATE_VARIANT_EVIDENCE, _S.INFO, _C.COLLECTION_STATE, _C.MATCHING
    ),
    LibraryHealthFindingCode.MATCHING_COVERAGE_GAP: _definition(
        _D.DUPLICATE_VARIANT_EVIDENCE, _S.INCOMPLETE, _C.COLLECTION_STATE, _C.MATCHING
    ),
    LibraryHealthFindingCode.MATCHING_CONFLICT: _definition(
        _D.DUPLICATE_VARIANT_EVIDENCE, _S.ATTENTION, _C.COLLECTION_STATE, _C.MATCHING
    ),
    LibraryHealthFindingCode.CALIBRE_DEPENDENCY_PRESENT: _definition(
        _D.DEPENDENCIES, _S.INFO, _C.COLLECTION_STATE, _C.CALIBRE
    ),
    LibraryHealthFindingCode.SIDECAR_DEPENDENCY_PRESENT: _definition(
        _D.DEPENDENCIES, _S.INFO, _C.COLLECTION_STATE, _C.SIDECAR
    ),
    LibraryHealthFindingCode.ARCHIVE_DEPENDENCY_PRESENT: _definition(
        _D.DEPENDENCIES, _S.INFO, _C.COLLECTION_STATE, _C.ARCHIVE
    ),
    LibraryHealthFindingCode.DEPENDENCY_COVERAGE_GAP: _definition(
        _D.DEPENDENCIES,
        _S.INCOMPLETE,
        _C.COLLECTION_STATE,
        _C.CALIBRE,
        _C.SIDECAR,
        _C.ARCHIVE,
    ),
    LibraryHealthFindingCode.CALIBRE_CONFLICT: _definition(
        _D.DEPENDENCIES, _S.ATTENTION, _C.COLLECTION_STATE, _C.CALIBRE
    ),
    LibraryHealthFindingCode.ARCHIVE_CONFLICT: _definition(
        _D.DEPENDENCIES, _S.ATTENTION, _C.COLLECTION_STATE, _C.ARCHIVE
    ),
    LibraryHealthFindingCode.CONSOLIDATION_BLOCKED: _definition(
        _D.BLOCKED_OPERATIONS, _S.BLOCKED, _C.COLLECTION_STATE, _C.CONSOLIDATION
    ),
    LibraryHealthFindingCode.QUARANTINE_BLOCKED: _definition(
        _D.BLOCKED_OPERATIONS, _S.BLOCKED, _C.COLLECTION_STATE, _C.QUARANTINE
    ),
}

_CURRENT_STATES: Final = frozenset(
    {CollectionStateItemState.CURRENT, CollectionStateItemState.CURRENT_CONFLICT}
)
_CONFLICT_STATES: Final = frozenset(
    {
        CollectionStateItemState.CURRENT_CONFLICT,
        CollectionStateItemState.STALE_CONFLICT,
        CollectionStateItemState.UNSCOPED_CONFLICT,
    }
)
_STALE_OR_UNSCOPED_STATES: Final = frozenset(
    {
        CollectionStateItemState.STALE,
        CollectionStateItemState.STALE_CONFLICT,
        CollectionStateItemState.UNSCOPED,
        CollectionStateItemState.UNSCOPED_CONFLICT,
    }
)
_METADATA_FIELDS: Final = frozenset({"title", "contributor", "identifier", "language", "publisher"})


@dataclass(frozen=True, slots=True)
class LibraryHealthItemFacts:
    """Bounded facts for one immutable CollectionState query document."""

    file_id: EntityId
    observation_id: EntityId
    full_fixity_value_count: int
    analysis_state: CollectionStateItemState
    resolution_state: CollectionStateItemState
    classification_state: CollectionStateItemState
    matching_state: CollectionStateItemState
    calibre_state: CollectionStateItemState
    archive_state: CollectionStateItemState
    consolidation_state: CollectionStateItemState
    quarantine_state: CollectionStateItemState
    metadata_fields: tuple[str, ...] = ()
    metadata_index_truncated: bool = False
    analysis_finding_present: bool = False
    review_states: tuple[str, ...] = ()
    sidecar_dependency_present: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("Library Health item IDs are invalid")
        if (
            isinstance(self.full_fixity_value_count, bool)
            or not isinstance(self.full_fixity_value_count, int)
            or self.full_fixity_value_count < 0
        ):
            raise ValueError("full_fixity_value_count must be a nonnegative integer")
        fields = tuple(self.metadata_fields)
        if fields != tuple(sorted(set(fields))) or not set(fields) <= _METADATA_FIELDS:
            raise ValueError("Library Health metadata fields are invalid")
        states = tuple(self.review_states)
        if states != tuple(sorted(set(states))) or not set(states) <= {"DEFERRED", "PENDING"}:
            raise ValueError("Library Health review states are invalid")
        for name in (
            "metadata_index_truncated",
            "analysis_finding_present",
            "sidecar_dependency_present",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class LibraryHealthItemEvaluation:
    finding_codes: tuple[LibraryHealthFindingCode, ...]
    covered_dimensions: tuple[LibraryHealthDimension, ...]

    def __post_init__(self) -> None:
        if self.finding_codes != tuple(
            code for code in LIBRARY_HEALTH_FINDING_ORDER if code in self.finding_codes
        ):
            raise ValueError("Library Health item findings must be ordered and unique")
        if self.covered_dimensions != tuple(
            dimension
            for dimension in LIBRARY_HEALTH_DIMENSION_ORDER
            if dimension in self.covered_dimensions
        ):
            raise ValueError("Library Health covered dimensions must be ordered and unique")


def evaluate_library_health_item(facts: LibraryHealthItemFacts) -> LibraryHealthItemEvaluation:
    """Evaluate one item without producing identity or operation decisions."""

    codes: set[LibraryHealthFindingCode] = set()
    covered: set[LibraryHealthDimension] = {
        LibraryHealthDimension.OPEN_REVIEWS,
        LibraryHealthDimension.BLOCKED_OPERATIONS,
    }

    if facts.full_fixity_value_count == 0:
        codes.add(LibraryHealthFindingCode.FULL_FIXITY_MISSING)
    elif facts.full_fixity_value_count > 1:
        codes.add(LibraryHealthFindingCode.FULL_FIXITY_CONFLICT)
    else:
        covered.add(LibraryHealthDimension.SCAN_FIXITY)

    if facts.analysis_state is CollectionStateItemState.MISSING:
        codes.add(LibraryHealthFindingCode.ANALYSIS_MISSING)
    elif facts.analysis_state in _STALE_OR_UNSCOPED_STATES:
        codes.add(LibraryHealthFindingCode.ANALYSIS_STALE_OR_UNSCOPED)
    else:
        covered.add(LibraryHealthDimension.ANALYSIS_TOOL_COVERAGE)
    if facts.analysis_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.ANALYSIS_CONFLICT)
    if facts.analysis_finding_present:
        codes.add(LibraryHealthFindingCode.ANALYSIS_QUALITY_FINDING_PRESENT)

    fields = set(facts.metadata_fields)
    missing_metadata = (
        ("title", LibraryHealthFindingCode.TITLE_METADATA_MISSING),
        ("contributor", LibraryHealthFindingCode.CONTRIBUTOR_METADATA_MISSING),
        ("identifier", LibraryHealthFindingCode.IDENTIFIER_METADATA_MISSING),
        ("language", LibraryHealthFindingCode.LANGUAGE_METADATA_MISSING),
        ("publisher", LibraryHealthFindingCode.PUBLISHER_METADATA_MISSING),
    )
    for field_name, code in missing_metadata:
        if field_name not in fields:
            codes.add(code)
    if facts.metadata_index_truncated:
        codes.add(LibraryHealthFindingCode.METADATA_INDEX_TRUNCATED)
    if facts.resolution_state not in _CURRENT_STATES:
        codes.add(LibraryHealthFindingCode.AUTHORITY_RESOLUTION_COVERAGE_GAP)
    if facts.resolution_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.AUTHORITY_RESOLUTION_CONFLICT)
    if facts.classification_state not in _CURRENT_STATES:
        codes.add(LibraryHealthFindingCode.CLASSIFICATION_COVERAGE_GAP)
    if facts.classification_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.CLASSIFICATION_CONFLICT)
    if (
        {"title", "contributor"} <= fields
        and not facts.metadata_index_truncated
        and facts.resolution_state in _CURRENT_STATES
        and facts.classification_state in _CURRENT_STATES
    ):
        covered.add(LibraryHealthDimension.METADATA_AUTHORITY_CLASSIFICATION)

    if "PENDING" in facts.review_states:
        codes.add(LibraryHealthFindingCode.PENDING_REVIEW)
    if "DEFERRED" in facts.review_states:
        codes.add(LibraryHealthFindingCode.DEFERRED_REVIEW)

    if facts.matching_state in _CURRENT_STATES:
        covered.add(LibraryHealthDimension.DUPLICATE_VARIANT_EVIDENCE)
        codes.add(LibraryHealthFindingCode.DUPLICATE_OR_VARIANT_EVIDENCE_PRESENT)
    else:
        codes.add(LibraryHealthFindingCode.MATCHING_COVERAGE_GAP)
    if facts.matching_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.MATCHING_CONFLICT)

    dependency_covered = False
    if facts.calibre_state in _CURRENT_STATES:
        dependency_covered = True
        codes.add(LibraryHealthFindingCode.CALIBRE_DEPENDENCY_PRESENT)
    if facts.sidecar_dependency_present:
        dependency_covered = True
        codes.add(LibraryHealthFindingCode.SIDECAR_DEPENDENCY_PRESENT)
    if facts.archive_state in _CURRENT_STATES:
        dependency_covered = True
        codes.add(LibraryHealthFindingCode.ARCHIVE_DEPENDENCY_PRESENT)
    if dependency_covered:
        covered.add(LibraryHealthDimension.DEPENDENCIES)
    else:
        codes.add(LibraryHealthFindingCode.DEPENDENCY_COVERAGE_GAP)
    if facts.calibre_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.CALIBRE_CONFLICT)
    if facts.archive_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.ARCHIVE_CONFLICT)

    if facts.consolidation_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.CONSOLIDATION_BLOCKED)
    if facts.quarantine_state in _CONFLICT_STATES:
        codes.add(LibraryHealthFindingCode.QUARANTINE_BLOCKED)

    return LibraryHealthItemEvaluation(
        tuple(code for code in LIBRARY_HEALTH_FINDING_ORDER if code in codes),
        tuple(dimension for dimension in LIBRARY_HEALTH_DIMENSION_ORDER if dimension in covered),
    )


def library_health_finding_definition(
    code: LibraryHealthFindingCode,
) -> LibraryHealthFindingDefinition:
    return LIBRARY_HEALTH_FINDING_DEFINITIONS[code]


def library_health_coverage_state(
    assessed_item_count: int, covered_item_count: int
) -> LibraryHealthCoverageState:
    if assessed_item_count < 0 or not 0 <= covered_item_count <= assessed_item_count:
        raise ValueError("Library Health coverage counts are invalid")
    if assessed_item_count == 0 or covered_item_count == assessed_item_count:
        return LibraryHealthCoverageState.COMPLETE
    if covered_item_count:
        return LibraryHealthCoverageState.PARTIAL
    return LibraryHealthCoverageState.NONE


def library_health_status(
    severities: tuple[LibraryHealthSeverity, ...],
) -> LibraryHealthStatus:
    values = set(severities)
    if LibraryHealthSeverity.BLOCKED in values:
        return LibraryHealthStatus.BLOCKED
    if LibraryHealthSeverity.INCOMPLETE in values:
        return LibraryHealthStatus.INCOMPLETE
    if LibraryHealthSeverity.ATTENTION in values:
        return LibraryHealthStatus.ATTENTION
    if LibraryHealthSeverity.INFO in values:
        return LibraryHealthStatus.OBSERVED
    return LibraryHealthStatus.CLEAR


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class LibraryHealthSample:
    ordinal: int
    file_id: EntityId
    observation_id: EntityId
    sample_digest: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not 0 <= self.ordinal < (
            MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING
        ):
            raise ValueError("Library Health sample ordinal is invalid")
        if not isinstance(self.file_id, EntityId) or not isinstance(self.observation_id, EntityId):
            raise ValueError("Library Health sample IDs are invalid")
        expected = sha256_digest(self.material_payload())
        if not self.sample_digest:
            object.__setattr__(self, "sample_digest", expected)
        _require_sha256(self.sample_digest, "sample_digest")
        if self.sample_digest != expected:
            raise ValueError("Library Health sample digest is inconsistent")

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "file_id": str(self.file_id),
            "observation_id": str(self.observation_id),
        }

    def canonical_payload(self) -> dict[str, object]:
        return {**self.material_payload(), "sample_digest": self.sample_digest}


@dataclass(frozen=True, slots=True)
class LibraryHealthFinding:
    ordinal: int
    code: LibraryHealthFindingCode
    dimension: LibraryHealthDimension
    severity: LibraryHealthSeverity
    evidence_categories: tuple[LibraryHealthEvidenceCategory, ...]
    item_count: int
    samples: tuple[LibraryHealthSample, ...]
    finding_digest: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("Library Health finding ordinal is invalid")
        definition = library_health_finding_definition(self.code)
        if (
            self.dimension is not definition.dimension
            or self.severity is not definition.severity
            or self.evidence_categories != definition.evidence_categories
        ):
            raise ValueError("Library Health finding definition is inconsistent")
        if isinstance(self.item_count, bool) or not isinstance(self.item_count, int):
            raise ValueError("Library Health finding count is invalid")
        if self.item_count <= 0:
            raise ValueError("Library Health findings require affected items")
        if len(self.samples) > min(self.item_count, MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING):
            raise ValueError("Library Health finding samples exceed the bound")
        if tuple(sample.ordinal for sample in self.samples) != tuple(range(len(self.samples))):
            raise ValueError("Library Health samples must be contiguous")
        file_ids = tuple(str(sample.file_id) for sample in self.samples)
        if file_ids != tuple(sorted(set(file_ids))):
            raise ValueError("Library Health samples must be sorted and unique")
        expected = sha256_digest(self.material_payload())
        if not self.finding_digest:
            object.__setattr__(self, "finding_digest", expected)
        _require_sha256(self.finding_digest, "finding_digest")
        if self.finding_digest != expected:
            raise ValueError("Library Health finding digest is inconsistent")

    @property
    def samples_truncated(self) -> bool:
        return len(self.samples) < self.item_count

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "code": self.code.value,
            "dimension": self.dimension.value,
            "severity": self.severity.value,
            "evidence_categories": [value.value for value in self.evidence_categories],
            "item_count": self.item_count,
            "samples": [sample.canonical_payload() for sample in self.samples],
        }

    def canonical_payload(self) -> dict[str, object]:
        return {**self.material_payload(), "finding_digest": self.finding_digest}


@dataclass(frozen=True, slots=True)
class LibraryHealthDimensionSummary:
    ordinal: int
    dimension: LibraryHealthDimension
    status: LibraryHealthStatus
    coverage_state: LibraryHealthCoverageState
    assessed_item_count: int
    covered_item_count: int
    affected_item_count: int
    evidence_categories: tuple[LibraryHealthEvidenceCategory, ...]
    findings: tuple[LibraryHealthFinding, ...]
    dimension_digest: str = ""

    def __post_init__(self) -> None:
        if self.ordinal != LIBRARY_HEALTH_DIMENSION_ORDER.index(self.dimension):
            raise ValueError("Library Health dimension ordinal is invalid")
        for name in ("assessed_item_count", "covered_item_count", "affected_item_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.covered_item_count > self.assessed_item_count or (
            self.affected_item_count > self.assessed_item_count
        ):
            raise ValueError("Library Health dimension counts are inconsistent")
        if self.coverage_state is not library_health_coverage_state(
            self.assessed_item_count, self.covered_item_count
        ):
            raise ValueError("Library Health dimension coverage is inconsistent")
        if tuple(finding.ordinal for finding in self.findings) != tuple(range(len(self.findings))):
            raise ValueError("Library Health findings must be contiguous")
        if any(finding.dimension is not self.dimension for finding in self.findings):
            raise ValueError("Library Health finding belongs to another dimension")
        expected_codes = tuple(
            code
            for code in LIBRARY_HEALTH_FINDING_ORDER
            if any(finding.code is code for finding in self.findings)
        )
        if tuple(finding.code for finding in self.findings) != expected_codes:
            raise ValueError("Library Health findings must be ordered and unique")
        if self.status is not library_health_status(
            tuple(finding.severity for finding in self.findings)
        ):
            raise ValueError("Library Health dimension status is inconsistent")
        categories = tuple(self.evidence_categories)
        if categories != tuple(
            value for value in LibraryHealthEvidenceCategory if value in categories
        ):
            raise ValueError("Library Health evidence categories must be ordered and unique")
        if not categories or LibraryHealthEvidenceCategory.COLLECTION_STATE not in categories:
            raise ValueError("Library Health dimensions must bind CollectionState evidence")
        expected = sha256_digest(self.material_payload())
        if not self.dimension_digest:
            object.__setattr__(self, "dimension_digest", expected)
        _require_sha256(self.dimension_digest, "dimension_digest")
        if self.dimension_digest != expected:
            raise ValueError("Library Health dimension digest is inconsistent")

    def material_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "dimension": self.dimension.value,
            "status": self.status.value,
            "coverage_state": self.coverage_state.value,
            "assessed_item_count": self.assessed_item_count,
            "covered_item_count": self.covered_item_count,
            "affected_item_count": self.affected_item_count,
            "evidence_categories": [value.value for value in self.evidence_categories],
            "findings": [finding.canonical_payload() for finding in self.findings],
        }

    def canonical_payload(self) -> dict[str, object]:
        return {**self.material_payload(), "dimension_digest": self.dimension_digest}


@dataclass(frozen=True, slots=True)
class LibraryHealthSnapshot:
    id: EntityId
    collection_state_snapshot_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    created_at: datetime
    item_count: int
    collection_state_content_digest: str
    query_index_content_digest: str
    dimensions: tuple[LibraryHealthDimensionSummary, ...]
    content_digest: str
    profile: str = LIBRARY_HEALTH_PROFILE
    serializer: str = LIBRARY_HEALTH_SERIALIZER

    def __post_init__(self) -> None:
        if self.profile != LIBRARY_HEALTH_PROFILE or self.serializer != (LIBRARY_HEALTH_SERIALIZER):
            raise ValueError("Library Health snapshot profile is invalid")
        if any(
            not isinstance(value, EntityId)
            for value in (
                self.id,
                self.collection_state_snapshot_id,
                self.scan_root_id,
                self.source_scan_run_id,
            )
        ):
            raise ValueError("Library Health snapshot IDs are invalid")
        require_aware_datetime(self.created_at, "created_at")
        if isinstance(self.item_count, bool) or not isinstance(self.item_count, int):
            raise ValueError("Library Health item count is invalid")
        if self.item_count < 0:
            raise ValueError("Library Health item count must not be negative")
        for name in ("collection_state_content_digest", "query_index_content_digest"):
            _require_sha256(getattr(self, name), name)
        if tuple(value.dimension for value in self.dimensions) != (LIBRARY_HEALTH_DIMENSION_ORDER):
            raise ValueError("Library Health dimensions must be complete and ordered")
        if any(value.assessed_item_count != self.item_count for value in self.dimensions):
            raise ValueError("Library Health dimensions must assess every snapshot item")
        _require_sha256(self.content_digest, "content_digest")
        if self.content_digest != library_health_content_digest(self):
            raise ValueError("Library Health content digest is inconsistent")
        if self.id != library_health_snapshot_id(self.content_digest):
            raise ValueError("Library Health snapshot ID is inconsistent")

    @property
    def finding_count(self) -> int:
        return sum(len(dimension.findings) for dimension in self.dimensions)

    @property
    def sample_count(self) -> int:
        return sum(
            len(finding.samples) for dimension in self.dimensions for finding in dimension.findings
        )

    def material_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "serializer": self.serializer,
            "collection_state_snapshot_id": str(self.collection_state_snapshot_id),
            "scan_root_id": str(self.scan_root_id),
            "source_scan_run_id": str(self.source_scan_run_id),
            "item_count": self.item_count,
            "collection_state_content_digest": self.collection_state_content_digest,
            "query_index_content_digest": self.query_index_content_digest,
            "dimensions": [dimension.canonical_payload() for dimension in self.dimensions],
        }


def library_health_content_digest(snapshot: LibraryHealthSnapshot) -> str:
    return sha256_digest(snapshot.material_payload())


def library_health_snapshot_id(content_digest: str) -> EntityId:
    _require_sha256(content_digest, "content_digest")
    return EntityId(uuid5(LIBRARY_HEALTH_NAMESPACE, content_digest))


@dataclass(frozen=True, slots=True)
class LibraryHealthDimensionDelta:
    dimension: LibraryHealthDimension
    before_status: LibraryHealthStatus
    after_status: LibraryHealthStatus
    before_coverage: LibraryHealthCoverageState
    after_coverage: LibraryHealthCoverageState
    before_affected_item_count: int
    after_affected_item_count: int

    @property
    def affected_item_delta(self) -> int:
        return self.after_affected_item_count - self.before_affected_item_count


@dataclass(frozen=True, slots=True)
class LibraryHealthFindingDelta:
    dimension: LibraryHealthDimension
    code: LibraryHealthFindingCode
    before_item_count: int
    after_item_count: int

    @property
    def item_delta(self) -> int:
        return self.after_item_count - self.before_item_count


@dataclass(frozen=True, slots=True)
class LibraryHealthComparison:
    before_health_snapshot_id: EntityId
    after_health_snapshot_id: EntityId
    scan_root_id: EntityId
    dimension_deltas: tuple[LibraryHealthDimensionDelta, ...]
    finding_deltas: tuple[LibraryHealthFindingDelta, ...]
    profile: str = LIBRARY_HEALTH_COMPARISON_PROFILE

    def __post_init__(self) -> None:
        if self.profile != LIBRARY_HEALTH_COMPARISON_PROFILE:
            raise ValueError("Library Health comparison profile is invalid")
        if self.before_health_snapshot_id == self.after_health_snapshot_id:
            raise ValueError("Library Health comparison requires distinct snapshots")
        if tuple(value.dimension for value in self.dimension_deltas) != (
            LIBRARY_HEALTH_DIMENSION_ORDER
        ):
            raise ValueError("Library Health dimension deltas are incomplete")
        expected = tuple(
            code
            for code in LIBRARY_HEALTH_FINDING_ORDER
            if any(delta.code is code for delta in self.finding_deltas)
        )
        if tuple(value.code for value in self.finding_deltas) != expected:
            raise ValueError("Library Health finding deltas must be ordered and unique")


def compare_library_health(
    before: LibraryHealthSnapshot,
    after: LibraryHealthSnapshot,
) -> LibraryHealthComparison:
    if before.id == after.id:
        raise ValueError("Library Health comparison requires distinct snapshots")
    if before.scan_root_id != after.scan_root_id:
        raise ValueError("Library Health snapshots belong to different ScanRoots")
    before_dimensions = {value.dimension: value for value in before.dimensions}
    after_dimensions = {value.dimension: value for value in after.dimensions}
    dimension_deltas = tuple(
        LibraryHealthDimensionDelta(
            dimension,
            before_dimensions[dimension].status,
            after_dimensions[dimension].status,
            before_dimensions[dimension].coverage_state,
            after_dimensions[dimension].coverage_state,
            before_dimensions[dimension].affected_item_count,
            after_dimensions[dimension].affected_item_count,
        )
        for dimension in LIBRARY_HEALTH_DIMENSION_ORDER
    )
    before_findings = {
        finding.code: finding for dimension in before.dimensions for finding in dimension.findings
    }
    after_findings = {
        finding.code: finding for dimension in after.dimensions for finding in dimension.findings
    }
    finding_deltas = tuple(
        LibraryHealthFindingDelta(
            library_health_finding_definition(code).dimension,
            code,
            before_findings[code].item_count if code in before_findings else 0,
            after_findings[code].item_count if code in after_findings else 0,
        )
        for code in LIBRARY_HEALTH_FINDING_ORDER
        if code in before_findings or code in after_findings
    )
    return LibraryHealthComparison(
        before.id,
        after.id,
        after.scan_root_id,
        dimension_deltas,
        finding_deltas,
    )


class LibraryHealthDimensionsHasher:
    """Stream a deterministic digest over complete dimension payloads."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256(b"foliotone:library-health-dimensions/v1\x00")
        self._count = 0

    def update(self, dimension: LibraryHealthDimensionSummary) -> None:
        if dimension.ordinal != self._count:
            raise ValueError("Library Health dimensions must be contiguous")
        payload = canonical_json_bytes(dimension.canonical_payload())
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def hexdigest(self) -> str:
        return self._digest.hexdigest()
