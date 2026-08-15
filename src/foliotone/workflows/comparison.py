"""Provider-neutral comparison of persisted, observation-bound e-book Evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine

from foliotone.analyzers.ebook import (
    COVER_FINGERPRINT_KIND,
    EBOOK_METADATA_CANDIDATE_RESULT,
    TEXT_FINGERPRINT_KIND,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import repository
from foliotone.tooling import ToolExecution, ToolResult
from foliotone.workflows.ebook import ebook_analysis_format

EBOOK_COMPARISON_PROFILE = "ebook-comparison/v1"
_CALIBRE_FORMATS = frozenset({"EPUB", "MOBI", "AZW", "AZW3"})
_METADATA_DIRECT_FIELDS = frozenset(
    {
        "title",
        "title_sort",
        "language",
        "publisher",
        "publication_date",
        "subject",
        "description",
        "rights",
        "type",
        "rating",
    }
)
_CALIBRE_ASSESSED_FIELDS = _METADATA_DIRECT_FIELDS | {
    "contributor.author",
    "contributor.untyped",
    "identifier.untyped",
    "series",
}
_PDF_ASSESSED_FIELDS = frozenset({"title", "contributor.author"})
_IGNORED_IDENTIFIER_NAMESPACES = frozenset({"calibre"})
_STRUCTURE_REQUIRED_KEYS = frozenset(
    {"conformance_status", "fatal_count", "error_count", "warning_count"}
)
_MAX_FACT_KEY_CHARS = 64
_MAX_FACT_VALUE_CHARS = 4096
_MAX_LISTED_FIELDS = 64


class EbookComparisonError(RuntimeError):
    """Persisted observations cannot be compared under the safe profile."""


class EbookComparisonStatus(StrEnum):
    """Aggregate evidence coverage without producing a match verdict."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class EbookComparisonDimensionName(StrEnum):
    """Stable provider-neutral comparison dimensions."""

    FILE_BYTES = "FILE_BYTES"
    NORMALIZED_TEXT = "NORMALIZED_TEXT"
    METADATA = "METADATA"
    STRUCTURE = "STRUCTURE"
    COVER = "COVER"


