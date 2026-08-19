"""Focused precondition-builder tests for S-EB08-03."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionInputs,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationPreconditionCode,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewState,
    build_consolidation_file_preconditions,
)
from foliotone.consolidation.contracts import ConsolidationReviewSnapshot
from foliotone.core import (
    EntityId,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ReviewCandidateKind,
    ReviewType,
)

_FILE_IDS = (1, 2)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_SIZE_BYTES = 12_288
_MODIFIED_AT = datetime(2026, 8, 19, 12, 34, 56, 654321, tzinfo=UTC)
_OBSERVED_AT = datetime(2026, 8, 19, 12, 34, 57, 123456, tzinfo=UTC)


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def _dependencies(role: ConsolidationFileRole) -> tuple[ConsolidationDependency, ...]:
    base = _FILE_IDS[0] if role is ConsolidationFileRole.KEEPER else _FILE_IDS[1]
    return (
        ConsolidationDependency(
            role,
            ConsolidationDependencyKind.CALIBRE,
            ConsolidationDependencyState.UNKNOWN,
            _HASH_A,
            "CALIBRE_SNAPSHOT",
            _id(100 + base),
        ),
        ConsolidationDependency(
            role,
            ConsolidationDependencyKind.SIDECAR,
            ConsolidationDependencyState.UNKNOWN,
            _HASH_A,
            "SIDECAR_SNAPSHOT",
            _id(200 + base),
        ),
        ConsolidationDependency(
            role,
            ConsolidationDependencyKind.ARCHIVE,
            ConsolidationDependencyState.KNOWN_PRESENT,
            _HASH_B,
            "ARCHIVE_SNAPSHOT",
            _id(300 + base),
        ),
    )


def _review(role: ConsolidationFileRole) -> ConsolidationReviewSnapshot:
    base = 1 if role is ConsolidationFileRole.KEEPER else 2
    if role is ConsolidationFileRole.KEEPER:
        review_type = ReviewType.KEEP_PREFERENCE
        candidate_kind = ReviewCandidateKind.KEEP_PREFERENCE
        producer_name = "ebook-keep-preference"
        compatibility = CONSOLIDATION_KEEP_PREFERENCE_DECISION
    else:
        review_type = ReviewType.CONSOLIDATION_CANDIDATE
        candidate_kind = ReviewCandidateKind.CONSOLIDATION_CANDIDATE
        producer_name = "ebook-consolidation-candidate"
        compatibility = CONSOLIDATION_CANDIDATE_DECISION
    return ConsolidationReviewSnapshot(
        review_type=review_type,
        state=ConsolidationReviewState.ACCEPTED,
        evidence_fingerprint=_HASH_A,
        candidate_set_fingerprint=_HASH_B,
        candidate_kind=candidate_kind,
        producer_name=producer_name,
        decision_compatibility_version=compatibility,
        review_item_id=_id(1000 + base),
        decision_id=_id(2000 + base),
        decision_sequence_no=1,
    )


def _inputs(role: ConsolidationFileRole) -> ConsolidationFilePreconditionInputs:
    base = 1 if role is ConsolidationFileRole.KEEPER else 2
    file_id = _id(base)
    scan_root_id = _id(10 + base)
    source_scan_run_id = _id(20 + base)
    observation_id = _id(30 + base)
    endpoint = ConsolidationFileEndpoint(
            role=role,
            file_id=file_id,
            observation_id=observation_id,
            scan_root_id=scan_root_id,
            source_scan_run_id=source_scan_run_id,
            expected_presence_state=PresenceState.PRESENT,
            expected_full_sha256=_HASH_A,
            expected_size_bytes=_SIZE_BYTES,
            expected_modified_at=_MODIFIED_AT,
            expected_observed_at=_OBSERVED_AT,
            format_label="EPUB",
        )
    return ConsolidationFilePreconditionInputs(
        file_endpoint=endpoint,
        file_record=FileRecord(
            id=file_id,
            scan_root_id=scan_root_id,
            relative_path="Synthetic/Book.epub",
            size_bytes=_SIZE_BYTES,
            modified_at=_MODIFIED_AT,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=_MODIFIED_AT,
            last_seen_at=_MODIFIED_AT,
        ),
        file_observation=FileObservation(
            id=observation_id,
            file_id=file_id,
            scan_run_id=source_scan_run_id,
            relative_path="Synthetic/Book.epub",
            size_bytes=_SIZE_BYTES,
            modified_at=_MODIFIED_AT,
            observed_at=_OBSERVED_AT,
        ),
        quality_evidence=ConsolidationQualityEvidenceSnapshot(
            id=_id(40 + base),
            role=role,
            collection_run_id=_id(50 + base),
            collection_item_id=_id(60 + base),
            observation_id=observation_id,
            scan_root_id=scan_root_id,
            source_scan_run_id=source_scan_run_id,
            collection_profile=CONSOLIDATION_COLLECTION_PROFILE,
            analysis_profile=CONSOLIDATION_ANALYSIS_PROFILE,
            quality_profile="ebook-quality/v1",
            format_label=endpoint.format_label,
            assessment_fingerprint=_HASH_A,
        ),
        dependencies=_dependencies(role),
        review_approval=_review(role),
    )


def _find_precondition(
    preconditions: tuple[ConsolidationFilePreconditionSnapshot, ...],
    code: ConsolidationPreconditionCode,
) -> ConsolidationFilePreconditionSnapshot:
    return next(item for item in preconditions if item.code is code)


FILE_CHECK_CODES = (
    ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
    ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
    ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
    ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
    ConsolidationPreconditionCode.SIZE_MATCHES,
    ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
)


DEPENDENCY_PRECONDITION_CASES = (
    (
        ConsolidationDependencyKind.CALIBRE,
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
    ),
    (
        ConsolidationDependencyKind.SIDECAR,
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
    ),
    (
        ConsolidationDependencyKind.ARCHIVE,
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
    ),
)

FILE_MATERIAL_FIELD_CASES = (
    ("expected_full_sha256", _HASH_A),
    ("expected_size_bytes", _SIZE_BYTES),
    ("expected_presence_state", PresenceState.PRESENT),
    ("expected_modified_at", _MODIFIED_AT),
    ("expected_observed_at", _OBSERVED_AT),
)

@pytest.mark.parametrize("role", ConsolidationFileRole)
def test_builder_generates_expected_codes_and_generation_fields(
    role: ConsolidationFileRole,
) -> None:
    source = _inputs(role)
    preconditions = build_consolidation_file_preconditions(source)
    expected_codes: tuple[ConsolidationPreconditionCode, ...] = (
        *(FILE_CHECK_CODES),
        *(code for _, code in DEPENDENCY_PRECONDITION_CASES),
        ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
    )
    if role is ConsolidationFileRole.KEEPER:
        expected_codes = (
            *expected_codes,
            ConsolidationPreconditionCode.KEEPER_READABLE,
        )
    expected_codes = tuple(sorted(set(expected_codes), key=lambda item: item.value))
    assert tuple(item.code for item in preconditions) == expected_codes
    assert len(preconditions) == len(expected_codes)
    assert all(
        item.file_role is role
        for item in preconditions
    )
    assert {
        item.expected_scan_root_id for item in preconditions
    } == {source.file_endpoint.scan_root_id}
    assert {
        item.expected_scan_run_id for item in preconditions
    } == {source.file_endpoint.source_scan_run_id}
    assert {
        item.expected_observation_id for item in preconditions
    } == {source.file_observation.id}


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize(
    ("code", "field", "expected"),
    tuple(
        (code, field, value)
        for code in FILE_CHECK_CODES
        for field, value in FILE_MATERIAL_FIELD_CASES
    ),
)
def test_builder_binds_file_material_fields(
    role: ConsolidationFileRole,
    code: ConsolidationPreconditionCode,
    field: str,
    expected: object,
) -> None:
    preconditions = build_consolidation_file_preconditions(_inputs(role))
    precondition = _find_precondition(preconditions, code)
    assert getattr(precondition, field) == expected


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize(("kind", "code"), DEPENDENCY_PRECONDITION_CASES)
def test_builder_binds_dependency_fields(
    role: ConsolidationFileRole,
    kind: ConsolidationDependencyKind,
    code: ConsolidationPreconditionCode,
) -> None:
    source = _inputs(role)
    preconditions = build_consolidation_file_preconditions(source)
    precondition = _find_precondition(preconditions, code)
    dependency = next(item for item in source.dependencies if item.kind is kind)
    assert precondition.dependency_kind is kind
    assert precondition.dependency_state is dependency.state
    assert precondition.dependency_fingerprint == dependency.material_fingerprint
    assert precondition.dependency_snapshot_kind == dependency.snapshot_kind
    assert precondition.dependency_snapshot_id == dependency.snapshot_id


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize(("kind", "code"), DEPENDENCY_PRECONDITION_CASES)
def test_builder_preserves_known_none_without_snapshot(
    role: ConsolidationFileRole,
    kind: ConsolidationDependencyKind,
    code: ConsolidationPreconditionCode,
) -> None:
    source = _inputs(role)
    dependencies = tuple(
        replace(
            dependency,
            state=ConsolidationDependencyState.KNOWN_NONE,
            snapshot_kind=None,
            snapshot_id=None,
        )
        if dependency.kind is kind
        else dependency
        for dependency in source.dependencies
    )
    precondition = _find_precondition(
        build_consolidation_file_preconditions(
            replace(source, dependencies=dependencies)
        ),
        code,
    )
    assert precondition.dependency_state is ConsolidationDependencyState.KNOWN_NONE
    assert precondition.dependency_snapshot_kind is None
    assert precondition.dependency_snapshot_id is None


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize(("field", "attribute"), (
    ("review_item_id", "review_item_id"),
    ("review_decision_id", "decision_id"),
    ("review_decision_sequence_no", "decision_sequence_no"),
    (
        "review_decision_compatibility_version",
        "decision_compatibility_version",
    ),
    ("review_evidence_fingerprint", "evidence_fingerprint"),
    ("review_candidate_set_fingerprint", "candidate_set_fingerprint"),
))
def test_builder_binds_review_fields(
    role: ConsolidationFileRole,
    field: str,
    attribute: str,
) -> None:
    source = _inputs(role)
    preconditions = build_consolidation_file_preconditions(source)
    precondition = _find_precondition(
        preconditions,
        ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
    )
    assert getattr(precondition, field) == getattr(source.review_approval, attribute)


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize("mutator", (
    lambda source: replace(
        source,
        file_endpoint=replace(source.file_endpoint, file_id=_id(10_000)),
    ),
    lambda source: replace(
        source,
        file_observation=replace(source.file_observation, size_bytes=0),
    ),
    lambda source: replace(
        source,
        file_observation=replace(
            source.file_observation, modified_at=_MODIFIED_AT.replace(year=2024)
        ),
    ),
    lambda source: replace(
        source,
        file_record=replace(source.file_record, modified_at=_MODIFIED_AT.replace(year=2024)),
    ),
    lambda source: replace(
        source,
        file_observation=replace(source.file_observation, observed_at=_MODIFIED_AT),
    ),
))
def test_builder_rejects_inconsistent_inputs(
    role: ConsolidationFileRole,
    mutator,
) -> None:
    source = _inputs(role)
    with pytest.raises(ValueError):
        build_consolidation_file_preconditions(mutator(source))


@pytest.mark.parametrize("role", ConsolidationFileRole)
@pytest.mark.parametrize(
    "kind",
    tuple(kind for kind, _ in DEPENDENCY_PRECONDITION_CASES),
)
def test_builder_rejects_missing_dependency(
    role: ConsolidationFileRole,
    kind: ConsolidationDependencyKind,
) -> None:
    source = _inputs(role)
    dependencies = tuple(dep for dep in source.dependencies if dep.kind is not kind)
    with pytest.raises(ValueError):
        build_consolidation_file_preconditions(replace(source, dependencies=dependencies))


def test_builder_rejects_missing_review_approval() -> None:
    source = _inputs(ConsolidationFileRole.KEEPER)
    source = replace(
        source,
        review_approval=replace(
            source.review_approval,
            state=ConsolidationReviewState.PENDING,
            review_item_id=None,
            decision_id=None,
            decision_sequence_no=None,
        ),
    )
    with pytest.raises(ValueError):
        build_consolidation_file_preconditions(source)


def test_builder_rejects_rejected_or_wrong_role_review() -> None:
    source = _inputs(ConsolidationFileRole.KEEPER)
    with pytest.raises(ValueError, match="not compatible"):
        build_consolidation_file_preconditions(
            replace(
                source,
                review_approval=replace(
                    source.review_approval,
                    state=ConsolidationReviewState.REJECTED,
                ),
            )
        )
    with pytest.raises(ValueError, match="not compatible"):
        build_consolidation_file_preconditions(
            replace(
                source,
                review_approval=_review(ConsolidationFileRole.CANDIDATE),
            )
        )


@pytest.mark.parametrize("role", ConsolidationFileRole)
def test_builder_rejects_foreign_quality_snapshot(role: ConsolidationFileRole) -> None:
    source = _inputs(role)
    with pytest.raises(ValueError, match="quality evidence"):
        build_consolidation_file_preconditions(
            replace(
                source,
                quality_evidence=replace(
                    source.quality_evidence,
                    observation_id=_id(99_999),
                ),
            )
        )


@pytest.mark.parametrize("role", ConsolidationFileRole)
def test_builder_has_no_side_effects(role: ConsolidationFileRole) -> None:
    source = _inputs(role)
    snapshot = (
        source.file_endpoint,
        source.file_record,
        source.file_observation,
        source.quality_evidence,
        source.dependencies,
        source.review_approval,
    )
    _ = build_consolidation_file_preconditions(source)
    assert snapshot == (
        source.file_endpoint,
        source.file_record,
        source.file_observation,
        source.quality_evidence,
        source.dependencies,
        source.review_approval,
    )
