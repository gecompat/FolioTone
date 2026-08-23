from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from foliotone.core import EntityId, PresenceState, ScanRunStatus
from foliotone.ebook_operation_recipes import (
    EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE,
    EBOOK_OPERATION_RECIPE_PLAN_PROFILE,
    EBOOK_OPERATION_RECIPE_SERIALIZER,
    EbookOperationBlockerCode,
    EbookOperationCollisionPolicy,
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationEvidenceReference,
    EbookOperationExecutionState,
    EbookOperationKind,
    EbookOperationPlanStatus,
    EbookOperationPreconditionCode,
    EbookOperationProcessorKind,
    EbookOperationRecipeCandidate,
    EbookOperationRecipeCandidateInputs,
    EbookOperationRecipePlanInputs,
    EbookOperationRecoveryMode,
    EbookOperationReviewSnapshot,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationSourceSnapshot,
    EbookOperationTargetSnapshot,
    EbookOperationWorkspaceMode,
    build_ebook_operation_expected_output,
    build_ebook_operation_processor_requirement,
    build_ebook_operation_recipe_candidate,
    build_ebook_operation_recipe_plan,
    build_ebook_operation_source_snapshot,
    canonical_ebook_operation_recipe_candidate_payload,
    canonical_ebook_operation_recipe_plan_payload,
    ebook_operation_recipe_candidate_content_hash,
    ebook_operation_recipe_candidate_evidence_fingerprint,
    ebook_operation_recipe_candidate_id,
    ebook_operation_recipe_plan_content_hash,
    ebook_operation_recipe_plan_id,
    operation_collision_policy,
    operation_output_identity_kind,
    operation_recovery_mode,
    operation_target_kind,
    operation_workspace_mode,
    required_verification_codes,
    serialize_ebook_operation_recipe_candidate,
    serialize_ebook_operation_recipe_plan,
)