class EbookComparisonState(StrEnum):
    """Comparison result for one dimension without identity semantics."""

    SAME = "SAME"
    DIFFERENT = "DIFFERENT"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EbookComparisonCoverage(StrEnum):
    """How completely the applicable dimension could be compared."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class EbookComparisonDimension:
    """Bounded result and provenance for one comparison dimension."""

    name: EbookComparisonDimensionName
    state: EbookComparisonState
    coverage: EbookComparisonCoverage
    facts: tuple[tuple[str, str], ...] = ()
    left_evidence_ids: tuple[EntityId, ...] = ()
    right_evidence_ids: tuple[EntityId, ...] = ()
    source_execution_ids: tuple[EntityId, ...] = ()

    def __post_init__(self) -> None:
        if (self.state is EbookComparisonState.NOT_APPLICABLE) != (
            self.coverage is EbookComparisonCoverage.NOT_APPLICABLE
        ):
            raise ValueError("not-applicable comparison state and coverage must agree")
        for values, label in (
            (self.left_evidence_ids, "left evidence IDs"),
            (self.right_evidence_ids, "right evidence IDs"),
            (self.source_execution_ids, "source execution IDs"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"comparison {label} must be unique")
        seen: set[str] = set()
        for key, value in self.facts:
            if not key or len(key) > _MAX_FACT_KEY_CHARS:
                raise ValueError("comparison fact key must be bounded and non-empty")
            if not value or len(value) > _MAX_FACT_VALUE_CHARS:
                raise ValueError("comparison fact value must be bounded and non-empty")
            if key in seen:
                raise ValueError("comparison fact keys must be unique within a dimension")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class EbookComparisonOutcome:
    """Read-only comparison of two exact FileObservations."""

    left_observation_id: EntityId
    right_observation_id: EntityId
    left_format: str
    right_format: str
    dimensions: tuple[EbookComparisonDimension, ...]
    profile: str = EBOOK_COMPARISON_PROFILE

    def __post_init__(self) -> None:
        if self.left_observation_id == self.right_observation_id:
            raise ValueError("e-book comparison requires two distinct observations")
        expected = tuple(EbookComparisonDimensionName)
        names = tuple(dimension.name for dimension in self.dimensions)
        if names != expected:
            raise ValueError("comparison dimensions must use the stable complete order")
        if not self.profile.strip():
            raise ValueError("comparison profile must not be empty")

    @property
    def status(self) -> EbookComparisonStatus:
        """Summarize evidence coverage without collapsing the dimension states."""
        applicable = tuple(
            dimension
            for dimension in self.dimensions
            if dimension.coverage is not EbookComparisonCoverage.NOT_APPLICABLE
        )
        comparable = tuple(
            dimension
            for dimension in applicable
            if dimension.state
            in {EbookComparisonState.SAME, EbookComparisonState.DIFFERENT}
        )
        if not comparable:
            return EbookComparisonStatus.UNAVAILABLE
        if all(
            dimension.coverage is EbookComparisonCoverage.COMPLETE
            for dimension in applicable
        ):
            return EbookComparisonStatus.COMPLETE
        return EbookComparisonStatus.PARTIAL


@dataclass(frozen=True, slots=True)
class _SelectedExecutions:
    successful: tuple[ToolExecution, ...]
    has_unusable_latest: bool


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    values: dict[str, frozenset[str]]
    assessed_fields: frozenset[str]
    scopes: frozenset[str]
    evidence_ids: tuple[EntityId, ...]
    execution_ids: tuple[EntityId, ...]
    partial: bool


class _EvidenceCatalog:
    """In-memory index built once for one CLI comparison request."""

    def __init__(self, engine: Engine, observation_ids: frozenset[EntityId]) -> None:
        identities = {f"file-observation:{value}" for value in observation_ids}
        self.executions = tuple(
            execution
            for execution in repository(engine, ToolExecution).list_all()
            if execution.input_identity in identities
        )
        self.results = tuple(
            result
            for result in repository(engine, ToolResult).list_all()
            if result.target_kind is EntityKind.FILE_OBSERVATION
            and result.target_id in observation_ids
        )
        self.fingerprints = tuple(
            fingerprint
            for fingerprint in repository(engine, Fingerprint).list_all()
            if fingerprint.target_kind is EntityKind.FILE_OBSERVATION
            and fingerprint.target_id in observation_ids
        )

    def latest(
        self,
        observation_id: EntityId,
        capabilities: frozenset[ToolCapability],
    ) -> _SelectedExecutions:
        input_identity = f"file-observation:{observation_id}"
        candidates = tuple(
            execution
            for execution in self.executions
            if execution.input_identity == input_identity
            and execution.capability in capabilities
        )
        grouped: dict[tuple[object, ...], list[ToolExecution]] = defaultdict(list)
        for execution in candidates:
            grouped[
                (
                    execution.provider_id,
                    execution.capability,
                )
            ].append(execution)
        latest = tuple(
            max(values, key=lambda value: (value.started_at, str(value.id)))
            for _, values in sorted(grouped.items(), key=lambda item: repr(item[0]))
        )
        return _SelectedExecutions(
            successful=tuple(
                execution
                for execution in latest
                if execution.status is ToolExecutionStatus.SUCCEEDED
            ),
            has_unusable_latest=any(
                execution.status is not ToolExecutionStatus.SUCCEEDED
                for execution in latest
            ),
        )

    def results_for(
        self,
        observation_id: EntityId,
        executions: tuple[ToolExecution, ...],
    ) -> tuple[ToolResult, ...]:
        execution_ids = {execution.id for execution in executions}
        return tuple(
            result
            for result in self.results
            if result.target_id == observation_id
            and result.execution_id in execution_ids
        )

    def fingerprints_for(
        self,
        observation_id: EntityId,
        kind: str,
        executions: tuple[ToolExecution, ...] | None = None,
    ) -> tuple[Fingerprint, ...]:
        execution_ids = (
            None if executions is None else {execution.id for execution in executions}
        )
        return tuple(
            fingerprint
            for fingerprint in self.fingerprints
            if fingerprint.target_id == observation_id
            and fingerprint.kind == kind
            and (
                execution_ids is None
                or fingerprint.tool_execution_id in execution_ids
            )
        )


class EbookComparisonService:
    """Compare persisted provider-neutral Evidence without opening source media."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._observations = repository(engine, FileObservation)

    def compare(
        self,
        left_observation_id: EntityId,
        right_observation_id: EntityId,
    ) -> EbookComparisonOutcome:
        """Return bounded dimension facts without persisting a Relation or verdict."""
        if left_observation_id == right_observation_id:
            raise EbookComparisonError("e-book comparison requires two distinct observations")
        left = self._observations.get(left_observation_id)
        right = self._observations.get(right_observation_id)
        if left is None:
            raise EbookComparisonError("left FileObservation does not exist")
        if right is None:
            raise EbookComparisonError("right FileObservation does not exist")
        try:
            left_format = ebook_analysis_format(left.relative_path)
            right_format = ebook_analysis_format(right.relative_path)
        except ValueError as error:
            raise EbookComparisonError(str(error)) from error
        except RuntimeError as error:
            raise EbookComparisonError(str(error)) from error

        catalog = _EvidenceCatalog(
            self._engine,
            frozenset({left_observation_id, right_observation_id}),
        )
        dimensions = (
            _file_bytes_dimension(catalog, left, right),
            _text_dimension(catalog, left, right),
            _metadata_dimension(catalog, left, right),
            _structure_dimension(catalog, left, right, left_format, right_format),
            _cover_dimension(catalog, left, right, left_format, right_format),
        )
        return EbookComparisonOutcome(
            left_observation_id=left.id,
            right_observation_id=right.id,
            left_format=left_format,
            right_format=right_format,
            dimensions=dimensions,
        )


