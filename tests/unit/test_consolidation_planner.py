"""Synthetic integration tests for S-EB08-07 consolidation planning."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationBlockerCode,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionInputs,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationIntentCode,
    ConsolidationPlannerInputs,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
    KeepPreferenceOutcome,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
    build_consolidation_plan,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    FileRecord,
    MatchStatus,
    MediaType,
    PresenceState,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
)

_HASH = "a" * 64
_NOW = datetime(2026, 8, 19, 13, 45, 0, tzinfo=UTC)


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def _identity() -> ConsolidationIdentitySnapshot:
    return ConsolidationIdentitySnapshot(
        relation_candidate_id=_id(10),
        relation_type=RelationType.EXACT_DUPLICATE,
        left_kind=EntityKind.FILE,
        right_kind=EntityKind.FILE,
        left_file_id=_id(1),
        right_file_id=_id(2),
        scan_root_id=_id(3),
        source_scan_run_id=_id(4),
        status=MatchStatus.CONFIRMED,
        matcher_version="synthetic-matcher/v1",
        decision_compatibility_version="synthetic-match/v1",
        evidence_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
    )


def _quality(role: ConsolidationFileRole) -> ConsolidationQualityEvidenceSnapshot:
    index = 11 if role is ConsolidationFileRole.KEEPER else 12
    return ConsolidationQualityEvidenceSnapshot(
        id=_id(20 + index),
        role=role,
        collection_run_id=_id(40 + index),
        collection_item_id=_id(60 + index),
        observation_id=_id(index),
        scan_root_id=_id(3),
        source_scan_run_id=_id(4),
        collection_profile=CONSOLIDATION_COLLECTION_PROFILE,
        analysis_profile=CONSOLIDATION_ANALYSIS_PROFILE,
        quality_profile="ebook-quality/v1",
        format_label="EPUB",
        assessment_fingerprint=("d" if role is ConsolidationFileRole.KEEPER else "e") * 64,
    )


def _preference(
    status: KeepPreferenceStatus = KeepPreferenceStatus.PREFERRED,
) -> KeepPreferenceOutcome:
    return KeepPreferenceOutcome(
        preference_id=_id(30),
        profile="ebook-keep-preference/v1",
        profile_version="1",
        left_file_id=_id(1),
        left_observation_id=_id(11),
        right_file_id=_id(2),
        right_observation_id=_id(12),
        status=status,
        keeper_file_id=_id(1) if status is KeepPreferenceStatus.PREFERRED else None,
        candidate_file_id=_id(2) if status is KeepPreferenceStatus.PREFERRED else None,
        reason_codes=(
            (KeepPreferenceReasonCode.FEWER_REVIEW_DIMENSIONS,)
            if status is KeepPreferenceStatus.PREFERRED
            else (KeepPreferenceReasonCode.TIED,)
        ),
        configuration_fingerprint="f" * 64,
        evidence_fingerprint="1" * 64,
        quality_evidence=(
            _quality(ConsolidationFileRole.KEEPER),
            _quality(ConsolidationFileRole.CANDIDATE),
        ),
        candidate_set_fingerprint="2" * 64,
    )


def _review(
    review_type: ReviewType,
    state: ConsolidationReviewState,
    evidence_fingerprint: str,
    candidate_set_fingerprint: str,
) -> ConsolidationReviewSnapshot:
    keep = review_type is ReviewType.KEEP_PREFERENCE
    return ConsolidationReviewSnapshot(
        review_type=review_type,
        state=state,
        evidence_fingerprint=evidence_fingerprint,
        candidate_set_fingerprint=candidate_set_fingerprint,
        candidate_kind=(
            ReviewCandidateKind.KEEP_PREFERENCE
            if keep
            else ReviewCandidateKind.CONSOLIDATION_CANDIDATE
        ),
        producer_name="ebook-keep-preference" if keep else "ebook-consolidation-candidate",
        decision_compatibility_version=(
            CONSOLIDATION_KEEP_PREFERENCE_DECISION if keep else CONSOLIDATION_CANDIDATE_DECISION
        ),
        review_item_id=_id(70 if keep else 71),
        decision_id=(
            _id(80 if keep else 81)
            if state in {ConsolidationReviewState.ACCEPTED, ConsolidationReviewState.REJECTED}
            else None
        ),
        decision_sequence_no=(
            1
            if state in {ConsolidationReviewState.ACCEPTED, ConsolidationReviewState.REJECTED}
            else None
        ),
    )


def _dependencies() -> tuple[ConsolidationDependency, ...]:
    return tuple(
        ConsolidationDependency(
            file_role=role,
            kind=kind,
            state=ConsolidationDependencyState.KNOWN_NONE,
            material_fingerprint=_HASH,
        )
        for role in ConsolidationFileRole
        for kind in ConsolidationDependencyKind
    )


def _precondition_input(
    role: ConsolidationFileRole,
    review: ConsolidationReviewSnapshot,
) -> ConsolidationFilePreconditionInputs:
    file_id = _id(1 if role is ConsolidationFileRole.KEEPER else 2)
    observation_id = _id(11 if role is ConsolidationFileRole.KEEPER else 12)
    endpoint = ConsolidationFileEndpoint(
        role=role,
        file_id=file_id,
        observation_id=observation_id,
        scan_root_id=_id(3),
        source_scan_run_id=_id(4),
        expected_presence_state=PresenceState.PRESENT,
        expected_full_sha256=_HASH,
        expected_size_bytes=123,
        expected_modified_at=_NOW,
        expected_observed_at=_NOW,
        format_label="EPUB",
    )
    return ConsolidationFilePreconditionInputs(
        file_endpoint=endpoint,
        file_record=FileRecord(
            id=file_id,
            scan_root_id=_id(3),
            relative_path="Synthetic/Book.epub",
            size_bytes=123,
            modified_at=_NOW,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        ),
        file_observation=FileObservation(
            id=observation_id,
            file_id=file_id,
            scan_run_id=_id(4),
            relative_path="Synthetic/Book.epub",
            size_bytes=123,
            modified_at=_NOW,
            observed_at=_NOW,
        ),
        quality_evidence=_quality(role),
        dependencies=tuple(item for item in _dependencies() if item.file_role is role),
        review_approval=review,
    )


def _inputs(
    *,
    preference: KeepPreferenceOutcome | None = None,
    reviews: tuple[ConsolidationReviewSnapshot, ...] | None = None,
    dependencies: tuple[ConsolidationDependency, ...] | None = None,
) -> ConsolidationPlannerInputs:
    preference = _preference() if preference is None else preference
    keep_review = _review(
        ReviewType.KEEP_PREFERENCE,
        ConsolidationReviewState.ACCEPTED,
        preference.evidence_fingerprint,
        preference.candidate_set_fingerprint,
    )
    return ConsolidationPlannerInputs(
        plan_id=_id(90),
        consolidation_candidate_id=_id(91),
        scan_root_id=_id(3),
        source_scan_run_id=_id(4),
        identity=_identity(),
        keep_preference=preference,
        dependencies=_dependencies() if dependencies is None else dependencies,
        required_reviews=(keep_review,) if reviews is None else reviews,
        precondition_inputs=(
            _precondition_input(ConsolidationFileRole.KEEPER, keep_review),
            _precondition_input(ConsolidationFileRole.CANDIDATE, keep_review),
        ),
    )


def _clock() -> datetime:
    return _NOW


def _candidate_review(
    inputs: ConsolidationPlannerInputs,
    state: ConsolidationReviewState,
) -> ConsolidationReviewSnapshot:
    provisional = build_consolidation_plan(inputs, clock=_clock)
    assert provisional.consolidation_candidate is not None
    candidate = provisional.consolidation_candidate
    return _review(
        ReviewType.CONSOLIDATION_CANDIDATE,
        state,
        candidate.evidence_fingerprint,
        candidate.candidate_set_fingerprint,
    )


def _with_candidate_review(
    inputs: ConsolidationPlannerInputs,
    state: ConsolidationReviewState,
) -> ConsolidationPlannerInputs:
    candidate_review = _candidate_review(inputs, state)
    keep_review = next(
        item for item in inputs.required_reviews if item.review_type is ReviewType.KEEP_PREFERENCE
    )
    return replace(
        inputs,
        required_reviews=(keep_review, candidate_review),
        precondition_inputs=(
            _precondition_input(ConsolidationFileRole.KEEPER, keep_review),
            _precondition_input(ConsolidationFileRole.CANDIDATE, candidate_review),
        ),
    )


def test_accepted_identity_quality_reviews_and_preconditions_are_approved() -> None:
    plan = build_consolidation_plan(
        _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED), clock=_clock
    )
    assert plan.status is ConsolidationPlanStatus.APPROVED_NON_EXECUTABLE
    assert plan.keeper is not None and plan.candidate is not None
    assert plan.consolidation_candidate is not None
    assert len(plan.preconditions) == 21
    assert not plan.blockers


def test_pending_compatible_candidate_review_is_review_required_not_directly_executable() -> None:
    plan = build_consolidation_plan(
        _with_candidate_review(_inputs(), ConsolidationReviewState.PENDING), clock=_clock
    )
    assert plan.status is ConsolidationPlanStatus.REVIEW_REQUIRED
    assert plan.consolidation_candidate is not None
    assert len(plan.preconditions) == 19
    assert all(
        item.code is not ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED
        for item in plan.preconditions
    )
    assert not plan.blockers


@pytest.mark.parametrize(
    "state", (ConsolidationReviewState.PENDING, ConsolidationReviewState.DEFERRED)
)
def test_waiting_candidate_reviews_keep_only_physical_preconditions(
    state: ConsolidationReviewState,
) -> None:
    plan = build_consolidation_plan(_with_candidate_review(_inputs(), state), clock=_clock)
    assert plan.status is ConsolidationPlanStatus.REVIEW_REQUIRED
    assert plan.consolidation_candidate is not None
    assert len(plan.preconditions) == 19


def test_compatible_pending_and_deferred_keep_reviews_are_review_required() -> None:
    source = _inputs()
    accepted = source.required_reviews[0]
    for state in (ConsolidationReviewState.PENDING, ConsolidationReviewState.DEFERRED):
        review = replace(accepted, state=state, decision_id=None, decision_sequence_no=None)
        plan = build_consolidation_plan(
            replace(source, required_reviews=(review,)), clock=_clock
        )
        assert plan.status is ConsolidationPlanStatus.REVIEW_REQUIRED
        assert plan.keeper is plan.candidate is plan.consolidation_candidate is None
        assert not plan.blockers


def test_incompatible_or_itemless_keep_review_is_missing_and_blocks() -> None:
    source = _inputs()
    accepted = source.required_reviews[0]
    for review in (
        replace(accepted, evidence_fingerprint="9" * 64),
        replace(
            accepted,
            state=ConsolidationReviewState.PENDING,
            decision_id=None,
            decision_sequence_no=None,
            review_item_id=None,
        ),
    ):
        plan = build_consolidation_plan(
            replace(source, required_reviews=(review,)), clock=_clock
        )
        assert plan.status is ConsolidationPlanStatus.BLOCKED
        assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING in {
            item.code for item in plan.blockers
        }


def test_foreign_rejected_keep_review_is_only_missing_not_rejected() -> None:
    source = _inputs()
    rejected = replace(
        source.required_reviews[0],
        state=ConsolidationReviewState.REJECTED,
        evidence_fingerprint="9" * 64,
    )
    plan = build_consolidation_plan(
        replace(source, required_reviews=(rejected,)), clock=_clock
    )
    codes = {item.code for item in plan.blockers}
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING in codes
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_REJECTED not in codes


def test_foreign_rejected_candidate_review_is_only_missing_not_rejected() -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.REJECTED)
    keep_review, candidate_review = inputs.required_reviews
    foreign = replace(candidate_review, evidence_fingerprint="9" * 64)
    plan = build_consolidation_plan(
        replace(
            inputs,
            required_reviews=(keep_review, foreign),
            precondition_inputs=(
                _precondition_input(ConsolidationFileRole.KEEPER, keep_review),
                _precondition_input(ConsolidationFileRole.CANDIDATE, foreign),
            ),
        ),
        clock=_clock,
    )
    codes = {item.code for item in plan.blockers}
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING in codes
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED not in codes


@pytest.mark.parametrize(
    ("review_type", "field", "value", "missing_code"),
    (
        (
            ReviewType.KEEP_PREFERENCE,
            "producer_name",
            "foreign-producer",
            ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
        ),
        (
            ReviewType.KEEP_PREFERENCE,
            "decision_compatibility_version",
            "foreign/v1",
            ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
        ),
        (
            ReviewType.KEEP_PREFERENCE,
            "evidence_fingerprint",
            "9" * 64,
            ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
        ),
        (
            ReviewType.KEEP_PREFERENCE,
            "candidate_set_fingerprint",
            "8" * 64,
            ConsolidationBlockerCode.KEEP_PREFERENCE_REVIEW_MISSING,
        ),
        (
            ReviewType.CONSOLIDATION_CANDIDATE,
            "producer_name",
            "foreign-producer",
            ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
        ),
        (
            ReviewType.CONSOLIDATION_CANDIDATE,
            "decision_compatibility_version",
            "foreign/v1",
            ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
        ),
        (
            ReviewType.CONSOLIDATION_CANDIDATE,
            "evidence_fingerprint",
            "9" * 64,
            ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
        ),
        (
            ReviewType.CONSOLIDATION_CANDIDATE,
            "candidate_set_fingerprint",
            "8" * 64,
            ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING,
        ),
    ),
)
def test_incompatible_accepted_review_is_omitted_without_effective_decision(
    review_type: ReviewType,
    field: str,
    value: str,
    missing_code: ConsolidationBlockerCode,
) -> None:
    source = _inputs()
    if review_type is ReviewType.CONSOLIDATION_CANDIDATE:
        source = _with_candidate_review(source, ConsolidationReviewState.ACCEPTED)
    reviews = list(source.required_reviews)
    index = next(index for index, item in enumerate(reviews) if item.review_type is review_type)
    reviews[index] = replace(reviews[index], **{field: value})

    plan = build_consolidation_plan(
        replace(source, required_reviews=tuple(reviews)), clock=_clock
    )

    assert all(item.review_type is not review_type for item in plan.required_reviews)
    assert missing_code in {item.code for item in plan.blockers}


def test_tied_preference_omits_an_irrelevant_keep_review() -> None:
    plan = build_consolidation_plan(
        _inputs(preference=_preference(KeepPreferenceStatus.TIED)), clock=_clock
    )
    assert not plan.required_reviews


@pytest.mark.parametrize(
    "state",
    (
        ConsolidationReviewState.MISSING,
        ConsolidationReviewState.REJECTED,
        ConsolidationReviewState.STALE,
    ),
)
def test_no_candidate_never_projects_downstream_candidate_review_blockers(
    state: ConsolidationReviewState,
) -> None:
    source = _inputs()
    review = _review(
        ReviewType.KEEP_PREFERENCE,
        state,
        source.keep_preference.evidence_fingerprint,
        source.keep_preference.candidate_set_fingerprint,
    )
    plan = build_consolidation_plan(
        replace(source, required_reviews=(review,)), clock=_clock
    )
    codes = {item.code for item in plan.blockers}
    assert plan.consolidation_candidate is None
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING not in codes
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED not in codes


def test_candidate_without_review_projects_the_explicit_missing_blocker() -> None:
    plan = build_consolidation_plan(_inputs(), clock=_clock)
    assert plan.consolidation_candidate is not None
    assert len(plan.preconditions) == 19
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING in {
        item.code for item in plan.blockers
    }


def test_stale_or_incompatible_candidate_review_keeps_physical_preconditions() -> None:
    source = _with_candidate_review(_inputs(), ConsolidationReviewState.PENDING)
    candidate = next(
        item
        for item in source.required_reviews
        if item.review_type is ReviewType.CONSOLIDATION_CANDIDATE
    )
    for review in (
        replace(candidate, state=ConsolidationReviewState.STALE),
        replace(candidate, evidence_fingerprint="9" * 64),
    ):
        plan = build_consolidation_plan(
            replace(
                source,
                required_reviews=(source.required_reviews[0], review),
            ),
            clock=_clock,
        )
        assert plan.consolidation_candidate is not None
        assert len(plan.preconditions) == 19


def test_tied_preference_cannot_create_direction_candidate_intents_or_preconditions() -> None:
    plan = build_consolidation_plan(
        _inputs(preference=_preference(KeepPreferenceStatus.TIED)), clock=_clock
    )
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.keeper is plan.candidate is plan.consolidation_candidate is None
    assert plan.future_operation_intents == plan.preconditions == ()
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED in {
        item.code for item in plan.blockers
    }


@pytest.mark.parametrize("status", (KeepPreferenceStatus.TIED, KeepPreferenceStatus.BLOCKED))
def test_valid_undirected_preference_has_only_the_unresolved_blocker(
    status: KeepPreferenceStatus,
) -> None:
    plan = build_consolidation_plan(_inputs(preference=_preference(status)), clock=_clock)
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.keeper is plan.candidate is plan.consolidation_candidate is None
    assert {item.code for item in plan.blockers} == {
        ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED
    }


def test_rejected_candidate_review_is_blocked_but_keeps_a_non_executable_snapshot() -> None:
    plan = build_consolidation_plan(
        _with_candidate_review(_inputs(), ConsolidationReviewState.REJECTED), clock=_clock
    )
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.consolidation_candidate is not None
    assert len(plan.preconditions) == 19
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_REJECTED in {
        item.code for item in plan.blockers
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (("scan_root_id", _id(999)), ("source_scan_run_id", _id(998))),
)
def test_foreign_quality_lineage_is_a_safe_blocker(field: str, value: EntityId) -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    foreign_quality = replace(inputs.keep_preference.quality_evidence[0], **{field: value})
    preference = replace(
        inputs.keep_preference,
        quality_evidence=(foreign_quality, inputs.keep_preference.quality_evidence[1]),
    )
    plan = build_consolidation_plan(replace(inputs, keep_preference=preference), clock=_clock)
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE in {
        item.code for item in plan.blockers
    }
    assert ConsolidationBlockerCode.LINEAGE_MISMATCH in {
        item.code for item in plan.blockers
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (("scan_root_id", _id(999)), ("source_scan_run_id", _id(998))),
)
def test_foreign_precondition_source_lineage_is_a_safe_blocker(
    field: str, value: EntityId
) -> None:
    source = _inputs()
    foreign_endpoint = replace(source.precondition_inputs[0].file_endpoint, **{field: value})
    plan = build_consolidation_plan(
        replace(
            source,
            precondition_inputs=(
                replace(source.precondition_inputs[0], file_endpoint=foreign_endpoint),
                source.precondition_inputs[1],
            ),
        ),
        clock=_clock,
    )
    assert ConsolidationBlockerCode.LINEAGE_MISMATCH in {
        item.code for item in plan.blockers
    }


def test_valid_preferred_quality_is_not_lost_when_identity_needs_confirmation() -> None:
    plan = build_consolidation_plan(
        replace(_inputs(), identity=replace(_identity(), status=MatchStatus.REVIEW_REQUIRED)),
        clock=_clock,
    )
    assert ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED in {
        item.code for item in plan.blockers
    }
    assert ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE not in {
        item.code for item in plan.blockers
    }


def test_shared_endpoint_observation_cannot_create_a_directed_plan() -> None:
    source = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    keeper_source, candidate_source = source.precondition_inputs
    shared_observation = keeper_source.file_endpoint.observation_id
    plan = build_consolidation_plan(
        replace(
            source,
            precondition_inputs=(
                keeper_source,
                replace(
                    candidate_source,
                    file_endpoint=replace(
                        candidate_source.file_endpoint,
                        observation_id=shared_observation,
                    ),
                ),
            ),
        ),
        clock=_clock,
    )
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.keeper is plan.candidate is plan.consolidation_candidate is None


def test_keep_preference_rejects_shared_observation_ids() -> None:
    source = _preference()
    with pytest.raises(ValueError, match="observations must be distinct"):
        replace(source, right_observation_id=source.left_observation_id)


def test_quality_preference_snapshots_are_matched_by_role_not_input_order() -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    reordered = replace(
        inputs.keep_preference,
        quality_evidence=tuple(reversed(inputs.keep_preference.quality_evidence)),
    )
    first = build_consolidation_plan(inputs, clock=_clock)
    plan = build_consolidation_plan(
        replace(
            inputs,
            dependencies=tuple(reversed(inputs.dependencies)),
            keep_preference=reordered,
        ),
        clock=_clock,
    )
    assert plan.status is ConsolidationPlanStatus.APPROVED_NON_EXECUTABLE
    assert plan == first
    assert plan.content_hash == first.content_hash


def test_precondition_inputs_require_exactly_one_of_each_role() -> None:
    inputs = _inputs()
    with pytest.raises(ValueError, match="exactly one input per file role"):
        replace(inputs, precondition_inputs=(inputs.precondition_inputs[0],))
    with pytest.raises(ValueError, match="exactly one input per file role"):
        replace(
            inputs,
            precondition_inputs=(inputs.precondition_inputs[0], inputs.precondition_inputs[0]),
        )
    with pytest.raises(ValueError, match="unique file role/kind pairs"):
        replace(inputs, dependencies=(inputs.dependencies[0], *inputs.dependencies))


def test_empty_precondition_inputs_allow_only_safe_partial_blocked_plans() -> None:
    preferred = build_consolidation_plan(
        replace(_inputs(), precondition_inputs=()), clock=_clock
    )
    assert preferred.status is ConsolidationPlanStatus.BLOCKED
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in {
        item.code for item in preferred.blockers
    }
    assert preferred.keeper is preferred.candidate is preferred.consolidation_candidate is None

    tied = build_consolidation_plan(
        replace(
            _inputs(preference=_preference(KeepPreferenceStatus.TIED)),
            precondition_inputs=(),
        ),
        clock=_clock,
    )
    assert tied.status is ConsolidationPlanStatus.BLOCKED
    assert tied.keeper is tied.candidate is tied.consolidation_candidate is None
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED in {
        item.code for item in tied.blockers
    }


def test_candidate_hashing_is_timezone_and_unicode_normalized() -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    dependency = replace(
        inputs.dependencies[0],
        state=ConsolidationDependencyState.NOT_APPLICABLE,
        snapshot_kind="Café",
        snapshot_id=_id(500),
    )
    inputs = replace(inputs, dependencies=(dependency, *inputs.dependencies[1:]))
    baseline = _with_candidate_review(inputs, ConsolidationReviewState.ACCEPTED)
    shifted = _NOW.astimezone(timezone(timedelta(hours=2)))
    changed_sources = tuple(
        replace(
            source,
            file_endpoint=replace(
                source.file_endpoint,
                expected_modified_at=shifted,
                expected_observed_at=shifted,
            ),
            file_record=replace(source.file_record, modified_at=shifted),
            file_observation=replace(
                source.file_observation, modified_at=shifted, observed_at=shifted
            ),
        )
        for source in baseline.precondition_inputs
    )
    normalized_dependency = replace(dependency, snapshot_kind="Cafe\u0301")
    equivalent = replace(
        baseline,
        dependencies=(normalized_dependency, *baseline.dependencies[1:]),
        precondition_inputs=changed_sources,
    )
    first = build_consolidation_plan(baseline, clock=_clock)
    second = build_consolidation_plan(equivalent, clock=_clock)
    assert first.consolidation_candidate == second.consolidation_candidate
    assert first.content_hash == second.content_hash


def test_intents_are_canonical_contiguous_and_shared_by_candidate_and_plan() -> None:
    intents = (
        ConsolidationFutureOperationIntent(
            1, ConsolidationIntentCode.VERIFY, ConsolidationFileRole.CANDIDATE
        ),
        ConsolidationFutureOperationIntent(
            0, ConsolidationIntentCode.KEEP, ConsolidationFileRole.KEEPER
        ),
    )
    inputs = replace(_inputs(), future_operation_intents=intents)
    plan = build_consolidation_plan(
        _with_candidate_review(inputs, ConsolidationReviewState.ACCEPTED), clock=_clock
    )
    assert tuple(item.ordinal for item in plan.future_operation_intents) == (0, 1)
    assert plan.consolidation_candidate is not None
    assert plan.consolidation_candidate.intents == plan.future_operation_intents
    with pytest.raises(ValueError, match="contiguous ordinals"):
        replace(inputs, future_operation_intents=(intents[0],))


def test_blocker_evidence_uses_full_canonical_sort_key() -> None:
    refs = (
        ConsolidationEvidenceReference(
            ConsolidationEvidenceKind.FINGERPRINT,
            "synthetic-evidence",
            ConsolidationEvidenceRole.IDENTITY,
            "b" * 64,
        ),
        ConsolidationEvidenceReference(
            ConsolidationEvidenceKind.FINGERPRINT,
            "synthetic-evidence",
            ConsolidationEvidenceRole.IDENTITY,
            "a" * 64,
        ),
    )
    first = build_consolidation_plan(
        _inputs(preference=_preference(KeepPreferenceStatus.TIED),), clock=_clock
    )
    second = build_consolidation_plan(
        replace(
            _inputs(preference=_preference(KeepPreferenceStatus.TIED)),
            evidence_refs=tuple(reversed(refs)),
        ),
        clock=_clock,
    )
    third = build_consolidation_plan(
        replace(_inputs(preference=_preference(KeepPreferenceStatus.TIED)), evidence_refs=refs),
        clock=_clock,
    )
    assert first.content_hash != second.content_hash
    assert second == third


def test_valid_identity_with_invalid_precondition_source_is_not_identity_failure() -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    invalid = replace(inputs.precondition_inputs[0].file_record, size_bytes=999)
    plan = build_consolidation_plan(
        replace(
            inputs,
            precondition_inputs=(
                replace(inputs.precondition_inputs[0], file_record=invalid),
                inputs.precondition_inputs[1],
            ),
        ),
        clock=_clock,
    )
    codes = {item.code for item in plan.blockers}
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE not in codes
    assert ConsolidationBlockerCode.PRECONDITION_INCOMPLETE in codes
    assert ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE not in codes
    assert ConsolidationBlockerCode.CONSOLIDATION_REVIEW_MISSING not in codes


def test_foreign_preferred_keep_preference_is_unresolved_and_never_directed() -> None:
    source = _inputs()
    preference = replace(
        source.keep_preference,
        left_file_id=_id(101),
        right_file_id=_id(102),
        keeper_file_id=_id(101),
        candidate_file_id=_id(102),
    )
    keep_review = _review(
        ReviewType.KEEP_PREFERENCE,
        ConsolidationReviewState.ACCEPTED,
        preference.evidence_fingerprint,
        preference.candidate_set_fingerprint,
    )
    plan = build_consolidation_plan(
        replace(source, keep_preference=preference, required_reviews=(keep_review,)),
        clock=_clock,
    )
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.keeper is plan.candidate is plan.consolidation_candidate is None
    assert ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED in {
        item.code for item in plan.blockers
    }


@pytest.mark.parametrize(
    ("status", "source_scan_run_completed"),
    (
        (MatchStatus.REVIEW_REQUIRED, True),
        (MatchStatus.REJECTED, True),
        (MatchStatus.CONFIRMED, False),
    ),
)
def test_exact_file_identity_without_confirmation_is_not_confirmed(
    status: MatchStatus,
    source_scan_run_completed: bool,
) -> None:
    inputs = replace(
        _inputs(),
        identity=replace(_identity(), status=status),
        source_scan_run_completed=source_scan_run_completed,
    )
    plan = build_consolidation_plan(inputs, clock=_clock)
    codes = {item.code for item in plan.blockers}
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED in codes
    assert ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE not in codes


def test_same_material_is_deterministic_and_dependency_changes_content_hash() -> None:
    inputs = _with_candidate_review(_inputs(), ConsolidationReviewState.ACCEPTED)
    first = build_consolidation_plan(inputs, clock=_clock)
    second = build_consolidation_plan(inputs, clock=_clock)
    changed = replace(
        inputs.dependencies[0], material_fingerprint="9" * 64
    )
    altered = build_consolidation_plan(
        replace(inputs, dependencies=(changed, *inputs.dependencies[1:])), clock=_clock
    )
    assert first == second
    assert first.content_hash != altered.content_hash


def test_planner_exposes_no_execution_operation() -> None:
    assert not hasattr(build_consolidation_plan, "execute")
    assert not hasattr(build_consolidation_plan, "apply")