NOW = datetime(2026, 8, 23, 10, 20, 30, 123456, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def _id(value: int) -> EntityId:
    return EntityId(UUID(int=value))


def _sha(value: str) -> str:
    assert len(value) == 1 and value in "0123456789abcdef"
    return value * 64


def _source(
    *,
    ordinal: int = 0,
    role: EbookOperationSourceRole = EbookOperationSourceRole.PRIMARY,
    scan_root_id: EntityId | None = None,
    scan_run_id: EntityId | None = None,
    file_id: EntityId | None = None,
    observation_id: EntityId | None = None,
    relative_locator: str = "library/Old.epub",
) -> EbookOperationSourceSnapshot:
    return build_ebook_operation_source_snapshot(
        ordinal=ordinal,
        role=role,
        scan_root_id=_id(1) if scan_root_id is None else scan_root_id,
        source_scan_run_id=_id(2) if scan_run_id is None else scan_run_id,
        source_scan_run_status=ScanRunStatus.COMPLETED,
        file_id=_id(3 + ordinal) if file_id is None else file_id,
        observation_id=_id(10 + ordinal) if observation_id is None else observation_id,
        relative_locator=relative_locator,
        format_label="EPUB",
        expected_presence_state=PresenceState.PRESENT,
        expected_full_sha256=_sha("a"),
        expected_size_bytes=4096,
        expected_modified_at=NOW - timedelta(days=1),
        expected_observed_at=NOW - timedelta(hours=2),
    )


def _dependencies(
    *,
    unknown: EbookOperationDependencyKind | None = None,
    reverse: bool = False,
) -> tuple[EbookOperationDependencySnapshot, ...]:
    values = tuple(
        EbookOperationDependencySnapshot(
            kind=kind,
            state=(
                EbookOperationDependencyState.UNKNOWN
                if kind is unknown
                else EbookOperationDependencyState.KNOWN_NONE
            ),
            snapshot_kind=f"ebook-{kind.value.lower()}-dependency/v1",
            snapshot_id=_id(30 + ordinal),
            material_fingerprint=_sha(str(ordinal + 1)),
        )
        for ordinal, kind in enumerate(EbookOperationDependencyKind)
    )
    return tuple(reversed(values)) if reverse else values


def _target_locator(operation_kind: EbookOperationKind, source_locator: str) -> str:
    if operation_kind is EbookOperationKind.FILE_RENAME:
        return "library/New.epub"
    if operation_kind is EbookOperationKind.FILE_REORGANIZE:
        return "organized/New.epub"
    if operation_kind is EbookOperationKind.FILE_IMPORT:
        return "imports/Old.epub"
    if operation_kind is EbookOperationKind.FILE_EXPORT:
        return "exports/Old.epub"
    if operation_kind is EbookOperationKind.FORMAT_TRANSFORM:
        return "generated/Old.pdf"
    return source_locator


def _candidate_inputs(
    operation_kind: EbookOperationKind,
    *,
    source_locator: str = "library/Old.epub",
    sources: tuple[EbookOperationSourceSnapshot, ...] | None = None,
    dependencies: tuple[EbookOperationDependencySnapshot, ...] | None = None,
    reverse: bool = False,
) -> EbookOperationRecipeCandidateInputs:
    primary = _source(relative_locator=source_locator)
    source_values = (primary,) if sources is None else sources
    target_scope = (
        _id(9)
        if operation_kind is EbookOperationKind.FILE_IMPORT
        else _id(10)
        if operation_kind is EbookOperationKind.FILE_EXPORT
        else _id(1)
    )
    target = EbookOperationTargetSnapshot(
        kind=operation_target_kind(operation_kind),
        scope_id=target_scope,
        relative_locator=_target_locator(operation_kind, source_locator),
        target_state_fingerprint=_sha("d"),
    )
    byte_preserving = operation_kind in {
        EbookOperationKind.FILE_RENAME,
        EbookOperationKind.FILE_REORGANIZE,
        EbookOperationKind.FILE_IMPORT,
        EbookOperationKind.FILE_EXPORT,
    }
    expected_output = build_ebook_operation_expected_output(
        operation_kind=operation_kind,
        format_label="EPUB" if operation_kind is not EbookOperationKind.FORMAT_TRANSFORM else "PDF",
        expected_full_sha256=_sha("a") if byte_preserving else _sha("b"),
        expected_size_bytes=4096 if byte_preserving else 8192,
    )
    processor = build_ebook_operation_processor_requirement(
        kind=(
            EbookOperationProcessorKind.FOLIOTONE_NATIVE
            if byte_preserving
            else EbookOperationProcessorKind.TOOL_PROVIDER
        ),
        processor_profile=(
            "byte-preserving-file-operation/v1"
            if byte_preserving
            else "deterministic-ebook-transform/v1"
        ),
        configuration_fingerprint=_sha("c"),
        provider_id=None if byte_preserving else "synthetic-tool-provider",
        tool_version=None if byte_preserving else "1.2.3",
        adapter_version=None if byte_preserving else "adapter-v1",
    )
    evidence = (
        EbookOperationEvidenceReference(
            kind="FILE_OBSERVATION",
            ref_id=_id(10),
            material_fingerprint=_sha("e"),
        ),
        EbookOperationEvidenceReference(
            kind="QUALITY_ASSESSMENT",
            ref_id=_id(20),
            material_fingerprint=_sha("f"),
        ),
    )
    return EbookOperationRecipeCandidateInputs(
        operation_kind=operation_kind,
        sources=tuple(reversed(source_values)) if reverse else source_values,
        target=target,
        expected_output=expected_output,
        processor_requirement=processor,
        dependencies=(
            _dependencies(reverse=reverse) if dependencies is None else dependencies
        ),
        evidence_refs=tuple(reversed(evidence)) if reverse else evidence,
    )


def _candidate(
    operation_kind: EbookOperationKind = EbookOperationKind.FILE_RENAME,
    *,
    clock_value: datetime = NOW,
    **kwargs: object,
) -> EbookOperationRecipeCandidate:
    return build_ebook_operation_recipe_candidate(
        _candidate_inputs(operation_kind, **kwargs),  # type: ignore[arg-type]
        clock=lambda: clock_value,
    )


def _review(
    candidate: EbookOperationRecipeCandidate,
    state: EbookOperationReviewState,
    *,
    candidate_id: EntityId | None = None,
    evidence_fingerprint: str | None = None,
    candidate_set_fingerprint: str | None = None,
    sequence_no: int = 1,
) -> EbookOperationReviewSnapshot:
    missing = state is EbookOperationReviewState.MISSING
    decided = state in {
        EbookOperationReviewState.ACCEPTED,
        EbookOperationReviewState.REJECTED,
    }
    return EbookOperationReviewSnapshot(
        candidate_id=candidate.id if candidate_id is None else candidate_id,
        state=state,
        evidence_fingerprint=(
            candidate.evidence_fingerprint
            if evidence_fingerprint is None
            else evidence_fingerprint
        ),
        candidate_set_fingerprint=(
            candidate.content_hash
            if candidate_set_fingerprint is None
            else candidate_set_fingerprint
        ),
        review_item_id=None if missing else _id(51),
        decision_id=_id(52) if decided else None,
        decision_sequence_no=sequence_no if decided else None,
    )


def _plan_inputs(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot | None,
    **overrides: object,
) -> EbookOperationRecipePlanInputs:
    values: dict[str, object] = {
        "candidate": candidate,
        "review": review,
        "lineage_matches": True,
        "source_evidence_complete": True,
        "target_valid": True,
        "output_identity_valid": True,
        "processor_requirement_valid": True,
        "preconditions_complete": True,
        "recovery_contract_complete": True,
        "verification_contract_complete": True,
    }
    values.update(overrides)
    return EbookOperationRecipePlanInputs(**values)  # type: ignore[arg-type]


def _plan(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot | None,
    *,
    clock_value: datetime = NOW,
    **overrides: object,
):
    return build_ebook_operation_recipe_plan(
        _plan_inputs(candidate, review, **overrides),
        clock=lambda: clock_value,
    )


@pytest.mark.parametrize("operation_kind", tuple(EbookOperationKind))
def test_all_operation_kinds_have_fixed_complete_recipe_shapes(
    operation_kind: EbookOperationKind,
) -> None:
    candidate = _candidate(operation_kind)

    assert candidate.profile == EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE
    assert candidate.serializer_version == EBOOK_OPERATION_RECIPE_SERIALIZER
    assert candidate.target.kind is operation_target_kind(operation_kind)
    assert candidate.expected_output.identity_kind is operation_output_identity_kind(
        operation_kind
    )
    assert candidate.collision_policy is operation_collision_policy(operation_kind)
    assert candidate.workspace_mode is operation_workspace_mode(operation_kind)
    assert candidate.recovery_mode is operation_recovery_mode(operation_kind)
    assert candidate.verification_codes == required_verification_codes(operation_kind)
    assert candidate.content_hash == ebook_operation_recipe_candidate_content_hash(
        candidate
    )
    assert candidate.id == ebook_operation_recipe_candidate_id(candidate.content_hash)


def test_operation_matrix_distinguishes_collision_workspace_and_recovery() -> None:
    rename = _candidate(EbookOperationKind.FILE_RENAME)
    imported = _candidate(EbookOperationKind.FILE_IMPORT)
    archive = _candidate(EbookOperationKind.ARCHIVE_REWRITE)

    assert rename.collision_policy is EbookOperationCollisionPolicy.REQUIRE_TARGET_ABSENT
    assert rename.workspace_mode is EbookOperationWorkspaceMode.NOT_REQUIRED
    assert rename.recovery_mode is EbookOperationRecoveryMode.REVERSE_RELOCATION
    assert imported.workspace_mode is EbookOperationWorkspaceMode.PRIVATE_STAGING_REQUIRED
    assert imported.recovery_mode is EbookOperationRecoveryMode.SOURCE_UNCHANGED
    assert archive.collision_policy is EbookOperationCollisionPolicy.REQUIRE_EXACT_SOURCE
    assert archive.recovery_mode is EbookOperationRecoveryMode.ORIGINAL_PRESERVED


def test_candidate_is_deterministic_and_canonicalizes_unordered_inputs() -> None:
    first = _candidate(reverse=False, clock_value=NOW)
    second = _candidate(reverse=True, clock_value=LATER)

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert first.created_at != second.created_at
    assert tuple(value.kind for value in first.dependencies) == tuple(
        EbookOperationDependencyKind
    )
    assert first.evidence_fingerprint == (
        ebook_operation_recipe_candidate_evidence_fingerprint(first)
    )


def test_candidate_hash_normalizes_unicode_and_equivalent_utc_instants() -> None:
    composed_inputs = _candidate_inputs(
        EbookOperationKind.ARCHIVE_REWRITE,
        source_locator="library/Café.epub",
    )
    decomposed_source = _source(relative_locator="library/Cafe\u0301.epub")
    shifted_source = replace(
        decomposed_source,
        expected_modified_at=decomposed_source.expected_modified_at.astimezone(
            timezone(timedelta(hours=2))
        ),
        expected_observed_at=decomposed_source.expected_observed_at.astimezone(
            timezone(timedelta(hours=2))
        ),
    )
    shifted_source = replace(
        shifted_source,
        source_evidence_fingerprint=_sha("0"),
    )
    shifted_source = build_ebook_operation_source_snapshot(
        ordinal=shifted_source.ordinal,
        role=shifted_source.role,
        scan_root_id=shifted_source.scan_root_id,
        source_scan_run_id=shifted_source.source_scan_run_id,
        source_scan_run_status=shifted_source.source_scan_run_status,
        file_id=shifted_source.file_id,
        observation_id=shifted_source.observation_id,
        relative_locator=shifted_source.relative_locator,
        format_label=shifted_source.format_label,
        expected_presence_state=shifted_source.expected_presence_state,
        expected_full_sha256=shifted_source.expected_full_sha256,
        expected_size_bytes=shifted_source.expected_size_bytes,
        expected_modified_at=shifted_source.expected_modified_at,
        expected_observed_at=shifted_source.expected_observed_at,
    )
    decomposed_inputs = _candidate_inputs(
        EbookOperationKind.ARCHIVE_REWRITE,
        source_locator="library/Cafe\u0301.epub",
        sources=(shifted_source,),
    )

    first = build_ebook_operation_recipe_candidate(composed_inputs, clock=lambda: NOW)
    second = build_ebook_operation_recipe_candidate(decomposed_inputs, clock=lambda: LATER)

    assert first.content_hash == second.content_hash
    assert first.id == second.id


def test_private_locators_and_hashes_are_hidden_from_repr_and_immutable() -> None:
    candidate = _candidate()
    rendered = repr(candidate)

    assert "library/Old.epub" not in rendered
    assert "library/New.epub" not in rendered
    assert candidate.sources[0].expected_full_sha256 not in rendered
    assert candidate.target.target_state_fingerprint not in rendered
    assert candidate.content_hash not in rendered
    with pytest.raises(FrozenInstanceError):
        candidate.operation_kind = EbookOperationKind.FILE_EXPORT  # type: ignore[misc]


@pytest.mark.parametrize(
    "locator",
    (
        "C:/library/Book.epub",
        "/library/Book.epub",
        "../library/Book.epub",
        "library//Book.epub",
        "library/./Book.epub",
    ),
)
def test_private_locator_grammar_rejects_absolute_and_ambiguous_paths(locator: str) -> None:
    with pytest.raises(ValueError, match="relative_locator|relative path"):
        _source(relative_locator=locator)


def test_byte_identical_output_binds_hash_format_and_size() -> None:
    inputs = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    changed = replace(inputs.expected_output, expected_full_sha256=_sha("b"))

    with pytest.raises(ValueError, match="byte-identical output"):
        build_ebook_operation_recipe_candidate(
            replace(inputs, expected_output=changed),
            clock=lambda: NOW,
        )


def test_operation_target_relations_are_hard_invariants() -> None:
    rename = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    same_source = replace(rename.target, relative_locator="library/Old.epub")
    with pytest.raises(ValueError, match="different basename"):
        build_ebook_operation_recipe_candidate(
            replace(rename, target=same_source),
            clock=lambda: NOW,
        )

    archive = _candidate_inputs(EbookOperationKind.ARCHIVE_REWRITE)
    different_slot = replace(archive.target, relative_locator="library/New.epub")
    with pytest.raises(ValueError, match="exact source replacement"):
        build_ebook_operation_recipe_candidate(
            replace(archive, target=different_slot),
            clock=lambda: NOW,
        )


def test_only_archive_rewrite_accepts_bounded_same_lineage_companions() -> None:
    primary = _source()
    companion = _source(
        ordinal=1,
        role=EbookOperationSourceRole.COMPANION,
        relative_locator="library/Companion.epub",
    )
    archive = _candidate(
        EbookOperationKind.ARCHIVE_REWRITE,
        sources=(primary, companion),
    )
    assert len(archive.sources) == 2

    with pytest.raises(ValueError, match="only archive rewrite"):
        _candidate(EbookOperationKind.FILE_RENAME, sources=(primary, companion))

    other_root = replace(companion, scan_root_id=_id(999))
    with pytest.raises(ValueError, match="share primary ScanRoot and ScanRun"):
        _candidate(
            EbookOperationKind.ARCHIVE_REWRITE,
            sources=(primary, other_root),
        )


def test_processor_requirement_is_bounded_and_has_no_command_surface() -> None:
    native = build_ebook_operation_processor_requirement(
        kind=EbookOperationProcessorKind.FOLIOTONE_NATIVE,
        processor_profile="byte-preserving-file-operation/v1",
        configuration_fingerprint=_sha("1"),
    )

    assert not hasattr(native, "command")
    assert not hasattr(native, "arguments")
    assert not hasattr(native, "executable")
    with pytest.raises(ValueError, match="cannot bind ToolProvider"):
        build_ebook_operation_processor_requirement(
            kind=EbookOperationProcessorKind.FOLIOTONE_NATIVE,
            processor_profile="byte-preserving-file-operation/v1",
            configuration_fingerprint=_sha("1"),
            provider_id="unexpected-provider",
        )


def test_candidate_rejects_corrupted_component_fingerprints() -> None:
    inputs = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    bad_source = replace(inputs.sources[0], source_evidence_fingerprint=_sha("f"))
    with pytest.raises(ValueError, match="source evidence fingerprint"):
        build_ebook_operation_recipe_candidate(
            replace(inputs, sources=(bad_source,)),
            clock=lambda: NOW,
        )

    bad_processor = replace(
        inputs.processor_requirement,
        material_fingerprint=_sha("f"),
    )
    with pytest.raises(ValueError, match="processor requirement fingerprint"):
        build_ebook_operation_recipe_candidate(
            replace(inputs, processor_requirement=bad_processor),
            clock=lambda: NOW,
        )


def test_candidate_requires_every_dependency_axis_exactly_once() -> None:
    inputs = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    with pytest.raises(ValueError, match="all axes"):
        build_ebook_operation_recipe_candidate(
            replace(inputs, dependencies=inputs.dependencies[:-1]),
            clock=lambda: NOW,
        )


def test_candidate_identity_changes_with_private_target_locator() -> None:
    first_inputs = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    second_inputs = replace(
        first_inputs,
        target=replace(first_inputs.target, relative_locator="library/Another.epub"),
    )
    first = build_ebook_operation_recipe_candidate(first_inputs, clock=lambda: NOW)
    second = build_ebook_operation_recipe_candidate(second_inputs, clock=lambda: LATER)

    assert first.id != second.id
    assert first.content_hash != second.content_hash
    assert first.evidence_fingerprint != second.evidence_fingerprint


def test_candidate_payload_excludes_persistence_fields() -> None:
    candidate = _candidate()
    payload = canonical_ebook_operation_recipe_candidate_payload(candidate)
    serialized = serialize_ebook_operation_recipe_candidate(candidate)

    assert payload["domain"] == "foliotone:ebook-operation-recipe-candidate/v1"
    assert "id" not in payload
    assert "content_hash" not in payload
    assert "created_at" not in payload
    assert b"library/Old.epub" in serialized
    assert candidate.content_hash == (
        "e8980af7a97305c025999732bf536729ee0b7ec43cfbcf9864038b1320652cbe"
    )
    assert str(candidate.id) == "1097e433-aee5-5fd7-9732-649c1d4706ff"


def test_accepted_review_is_approved_but_permanently_non_executable() -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, EbookOperationReviewState.ACCEPTED))

    assert plan.profile == EBOOK_OPERATION_RECIPE_PLAN_PROFILE
    assert plan.status is EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
    assert plan.execution_state is EbookOperationExecutionState.NOT_EXECUTABLE
    assert plan.blockers == ()
    assert {value.code for value in plan.preconditions} == set(
        EbookOperationPreconditionCode
    )
    assert plan.content_hash == ebook_operation_recipe_plan_content_hash(plan)
    assert plan.id == ebook_operation_recipe_plan_id(plan.content_hash)


