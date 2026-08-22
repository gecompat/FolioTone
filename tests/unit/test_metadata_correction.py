from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from foliotone.core import EntityId, PresenceState, ScanRunStatus, ValueState
from foliotone.metadata_correction import (
    METADATA_CORRECTION_CANDIDATE_PROFILE,
    METADATA_CORRECTION_PLAN_PROFILE,
    METADATA_CORRECTION_SERIALIZER_VERSION,
    METADATA_CORRECTION_VERIFICATION_PROFILE,
    METADATA_CORRECTION_WRITE_INTENT_PROFILE,
    METADATA_TARGET_REFERENCE_KIND,
    MetadataCorrectionBlockerCode,
    MetadataCorrectionCandidateInputs,
    MetadataCorrectionExecutionState,
    MetadataCorrectionOperation,
    MetadataCorrectionPlanInputs,
    MetadataCorrectionPlanStatus,
    MetadataCorrectionPreconditionCode,
    MetadataCorrectionReviewSnapshot,
    MetadataCorrectionReviewState,
    MetadataDependencyKind,
    MetadataDependencySnapshot,
    MetadataDependencyState,
    MetadataEvidenceReference,
    MetadataFieldCorrection,
    MetadataTargetCarrier,
    MetadataTargetReferenceKind,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    MetadataWriterRequirement,
    build_metadata_correction_candidate,
    build_metadata_correction_plan,
    build_metadata_field_correction,
    build_metadata_writer_requirement,
    canonical_metadata_correction_candidate_payload,
    canonical_metadata_correction_plan_payload,
    metadata_correction_candidate_content_hash,
    metadata_correction_candidate_evidence_fingerprint,
    metadata_correction_candidate_id,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
    metadata_field_selection_fingerprint,
    metadata_writer_requirement_fingerprint,
    serialize_metadata_correction_candidate,
    serialize_metadata_correction_plan,
    validate_metadata_field_path,
)

NOW = datetime(2026, 8, 22, 12, 34, 56, 123456, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def _id(value: int) -> EntityId:
    return EntityId(UUID(int=value))


def _sha(value: str) -> str:
    assert len(value) == 1 and value in "0123456789abcdef"
    return value * 64


def _ref(kind: str, identifier: int, digest: str) -> MetadataEvidenceReference:
    return MetadataEvidenceReference(
        kind=kind,
        ref_id=_id(identifier),
        material_fingerprint=_sha(digest),
    )


def _value(
    *,
    ordinal: int,
    state: ValueState,
    value: str,
    identifier: int,
    digest: str,
) -> MetadataValueSnapshot:
    return MetadataValueSnapshot(
        ordinal=ordinal,
        state=state,
        source_ref=_ref("VALUE_ASSERTION", identifier, digest),
        value=value,
    )


def _title_correction(
    selected: str = "Corrected private title",
) -> MetadataFieldCorrection:
    observed = (
        _value(
            ordinal=0,
            state=ValueState.OBSERVED,
            value="Observed private title",
            identifier=21,
            digest="1",
        ),
    )
    selected_values = (
        _value(
            ordinal=0,
            state=ValueState.USER_CONFIRMED,
            value=selected,
            identifier=22,
            digest="2",
        ),
    )
    return build_metadata_field_correction(
        field_path="title",
        operation=MetadataCorrectionOperation.REPLACE,
        observed_values=observed,
        selected_values=selected_values,
        evidence_refs=(_ref("TOOL_RESULT", 23, "3"), _ref("VALUE_ASSERTION", 21, "1")),
    )


def _publisher_removal() -> MetadataFieldCorrection:
    return build_metadata_field_correction(
        field_path="publisher",
        operation=MetadataCorrectionOperation.REMOVE,
        observed_values=(
            _value(
                ordinal=0,
                state=ValueState.OBSERVED,
                value="Private legacy publisher",
                identifier=24,
                digest="4",
            ),
        ),
        selected_values=(),
    )


def _dependencies(
    *,
    calibre: MetadataDependencyState = MetadataDependencyState.KNOWN_NONE,
    sidecar: MetadataDependencyState = MetadataDependencyState.KNOWN_NONE,
    archive: MetadataDependencyState = MetadataDependencyState.NOT_APPLICABLE,
    reverse: bool = False,
) -> tuple[MetadataDependencySnapshot, ...]:
    values = (
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.CALIBRE,
            state=calibre,
            snapshot_kind="calibre-dependency/v1",
            snapshot_id=_id(31),
            material_fingerprint=_sha("5"),
        ),
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.SIDECAR,
            state=sidecar,
            snapshot_kind="sidecar-dependency/v1",
            snapshot_id=_id(32),
            material_fingerprint=_sha("6"),
        ),
        MetadataDependencySnapshot(
            kind=MetadataDependencyKind.ARCHIVE,
            state=archive,
            snapshot_kind="archive-dependency/v1",
            snapshot_id=_id(33),
            material_fingerprint=_sha("7"),
        ),
    )
    return tuple(reversed(values)) if reverse else values


