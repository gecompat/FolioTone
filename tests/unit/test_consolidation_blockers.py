"""Focused synthetic tests for S-EB08-04 hard blockers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationBlockerCode,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationHardBlockerInputs,
    ConsolidationIdentitySnapshot,
    ConsolidationPreconditionCode,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewState,
    build_consolidation_blockers,
)
from foliotone.consolidation.contracts import ConsolidationReviewSnapshot
from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    PresenceState,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
)

_HASH = "a" * 64
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def _identity(status: MatchStatus = MatchStatus.CONFIRMED) -> ConsolidationIdentitySnapshot:
    return ConsolidationIdentitySnapshot(
        relation_candidate_id=_id(1),
        relation_type=RelationType.EXACT_DUPLICATE,
        left_kind=EntityKind.FILE,
        right_kind=EntityKind.FILE,
        left_file_id=_id(2),
        right_file_id=_id(3),
        scan_root_id=_id(4),
        source_scan_run_id=_id(5),
        status=status,
        matcher_version="synthetic-matcher/v1",
        decision_compatibility_version="synthetic-decision/v1",
        evidence_fingerprint=_HASH,
        candidate_set_fingerprint="b" * 64,
    )


def _quality(role: ConsolidationFileRole) -> ConsolidationQualityEvidenceSnapshot:
    return ConsolidationQualityEvidenceSnapshot(
        id=_id(10 if role is ConsolidationFileRole.KEEPER else 11),
        role=role,
        collection_run_id=_id(12),
        collection_item_id=_id(13 if role is ConsolidationFileRole.KEEPER else 14),
        observation_id=_id(15 if role is ConsolidationFileRole.KEEPER else 16),
        scan_root_id=_id(4),
        source_scan_run_id=_id(5),
        collection_profile="ebook-collection-analysis/v1",
        analysis_profile="ebook-analysis-workflow/v3",
        quality_profile="ebook-quality/v1",
        format_label="EPUB",
        assessment_fingerprint=_HASH,
    )


def _review(
    review_type: ReviewType,
    state: ConsolidationReviewState,
) -> ConsolidationReviewSnapshot:
    is_keep = review_type is ReviewType.KEEP_PREFERENCE
    return ConsolidationReviewSnapshot(
        review_type=review_type,
        state=state,
        evidence_fingerprint=_HASH,
        candidate_set_fingerprint="b" * 64,
        candidate_kind=(
            ReviewCandidateKind.KEEP_PREFERENCE
            if is_keep
            else ReviewCandidateKind.CONSOLIDATION_CANDIDATE
        ),
        producer_name=("ebook-keep-preference" if is_keep else "ebook-consolidation-candidate"),
        decision_compatibility_version=(
            CONSOLIDATION_KEEP_PREFERENCE_DECISION
            if is_keep
            else CONSOLIDATION_CANDIDATE_DECISION
        ),
        review_item_id=_id(20 if is_keep else 21),
        decision_id=(
            _id(22 if is_keep else 23)
            if state in {ConsolidationReviewState.ACCEPTED, ConsolidationReviewState.REJECTED}
            else None
        ),
        decision_sequence_no=(
            1
            if state in {ConsolidationReviewState.ACCEPTED, ConsolidationReviewState.REJECTED}
            else None
        ),
    )


def _dependencies(
    role: ConsolidationFileRole,
    state: ConsolidationDependencyState = ConsolidationDependencyState.KNOWN_NONE,
) -> tuple[ConsolidationDependency, ...]:
    return tuple(
        ConsolidationDependency(
            file_role=role,
            kind=kind,
            state=state,
            material_fingerprint=_HASH,
            snapshot_kind=(
                None
                if state is ConsolidationDependencyState.KNOWN_NONE
                else "snapshot/v1"
            ),
            snapshot_id=(
                None
                if state is ConsolidationDependencyState.KNOWN_NONE
                else _id(30 + index)
            ),
        )
        for index, kind in enumerate(ConsolidationDependencyKind)
    )


def _evidence() -> tuple[ConsolidationEvidenceReference, ...]:
    return (
        ConsolidationEvidenceReference(
            kind=ConsolidationEvidenceKind.FINGERPRINT,
            ref_id="synthetic-evidence-b",
            role=ConsolidationEvidenceRole.IDENTITY,
            material_fingerprint="b" * 64,
        ),
        ConsolidationEvidenceReference(
            kind=ConsolidationEvidenceKind.FINGERPRINT,
            ref_id="synthetic-evidence-a",
            role=ConsolidationEvidenceRole.IDENTITY,
            material_fingerprint=_HASH,
        ),
    )


def _preconditions() -> tuple[ConsolidationFilePreconditionSnapshot, ...]:
    base_codes = (
        ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
        ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
        ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
        ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
        ConsolidationPreconditionCode.SIZE_MATCHES,
        ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
    )
    relationship_codes = (
        (
            ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
            ConsolidationDependencyKind.CALIBRE,
        ),
        (
            ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
            ConsolidationDependencyKind.SIDECAR,
        ),
        (
            ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
            ConsolidationDependencyKind.ARCHIVE,
        ),
    )
    result: list[ConsolidationFilePreconditionSnapshot] = []
    for role in ConsolidationFileRole:
        common = {
            "file_role": role,
            "expected_file_id": _id(2 if role is ConsolidationFileRole.KEEPER else 3),
            "expected_observation_id": _id(
                15 if role is ConsolidationFileRole.KEEPER else 16
            ),
            "expected_scan_root_id": _id(4),
            "expected_scan_run_id": _id(5),
            "expected_presence_state": PresenceState.PRESENT,
            "expected_full_sha256": _HASH,
            "expected_size_bytes": 42,
            "expected_modified_at": _NOW,
            "expected_observed_at": _NOW,
        }
        for code in base_codes:
            result.append(ConsolidationFilePreconditionSnapshot(code=code, **common))
        if role is ConsolidationFileRole.KEEPER:
            result.append(
                ConsolidationFilePreconditionSnapshot(
                    code=ConsolidationPreconditionCode.KEEPER_READABLE,
                    **common,
                )
            )
        for code, kind in relationship_codes:
            result.append(
                ConsolidationFilePreconditionSnapshot(
                    code=code,
                    dependency_kind=kind,
                    dependency_state=ConsolidationDependencyState.KNOWN_NONE,
                    dependency_fingerprint=_HASH,
                    **common,
                )
            )
        result.append(
            ConsolidationFilePreconditionSnapshot(
                code=ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
                review_item_id=_id(20 if role is ConsolidationFileRole.KEEPER else 21),
                review_decision_id=_id(22 if role is ConsolidationFileRole.KEEPER else 23),
                review_decision_sequence_no=1,
                review_decision_compatibility_version=(
                    CONSOLIDATION_KEEP_PREFERENCE_DECISION
                    if role is ConsolidationFileRole.KEEPER
                    else CONSOLIDATION_CANDIDATE_DECISION
                ),
                review_evidence_fingerprint=_HASH,
                review_candidate_set_fingerprint="b" * 64,
                **common,
            )
        )
    return tuple(result)


def _base() -> ConsolidationHardBlockerInputs:
    return ConsolidationHardBlockerInputs(
        identity=_identity(),
        quality_evidence=(
            _quality(ConsolidationFileRole.KEEPER),
            _quality(ConsolidationFileRole.CANDIDATE),
        ),
        dependencies=(
            *_dependencies(ConsolidationFileRole.KEEPER),
            *_dependencies(ConsolidationFileRole.CANDIDATE),
        ),
        required_reviews=(
            _review(ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.ACCEPTED),
            _review(ReviewType.CONSOLIDATION_CANDIDATE, ConsolidationReviewState.ACCEPTED),
        ),
        preconditions=_preconditions(),
        evidence_refs=_evidence(),
    )


def _codes(inputs: ConsolidationHardBlockerInputs) -> tuple[ConsolidationBlockerCode, ...]:
    return tuple(blocker.code for blocker in build_consolidation_blockers(inputs))


def test_complete_inputs_have_no_hard_blockers_and_evidence_is_canonical() -> None:
    assert _codes(_base()) == ()
    blockers = build_consolidation_blockers(
        replace(_base(), protected_source_root=True)
    )
    assert blockers[0].code is ConsolidationBlockerCode.PROTECTED_SOURCE_ROOT
    assert tuple(ref.ref_id for ref in blockers[0].evidence_refs) == (
        "synthetic-evidence-a",
        "synthetic-evidence-b",
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("lineage_matches", False, ConsolidationBlockerCode.LINEAGE_MISMATCH),
        ("source_scan_run_completed", False, ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED),
        ("file_sha256_equal", False, ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE),
        ("quality_evidence", (), ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE),
        ("preconditions", (), ConsolidationBlockerCode.PRECONDITION_INCOMPLETE),
    ),
)
def test_each_hard_constraint_is_visible(
    field: str,
    value: object,
    expected: ConsolidationBlockerCode,
) -> None:
    assert expected in _codes(replace(_base(), **{field: value}))


def test_identity_actionability_and_confirmation_are_distinct() -> None:
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE in _codes(
        replace(_base(), identity=None)
    )
    assert ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED in _codes(
        replace(_base(), identity=_identity(MatchStatus.REVIEW_REQUIRED))
    )
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE in _codes(
        replace(
            _base(),
            identity=replace(
                _identity(),
                relation_type=RelationType.SAME_EDITION,
            ),
        )
    )


def test_missing_and_rejected_reviews_block_but_pending_and_deferred_do_not() -> None:
    missing = _codes(replace(_base(), required_reviews=()))
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING in missing
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING in missing

    rejected = _codes(
        replace(
            _base(),
            required_reviews=(
                _review(ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.REJECTED),
                _review(ReviewType.CONSOLIDATION_CANDIDATE, ConsolidationReviewState.REJECTED),
            ),
        )
    )
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_REJECTED in rejected
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED in rejected

    for state in (ConsolidationReviewState.PENDING, ConsolidationReviewState.DEFERRED):
        reviews = (
            _review(ReviewType.KEEP_PREFERENCE, state),
            _review(ReviewType.CONSOLIDATION_CANDIDATE, state),
        )
        assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_REJECTED not in _codes(
            replace(_base(), required_reviews=reviews)
        )

    for state in (ConsolidationReviewState.MISSING, ConsolidationReviewState.STALE):
        reviews = (
            _review(ReviewType.KEEP_PREFERENCE, state),
            _review(ReviewType.CONSOLIDATION_CANDIDATE, state),
        )
        codes = _codes(replace(_base(), required_reviews=reviews))
        assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING in codes
        assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING in codes


def test_duplicate_or_incompatible_reviews_cannot_hide_a_blocker() -> None:
    accepted = _review(ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.ACCEPTED)
    rejected = _review(ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.REJECTED)
    with pytest.raises(ValueError, match="unique review types"):
        replace(_base(), required_reviews=(accepted, rejected))

    incompatible = replace(accepted, producer_name="foreign-producer")
    codes = _codes(
        replace(
            _base(),
            required_reviews=(
                incompatible,
                _review(
                    ReviewType.CONSOLIDATION_CANDIDATE,
                    ConsolidationReviewState.ACCEPTED,
                ),
            ),
        )
    )
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING in codes


def test_dependency_rules_distinguish_unknown_and_candidate_presence() -> None:
    unknown_codes = _codes(replace(_base(), dependencies=()))
    assert unknown_codes.count(ConsolidationBlockerCode.CALIBRE_RELATIONSHIP_UNKNOWN) == 1
    assert unknown_codes.count(ConsolidationBlockerCode.SIDECAR_RELATIONSHIP_UNKNOWN) == 1
    assert unknown_codes.count(ConsolidationBlockerCode.ARCHIVE_RELATIONSHIP_UNKNOWN) == 1

    candidate_present = _dependencies(
        ConsolidationFileRole.CANDIDATE,
        ConsolidationDependencyState.KNOWN_PRESENT,
    )
    codes = _codes(
        replace(
            _base(),
            dependencies=(*_dependencies(ConsolidationFileRole.KEEPER), *candidate_present),
        )
    )
    assert ConsolidationBlockerCode.CALIBRE_OWNERSHIP_PRESENT in codes
    assert ConsolidationBlockerCode.SIDECAR_DEPENDENCY_PRESENT in codes
    assert ConsolidationBlockerCode.ARCHIVE_MEMBERSHIP_PRESENT in codes


def test_not_applicable_requires_an_adapter_bound_proof() -> None:
    unproven = tuple(
        replace(
            dependency,
            state=ConsolidationDependencyState.NOT_APPLICABLE,
        )
        for dependency in _dependencies(ConsolidationFileRole.CANDIDATE)
    )
    codes = _codes(
        replace(
            _base(),
            dependencies=(*_dependencies(ConsolidationFileRole.KEEPER), *unproven),
        )
    )
    assert ConsolidationBlockerCode.CALIBRE_RELATIONSHIP_UNKNOWN in codes
    assert ConsolidationBlockerCode.SIDECAR_RELATIONSHIP_UNKNOWN in codes
    assert ConsolidationBlockerCode.ARCHIVE_RELATIONSHIP_UNKNOWN in codes

    proven = _dependencies(
        ConsolidationFileRole.CANDIDATE,
        ConsolidationDependencyState.NOT_APPLICABLE,
    )
    proven_codes = _codes(
        replace(
            _base(),
            dependencies=(*_dependencies(ConsolidationFileRole.KEEPER), *proven),
        )
    )
    assert not {
        ConsolidationBlockerCode.CALIBRE_RELATIONSHIP_UNKNOWN,
        ConsolidationBlockerCode.SIDECAR_RELATIONSHIP_UNKNOWN,
        ConsolidationBlockerCode.ARCHIVE_RELATIONSHIP_UNKNOWN,
    }.intersection(proven_codes)


def test_foreign_quality_or_precondition_lineage_is_incomplete() -> None:
    foreign_quality = tuple(
        replace(item, source_scan_run_id=_id(99)) for item in _base().quality_evidence
    )
    assert ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE in _codes(
        replace(_base(), quality_evidence=foreign_quality)
    )

    foreign_preconditions = tuple(
        replace(item, expected_scan_run_id=_id(99)) for item in _base().preconditions
    )
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in _codes(
        replace(_base(), preconditions=foreign_preconditions)
    )


def test_role_preconditions_must_bind_one_coherent_endpoint_and_hash() -> None:
    mixed_endpoint = tuple(
        replace(item, expected_file_id=_id(3))
        if item.file_role is ConsolidationFileRole.KEEPER
        and item.code is ConsolidationPreconditionCode.SIZE_MATCHES
        else item
        for item in _base().preconditions
    )
    mixed_codes = _codes(replace(_base(), preconditions=mixed_endpoint))
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in mixed_codes
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE in mixed_codes

    different_hash = tuple(
        replace(item, expected_full_sha256="c" * 64)
        if item.file_role is ConsolidationFileRole.CANDIDATE
        else item
        for item in _base().preconditions
    )
    hash_codes = _codes(replace(_base(), preconditions=different_hash))
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE in hash_codes


def test_quality_observation_must_match_its_role_preconditions() -> None:
    foreign_observation = tuple(
        replace(item, observation_id=_id(99))
        if item.role is ConsolidationFileRole.CANDIDATE
        else item
        for item in _base().quality_evidence
    )
    assert ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE in _codes(
        replace(_base(), quality_evidence=foreign_observation)
    )


def test_preconditions_bind_the_exact_dependency_and_review_snapshots() -> None:
    foreign_dependency = tuple(
        replace(item, dependency_fingerprint="c" * 64)
        if item.file_role is ConsolidationFileRole.CANDIDATE
        and item.code
        is ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED
        else item
        for item in _base().preconditions
    )
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in _codes(
        replace(_base(), preconditions=foreign_dependency)
    )

    foreign_review = tuple(
        replace(item, review_decision_sequence_no=2)
        if item.file_role is ConsolidationFileRole.KEEPER
        and item.code is ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED
        else item
        for item in _base().preconditions
    )
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in _codes(
        replace(_base(), preconditions=foreign_review)
    )