@pytest.mark.parametrize(
    "state",
    (EbookOperationReviewState.PENDING, EbookOperationReviewState.DEFERRED),
)
def test_open_review_stays_review_required_without_fake_approval(
    state: EbookOperationReviewState,
) -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, state))

    assert plan.status is EbookOperationPlanStatus.REVIEW_REQUIRED
    assert plan.blockers == ()
    assert EbookOperationPreconditionCode.REVIEW_APPROVAL_UNCHANGED not in {
        value.code for value in plan.preconditions
    }
    assert plan.execution_state is EbookOperationExecutionState.NOT_EXECUTABLE


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        (None, EbookOperationBlockerCode.REVIEW_MISSING),
        (EbookOperationReviewState.MISSING, EbookOperationBlockerCode.REVIEW_MISSING),
        (EbookOperationReviewState.REJECTED, EbookOperationBlockerCode.REVIEW_REJECTED),
        (EbookOperationReviewState.STALE, EbookOperationBlockerCode.REVIEW_STALE),
    ),
)
def test_missing_rejected_and_stale_reviews_are_hard_blockers(
    state: EbookOperationReviewState | None,
    expected: EbookOperationBlockerCode,
) -> None:
    candidate = _candidate()
    review = None if state is None else _review(candidate, state)
    plan = _plan(candidate, review)

    assert plan.status is EbookOperationPlanStatus.BLOCKED
    assert expected in {value.code for value in plan.blockers}