def _candidate(
    *,
    selected_title: str = "Corrected private title",
    clock_value: datetime = NOW,
    dependencies: tuple[MetadataDependencySnapshot, ...] | None = None,
    target_carrier: MetadataTargetCarrier = MetadataTargetCarrier.SOURCE_METADATA,
    reverse_inputs: bool = False,
):
    file_id = _id(3)
    reference_id = file_id if target_carrier is MetadataTargetCarrier.SOURCE_METADATA else _id(41)
    target = MetadataTargetSnapshot(
        carrier=target_carrier,
        reference_kind=METADATA_TARGET_REFERENCE_KIND[target_carrier],
        reference_id=reference_id,
        carrier_state_fingerprint=_sha("8"),
    )
    fields = (_publisher_removal(), _title_correction(selected_title))
    evidence = (_ref("VALUE_ASSERTION", 21, "1"), _ref("FILE_OBSERVATION", 4, "a"))
    return build_metadata_correction_candidate(
        MetadataCorrectionCandidateInputs(
            scan_root_id=_id(1),
            source_scan_run_id=_id(2),
            source_scan_run_status=ScanRunStatus.COMPLETED,
            file_id=file_id,
            observation_id=_id(4),
            format_label="EPUB",
            expected_presence_state=PresenceState.PRESENT,
            expected_full_sha256=_sha("b"),
            expected_size_bytes=4096,
            expected_modified_at=NOW - timedelta(days=1),
            expected_observed_at=NOW - timedelta(hours=2),
            metadata_evidence_fingerprint=_sha("c"),
            target=target,
            field_corrections=tuple(reversed(fields)) if reverse_inputs else fields,
            dependencies=(
                _dependencies(reverse=reverse_inputs)
                if dependencies is None
                else dependencies
            ),
            writer_requirement=build_metadata_writer_requirement(
                format_label="EPUB",
                target_carrier=target_carrier,
            ),
            evidence_refs=tuple(reversed(evidence)) if reverse_inputs else evidence,
        ),
        clock=lambda: clock_value,
    )