def _file_bytes_dimension(
    catalog: _EvidenceCatalog,
    left: FileObservation,
    right: FileObservation,
) -> EbookComparisonDimension:
    return _fingerprint_dimension(
        EbookComparisonDimensionName.FILE_BYTES,
        catalog.fingerprints_for(left.id, "FILE_SHA256"),
        catalog.fingerprints_for(right.id, "FILE_SHA256"),
        (),
        partial=False,
        missing_reason="FULL_FILE_SHA256_MISSING",
    )


def _text_dimension(
    catalog: _EvidenceCatalog,
    left: FileObservation,
    right: FileObservation,
) -> EbookComparisonDimension:
    capabilities = frozenset({ToolCapability.EXTRACT_TEXT})
    left_sources = catalog.latest(left.id, capabilities)
    right_sources = catalog.latest(right.id, capabilities)
    executions = _execution_ids(left_sources.successful + right_sources.successful)
    return _fingerprint_dimension(
        EbookComparisonDimensionName.NORMALIZED_TEXT,
        catalog.fingerprints_for(
            left.id,
            TEXT_FINGERPRINT_KIND,
            left_sources.successful,
        ),
        catalog.fingerprints_for(
            right.id,
            TEXT_FINGERPRINT_KIND,
            right_sources.successful,
        ),
        executions,
        partial=(
            left_sources.has_unusable_latest or right_sources.has_unusable_latest
        ),
        missing_reason="NORMALIZED_TEXT_FINGERPRINT_MISSING",
    )


def _fingerprint_dimension(
    name: EbookComparisonDimensionName,
    left: tuple[Fingerprint, ...],
    right: tuple[Fingerprint, ...],
    execution_ids: tuple[EntityId, ...],
    *,
    partial: bool,
    missing_reason: str,
) -> EbookComparisonDimension:
    left_profiles = _fingerprint_profiles(left)
    right_profiles = _fingerprint_profiles(right)
    evidence_left = _entity_ids(value.id for value in left)
    evidence_right = _entity_ids(value.id for value in right)
    if not left_profiles or not right_profiles:
        return _dimension(
            name,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", missing_reason),),
            evidence_left,
            evidence_right,
            execution_ids,
        )
    common_profiles = set(left_profiles) & set(right_profiles)
    if len(common_profiles) != 1:
        return _dimension(
            name,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.PARTIAL,
            (("reason", "FINGERPRINT_PROFILE_INCOMPATIBLE"),),
            evidence_left,
            evidence_right,
            execution_ids,
        )
    profile = next(iter(common_profiles))
    left_values = left_profiles[profile]
    right_values = right_profiles[profile]
    if len(left_values) != 1 or len(right_values) != 1:
        return _dimension(
            name,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.PARTIAL,
            (("reason", "FINGERPRINT_EVIDENCE_CONFLICT"),),
            evidence_left,
            evidence_right,
            execution_ids,
        )
    profile_partial = (
        partial
        or set(left_profiles) != {profile}
        or set(right_profiles) != {profile}
    )
    facts = (("algorithm", profile[0]), ("algorithm_version", profile[1]))
    return _dimension(
        name,
        (
            EbookComparisonState.SAME
            if left_values == right_values
            else EbookComparisonState.DIFFERENT
        ),
        (
            EbookComparisonCoverage.PARTIAL
            if profile_partial
            else EbookComparisonCoverage.COMPLETE
        ),
        facts,
        evidence_left,
        evidence_right,
        execution_ids,
    )