def test_review_for_another_candidate_becomes_stale_plan_evidence() -> None:
    candidate = _candidate()
    review = _review(
        candidate,
        EbookOperationReviewState.ACCEPTED,
        candidate_id=_id(999),
    )
    plan = _plan(candidate, review)

    assert plan.status is EbookOperationPlanStatus.BLOCKED
    assert {value.code for value in plan.blockers} == {
        EbookOperationBlockerCode.REVIEW_STALE
    }
    assert plan.review.candidate_id == candidate.id
    assert plan.review.state is EbookOperationReviewState.STALE
    assert plan.review.review_item_id == review.review_item_id
    assert plan.review.decision_id is None


def test_plan_dto_rejects_direct_status_review_and_precondition_bypasses() -> None:
    candidate = _candidate()
    accepted = _review(candidate, EbookOperationReviewState.ACCEPTED)
    plan = _plan(candidate, accepted)

    with pytest.raises(ValueError, match="requires at least one blocker"):
        replace(plan, status=EbookOperationPlanStatus.BLOCKED)
    with pytest.raises(ValueError, match="accepted review"):
        replace(
            plan,
            review=_review(candidate, EbookOperationReviewState.PENDING),
        )
    with pytest.raises(ValueError, match="approval precondition"):
        replace(
            plan,
            preconditions=tuple(
                value
                for value in plan.preconditions
                if value.code
                is not EbookOperationPreconditionCode.REVIEW_APPROVAL_UNCHANGED
            ),
        )