def _review(
    candidate,
    state: MetadataCorrectionReviewState,
    *,
    evidence_fingerprint: str | None = None,
    candidate_set_fingerprint: str | None = None,
    candidate_id: EntityId | None = None,
    sequence_no: int = 1,
) -> MetadataCorrectionReviewSnapshot:
    decided = state in {
        MetadataCorrectionReviewState.ACCEPTED,
        MetadataCorrectionReviewState.REJECTED,
    }
    missing = state is MetadataCorrectionReviewState.MISSING
    return MetadataCorrectionReviewSnapshot(
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


def _plan_inputs(candidate, review, **overrides: object) -> MetadataCorrectionPlanInputs:
    values: dict[str, object] = {
        "candidate": candidate,
        "review": review,
        "preserved_fields_fingerprint": _sha("d"),
        "analysis_profile": "ebook-analysis-workflow/v3",
        "lineage_matches": True,
        "source_evidence_complete": True,
        "field_selection_valid": True,
        "target_carrier_valid": True,
        "writer_requirement_valid": True,
        "preconditions_complete": True,
        "verification_contract_complete": True,
    }
    values.update(overrides)
    return MetadataCorrectionPlanInputs(**values)  # type: ignore[arg-type]


def _plan(candidate, review, *, clock_value: datetime = NOW, **overrides: object):
    return build_metadata_correction_plan(
        _plan_inputs(candidate, review, **overrides),
        clock=lambda: clock_value,
    )


@pytest.mark.parametrize(
    "field_path",
    (
        "title",
        "publication_date",
        "contributor.1.name",
        "contributor.12.source_role.2",
        "identifier.1.namespace",
        "series.3.position.2",
    ),
)
def test_bounded_field_grammar_accepts_provider_neutral_book_fields(field_path: str) -> None:
    assert validate_metadata_field_path(field_path) == field_path


@pytest.mark.parametrize(
    "field_path",
    (
        "$.title",
        "../title",
        "path_context",
        "provider.raw.payload",
        "contributor.0.name",
        "identifier.1.unknown",
    ),
)
def test_bounded_field_grammar_rejects_free_paths(field_path: str) -> None:
    with pytest.raises(ValueError, match="bounded e-book metadata grammar"):
        validate_metadata_field_path(field_path)


def test_field_correction_enforces_operation_state_and_order() -> None:
    observed = (
        _value(
            ordinal=0,
            state=ValueState.OBSERVED,
            value="Observed",
            identifier=60,
            digest="1",
        ),
    )
    canonical = (
        _value(
            ordinal=0,
            state=ValueState.CANONICAL,
            value="Selected",
            identifier=61,
            digest="2",
        ),
    )

    with pytest.raises(ValueError, match="REPLACE requires"):
        build_metadata_field_correction(
            field_path="title",
            operation=MetadataCorrectionOperation.REPLACE,
            observed_values=observed,
            selected_values=(),
        )
    with pytest.raises(ValueError, match="REMOVE requires"):
        build_metadata_field_correction(
            field_path="title",
            operation=MetadataCorrectionOperation.REMOVE,
            observed_values=observed,
            selected_values=canonical,
        )
    with pytest.raises(ValueError, match="CANONICAL or USER_CONFIRMED"):
        build_metadata_field_correction(
            field_path="title",
            operation=MetadataCorrectionOperation.REPLACE,
            observed_values=observed,
            selected_values=(replace(canonical[0], state=ValueState.DERIVED),),
        )
    with pytest.raises(ValueError, match="ordinals must be contiguous"):
        build_metadata_field_correction(
            field_path="title",
            operation=MetadataCorrectionOperation.REPLACE,
            observed_values=observed,
            selected_values=(replace(canonical[0], ordinal=1),),
        )
    with pytest.raises(ValueError, match="semantically unique"):
        build_metadata_field_correction(
            field_path="title",
            operation=MetadataCorrectionOperation.REPLACE,
            observed_values=observed,
            selected_values=canonical,
            evidence_refs=(
                _ref("VALUE_ASSERTION", 70, "1"),
                _ref("VALUE_ASSERTION", 70, "2"),
            ),
        )


def test_target_carrier_requires_its_fixed_reference_kind() -> None:
    with pytest.raises(ValueError, match="does not match"):
        MetadataTargetSnapshot(
            carrier=MetadataTargetCarrier.SIDECAR,
            reference_kind=MetadataTargetReferenceKind.SOURCE_FILE,
            reference_id=_id(3),
            carrier_state_fingerprint=_sha("1"),
        )


@pytest.mark.parametrize("carrier", tuple(MetadataTargetCarrier))
def test_each_target_carrier_stays_distinct_through_candidate_and_verification(
    carrier: MetadataTargetCarrier,
) -> None:
    candidate = _candidate(target_carrier=carrier)
    plan = _plan(candidate, _review(candidate, MetadataCorrectionReviewState.ACCEPTED))

    assert candidate.target.carrier is carrier
    assert candidate.target.reference_kind is METADATA_TARGET_REFERENCE_KIND[carrier]
    assert candidate.writer_requirement.target_carrier is carrier
    assert plan.verification.target_carrier is carrier
    if carrier is MetadataTargetCarrier.CALIBRE_LIBRARY:
        assert plan.verification.dependency_reconciliation == (
            MetadataDependencyKind.CALIBRE,
        )
    elif carrier is MetadataTargetCarrier.SIDECAR:
        assert plan.verification.dependency_reconciliation == (
            MetadataDependencyKind.SIDECAR,
        )
    else:
        assert plan.verification.dependency_reconciliation == ()


def test_source_metadata_target_must_bind_the_candidate_file() -> None:
    candidate = _candidate()
    with pytest.raises(ValueError, match="must bind the source file"):
        replace(
            candidate,
            target=replace(candidate.target, reference_id=_id(999)),
        )


def test_writer_requirement_is_semantic_and_fingerprint_bound() -> None:
    requirement = build_metadata_writer_requirement(
        format_label="AZW3",
        target_carrier=MetadataTargetCarrier.SIDECAR,
    )

    assert requirement.profile == METADATA_CORRECTION_WRITE_INTENT_PROFILE
    assert requirement.material_fingerprint == metadata_writer_requirement_fingerprint(
        format_label="AZW3",
        target_carrier=MetadataTargetCarrier.SIDECAR,
    )
    assert not hasattr(requirement, "command")
    assert not hasattr(requirement, "executable")


def test_candidate_is_deterministic_and_canonicalizes_unordered_sets() -> None:
    first = _candidate(reverse_inputs=False, clock_value=NOW)
    second = _candidate(reverse_inputs=True, clock_value=LATER)

    assert first.profile == METADATA_CORRECTION_CANDIDATE_PROFILE
    assert first.serializer_version == METADATA_CORRECTION_SERIALIZER_VERSION
    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert first.created_at != second.created_at
    assert tuple(item.field_path for item in first.field_corrections) == (
        "publisher",
        "title",
    )
    assert tuple(item.kind for item in first.dependencies) == tuple(MetadataDependencyKind)
    assert first.content_hash == metadata_correction_candidate_content_hash(first)
    assert first.id == metadata_correction_candidate_id(first.content_hash)
    assert first.evidence_fingerprint == (
        metadata_correction_candidate_evidence_fingerprint(first)
    )


def test_candidate_identity_changes_with_selected_private_value() -> None:
    first = _candidate(selected_title="First selected title")
    second = _candidate(selected_title="Second selected title")

    assert first.id != second.id
    assert first.content_hash != second.content_hash
    assert first.evidence_fingerprint != second.evidence_fingerprint


def test_candidate_hash_normalizes_unicode_and_equivalent_utc_instants() -> None:
    first = _candidate(selected_title="Café")
    second = _candidate(selected_title="Cafe\u0301")
    shifted = replace(
        first,
        expected_modified_at=first.expected_modified_at.astimezone(
            timezone(timedelta(hours=2))
        ),
    )
    # Rebuild rather than accepting the intentionally stale replaced content identity.
    rebuilt_shifted = build_metadata_correction_candidate(
        MetadataCorrectionCandidateInputs(
            scan_root_id=shifted.scan_root_id,
            source_scan_run_id=shifted.source_scan_run_id,
            source_scan_run_status=shifted.source_scan_run_status,
            file_id=shifted.file_id,
            observation_id=shifted.observation_id,
            format_label=shifted.format_label,
            expected_presence_state=shifted.expected_presence_state,
            expected_full_sha256=shifted.expected_full_sha256,
            expected_size_bytes=shifted.expected_size_bytes,
            expected_modified_at=shifted.expected_modified_at,
            expected_observed_at=shifted.expected_observed_at,
            metadata_evidence_fingerprint=shifted.metadata_evidence_fingerprint,
            target=shifted.target,
            field_corrections=shifted.field_corrections,
            dependencies=shifted.dependencies,
            writer_requirement=shifted.writer_requirement,
            evidence_refs=shifted.evidence_refs,
        ),
        clock=lambda: LATER,
    )

    assert first.content_hash == second.content_hash
    assert first.content_hash == rebuilt_shifted.content_hash


def test_candidate_requires_all_dependency_axes_without_silently_deduplicating() -> None:
    dependencies = _dependencies()
    with pytest.raises(ValueError, match="all axes"):
        _candidate(dependencies=dependencies[:2])
    with pytest.raises(ValueError, match="all axes"):
        _candidate(dependencies=(dependencies[0], dependencies[0], dependencies[2]))


def test_candidate_requires_a_completed_source_scan_run() -> None:
    with pytest.raises(ValueError, match="completed ScanRun"):
        replace(_candidate(), source_scan_run_status=ScanRunStatus.RUNNING)


def test_candidate_rejects_writer_fingerprint_mismatch() -> None:
    candidate = _candidate()
    bad_requirement = replace(
        candidate.writer_requirement,
        material_fingerprint=_sha("e"),
    )
    with pytest.raises(ValueError, match="writer requirement fingerprint"):
        build_metadata_correction_candidate(
            MetadataCorrectionCandidateInputs(
                scan_root_id=candidate.scan_root_id,
                source_scan_run_id=candidate.source_scan_run_id,
                source_scan_run_status=candidate.source_scan_run_status,
                file_id=candidate.file_id,
                observation_id=candidate.observation_id,
                format_label=candidate.format_label,
                expected_presence_state=candidate.expected_presence_state,
                expected_full_sha256=candidate.expected_full_sha256,
                expected_size_bytes=candidate.expected_size_bytes,
                expected_modified_at=candidate.expected_modified_at,
                expected_observed_at=candidate.expected_observed_at,
                metadata_evidence_fingerprint=candidate.metadata_evidence_fingerprint,
                target=candidate.target,
                field_corrections=candidate.field_corrections,
                dependencies=candidate.dependencies,
                writer_requirement=bad_requirement,
                evidence_refs=candidate.evidence_refs,
            ),
            clock=lambda: NOW,
        )


def test_private_metadata_values_and_material_hashes_are_hidden_from_repr() -> None:
    candidate = _candidate()
    rendered = repr(candidate)

    assert "Observed private title" not in rendered
    assert "Corrected private title" not in rendered
    assert "Private legacy publisher" not in rendered
    assert candidate.expected_full_sha256 not in rendered
    assert candidate.content_hash not in rendered

    with pytest.raises(FrozenInstanceError):
        candidate.format_label = "PDF"  # type: ignore[misc]


def test_candidate_canonical_payload_excludes_persistence_fields_and_has_golden_identity() -> None:
    candidate = _candidate()
    payload = canonical_metadata_correction_candidate_payload(candidate)
    serialized = serialize_metadata_correction_candidate(candidate)

    assert payload["domain"] == "foliotone:metadata-correction-candidate/v1"
    assert "id" not in payload
    assert "content_hash" not in payload
    assert "created_at" not in payload
    assert b"Corrected private title" in serialized
    assert candidate.content_hash == (
        "c4278802786bc6650ab60d41f685220d6e07df18ba6e8dc7b2087c2a9bac321c"
    )
    assert str(candidate.id) == "93fc3b5f-461a-5826-8dd5-15f16609b814"


def test_accepted_review_produces_approved_but_permanently_non_executable_plan() -> None:
    candidate = _candidate()
    review = _review(candidate, MetadataCorrectionReviewState.ACCEPTED)
    plan = _plan(candidate, review)

    assert plan.profile == METADATA_CORRECTION_PLAN_PROFILE
    assert plan.status is MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
    assert plan.execution_state is MetadataCorrectionExecutionState.NOT_EXECUTABLE
    assert plan.blockers == ()
    assert tuple(item.code for item in plan.preconditions) == tuple(
        MetadataCorrectionPreconditionCode
    )
    assert plan.verification.profile == METADATA_CORRECTION_VERIFICATION_PROFILE
    assert plan.verification.changed_field_paths == ("publisher", "title")
    assert plan.content_hash == metadata_correction_plan_content_hash(plan)
    assert plan.id == metadata_correction_plan_id(plan.content_hash)


@pytest.mark.parametrize(
    "state",
    (MetadataCorrectionReviewState.PENDING, MetadataCorrectionReviewState.DEFERRED),
)
def test_open_review_produces_review_required_without_fake_approval_precondition(
    state: MetadataCorrectionReviewState,
) -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, state))

    assert plan.status is MetadataCorrectionPlanStatus.REVIEW_REQUIRED
    assert plan.blockers == ()
    assert MetadataCorrectionPreconditionCode.REVIEW_APPROVAL_UNCHANGED not in {
        item.code for item in plan.preconditions
    }
    assert plan.execution_state is MetadataCorrectionExecutionState.NOT_EXECUTABLE