def _metadata_dimension(
    catalog: _EvidenceCatalog,
    left: FileObservation,
    right: FileObservation,
) -> EbookComparisonDimension:
    capabilities = frozenset(
        {ToolCapability.READ_METADATA, ToolCapability.TECHNICAL_METADATA}
    )
    left_sources = catalog.latest(left.id, capabilities)
    right_sources = catalog.latest(right.id, capabilities)
    left_snapshot = _metadata_snapshot(catalog, left.id, left_sources)
    right_snapshot = _metadata_snapshot(catalog, right.id, right_sources)
    execution_ids = _entity_ids(
        (*left_snapshot.execution_ids, *right_snapshot.execution_ids)
    )
    if not left_snapshot.scopes or not right_snapshot.scopes:
        return _dimension(
            EbookComparisonDimensionName.METADATA,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", "METADATA_EVIDENCE_MISSING"),),
            left_snapshot.evidence_ids,
            right_snapshot.evidence_ids,
            execution_ids,
        )
    compared_fields = (
        left_snapshot.assessed_fields | right_snapshot.assessed_fields
        if left_snapshot.scopes == right_snapshot.scopes
        and len(left_snapshot.scopes) == 1
        else left_snapshot.assessed_fields & right_snapshot.assessed_fields
    )
    if not compared_fields:
        return _dimension(
            EbookComparisonDimensionName.METADATA,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", "METADATA_SCOPE_INCOMPATIBLE"),),
            left_snapshot.evidence_ids,
            right_snapshot.evidence_ids,
            execution_ids,
        )
    different = tuple(
        sorted(
            field
            for field in compared_fields
            if left_snapshot.values.get(field, frozenset())
            != right_snapshot.values.get(field, frozenset())
        )
    )
    left_multiple = tuple(
        sorted(field for field, values in left_snapshot.values.items() if len(values) > 1)
    )
    right_multiple = tuple(
        sorted(
            field for field, values in right_snapshot.values.items() if len(values) > 1
        )
    )
    facts = (
        ("compared_field_count", str(len(compared_fields))),
        ("different_field_count", str(len(different))),
        ("different_fields", _field_list(different)),
        ("left_multiple_candidate_fields", _field_list(left_multiple)),
        ("right_multiple_candidate_fields", _field_list(right_multiple)),
    )
    partial = (
        left_snapshot.partial
        or right_snapshot.partial
        or left_snapshot.scopes != right_snapshot.scopes
        or left_snapshot.assessed_fields != right_snapshot.assessed_fields
    )
    return _dimension(
        EbookComparisonDimensionName.METADATA,
        EbookComparisonState.DIFFERENT if different else EbookComparisonState.SAME,
        (
            EbookComparisonCoverage.PARTIAL
            if partial
            else EbookComparisonCoverage.COMPLETE
        ),
        facts,
        left_snapshot.evidence_ids,
        right_snapshot.evidence_ids,
        execution_ids,
    )


