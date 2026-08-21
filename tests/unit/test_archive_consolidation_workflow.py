"""Synthetic archive dependency composition for the consolidation planner."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
)
from foliotone.consolidation import (
    CONSOLIDATION_ANALYSIS_PROFILE,
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_COLLECTION_PROFILE,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ArchiveSourceDependencyBinding,
    ConsolidationBlockerCode,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionInputs,
    ConsolidationFileRole,
    ConsolidationIdentitySnapshot,
    ConsolidationPlannerInputs,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
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
from foliotone.workflows.archive_consolidation import (
    archive_aware_planner_inputs,
    build_archive_aware_consolidation_plan,
)

NOW = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("00000000-0000-4000-8000-000000000003")
RUN_ID = EntityId.parse("00000000-0000-4000-8000-000000000004")
FULL_SHA256 = "a" * 64


def _id(value: int) -> EntityId:
    return EntityId.parse(f"00000000-0000-4000-8000-{value:012d}")


def _source(role: ConsolidationFileRole) -> ConsolidationFilePreconditionInputs:
    file_id = _id(1 if role is ConsolidationFileRole.KEEPER else 2)
    observation_id = _id(11 if role is ConsolidationFileRole.KEEPER else 12)
    relative_path = f"synthetic-{role.value.lower()}.epub"
    endpoint = ConsolidationFileEndpoint(
        role,
        file_id,
        observation_id,
        ROOT_ID,
        RUN_ID,
        PresenceState.PRESENT,
        FULL_SHA256,
        10,
        NOW,
        NOW,
        "EPUB",
    )
    quality = ConsolidationQualityEvidenceSnapshot(
        id=_id(30 if role is ConsolidationFileRole.KEEPER else 31),
        role=role,
        collection_run_id=_id(40 if role is ConsolidationFileRole.KEEPER else 41),
        collection_item_id=_id(50 if role is ConsolidationFileRole.KEEPER else 51),
        observation_id=observation_id,
        scan_root_id=ROOT_ID,
        source_scan_run_id=RUN_ID,
        collection_profile=CONSOLIDATION_COLLECTION_PROFILE,
        analysis_profile=CONSOLIDATION_ANALYSIS_PROFILE,
        quality_profile="ebook-quality/v1",
        format_label="EPUB",
        assessment_fingerprint=(
            "b" if role is ConsolidationFileRole.KEEPER else "c"
        )
        * 64,
    )
    dependencies = tuple(
        ConsolidationDependency(
            role,
            kind,
            ConsolidationDependencyState.KNOWN_NONE,
            ("d" if role is ConsolidationFileRole.KEEPER else "e") * 64,
        )
        for kind in ConsolidationDependencyKind
    )
    keep = role is ConsolidationFileRole.KEEPER
    review = ConsolidationReviewSnapshot(
        review_type=(
            ReviewType.KEEP_PREFERENCE
            if keep
            else ReviewType.CONSOLIDATION_CANDIDATE
        ),
        state=ConsolidationReviewState.MISSING,
        evidence_fingerprint="4" * 64,
        candidate_set_fingerprint="5" * 64,
        candidate_kind=(
            ReviewCandidateKind.KEEP_PREFERENCE
            if keep
            else ReviewCandidateKind.CONSOLIDATION_CANDIDATE
        ),
        producer_name=(
            "ebook-keep-preference" if keep else "ebook-consolidation-candidate"
        ),
        decision_compatibility_version=(
            CONSOLIDATION_KEEP_PREFERENCE_DECISION
            if keep
            else CONSOLIDATION_CANDIDATE_DECISION
        ),
    )
    return ConsolidationFilePreconditionInputs(
        endpoint,
        FileRecord(
            file_id,
            ROOT_ID,
            relative_path,
            10,
            NOW,
            MediaType.EBOOK,
            PresenceState.PRESENT,
            NOW,
            NOW,
        ),
        FileObservation(
            observation_id,
            file_id,
            RUN_ID,
            relative_path,
            10,
            NOW,
            NOW,
        ),
        quality,
        dependencies,
        review,
    )


def _inputs() -> ConsolidationPlannerInputs:
    sources = tuple(_source(role) for role in ConsolidationFileRole)
    return ConsolidationPlannerInputs(
        plan_id=_id(80),
        consolidation_candidate_id=_id(81),
        scan_root_id=ROOT_ID,
        source_scan_run_id=RUN_ID,
        identity=ConsolidationIdentitySnapshot(
            relation_candidate_id=_id(82),
            relation_type=RelationType.EXACT_DUPLICATE,
            left_kind=EntityKind.FILE,
            right_kind=EntityKind.FILE,
            left_file_id=_id(1),
            right_file_id=_id(2),
            scan_root_id=ROOT_ID,
            source_scan_run_id=RUN_ID,
            status=MatchStatus.CONFIRMED,
            matcher_version="synthetic/v1",
            decision_compatibility_version="synthetic/v1",
            evidence_fingerprint="1" * 64,
            candidate_set_fingerprint="2" * 64,
        ),
        keep_preference=None,
        dependencies=tuple(
            item for source in sources for item in source.dependencies
        ),
        precondition_inputs=sources,
    )


def _binding(
    observation_id: EntityId | None = None,
) -> ArchiveSourceDependencyBinding:
    observation_id = _id(12) if observation_id is None else observation_id
    return ArchiveSourceDependencyBinding(
        archive_observation_id=_id(90),
        file_observation_id=observation_id,
        scan_root_id=ROOT_ID,
        source_scan_run_id=RUN_ID,
        source_ordinal=0,
        container_class=ArchiveContainerClass.GENERIC_ARCHIVE,
        publication_kind=ArchivePublicationKind.NONE,
        storage_family=ArchiveStorageFamily.ZIP,
        outer_compression_kind=ArchiveOuterCompressionKind.NONE,
        recognition_status=ArchiveRecognitionStatus.MATCHED,
        archive_content_hash="3" * 64,
    )


def test_workflow_replaces_archive_dependencies_in_all_input_slots() -> None:
    updated = archive_aware_planner_inputs(_inputs(), (_binding(),))

    archive = {
        item.file_role: item
        for item in updated.dependencies
        if item.kind is ConsolidationDependencyKind.ARCHIVE
    }
    assert archive[ConsolidationFileRole.KEEPER].state is (
        ConsolidationDependencyState.UNKNOWN
    )
    assert archive[ConsolidationFileRole.CANDIDATE].state is (
        ConsolidationDependencyState.KNOWN_PRESENT
    )
    assert archive[ConsolidationFileRole.CANDIDATE].snapshot_id == _id(90)
    for source in updated.precondition_inputs:
        assert tuple(
            item
            for item in updated.dependencies
            if item.file_role is source.file_endpoint.role
        ) == source.dependencies


def test_candidate_archive_source_is_a_non_execution_blocker() -> None:
    plan = build_archive_aware_consolidation_plan(
        _inputs(), (_binding(),), clock=lambda: NOW
    )

    assert plan.execution_state.value == "NOT_EXECUTABLE"
    assert ConsolidationBlockerCode.ARCHIVE_MEMBERSHIP_PRESENT in {
        item.code for item in plan.blockers
    }


def test_missing_archive_source_remains_unknown_and_blocked() -> None:
    plan = build_archive_aware_consolidation_plan(_inputs(), (), clock=lambda: NOW)

    assert ConsolidationBlockerCode.ARCHIVE_RELATIONSHIP_UNKNOWN in {
        item.code for item in plan.blockers
    }


def test_foreign_or_non_actionable_material_fails_before_planning() -> None:
    with pytest.raises(ValueError, match="directed endpoints"):
        archive_aware_planner_inputs(_inputs(), (_binding(_id(99)),))
    with pytest.raises(ValueError, match="actionable"):
        archive_aware_planner_inputs(replace(_inputs(), identity=None), ())
    inputs = _inputs()
    foreign_source = replace(
        inputs.precondition_inputs[0],
        file_endpoint=replace(
            inputs.precondition_inputs[0].file_endpoint, scan_root_id=_id(99)
        ),
    )
    with pytest.raises(ValueError, match="foreign lineage"):
        archive_aware_planner_inputs(
            replace(
                inputs,
                precondition_inputs=(
                    foreign_source,
                    inputs.precondition_inputs[1],
                ),
            ),
            (),
        )
