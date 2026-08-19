"""Golden and adversarial tests for S-EB08-02 canonical serialization."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_CANDIDATE_PROFILE,
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationCandidateSnapshot,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIntentCode,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    canonical_plan_bytes,
    consolidation_plan_content_hash,
)
from foliotone.core import EntityId, PresenceState

_HASH = "a" * 64
_STAMP = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def _plan() -> ConsolidationPlan:
    # Deliberately reverse the intent and blocker input order.
    intents = (
        ConsolidationFutureOperationIntent(
            1, ConsolidationIntentCode.PURGE, ConsolidationFileRole.CANDIDATE
        ),
        ConsolidationFutureOperationIntent(
            0, ConsolidationIntentCode.KEEP, ConsolidationFileRole.KEEPER
        ),
    )
    candidate = ConsolidationCandidateSnapshot(
        candidate_id=_id(20),
        profile=CONSOLIDATION_CANDIDATE_PROFILE,
        scan_root_id=_id(1),
        source_scan_run_id=_id(2),
        relation_candidate_id=_id(3),
        relation_fingerprint=_HASH,
        keep_preference_id=_id(4),
        keep_preference_fingerprint="b" * 64,
        keeper_file_id=_id(5),
        candidate_file_id=_id(6),
        dependency_fingerprint="c" * 64,
        precondition_fingerprint="d" * 64,
        evidence_fingerprint="e" * 64,
        candidate_set_fingerprint="f" * 64,
        intents=intents,
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    refs = (
        ConsolidationEvidenceReference(
            ConsolidationEvidenceKind.FINGERPRINT,
            "e\u0301vidence",
            ConsolidationEvidenceRole.IDENTITY,
            "1" * 64,
        ),
        ConsolidationEvidenceReference(
            ConsolidationEvidenceKind.TOOL_RESULT,
            "zeta",
            ConsolidationEvidenceRole.DEPENDENCY,
            "2" * 64,
        ),
    )
    return ConsolidationPlan(
        id=_id(99),
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=1,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=_id(1),
        source_scan_run_id=_id(2),
        identity=None,
        keeper=None,
        candidate=None,
        keep_preference=None,
        consolidation_candidate=candidate,
        dependencies=(),
        quality_evidence=(),
        required_reviews=(),
        preconditions=(),
        future_operation_intents=intents,
        blockers=(
            ConsolidationBlocker(ConsolidationBlockerCode.PROTECTED_SOURCE_ROOT),
            ConsolidationBlocker(ConsolidationBlockerCode.LINEAGE_MISMATCH, refs),
        ),
        status=ConsolidationPlanStatus.BLOCKED,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash="0" * 64,
        created_at=_STAMP,
    )


def test_canonical_bytes_and_hash_match_golden_value() -> None:
    plan = _plan()
    serialized = canonical_plan_bytes(plan)
    assert serialized.startswith(b'{"blockers":')
    assert b'"domain":"foliotone:consolidation-plan/v1"' in serialized
    assert b'"id"' not in serialized
    assert b'"created_at"' not in serialized
    assert b'"content_hash"' not in serialized
    assert consolidation_plan_content_hash(plan) == (
        "74880eef84b79c0f7c3cec078631a9eac11a254d8d5a5009e882a02fae64f591"
    )


def test_identity_and_audit_fields_are_excluded_but_material_changes_hash() -> None:
    plan = _plan()
    assert consolidation_plan_content_hash(replace(plan, id=_id(100))) == (
        consolidation_plan_content_hash(plan)
    )
    assert consolidation_plan_content_hash(
        replace(plan, created_at=datetime(2040, 1, 1, tzinfo=UTC))
    ) == consolidation_plan_content_hash(plan)
    assert consolidation_plan_content_hash(
        replace(
            plan,
            consolidation_candidate=replace(
                plan.consolidation_candidate,
                created_at=datetime(2040, 1, 1, tzinfo=UTC),
            ),
        )
    ) == consolidation_plan_content_hash(plan)
    changed = replace(
        plan,
        consolidation_candidate=replace(
            plan.consolidation_candidate, relation_fingerprint="9" * 64
        ),
    )
    assert consolidation_plan_content_hash(changed) != consolidation_plan_content_hash(plan)


def test_semantic_duplicate_collections_are_rejected() -> None:
    first = ConsolidationFutureOperationIntent(
        0, ConsolidationIntentCode.KEEP, ConsolidationFileRole.KEEPER
    )
    duplicate = _plan()
    object.__setattr__(duplicate, "future_operation_intents", (first, first))
    with pytest.raises(ValueError, match="duplicate semantic"):
        canonical_plan_bytes(duplicate)


def test_unicode_nfc_and_precondition_bindings_are_material() -> None:
    plan = _plan()
    composed_ref = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.FINGERPRINT,
        "évidence",
        ConsolidationEvidenceRole.IDENTITY,
        "1" * 64,
    )
    composed = replace(
        plan,
        blockers=(
            plan.blockers[0],
            replace(
                plan.blockers[1],
                evidence_refs=(composed_ref, plan.blockers[1].evidence_refs[1]),
            ),
        ),
    )
    assert canonical_plan_bytes(composed) == canonical_plan_bytes(plan)

    precondition = ConsolidationFilePreconditionSnapshot(
        file_role=ConsolidationFileRole.CANDIDATE,
        code=ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
        expected_file_id=_id(6),
        expected_observation_id=_id(7),
        expected_scan_root_id=_id(1),
        expected_scan_run_id=_id(2),
        expected_presence_state=PresenceState.PRESENT,
        expected_full_sha256=_HASH,
        expected_size_bytes=42,
        expected_modified_at=datetime(
            2026,
            1,
            2,
            3,
            4,
            5,
            678901,
            tzinfo=timezone(timedelta(hours=2)),
        ),
        expected_observed_at=_STAMP,
        dependency_kind=ConsolidationDependencyKind.CALIBRE,
        dependency_state=ConsolidationDependencyState.UNKNOWN,
        dependency_fingerprint="3" * 64,
        dependency_snapshot_kind="CALIBRE_SNAPSHOT",
        dependency_snapshot_id=_id(30),
    )
    with_precondition = replace(plan, preconditions=(precondition,))
    serialized = canonical_plan_bytes(with_precondition)
    assert b'"expected_modified_at":"2026-01-02T01:04:05.678901Z"' in serialized
    assert consolidation_plan_content_hash(
        replace(
            with_precondition,
            preconditions=(replace(precondition, dependency_fingerprint="4" * 64),),
        )
    ) != consolidation_plan_content_hash(with_precondition)

    object.__setattr__(precondition, "expected_modified_at", datetime(2026, 1, 2))
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_plan_bytes(with_precondition)