@pytest.mark.parametrize(
    ("review", "expected"),
    (
        (None, MetadataCorrectionBlockerCode.REVIEW_MISSING),
        (MetadataCorrectionReviewState.MISSING, MetadataCorrectionBlockerCode.REVIEW_MISSING),
        (MetadataCorrectionReviewState.REJECTED, MetadataCorrectionBlockerCode.REVIEW_REJECTED),
        (MetadataCorrectionReviewState.STALE, MetadataCorrectionBlockerCode.REVIEW_STALE),
    ),
)
def test_missing_rejected_and_stale_reviews_are_hard_blockers(review, expected) -> None:
    candidate = _candidate()
    snapshot = review if review is None else _review(candidate, review)
    plan = _plan(candidate, snapshot)

    assert plan.status is MetadataCorrectionPlanStatus.BLOCKED
    assert expected in {item.code for item in plan.blockers}


def test_review_for_another_candidate_is_preserved_as_stale_blocked_evidence() -> None:
    candidate = _candidate()
    review = _review(
        candidate,
        MetadataCorrectionReviewState.ACCEPTED,
        candidate_id=_id(999),
    )
    plan = _plan(candidate, review)

    assert plan.status is MetadataCorrectionPlanStatus.BLOCKED
    assert {item.code for item in plan.blockers} == {
        MetadataCorrectionBlockerCode.REVIEW_STALE
    }
    assert plan.review is review