@pytest.mark.parametrize(
    ("flag", "blocker"),
    (
        ("lineage_matches", EbookOperationBlockerCode.LINEAGE_MISMATCH),
        (
            "source_evidence_complete",
            EbookOperationBlockerCode.SOURCE_EVIDENCE_INCOMPLETE,
        ),
        ("target_valid", EbookOperationBlockerCode.TARGET_INVALID),
        ("output_identity_valid", EbookOperationBlockerCode.OUTPUT_IDENTITY_INVALID),
        (
            "processor_requirement_valid",
            EbookOperationBlockerCode.PROCESSOR_REQUIREMENT_INVALID,
        ),
        ("preconditions_complete", EbookOperationBlockerCode.PRECONDITION_INCOMPLETE),
        (
            "recovery_contract_complete",
            EbookOperationBlockerCode.RECOVERY_CONTRACT_INCOMPLETE,
        ),
        (
            "verification_contract_complete",
            EbookOperationBlockerCode.VERIFICATION_CONTRACT_INCOMPLETE,
        ),
    ),
)
def test_external_checks_map_to_fixed_blockers(
    flag: str,
    blocker: EbookOperationBlockerCode,
) -> None:
    candidate = _candidate()
    plan = _plan(
        candidate,
        _review(candidate, EbookOperationReviewState.ACCEPTED),
        **{flag: False},
    )

    assert plan.status is EbookOperationPlanStatus.BLOCKED
    assert blocker in {value.code for value in plan.blockers}