def _metadata_snapshot(
    catalog: _EvidenceCatalog,
    observation_id: EntityId,
    sources: _SelectedExecutions,
) -> _MetadataSnapshot:
    values: dict[str, set[str]] = defaultdict(set)
    assessed: set[str] = set()
    scopes: set[str] = set()
    relevant_results: list[ToolResult] = []
    for execution in sources.successful:
        results = catalog.results_for(observation_id, (execution,))
        if execution.capability is ToolCapability.READ_METADATA:
            scopes.add("CALIBRE_CANDIDATES")
            assessed.update(_CALIBRE_ASSESSED_FIELDS)
            candidates = tuple(
                result
                for result in results
                if result.result_type == EBOOK_METADATA_CANDIDATE_RESULT
            )
            relevant_results.extend(candidates)
            for field, field_values in _calibre_metadata_values(candidates).items():
                values[field].update(field_values)
                assessed.add(field)
        elif execution.capability is ToolCapability.TECHNICAL_METADATA:
            scopes.add("PDF_METADATA")
            assessed.update(_PDF_ASSESSED_FIELDS)
            selected = tuple(
                result
                for result in results
                if result.result_type == "poppler_pdf_metadata"
                and result.key in {"title", "author"}
            )
            relevant_results.extend(selected)
            for result in selected:
                field = "contributor.author" if result.key == "author" else "title"
                values[field].add(result.value)
    return _MetadataSnapshot(
        values={field: frozenset(items) for field, items in values.items()},
        assessed_fields=frozenset(assessed),
        scopes=frozenset(scopes),
        evidence_ids=_entity_ids(result.id for result in relevant_results),
        execution_ids=_execution_ids(sources.successful),
        partial=sources.has_unusable_latest or len(scopes) > 1,
    )


def _calibre_metadata_values(
    results: tuple[ToolResult, ...],
) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    grouped: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for result in results:
        if result.key in _METADATA_DIRECT_FIELDS:
            values[result.key].add(result.value)
            continue
        parts = result.key.split(".")
        if len(parts) < 3 or parts[0] not in {"contributor", "identifier", "series"}:
            continue
        grouped[(parts[0], parts[1])][parts[2]].add(result.value)

    for (kind, _index), fields in grouped.items():
        if kind == "contributor":
            roles = fields.get("role", set()) or {"untyped"}
            for role in roles:
                for name in fields.get("name", set()):
                    values[f"contributor.{role}"].add(name)
        elif kind == "identifier":
            namespaces = fields.get("namespace", set()) or {"untyped"}
            for namespace in namespaces:
                if namespace.strip().lower() in _IGNORED_IDENTIFIER_NAMESPACES:
                    continue
                for value in fields.get("value", set()):
                    values[f"identifier.{namespace}"].add(value)
        elif kind == "series":
            names = fields.get("name", set()) or {""}
            positions = fields.get("position", set()) or {""}
            for name in names:
                for position in positions:
                    values["series"].add(f"{name}\0{position}")
    return {field: frozenset(items) for field, items in values.items()}


def _structure_dimension(
    catalog: _EvidenceCatalog,
    left: FileObservation,
    right: FileObservation,
    left_format: str,
    right_format: str,
) -> EbookComparisonDimension:
    if left_format != "EPUB" or right_format != "EPUB":
        return _not_applicable(EbookComparisonDimensionName.STRUCTURE)
    capabilities = frozenset({ToolCapability.STRUCTURAL_VALIDATION})
    left_sources = catalog.latest(left.id, capabilities)
    right_sources = catalog.latest(right.id, capabilities)
    left_results = _structure_results(
        catalog.results_for(left.id, left_sources.successful)
    )
    right_results = _structure_results(
        catalog.results_for(right.id, right_sources.successful)
    )
    execution_ids = _execution_ids(
        left_sources.successful + right_sources.successful
    )
    if not _STRUCTURE_REQUIRED_KEYS.issubset(left_results) or not (
        _STRUCTURE_REQUIRED_KEYS.issubset(right_results)
    ):
        return _dimension(
            EbookComparisonDimensionName.STRUCTURE,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", "STRUCTURE_EVIDENCE_MISSING"),),
            _structure_evidence_ids(catalog, left.id, left_sources.successful),
            _structure_evidence_ids(catalog, right.id, right_sources.successful),
            execution_ids,
        )
    fields = set(left_results) | set(right_results)
    different = tuple(
        sorted(
            field
            for field in fields
            if left_results.get(field, frozenset())
            != right_results.get(field, frozenset())
        )
    )
    return _dimension(
        EbookComparisonDimensionName.STRUCTURE,
        EbookComparisonState.DIFFERENT if different else EbookComparisonState.SAME,
        (
            EbookComparisonCoverage.PARTIAL
            if left_sources.has_unusable_latest or right_sources.has_unusable_latest
            else EbookComparisonCoverage.COMPLETE
        ),
        (
            ("different_field_count", str(len(different))),
            ("different_fields", _field_list(different)),
        ),
        _structure_evidence_ids(catalog, left.id, left_sources.successful),
        _structure_evidence_ids(catalog, right.id, right_sources.successful),
        execution_ids,
    )