@pytest.mark.parametrize(
    ("flag", "blocker"),
    (
        ("lineage_matches", MetadataCorrectionBlockerCode.LINEAGE_MISMATCH),
        (
            "source_evidence_complete",
            MetadataCorrectionBlockerCode.SOURCE_EVIDENCE_INCOMPLETE,
        ),
        ("field_selection_valid", MetadataCorrectionBlockerCode.FIELD_SELECTION_INVALID),
        ("target_carrier_valid", MetadataCorrectionBlockerCode.TARGET_CARRIER_INVALID),
        (
            "writer_requirement_valid",
            MetadataCorrectionBlockerCode.WRITER_REQUIREMENT_INVALID,
        ),
        (
            "preconditions_complete",
            MetadataCorrectionBlockerCode.PRECONDITION_INCOMPLETE,
        ),
        (
            "verification_contract_complete",
            MetadataCorrectionBlockerCode.VERIFICATION_CONTRACT_INCOMPLETE,
        ),
    ),
)
def test_external_lineage_and_completeness_checks_map_to_fixed_blockers(
    flag: str,
    blocker: MetadataCorrectionBlockerCode,
) -> None:
    candidate = _candidate()
    plan = _plan(
        candidate,
        _review(candidate, MetadataCorrectionReviewState.ACCEPTED),
        **{flag: False},
    )

    assert plan.status is MetadataCorrectionPlanStatus.BLOCKED
    assert blocker in {item.code for item in plan.blockers}


