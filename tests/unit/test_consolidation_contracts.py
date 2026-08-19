"""Focused synthetic contract tests for S-EB08-01."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_FORMATS,
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    CONSOLIDATION_PLAN_VERSION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationCandidateSnapshot,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationIntentCode,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationQualityEvidenceSnapshot,
    KeepPreferenceOutcome,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    MatchStatus,
    PresenceState,
    RelationType,
)

_STAMP = datetime(2026, 1, 1, tzinfo=UTC)
_HASH = "a" * 64


def _id(number: int) -> EntityId:
    return EntityId(UUID(f"00000000-0000-0000-0000-{number:012d}"))


def _ref(number: int = 1) -> ConsolidationEvidenceReference:
    return ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.FINGERPRINT,
        f"evidence-{number}",
        ConsolidationEvidenceRole.IDENTITY,
        _HASH,
    )


def test_public_literals_are_exact_and_plans_are_never_executable() -> None:
    assert tuple(item.value for item in ConsolidationPlanStatus) == (
        "BLOCKED",
        "REVIEW_REQUIRED",
        "APPROVED_NON_EXECUTABLE",
    )
    assert tuple(item.value for item in ConsolidationExecutionState) == ("NOT_EXECUTABLE",)
    assert tuple(item.value for item in ConsolidationBlockerCode) == (
        "IDENTITY_NOT_ACTIONABLE",
        "IDENTITY_NOT_CONFIRMED",
        "LINEAGE_MISMATCH",
        "PRECONDITION_INCOMPLETE",
        "PROTECTED_SOURCE_ROOT",
        "QUALITY_EVIDENCE_INCOMPLETE",
        "KEEP_PREFERENCE_UNRESOLVED",
        "KEEP_PREFERENCE_REVIEW_MISSING",
        "KEEP_PREFERENCE_REVIEW_REJECTED",
        "CONSOLIDATION_REVIEW_MISSING",
        "CONSOLIDATION_REVIEW_REJECTED",
        "CALIBRE_RELATIONSHIP_UNKNOWN",
        "CALIBRE_OWNERSHIP_PRESENT",
        "SIDECAR_RELATIONSHIP_UNKNOWN",
        "SIDECAR_DEPENDENCY_PRESENT",
        "ARCHIVE_RELATIONSHIP_UNKNOWN",
        "ARCHIVE_MEMBERSHIP_PRESENT",
    )
    assert CONSOLIDATION_FORMATS == ("EPUB", "MOBI", "AZW", "AZW3", "PDF")


def test_identity_and_endpoint_boundaries_are_enforced() -> None:
    left, right = _id(1), _id(2)
    identity = ConsolidationIdentitySnapshot(
        _id(3),
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        EntityKind.FILE,
        left,
        right,
        _id(4),
        _id(5),
        MatchStatus.CONFIRMED,
        "matcher/v1",
        "decision/v1",
        _HASH,
        _HASH,
    )
    endpoint = ConsolidationFileEndpoint(
        ConsolidationFileRole.KEEPER,
        left,
        _id(6),
        _id(4),
        _id(5),
        PresenceState.PRESENT,
        _HASH,
        42,
        _STAMP,
        _STAMP,
        "epub",
    )
    assert identity.left_file_id == left
    assert endpoint.format_label == "EPUB"
    blocked_identity = ConsolidationIdentitySnapshot(
        _id(8),
        RelationType.SAME_WORK,
        EntityKind.WORK,
        EntityKind.WORK,
        left,
        right,
        _id(4),
        _id(5),
        MatchStatus.REVIEW_REQUIRED,
        "matcher/v1",
        "decision/v1",
        _HASH,
        _HASH,
    )
    assert blocked_identity.status is MatchStatus.REVIEW_REQUIRED
    with pytest.raises(ValueError, match="canonically ordered"):
        ConsolidationIdentitySnapshot(
            _id(3),
            RelationType.EXACT_DUPLICATE,
            EntityKind.FILE,
            EntityKind.FILE,
            right,
            left,
            _id(4),
            _id(5),
            MatchStatus.CONFIRMED,
            "matcher/v1",
            "decision/v1",
            _HASH,
            _HASH,
        )
    with pytest.raises(ValueError, match="PRESENT"):
        ConsolidationFileEndpoint(
            ConsolidationFileRole.CANDIDATE,
            right,
            _id(7),
            _id(4),
            _id(5),
            PresenceState.MISSING,
            _HASH,
            42,
            _STAMP,
            _STAMP,
            "EPUB",
        )


def test_preference_candidate_review_and_privacy_contracts() -> None:
    left, right = _id(1), _id(2)
    quality = (
        # Snapshot construction is deliberately kept to the opaque, path-free fields.
        ConsolidationQualityEvidenceSnapshot(
            _id(10),
            ConsolidationFileRole.KEEPER,
            _id(11),
            _id(12),
            _id(6),
            _id(4),
            _id(5),
            CONSOLIDATION_COLLECTION_PROFILE,
            CONSOLIDATION_ANALYSIS_PROFILE,
            "ebook-quality/v1",
            "EPUB",
            _HASH,
        ),
        ConsolidationQualityEvidenceSnapshot(
            _id(13),
            ConsolidationFileRole.CANDIDATE,
            _id(14),
            _id(15),
            _id(7),
            _id(4),
            _id(5),
            CONSOLIDATION_COLLECTION_PROFILE,
            CONSOLIDATION_ANALYSIS_PROFILE,
            "ebook-quality/v1",
            "PDF",
            _HASH,
        ),
    )
    outcome = KeepPreferenceOutcome(
        _id(20),
        "ebook-keep-preference/v1",
        "1",
        left,
        _id(6),
        right,
        _id(7),
        KeepPreferenceStatus.PREFERRED,
        left,
        right,
        (KeepPreferenceReasonCode.PREFERRED_FORMAT,),
        _HASH,
        _HASH,
        quality,
        _HASH,
    )
    candidate = ConsolidationCandidateSnapshot(
        _id(30),
        "ebook-consolidation-candidate/v1",
        _id(4),
        _id(5),
        _id(3),
        _HASH,
        _id(20),
        _HASH,
        left,
        right,
        _HASH,
        _HASH,
        _HASH,
        _HASH,
        (  # KEEP is the only intent that addresses the keeper.
            ConsolidationFutureOperationIntent(
                0,
                ConsolidationIntentCode.KEEP,
                ConsolidationFileRole.KEEPER,
            ),
        ),
    )
    assert outcome.keeper_file_id == left
    assert candidate.candidate_file_id == right
    assert _HASH not in repr(outcome)
    identity = ConsolidationIdentitySnapshot(
        _id(3),
        RelationType.EXACT_DUPLICATE,
        EntityKind.FILE,
        EntityKind.FILE,
        left,
        right,
        _id(4),
        _id(5),
        MatchStatus.CONFIRMED,
        "matcher/v1",
        "decision/v1",
        _HASH,
        _HASH,
    )
    keeper = ConsolidationFileEndpoint(
        ConsolidationFileRole.KEEPER,
        left,
        _id(6),
        _id(4),
        _id(5),
        PresenceState.PRESENT,
        _HASH,
        42,
        _STAMP,
        _STAMP,
        "EPUB",
    )
    removed_candidate = ConsolidationFileEndpoint(
        ConsolidationFileRole.CANDIDATE,
        right,
        _id(7),
        _id(4),
        _id(5),
        PresenceState.PRESENT,
        _HASH,
        42,
        _STAMP,
        _STAMP,
        "PDF",
    )
    plan = ConsolidationPlan(
        _id(40),
        CONSOLIDATION_PLAN_PROFILE,
        CONSOLIDATION_PLAN_VERSION,
        CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        _id(4),
        _id(5),
        identity,
        keeper,
        removed_candidate,
        outcome,
        candidate,
        (),
        quality,
        (),
        (),
        candidate.intents,
        (),
        ConsolidationPlanStatus.REVIEW_REQUIRED,
        ConsolidationExecutionState.NOT_EXECUTABLE,
        _HASH,
        _STAMP,
    )
    with pytest.raises(ValueError, match="candidate endpoints"):
        replace(
            plan,
            consolidation_candidate=replace(
                candidate,
                keeper_file_id=right,
                candidate_file_id=left,
            ),
        )
    with pytest.raises(ValueError, match="candidate intents"):
        replace(plan, consolidation_candidate=replace(candidate, intents=()))
    with pytest.raises(ValueError, match="quality evidence"):
        replace(
            plan,
            quality_evidence=(
                replace(quality[0], assessment_fingerprint="b" * 64),
                quality[1],
            ),
        )
    with pytest.raises((AttributeError, TypeError)):
        outcome.status = KeepPreferenceStatus.TIED  # type: ignore[misc]


def test_bounds_privacy_and_blocked_plan_snapshot() -> None:
    blocker = ConsolidationBlocker(ConsolidationBlockerCode.LINEAGE_MISMATCH, (_ref(),))
    assert blocker.evidence_refs == (_ref(),)
    private_ref = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.TOOL_RESULT,
        "private/path/book.epub",
        ConsolidationEvidenceRole.DEPENDENCY,
        _HASH,
    )
    assert "private/path" not in repr(private_ref)
    with pytest.raises(ValueError, match="configured limit"):
        ConsolidationBlocker(
            ConsolidationBlockerCode.LINEAGE_MISMATCH,
            tuple(_ref(i) for i in range(65)),
        )
    blocked_identity = ConsolidationIdentitySnapshot(
        relation_candidate_id=_id(70),
        relation_type=RelationType.SAME_EDITION,
        left_kind=EntityKind.EDITION,
        right_kind=EntityKind.EDITION,
        left_file_id=_id(71),
        right_file_id=_id(72),
        scan_root_id=_id(4),
        source_scan_run_id=_id(5),
        status=MatchStatus.REVIEW_REQUIRED,
        matcher_version="matcher/v1",
        decision_compatibility_version="decision/v1",
        evidence_fingerprint=_HASH,
        candidate_set_fingerprint=_HASH,
    )
    plan = ConsolidationPlan(
        id=_id(80),
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=CONSOLIDATION_PLAN_VERSION,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=_id(4),
        source_scan_run_id=_id(5),
        identity=blocked_identity,
        keeper=None,
        candidate=None,
        keep_preference=None,
        consolidation_candidate=None,
        dependencies=(),
        quality_evidence=(),
        required_reviews=(),
        preconditions=(),
        future_operation_intents=(),
        blockers=(
            ConsolidationBlocker(ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE),
        ),
        status=ConsolidationPlanStatus.BLOCKED,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash=_HASH,
        created_at=_STAMP,
    )
    assert plan.status is ConsolidationPlanStatus.BLOCKED
    assert plan.keeper is None