def _structure_results(results: tuple[ToolResult, ...]) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for result in results:
        if result.key in _STRUCTURE_REQUIRED_KEYS or result.key.startswith("diagnostic."):
            values[result.key].add(result.value)
    return {field: frozenset(items) for field, items in values.items()}


def _structure_evidence_ids(
    catalog: _EvidenceCatalog,
    observation_id: EntityId,
    executions: tuple[ToolExecution, ...],
) -> tuple[EntityId, ...]:
    return _entity_ids(
        result.id
        for result in catalog.results_for(observation_id, executions)
        if result.key in _STRUCTURE_REQUIRED_KEYS or result.key.startswith("diagnostic.")
    )


def _cover_dimension(
    catalog: _EvidenceCatalog,
    left: FileObservation,
    right: FileObservation,
    left_format: str,
    right_format: str,
) -> EbookComparisonDimension:
    if left_format not in _CALIBRE_FORMATS or right_format not in _CALIBRE_FORMATS:
        return _not_applicable(EbookComparisonDimensionName.COVER)
    capabilities = frozenset({ToolCapability.FINGERPRINT})
    left_sources = catalog.latest(left.id, capabilities)
    right_sources = catalog.latest(right.id, capabilities)
    left_results = tuple(
        result
        for result in catalog.results_for(left.id, left_sources.successful)
        if result.key == "cover_status"
    )
    right_results = tuple(
        result
        for result in catalog.results_for(right.id, right_sources.successful)
        if result.key == "cover_status"
    )
    left_statuses = {result.value for result in left_results}
    right_statuses = {result.value for result in right_results}
    execution_ids = _execution_ids(
        left_sources.successful + right_sources.successful
    )
    left_evidence = _entity_ids(result.id for result in left_results)
    right_evidence = _entity_ids(result.id for result in right_results)
    if len(left_statuses) != 1 or len(right_statuses) != 1:
        return _dimension(
            EbookComparisonDimensionName.COVER,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", "COVER_STATUS_EVIDENCE_MISSING_OR_CONFLICTING"),),
            left_evidence,
            right_evidence,
            execution_ids,
        )
    left_status = next(iter(left_statuses))
    right_status = next(iter(right_statuses))
    allowed = {"COVER_EXTRACTED", "NO_EMBEDDED_COVER"}
    if left_status not in allowed or right_status not in allowed:
        return _dimension(
            EbookComparisonDimensionName.COVER,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.NONE,
            (("reason", "COVER_STATUS_EVIDENCE_INVALID"),),
            left_evidence,
            right_evidence,
            execution_ids,
        )
    partial = left_sources.has_unusable_latest or right_sources.has_unusable_latest
    if left_status != right_status:
        return _dimension(
            EbookComparisonDimensionName.COVER,
            EbookComparisonState.DIFFERENT,
            EbookComparisonCoverage.PARTIAL if partial else EbookComparisonCoverage.COMPLETE,
            (("comparison_basis", "COVER_PRESENCE"),),
            left_evidence,
            right_evidence,
            execution_ids,
        )
    if left_status == "NO_EMBEDDED_COVER":
        return _dimension(
            EbookComparisonDimensionName.COVER,
            EbookComparisonState.SAME,
            EbookComparisonCoverage.PARTIAL if partial else EbookComparisonCoverage.COMPLETE,
            (("comparison_basis", "COVER_PRESENCE"),),
            left_evidence,
            right_evidence,
            execution_ids,
        )

    left_fingerprints = catalog.fingerprints_for(
        left.id,
        COVER_FINGERPRINT_KIND,
        left_sources.successful,
    )
    right_fingerprints = catalog.fingerprints_for(
        right.id,
        COVER_FINGERPRINT_KIND,
        right_sources.successful,
    )
    compared = _fingerprint_dimension(
        EbookComparisonDimensionName.COVER,
        left_fingerprints,
        right_fingerprints,
        execution_ids,
        partial=partial,
        missing_reason="COVER_FINGERPRINT_MISSING",
    )
    if compared.state not in {EbookComparisonState.SAME, EbookComparisonState.DIFFERENT}:
        return EbookComparisonDimension(
            name=compared.name,
            state=compared.state,
            coverage=compared.coverage,
            facts=compared.facts,
            left_evidence_ids=_entity_ids(
                (*left_evidence, *compared.left_evidence_ids)
            ),
            right_evidence_ids=_entity_ids(
                (*right_evidence, *compared.right_evidence_ids)
            ),
            source_execution_ids=compared.source_execution_ids,
        )
    left_profiles = _fingerprint_profiles(left_fingerprints)
    right_profiles = _fingerprint_profiles(right_fingerprints)
    common_profile = next(iter(set(left_profiles) & set(right_profiles)))
    left_hash = next(iter(left_profiles[common_profile]))
    right_hash = next(iter(right_profiles[common_profile]))
    try:
        if len(left_hash) != 16 or len(right_hash) != 16:
            raise ValueError
        distance = (int(left_hash, 16) ^ int(right_hash, 16)).bit_count()
    except ValueError:
        return _dimension(
            EbookComparisonDimensionName.COVER,
            EbookComparisonState.INDETERMINATE,
            EbookComparisonCoverage.PARTIAL,
            (("reason", "COVER_FINGERPRINT_INVALID"),),
            _entity_ids((*left_evidence, *(value.id for value in left_fingerprints))),
            _entity_ids((*right_evidence, *(value.id for value in right_fingerprints))),
            execution_ids,
        )
    return EbookComparisonDimension(
        name=compared.name,
        state=compared.state,
        coverage=compared.coverage,
        facts=compared.facts + (("dhash_distance", str(distance)),),
        left_evidence_ids=_entity_ids(
            (*left_evidence, *compared.left_evidence_ids)
        ),
        right_evidence_ids=_entity_ids(
            (*right_evidence, *compared.right_evidence_ids)
        ),
        source_execution_ids=compared.source_execution_ids,
    )