def test_unknown_dependency_blocks_and_known_dependencies_require_reconciliation() -> None:
    unknown = _candidate(
        dependencies=_dependencies(calibre=MetadataDependencyState.UNKNOWN)
    )
    blocked = _plan(unknown, _review(unknown, MetadataCorrectionReviewState.ACCEPTED))
    assert MetadataCorrectionBlockerCode.DEPENDENCY_EVIDENCE_INCOMPLETE in {
        item.code for item in blocked.blockers
    }

    known = _candidate(
        dependencies=_dependencies(
            calibre=MetadataDependencyState.KNOWN_PRESENT,
            sidecar=MetadataDependencyState.KNOWN_PRESENT,
        )
    )
    approved = _plan(known, _review(known, MetadataCorrectionReviewState.ACCEPTED))
    assert approved.verification.dependency_reconciliation == (
        MetadataDependencyKind.CALIBRE,
        MetadataDependencyKind.SIDECAR,
    )


def test_plan_identity_is_audit_time_independent_but_review_material_dependent() -> None:
    candidate = _candidate()
    review = _review(candidate, MetadataCorrectionReviewState.ACCEPTED)
    first = _plan(candidate, review, clock_value=NOW)
    second = _plan(candidate, review, clock_value=LATER)
    changed_review = replace(review, decision_id=_id(53), decision_sequence_no=2)
    changed = _plan(candidate, changed_review, clock_value=LATER)

    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert first.created_at != second.created_at
    assert changed.id != first.id
    assert changed.content_hash != first.content_hash