def test_unknown_dependency_is_a_hard_blocker() -> None:
    candidate = _candidate(
        dependencies=_dependencies(unknown=EbookOperationDependencyKind.ARCHIVE)
    )
    plan = _plan(candidate, _review(candidate, EbookOperationReviewState.ACCEPTED))

    assert EbookOperationBlockerCode.DEPENDENCY_EVIDENCE_INCOMPLETE in {
        value.code for value in plan.blockers
    }


def test_plan_identity_ignores_audit_time_but_binds_review_material() -> None:
    candidate = _candidate()
    review = _review(candidate, EbookOperationReviewState.ACCEPTED)
    first = _plan(candidate, review, clock_value=NOW)
    second = _plan(candidate, review, clock_value=LATER)
    changed = _plan(
        candidate,
        replace(review, decision_id=_id(53), decision_sequence_no=2),
        clock_value=LATER,
    )

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert first.created_at != second.created_at
    assert changed.id != first.id
    assert changed.content_hash != first.content_hash


def test_plan_payload_binds_candidate_and_review_without_private_locator() -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, EbookOperationReviewState.ACCEPTED))
    payload = canonical_ebook_operation_recipe_plan_payload(plan)
    serialized = serialize_ebook_operation_recipe_plan(plan)

    assert payload["domain"] == "foliotone:ebook-operation-recipe-plan/v1"
    assert "id" not in payload
    assert "content_hash" not in payload
    assert "created_at" not in payload
    assert payload["candidate"] == {
        "id": str(candidate.id),
        "profile": candidate.profile,
        "content_hash": candidate.content_hash,
        "evidence_fingerprint": candidate.evidence_fingerprint,
    }
    assert b"library/Old.epub" not in serialized
    assert plan.content_hash == (
        "bd4e26adc0e9d8c2a32e26722c560aff4de841811ccf2711ea2fd85138a19521"
    )
    assert str(plan.id) == "0d9e6623-f820-5433-bec2-1ef67b8fab3d"


def test_plan_builder_rejects_corrupted_content_addressed_candidate() -> None:
    candidate = replace(_candidate(), content_hash=_sha("e"))
    review = _review(candidate, EbookOperationReviewState.ACCEPTED)

    with pytest.raises(ValueError, match="content hash"):
        _plan(candidate, review)


def test_serialized_payloads_are_minimal_valid_json() -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, EbookOperationReviewState.PENDING))

    for serialized in (
        serialize_ebook_operation_recipe_candidate(candidate),
        serialize_ebook_operation_recipe_plan(plan),
    ):
        assert b"\n" not in serialized
        assert b": " not in serialized
        assert json.loads(serialized.decode("utf-8"))