def _fingerprint_profiles(
    fingerprints: tuple[Fingerprint, ...],
) -> dict[tuple[str, str], frozenset[str]]:
    profiles: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fingerprint in fingerprints:
        profiles[(fingerprint.algorithm, fingerprint.algorithm_version)].add(
            fingerprint.value
        )
    return {profile: frozenset(values) for profile, values in profiles.items()}


def _dimension(
    name: EbookComparisonDimensionName,
    state: EbookComparisonState,
    coverage: EbookComparisonCoverage,
    facts: tuple[tuple[str, str], ...],
    left_evidence_ids: tuple[EntityId, ...],
    right_evidence_ids: tuple[EntityId, ...],
    execution_ids: tuple[EntityId, ...],
) -> EbookComparisonDimension:
    return EbookComparisonDimension(
        name=name,
        state=state,
        coverage=coverage,
        facts=facts,
        left_evidence_ids=left_evidence_ids,
        right_evidence_ids=right_evidence_ids,
        source_execution_ids=execution_ids,
    )


def _not_applicable(name: EbookComparisonDimensionName) -> EbookComparisonDimension:
    return EbookComparisonDimension(
        name=name,
        state=EbookComparisonState.NOT_APPLICABLE,
        coverage=EbookComparisonCoverage.NOT_APPLICABLE,
    )


def _field_list(fields: tuple[str, ...]) -> str:
    selected = fields[:_MAX_LISTED_FIELDS]
    value = ",".join(selected) if selected else "none"
    if len(fields) > len(selected):
        value += f",...(+{len(fields) - len(selected)})"
    return value[:_MAX_FACT_VALUE_CHARS]


def _execution_ids(executions: tuple[ToolExecution, ...]) -> tuple[EntityId, ...]:
    return _entity_ids(execution.id for execution in executions)


def _entity_ids(values: Iterable[EntityId]) -> tuple[EntityId, ...]:
    return tuple(sorted(set(values), key=str))