def test_plan_canonical_payload_binds_candidate_review_and_has_golden_identity() -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, MetadataCorrectionReviewState.ACCEPTED))
    payload = canonical_metadata_correction_plan_payload(plan)
    serialized = serialize_metadata_correction_plan(plan)

    assert payload["domain"] == "foliotone:metadata-correction-plan/v1"
    assert "id" not in payload
    assert "content_hash" not in payload
    assert "created_at" not in payload
    assert payload["candidate"] == {
        "id": str(candidate.id),
        "profile": candidate.profile,
        "content_hash": candidate.content_hash,
        "evidence_fingerprint": candidate.evidence_fingerprint,
    }
    assert b"Observed private title" not in serialized
    assert plan.content_hash == (
        "20c736074ed3946f0f9f4442bf6a725755d73a48f3502a009f5e26e2f86edb53"
    )
    assert str(plan.id) == "b7825c32-e69a-5abf-872d-16ecfdc77d7b"


def test_plan_builder_rejects_corrupted_content_addressed_candidate() -> None:
    candidate = replace(_candidate(), content_hash=_sha("e"))
    review = _review(candidate, MetadataCorrectionReviewState.ACCEPTED)

    with pytest.raises(ValueError, match="content hash"):
        _plan(candidate, review)


def test_serialized_payloads_are_valid_minimal_canonical_json() -> None:
    candidate = _candidate()
    plan = _plan(candidate, _review(candidate, MetadataCorrectionReviewState.PENDING))

    for serialized in (
        serialize_metadata_correction_candidate(candidate),
        serialize_metadata_correction_plan(plan),
    ):
        assert b"\n" not in serialized
        assert b": " not in serialized
        assert json.loads(serialized.decode("utf-8"))


def test_selection_fingerprint_binds_order_and_provenance() -> None:
    correction = _title_correction()
    changed_source = replace(
        correction.selected_values[0],
        source_ref=_ref("VALUE_ASSERTION", 99, "f"),
    )
    changed = metadata_field_selection_fingerprint(
        field_path=correction.field_path,
        operation=correction.operation,
        observed_values=correction.observed_values,
        selected_values=(changed_source,),
    )

    assert changed != correction.selection_fingerprint


def test_direct_invalid_field_fingerprint_becomes_a_plan_blocker() -> None:
    candidate = _candidate()
    bad_field = replace(candidate.field_corrections[0], selection_fingerprint=_sha("f"))
    draft = replace(candidate, field_corrections=(bad_field, candidate.field_corrections[1]))
    draft = replace(
        draft,
        evidence_fingerprint=metadata_correction_candidate_evidence_fingerprint(draft),
    )
    draft = replace(draft, content_hash=metadata_correction_candidate_content_hash(draft))
    draft = replace(draft, id=metadata_correction_candidate_id(draft.content_hash))
    review = _review(draft, MetadataCorrectionReviewState.ACCEPTED)
    plan = _plan(draft, review)

    assert MetadataCorrectionBlockerCode.FIELD_SELECTION_INVALID in {
        item.code for item in plan.blockers
    }


def test_direct_invalid_writer_requirement_becomes_a_plan_blocker() -> None:
    candidate = _candidate()
    bad_requirement = MetadataWriterRequirement(
        format_label=candidate.format_label,
        target_carrier=candidate.target.carrier,
        material_fingerprint=_sha("f"),
    )
    draft = replace(candidate, writer_requirement=bad_requirement)
    draft = replace(
        draft,
        evidence_fingerprint=metadata_correction_candidate_evidence_fingerprint(draft),
    )
    draft = replace(draft, content_hash=metadata_correction_candidate_content_hash(draft))
    draft = replace(draft, id=metadata_correction_candidate_id(draft.content_hash))
    review = _review(draft, MetadataCorrectionReviewState.ACCEPTED)
    plan = _plan(draft, review)

    assert MetadataCorrectionBlockerCode.WRITER_REQUIREMENT_INVALID in {
        item.code for item in plan.blockers
    }
