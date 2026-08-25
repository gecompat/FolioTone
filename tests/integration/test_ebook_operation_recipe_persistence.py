"""Focused synthetic coverage for S-W9-007B persistence and S-W9-007C reports."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from foliotone.cli.main import build_parser, main
from foliotone.core import (
    EntityId,
    EntityKind,
    PresenceState,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ScanRunStatus,
)
from foliotone.ebook_operation_recipes import (
    EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY,
    EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
    EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationEvidenceReference,
    EbookOperationKind,
    EbookOperationPlanStatus,
    EbookOperationProcessorKind,
    EbookOperationRecipeCandidate,
    EbookOperationRecipeCandidateInputs,
    EbookOperationRecipePlan,
    EbookOperationRecipePlanInputs,
    EbookOperationReviewSnapshot,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationSourceSnapshot,
    EbookOperationTargetSnapshot,
    build_ebook_operation_expected_output,
    build_ebook_operation_processor_requirement,
    build_ebook_operation_recipe_candidate,
    build_ebook_operation_recipe_plan,
    build_ebook_operation_source_snapshot,
    ebook_operation_recipe_plan_content_hash,
    ebook_operation_recipe_plan_id,
    operation_target_kind,
)
from foliotone.persistence import (
    EbookOperationRecipeStoreError,
    SQLiteEbookOperationRecipeStore,
    SQLiteResolutionReviewStore,
    alembic_config,
    consolidation_schema,
    create_sqlite_engine,
    migrate,
    schema,
)
from foliotone.persistence import ebook_operation_recipe_schema as recipe_schema
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence.ebook_operation_recipe_report import (
    EbookOperationRecipePlanReport,
    SQLiteEbookOperationRecipePlanReportReader,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("a1000000-0000-0000-0000-000000000001")
SCAN_ID = EntityId.parse("a2000000-0000-0000-0000-000000000001")
FILE_IDS = (
    EntityId.parse("a3000000-0000-0000-0000-000000000001"),
    EntityId.parse("a3000000-0000-0000-0000-000000000002"),
)
OBSERVATION_IDS = (
    EntityId.parse("a4000000-0000-0000-0000-000000000001"),
    EntityId.parse("a4000000-0000-0000-0000-000000000002"),
)
FINGERPRINT_IDS = (
    EntityId.parse("a5000000-0000-0000-0000-000000000001"),
    EntityId.parse("a5000000-0000-0000-0000-000000000002"),
)
TOOL_EXECUTION_ID = EntityId.parse("a6000000-0000-0000-0000-000000000001")
TOOL_RESULT_ID = EntityId.parse("a7000000-0000-0000-0000-000000000001")
PRIVATE_LOCATORS = (
    "private/synthetic-secret-primary.epub",
    "private/synthetic-secret-companion.epub",
)


def _sha(character: str) -> str:
    return character * 64


def _seed_sources(engine: Engine, *, count: int = 2) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {
                "id": str(ROOT_ID),
                "name": "synthetic-operation-recipe-root",
                "media_type": "EBOOK",
                "enabled": True,
            },
        )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(SCAN_ID),
                "scan_root_id": str(ROOT_ID),
                "started_at": (NOW - timedelta(minutes=1)).isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
            },
        )
        for ordinal in range(count):
            connection.execute(
                insert(schema.file_records),
                {
                    "id": str(FILE_IDS[ordinal]),
                    "scan_root_id": str(ROOT_ID),
                    "relative_path": PRIVATE_LOCATORS[ordinal],
                    "size_bytes": 4096 + ordinal,
                    "modified_at": NOW.isoformat(),
                    "media_type": "EBOOK",
                    "presence_state": "PRESENT",
                    "first_seen_at": NOW.isoformat(),
                    "last_seen_at": NOW.isoformat(),
                    "missing_since_at": None,
                    "consecutive_missing_scans": 0,
                },
            )
            connection.execute(
                insert(schema.file_observations),
                {
                    "id": str(OBSERVATION_IDS[ordinal]),
                    "file_id": str(FILE_IDS[ordinal]),
                    "scan_run_id": str(SCAN_ID),
                    "relative_path": PRIVATE_LOCATORS[ordinal],
                    "size_bytes": 4096 + ordinal,
                    "modified_at": NOW.isoformat(),
                    "observed_at": NOW.isoformat(),
                },
            )
            connection.execute(
                insert(schema.fingerprints),
                {
                    "id": str(FINGERPRINT_IDS[ordinal]),
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(OBSERVATION_IDS[ordinal]),
                    "kind": "FILE_SHA256",
                    "algorithm": "sha256",
                    "algorithm_version": "1",
                    "value": _sha(chr(ord("a") + ordinal)),
                    "created_at": NOW.isoformat(),
                    "tool_execution_id": None,
                },
            )
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(TOOL_EXECUTION_ID),
                "provider_id": "synthetic-recipe-reader",
                "tool_version": "1",
                "adapter_version": "test/1",
                "capability": "READ_METADATA",
                "input_identity": f"file-observation:{OBSERVATION_IDS[0]}",
                "config_identity": "synthetic",
                "started_at": NOW.isoformat(),
                "finished_at": NOW.isoformat(),
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            },
        )
        connection.execute(
            insert(schema.tool_results),
            {
                "id": str(TOOL_RESULT_ID),
                "execution_id": str(TOOL_EXECUTION_ID),
                "result_type": "synthetic-recipe-evidence",
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(OBSERVATION_IDS[0]),
                "key": "operation_candidate",
                "value": "synthetic",
                "confidence": 1.0,
                "explanation": "synthetic evidence",
            },
        )


def _source(
    ordinal: int,
    role: EbookOperationSourceRole,
) -> EbookOperationSourceSnapshot:
    return build_ebook_operation_source_snapshot(
        ordinal=ordinal,
        role=role,
        scan_root_id=ROOT_ID,
        source_scan_run_id=SCAN_ID,
        source_scan_run_status=ScanRunStatus.COMPLETED,
        file_id=FILE_IDS[ordinal],
        observation_id=OBSERVATION_IDS[ordinal],
        relative_locator=PRIVATE_LOCATORS[ordinal],
        format_label="EPUB",
        expected_presence_state=PresenceState.PRESENT,
        expected_full_sha256=_sha(chr(ord("a") + ordinal)),
        expected_size_bytes=4096 + ordinal,
        expected_modified_at=NOW,
        expected_observed_at=NOW,
    )


def _candidate(
    *,
    operation_kind: EbookOperationKind = EbookOperationKind.FILE_RENAME,
    created_at: datetime = NOW,
    extra_evidence: tuple[EbookOperationEvidenceReference, ...] = (),
) -> EbookOperationRecipeCandidate:
    archive = operation_kind is EbookOperationKind.ARCHIVE_REWRITE
    sources = (
        (
            _source(0, EbookOperationSourceRole.PRIMARY),
            _source(1, EbookOperationSourceRole.COMPANION),
        )
        if archive
        else (_source(0, EbookOperationSourceRole.PRIMARY),)
    )
    target_locator = PRIVATE_LOCATORS[0] if archive else "private/synthetic-secret-renamed.epub"
    target = EbookOperationTargetSnapshot(
        kind=operation_target_kind(operation_kind),
        scope_id=ROOT_ID,
        relative_locator=target_locator,
        target_state_fingerprint=_sha("d"),
    )
    processor = build_ebook_operation_processor_requirement(
        kind=(
            EbookOperationProcessorKind.TOOL_PROVIDER
            if archive
            else EbookOperationProcessorKind.FOLIOTONE_NATIVE
        ),
        processor_profile=(
            "deterministic-archive-rewrite/v1" if archive else "byte-preserving-file-operation/v1"
        ),
        configuration_fingerprint=_sha("c"),
        provider_id="synthetic-provider" if archive else None,
        tool_version="1.2.3" if archive else None,
        adapter_version="adapter-v1" if archive else None,
    )
    expected = build_ebook_operation_expected_output(
        operation_kind=operation_kind,
        format_label="EPUB",
        expected_full_sha256=_sha("e") if archive else _sha("a"),
        expected_size_bytes=8192 if archive else 4096,
    )
    dependencies = tuple(
        EbookOperationDependencySnapshot(
            kind=kind,
            state=EbookOperationDependencyState.KNOWN_NONE,
            snapshot_kind=f"ebook-{kind.value.lower()}-dependency/v1",
            snapshot_id=OBSERVATION_IDS[0],
            material_fingerprint=_sha(str(ordinal + 1)),
        )
        for ordinal, kind in enumerate(EbookOperationDependencyKind)
    )
    evidence = [
        EbookOperationEvidenceReference(
            kind="FILE_OBSERVATION",
            ref_id=OBSERVATION_IDS[0],
            material_fingerprint=_sha("6"),
        ),
        EbookOperationEvidenceReference(
            kind="FINGERPRINT",
            ref_id=FINGERPRINT_IDS[0],
            material_fingerprint=_sha("7"),
        ),
        EbookOperationEvidenceReference(
            kind="TOOL_RESULT",
            ref_id=TOOL_RESULT_ID,
            material_fingerprint=_sha("8"),
        ),
    ]
    if archive:
        evidence.extend(
            (
                EbookOperationEvidenceReference(
                    kind="FILE_OBSERVATION",
                    ref_id=OBSERVATION_IDS[1],
                    material_fingerprint=_sha("9"),
                ),
                EbookOperationEvidenceReference(
                    kind="FINGERPRINT",
                    ref_id=FINGERPRINT_IDS[1],
                    material_fingerprint=_sha("b"),
                ),
            )
        )
    evidence.extend(extra_evidence)
    return build_ebook_operation_recipe_candidate(
        EbookOperationRecipeCandidateInputs(
            operation_kind=operation_kind,
            sources=sources,
            target=target,
            expected_output=expected,
            processor_requirement=processor,
            dependencies=dependencies,
            evidence_refs=tuple(evidence),
        ),
        clock=lambda: created_at,
    )


def _review_item(
    candidate: EbookOperationRecipeCandidate,
    *,
    created_at: datetime = NOW,
) -> ReviewItem:
    return ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.EBOOK_OPERATION_RECIPE,
        subject_kind=EntityKind.FILE,
        subject_id=candidate.sources[0].file_id,
        candidate_kind=ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE,
        candidate_id=candidate.id,
        producer_name=EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
        producer_version=EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
        decision_compatibility_version=(EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY),
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.content_hash,
        state=ReviewItemState.PENDING,
        created_at=created_at,
    )


def _plan(
    candidate: EbookOperationRecipeCandidate,
    review: EbookOperationReviewSnapshot,
    *,
    created_at: datetime = NOW,
) -> EbookOperationRecipePlan:
    return build_ebook_operation_recipe_plan(
        EbookOperationRecipePlanInputs(
            candidate=candidate,
            review=review,
            lineage_matches=True,
            source_evidence_complete=True,
            target_valid=True,
            output_identity_valid=True,
            processor_requirement_valid=True,
            preconditions_complete=True,
            recovery_contract_complete=True,
            verification_contract_complete=True,
        ),
        clock=lambda: created_at,
    )


def test_migration_0030_preserves_review_history_and_old_triggers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operation-recipe-migration.db"
    migrate(database, "0029_metadata_write_reconciliation")
    engine = create_sqlite_engine(database)
    item_id = EntityId.new()
    decision_id = EntityId.new()
    plan_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {
                "id": str(ROOT_ID),
                "name": "synthetic-existing-review-root",
                "media_type": "EBOOK",
                "enabled": True,
            },
        )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(SCAN_ID),
                "scan_root_id": str(ROOT_ID),
                "started_at": NOW.isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(consolidation_schema.consolidation_plans),
            {
                "id": str(plan_id),
                "profile": "consolidation-plan/v1",
                "plan_version": 1,
                "serializer_version": "canonical-json/v1",
                "scan_root_id": str(ROOT_ID),
                "source_scan_run_id": str(SCAN_ID),
                "relation_candidate_id": None,
                "keep_preference_id": None,
                "consolidation_candidate_id": None,
                "keeper_file_id": None,
                "keeper_observation_id": None,
                "candidate_file_id": None,
                "candidate_observation_id": None,
                "status": "BLOCKED",
                "execution_state": "NOT_EXECUTABLE",
                "content_hash": _sha("e"),
                "created_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(review_schema.review_items),
            {
                "id": str(item_id),
                "review_type": "CLASSIFICATION",
                "subject_kind": "WORK",
                "subject_id": str(EntityId.new()),
                "candidate_kind": "CLASSIFICATION_ASSERTION",
                "candidate_id": str(EntityId.new()),
                "producer_name": "synthetic-existing-review",
                "producer_version": "1",
                "decision_compatibility_version": "synthetic/v1",
                "evidence_fingerprint": _sha("1"),
                "candidate_set_fingerprint": _sha("2"),
                "state": "DECIDED",
                "created_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(review_schema.review_decisions),
            {
                "id": str(decision_id),
                "review_item_id": str(item_id),
                "sequence_no": 1,
                "decision": "ACCEPT",
                "decision_reason": "SYNTHETIC_ACCEPT",
                "evidence_fingerprint": _sha("1"),
                "candidate_set_fingerprint": _sha("2"),
                "decision_compatibility_version": "synthetic/v1",
                "actor_kind": "USER",
                "decided_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(consolidation_schema.consolidation_plan_reviews),
            {
                "plan_id": str(plan_id),
                "ordinal": 0,
                "review_type": "KEEP_PREFERENCE",
                "state": "ACCEPTED",
                "review_item_id": str(item_id),
                "decision_id": str(decision_id),
                "decision_sequence_no": 1,
                "producer_name": "synthetic-existing-review",
                "producer_version": "1",
                "decision_compatibility_version": "synthetic/v1",
                "evidence_fingerprint": _sha("1"),
                "candidate_set_fingerprint": _sha("2"),
            },
        )
    engine.dispose()

    migrate(database)
    upgraded = create_sqlite_engine(database)
    with upgraded.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        retained = connection.execute(
            select(review_schema.review_decisions.c.id).where(
                review_schema.review_decisions.c.id == str(decision_id)
            )
        ).scalar_one()
        retained_plan_review = connection.execute(
            select(consolidation_schema.consolidation_plan_reviews.c.plan_id).where(
                consolidation_schema.consolidation_plan_reviews.c.plan_id == str(plan_id)
            )
        ).scalar_one()
        review_ddl = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='review_items'")
        ).scalar_one()
        restored_trigger = connection.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name='metadata_correction_plan_reviews_no_update'"
            )
        ).scalar_one()
    assert revision == "0034_ebook_rename_operator_jobs"
    assert retained == str(decision_id)
    assert retained_plan_review == str(plan_id)
    assert restored_trigger == "metadata_correction_plan_reviews_no_update"
    assert "EBOOK_OPERATION_RECIPE" in review_ddl
    assert {table.name for table in recipe_schema.EBOOK_OPERATION_RECIPE_TABLES} <= set(
        inspect(upgraded).get_table_names()
    )
    upgraded.dispose()

    command.downgrade(
        alembic_config(database),
        "0029_metadata_write_reconciliation",
    )
    downgraded = create_sqlite_engine(database)
    with downgraded.connect() as connection:
        retained_after = connection.execute(
            select(review_schema.review_decisions.c.id).where(
                review_schema.review_decisions.c.id == str(decision_id)
            )
        ).scalar_one()
        review_ddl_after = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='review_items'")
        ).scalar_one()
    assert retained_after == str(decision_id)
    assert "EBOOK_OPERATION_RECIPE" not in review_ddl_after
    assert not (
        {table.name for table in recipe_schema.EBOOK_OPERATION_RECIPE_TABLES}
        & set(inspect(downgraded).get_table_names())
    )
    downgraded.dispose()


def test_candidate_roundtrip_is_bounded_immutable_and_idempotent(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine)
    store = SQLiteEbookOperationRecipeStore(engine)
    candidate = _candidate(operation_kind=EbookOperationKind.ARCHIVE_REWRITE)

    assert store.create_or_get_candidate(candidate) == candidate
    assert store.get_candidate(candidate.id) == candidate
    retry = _candidate(
        operation_kind=EbookOperationKind.ARCHIVE_REWRITE,
        created_at=NOW + timedelta(hours=1),
    )
    assert retry.id == candidate.id
    assert store.create_or_get_candidate(retry) == candidate

    with engine.begin() as connection:
        with pytest.raises(Exception, match="operation recipe rows are immutable"):
            connection.execute(
                recipe_schema.ebook_operation_recipe_candidates.update()
                .where(recipe_schema.ebook_operation_recipe_candidates.c.id == str(candidate.id))
                .values(target_relative_locator="changed/private.epub")
            )
        with pytest.raises(Exception, match="child exceeds parent count"):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_evidence),
                {
                    "candidate_id": str(candidate.id),
                    "ordinal": len(candidate.evidence_refs),
                    "kind": "FILE_OBSERVATION",
                    "ref_id": str(OBSERVATION_IDS[0]),
                    "material_fingerprint": _sha("f"),
                },
            )
    engine.dispose()
    with pytest.raises(RuntimeError, match="operation recipe data prevents"):
        command.downgrade(
            alembic_config(head_database),
            "0029_metadata_write_reconciliation",
        )


def test_review_and_plan_roundtrip_bind_latest_compatible_decision(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine, count=1)
    recipe_store = SQLiteEbookOperationRecipeStore(engine)
    candidate = recipe_store.create_or_get_candidate(_candidate())
    review_store = SQLiteResolutionReviewStore(engine)
    item = review_store.enqueue_or_get_review(_review_item(candidate))

    pending = recipe_store.get_latest_review(candidate.id)
    assert pending.state is EbookOperationReviewState.PENDING
    assert pending.review_item_id == item.id
    pending_plan = _plan(candidate, pending)
    assert pending_plan.status is EbookOperationPlanStatus.REVIEW_REQUIRED
    assert recipe_store.create_or_get_plan(pending_plan) == pending_plan

    decision = ReviewDecision(
        id=EntityId.new(),
        review_item_id=item.id,
        sequence_no=1,
        decision=ReviewDecisionValue.ACCEPT,
        decision_reason="USER_CONFIRMED",
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.content_hash,
        decision_compatibility_version=(EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY),
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW + timedelta(minutes=1),
    )
    review_store.append_decision(decision, expected_latest_decision_id=None)
    assert recipe_store.get_plan(pending_plan.id) == pending_plan

    accepted = recipe_store.get_latest_review(candidate.id)
    assert accepted.state is EbookOperationReviewState.ACCEPTED
    assert accepted.decision_id == decision.id
    approved = _plan(candidate, accepted, created_at=NOW + timedelta(minutes=2))
    assert approved.status is EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
    assert recipe_store.create_or_get_plan(approved) == approved
    assert recipe_store.get_plan(approved.id) == approved
    retry = _plan(candidate, accepted, created_at=NOW + timedelta(hours=1))
    assert recipe_store.create_or_get_plan(retry) == approved
    approved_report = SQLiteEbookOperationRecipePlanReportReader(engine).read(approved.id)
    assert approved_report.review_status == "ACCEPTED"
    assert approved_report.counts.review_items == 1
    assert approved_report.counts.decisions == 1
    assert approved_report.counts.blockers == 0
    assert approved_report.blocker_codes == ()

    changed = replace(
        approved.preconditions[0],
        expected_fingerprint=_sha("f"),
    )
    invalid_draft = replace(
        approved,
        preconditions=(changed, *approved.preconditions[1:]),
        content_hash=_sha("0"),
    )
    invalid_hash = ebook_operation_recipe_plan_content_hash(invalid_draft)
    invalid = replace(
        invalid_draft,
        id=ebook_operation_recipe_plan_id(invalid_hash),
        content_hash=invalid_hash,
    )
    with pytest.raises(EbookOperationRecipeStoreError, match="canonical reducer"):
        recipe_store.create_or_get_plan(invalid)
    with pytest.raises(
        EbookOperationRecipeStoreError,
        match="latest compatible review",
    ):
        recipe_store.create_or_get_plan(pending_plan)
    assert review_store.list_queue(review_type=ReviewType.EBOOK_OPERATION_RECIPE).items == ()
    engine.dispose()


def test_missing_evidence_rolls_back_without_private_details(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine, count=1)
    with engine.begin() as connection:
        connection.execute(
            schema.tool_results.delete().where(schema.tool_results.c.id == str(TOOL_RESULT_ID))
        )
    store = SQLiteEbookOperationRecipeStore(engine)
    candidate = _candidate()
    with pytest.raises(EbookOperationRecipeStoreError) as failure:
        store.create_or_get_candidate(candidate)
    message = str(failure.value)
    assert PRIVATE_LOCATORS[0] not in message
    assert candidate.sources[0].expected_full_sha256 not in message
    assert candidate.target.target_state_fingerprint not in message
    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(recipe_schema.ebook_operation_recipe_candidates)
        ).scalar_one()
    assert count == 0
    engine.dispose()


def test_database_failure_rolls_back_without_private_parameters(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine, count=1)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER ebook_operation_recipe_sources_synthetic_failure "
            "BEFORE INSERT ON ebook_operation_recipe_sources "
            "BEGIN SELECT RAISE(ABORT, 'synthetic source persistence failure'); END"
        )

    candidate = _candidate()
    store = SQLiteEbookOperationRecipeStore(engine)
    with pytest.raises(EbookOperationRecipeStoreError) as failure:
        store.create_or_get_candidate(candidate)
    assert str(failure.value) == "operation recipe database transaction failed"
    assert PRIVATE_LOCATORS[0] not in str(failure.value)
    assert failure.value.__cause__ is None
    assert failure.value.__suppress_context__ is True
    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(recipe_schema.ebook_operation_recipe_candidates)
        ).scalar_one()
    assert count == 0
    engine.dispose()


def test_review_decision_evidence_requires_source_file_lineage(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine)
    item_id = EntityId.new()
    decision_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(review_schema.review_items),
            {
                "id": str(item_id),
                "review_type": "CLASSIFICATION",
                "subject_kind": "FILE",
                "subject_id": str(FILE_IDS[1]),
                "candidate_kind": "CLASSIFICATION_ASSERTION",
                "candidate_id": str(EntityId.new()),
                "producer_name": "synthetic-foreign-review",
                "producer_version": "1",
                "decision_compatibility_version": "synthetic/v1",
                "evidence_fingerprint": _sha("1"),
                "candidate_set_fingerprint": _sha("2"),
                "state": "DECIDED",
                "created_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(review_schema.review_decisions),
            {
                "id": str(decision_id),
                "review_item_id": str(item_id),
                "sequence_no": 1,
                "decision": "ACCEPT",
                "decision_reason": "SYNTHETIC_ACCEPT",
                "evidence_fingerprint": _sha("1"),
                "candidate_set_fingerprint": _sha("2"),
                "decision_compatibility_version": "synthetic/v1",
                "actor_kind": "USER",
                "decided_at": NOW.isoformat(),
            },
        )

    candidate = _candidate(
        extra_evidence=(
            EbookOperationEvidenceReference(
                kind="REVIEW_DECISION",
                ref_id=decision_id,
                material_fingerprint=_sha("f"),
            ),
        )
    )
    store = SQLiteEbookOperationRecipeStore(engine)
    with pytest.raises(EbookOperationRecipeStoreError, match="foreign lineage"):
        store.create_or_get_candidate(candidate)
    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(recipe_schema.ebook_operation_recipe_candidates)
        ).scalar_one()
    assert count == 0
    engine.dispose()


def test_recipe_review_pair_is_exact_in_domain_store_and_database(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_sources(engine, count=1)
    candidate = SQLiteEbookOperationRecipeStore(engine).create_or_get_candidate(_candidate())
    store = SQLiteResolutionReviewStore(engine)
    valid = _review_item(candidate)
    assert store.enqueue_or_get_review(valid) == valid
    with pytest.raises(ValueError, match="operation recipe"):
        replace(
            valid,
            id=EntityId.new(),
            review_type=ReviewType.CLASSIFICATION,
        )
    with pytest.raises(Exception, match="does not match candidate"):
        store.enqueue_or_get_review(
            replace(valid, id=EntityId.new(), producer_name="foreign-producer")
        )
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(review_schema.review_items),
                {
                    "id": str(EntityId.new()),
                    "review_type": "CLASSIFICATION",
                    "subject_kind": "FILE",
                    "subject_id": str(FILE_IDS[0]),
                    "candidate_kind": "EBOOK_OPERATION_RECIPE_CANDIDATE",
                    "candidate_id": str(candidate.id),
                    "producer_name": EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
                    "producer_version": EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
                    "decision_compatibility_version": (
                        EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY
                    ),
                    "evidence_fingerprint": candidate.evidence_fingerprint,
                    "candidate_set_fingerprint": candidate.content_hash,
                    "state": "PENDING",
                    "created_at": NOW.isoformat(),
                },
            )
    engine.dispose()


def _persisted_operation_recipe_report_plan(
    database: Path,
) -> EbookOperationRecipePlan:
    engine = create_sqlite_engine(database)
    _seed_sources(engine, count=1)
    store = SQLiteEbookOperationRecipeStore(engine)
    candidate = store.create_or_get_candidate(_candidate())
    plan = _plan(candidate, store.get_latest_review(candidate.id))
    persisted = store.create_or_get_plan(plan)
    engine.dispose()
    return persisted


@pytest.mark.parametrize("output", ["json", "text"])
def test_operation_recipe_report_cli_is_strictly_read_only_and_private(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    output: str,
) -> None:
    plan = _persisted_operation_recipe_report_plan(head_database)
    before = head_database.read_bytes()
    original_read = SQLiteEbookOperationRecipePlanReportReader.read

    def _read_with_query_only_assertion(
        reader: SQLiteEbookOperationRecipePlanReportReader,
        plan_id: EntityId,
    ) -> EbookOperationRecipePlanReport:
        with reader._engine.connect() as connection:
            assert connection.execute(text("PRAGMA query_only")).scalar_one() == 1
        return original_read(reader, plan_id)

    monkeypatch.setattr(
        "foliotone.cli.main.migrate",
        lambda _path: pytest.fail("read-only report must not migrate"),
    )
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("read-only report must not open a writable engine"),
    )
    monkeypatch.setattr(
        SQLiteEbookOperationRecipePlanReportReader,
        "read",
        _read_with_query_only_assertion,
    )

    assert (
        main(
            [
                "ebook-operation-recipe-report",
                "--plan",
                str(plan.id),
                "--database",
                str(head_database),
                "--output",
                output,
            ]
        )
        == 0
    )
    assert head_database.read_bytes() == before
    rendered = capsys.readouterr().out
    for private_material in (
        *PRIVATE_LOCATORS,
        str(ROOT_ID),
        str(SCAN_ID),
        str(FILE_IDS[0]),
        str(OBSERVATION_IDS[0]),
        str(FINGERPRINT_IDS[0]),
        str(TOOL_RESULT_ID),
        plan.content_hash,
        plan.candidate.content_hash,
        plan.candidate.sources[0].expected_full_sha256,
        plan.candidate.target.target_state_fingerprint,
        plan.candidate.processor_requirement.material_fingerprint,
    ):
        assert private_material not in rendered

    if output == "text":
        assert f"Plan: {plan.id}" in rendered
        assert f"Candidate: {plan.candidate.id}" in rendered
        assert "Operation kind: FILE_RENAME" in rendered
        assert "Status: BLOCKED" in rendered
        assert "Execution state: NOT_EXECUTABLE" in rendered
        assert "Review status: MISSING" in rendered
        assert "Sources: 1" in rendered
        assert "Dependencies: 5" in rendered
        assert "Verifications: 7" in rendered
        assert "Blocker code: REVIEW_MISSING" in rendered
        return

    payload = json.loads(rendered)
    assert set(payload) == {
        "schema_version",
        "command",
        "ok",
        "plan_id",
        "candidate_id",
        "plan_profile",
        "candidate_profile",
        "operation_kind",
        "status",
        "execution_state",
        "review_status",
        "counts",
        "blocker_codes",
    }
    assert payload == {
        "schema_version": 1,
        "command": "ebook-operation-recipe-report",
        "ok": True,
        "plan_id": str(plan.id),
        "candidate_id": str(plan.candidate.id),
        "plan_profile": plan.profile,
        "candidate_profile": plan.candidate.profile,
        "operation_kind": "FILE_RENAME",
        "status": "BLOCKED",
        "execution_state": "NOT_EXECUTABLE",
        "review_status": "MISSING",
        "counts": {
            "sources": 1,
            "dependencies": 5,
            "verifications": 7,
            "candidate_evidence_refs": 3,
            "preconditions": 8,
            "blockers": 1,
            "blocker_evidence_refs": 3,
            "review_items": 0,
            "decisions": 0,
        },
        "blocker_codes": ["REVIEW_MISSING"],
    }


def test_operation_recipe_report_rejects_invalid_plan_token() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ebook-operation-recipe-report", "--plan", "not-a-uuid"])


def test_operation_recipe_report_missing_plan_is_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "ebook-operation-recipe-report",
                "--plan",
                "00000000-0000-0000-0000-000000000001",
                "--database",
                str(head_database),
                "--output",
                "json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-operation-recipe-report",
        "ok": False,
        "error": {"code": "PLAN_UNAVAILABLE"},
    }


def test_operation_recipe_report_older_schema_is_not_migrated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "older-operation-recipe-schema.db"
    migrate(database, "0029_metadata_write_reconciliation")
    monkeypatch.setattr(
        "foliotone.cli.main.migrate",
        lambda _path: pytest.fail("read-only report must not migrate"),
    )

    assert (
        main(
            [
                "ebook-operation-recipe-report",
                "--plan",
                "00000000-0000-0000-0000-000000000001",
                "--database",
                str(database),
                "--output",
                "json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-operation-recipe-report",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    assert revision == "0029_metadata_write_reconciliation"


def test_operation_recipe_report_internal_failure_does_not_leak_details(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(
        _reader: SQLiteEbookOperationRecipePlanReportReader,
        _plan_id: EntityId,
    ) -> object:
        raise RuntimeError(f"synthetic private failure: {PRIVATE_LOCATORS[0]}")

    monkeypatch.setattr(SQLiteEbookOperationRecipePlanReportReader, "read", _boom)
    assert (
        main(
            [
                "ebook-operation-recipe-report",
                "--plan",
                "00000000-0000-0000-0000-000000000001",
                "--database",
                str(head_database),
                "--output",
                "json",
            ]
        )
        == 2
    )
    rendered = capsys.readouterr().out
    assert PRIVATE_LOCATORS[0] not in rendered
    assert json.loads(rendered) == {
        "schema_version": 1,
        "command": "ebook-operation-recipe-report",
        "ok": False,
        "error": {"code": "INTERNAL_READ_ERROR"},
    }
