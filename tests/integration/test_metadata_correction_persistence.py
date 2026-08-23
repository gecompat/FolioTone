"""Focused synthetic coverage for S-W9-006B/C persistence and reporting."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import func, insert, inspect, select, text
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
    ValueState,
)
from foliotone.metadata_correction import (
    METADATA_CORRECTION_DECISION_COMPATIBILITY,
    METADATA_CORRECTION_PRODUCER_NAME,
    METADATA_CORRECTION_PRODUCER_VERSION,
    METADATA_TARGET_REFERENCE_KIND,
    MetadataCorrectionCandidateInputs,
    MetadataCorrectionOperation,
    MetadataCorrectionPlanInputs,
    MetadataCorrectionPlanStatus,
    MetadataCorrectionReviewState,
    MetadataDependencyKind,
    MetadataDependencySnapshot,
    MetadataDependencyState,
    MetadataEvidenceReference,
    MetadataTargetCarrier,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    build_metadata_correction_candidate,
    build_metadata_correction_plan,
    build_metadata_field_correction,
    build_metadata_writer_requirement,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
)
from foliotone.metadata_write import (
    EpubConformanceStatus,
    EpubInputConformance,
    EpubPublicationKind,
    EpubTitleStagedValidation,
    EpubTitleVerifiedStage,
    EpubTitleWritePreparationSnapshot,
    MetadataWriteExecutionEvent,
    MetadataWriteRunStatus,
    ResolvedMetadataWriteCapability,
    build_epub3_title_package_patch,
    build_epub3_title_write_preparation,
    build_metadata_write_authorization,
    build_metadata_write_run,
    build_private_epub3_title_stage,
    metadata_write_confirmation_digest,
    metadata_write_confirmation_text,
    preflight_epub3_title_write,
)
from foliotone.metadata_write.authorization import (
    _preparation_hash_from_material,
    _preparation_id,
)
from foliotone.metadata_write.executor import (
    execute_epub3_title_metadata_write,
    recover_epub3_title_metadata_write,
)
from foliotone.metadata_write.linux_backend import (
    LinuxMetadataWriteBackendError,
    LinuxMetadataWriteBackendErrorCode,
    LinuxMetadataWritePhysicalSnapshot,
    LinuxMetadataWritePhysicalState,
)
from foliotone.metadata_write.reconciliation import (
    MetadataWriteReconciliationOutcome,
    build_metadata_write_reconciliation,
)
from foliotone.persistence import (
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
    SQLiteResolutionReviewStore,
    alembic_config,
    consolidation_schema,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    schema,
)
from foliotone.persistence import metadata_correction_schema as mc_schema
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence.metadata_correction_report import (
    SQLiteMetadataCorrectionPlanReportReader,
)
from foliotone.persistence.metadata_write import (
    MetadataWriteStoreError,
    SQLiteMetadataWriteStore,
)
from foliotone.persistence.metadata_write_schema import (
    metadata_write_backend_bindings,
    metadata_write_reconciliations,
)
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.workflows.collection_state import CollectionStateBuildService
from foliotone.workflows.metadata_write_operation import (
    MetadataWriteOperatorError,
    MetadataWriteOperatorErrorCode,
    MetadataWriteOperatorService,
)
from foliotone.workflows.metadata_write_report import (
    MetadataWriteStatusReportError,
    SQLiteMetadataWriteStatusReportReader,
)

NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("91000000-0000-0000-0000-000000000001")
SCAN_ID = EntityId.parse("92000000-0000-0000-0000-000000000001")
FILE_ID = EntityId.parse("93000000-0000-0000-0000-000000000001")
OBSERVATION_ID = EntityId.parse("94000000-0000-0000-0000-000000000001")
OBSERVED_ASSERTION_ID = EntityId.parse("95000000-0000-0000-0000-000000000001")
SELECTED_ASSERTION_ID = EntityId.parse("95000000-0000-0000-0000-000000000002")
TOOL_EXECUTION_ID = EntityId.parse("96000000-0000-0000-0000-000000000001")
TOOL_RESULT_ID = EntityId.parse("97000000-0000-0000-0000-000000000001")
FULL_HASH = "a" * 64
PRIVATE_PATH = "private/synthetic-secret-title.epub"
OBSERVED_TITLE = "Observed synthetic private title"
SELECTED_TITLE = "Confirmed synthetic private title"
PREPARATION_OWNER_ID = EntityId.parse("98000000-0000-0000-0000-000000000001")
METADATA_WRITE_CAPABILITY_ID = EntityId.parse("98000000-0000-0000-0000-000000000002")
METADATA_WRITE_RUN_ID = EntityId.parse("98000000-0000-0000-0000-000000000003")
EXPECTED_OUTPUT_HASH = "e" * 64


def _sha(character: str) -> str:
    return character * 64


def _evidence(kind: str, ref_id: EntityId, digest: str) -> MetadataEvidenceReference:
    return MetadataEvidenceReference(kind, ref_id, _sha(digest))


def _seed_source(
    engine,
    *,
    source_sha256: str = FULL_HASH,
    source_size_bytes: int = 4096,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {
                "id": str(ROOT_ID),
                "name": "synthetic-metadata-correction",
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
        connection.execute(
            insert(schema.file_records),
            {
                "id": str(FILE_ID),
                "scan_root_id": str(ROOT_ID),
                "relative_path": PRIVATE_PATH,
                "size_bytes": source_size_bytes,
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
                "id": str(OBSERVATION_ID),
                "file_id": str(FILE_ID),
                "scan_run_id": str(SCAN_ID),
                "relative_path": PRIVATE_PATH,
                "size_bytes": source_size_bytes,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(EntityId.new()),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(OBSERVATION_ID),
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": source_sha256,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            },
        )
        for assertion_id, value, state in (
            (OBSERVED_ASSERTION_ID, OBSERVED_TITLE, "OBSERVED"),
            (SELECTED_ASSERTION_ID, SELECTED_TITLE, "USER_CONFIRMED"),
        ):
            connection.execute(
                insert(schema.value_assertions),
                {
                    "id": str(assertion_id),
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(OBSERVATION_ID),
                    "field_name": "title",
                    "value": value,
                    "state": state,
                    "source_kind": "SYNTHETIC",
                    "source_name": "metadata-correction-test",
                    "source_version": "1",
                    "observed_at": NOW.isoformat(),
                    "confidence": 1.0,
                    "explanation": "synthetic evidence",
                },
            )
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(TOOL_EXECUTION_ID),
                "provider_id": "synthetic-metadata-reader",
                "tool_version": "1",
                "adapter_version": "test/1",
                "capability": "READ_METADATA",
                "input_identity": f"file-observation:{OBSERVATION_ID}",
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
                "result_type": "ebook_metadata_candidate",
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(OBSERVATION_ID),
                "key": "title",
                "value": OBSERVED_TITLE,
                "confidence": 1.0,
                "explanation": "synthetic title",
            },
        )


def _candidate(
    *,
    created_at: datetime = NOW,
    selected_title: str = SELECTED_TITLE,
    expected_full_sha256: str = FULL_HASH,
    expected_size_bytes: int = 4096,
):
    observed = MetadataValueSnapshot(
        0,
        ValueState.OBSERVED,
        _evidence("VALUE_ASSERTION", OBSERVED_ASSERTION_ID, "1"),
        OBSERVED_TITLE,
    )
    selected = MetadataValueSnapshot(
        0,
        ValueState.USER_CONFIRMED,
        _evidence("VALUE_ASSERTION", SELECTED_ASSERTION_ID, "2"),
        selected_title,
    )
    field = build_metadata_field_correction(
        field_path="title",
        operation=MetadataCorrectionOperation.REPLACE,
        observed_values=(observed,),
        selected_values=(selected,),
        evidence_refs=(
            _evidence("TOOL_RESULT", TOOL_RESULT_ID, "3"),
            _evidence("VALUE_ASSERTION", OBSERVED_ASSERTION_ID, "1"),
        ),
    )
    dependencies = tuple(
        MetadataDependencySnapshot(
            kind=kind,
            state=(
                MetadataDependencyState.NOT_APPLICABLE
                if kind is MetadataDependencyKind.ARCHIVE
                else MetadataDependencyState.KNOWN_NONE
            ),
            snapshot_kind={
                MetadataDependencyKind.CALIBRE: "calibre-dependency/v1",
                MetadataDependencyKind.SIDECAR: "sidecar-dependency/v1",
                MetadataDependencyKind.ARCHIVE: "archive-dependency/v1",
            }[kind],
            snapshot_id=OBSERVATION_ID,
            material_fingerprint=_sha(str(index + 4)),
        )
        for index, kind in enumerate(MetadataDependencyKind)
    )
    target = MetadataTargetSnapshot(
        MetadataTargetCarrier.SOURCE_METADATA,
        METADATA_TARGET_REFERENCE_KIND[MetadataTargetCarrier.SOURCE_METADATA],
        FILE_ID,
        _sha("8"),
    )
    return build_metadata_correction_candidate(
        MetadataCorrectionCandidateInputs(
            scan_root_id=ROOT_ID,
            source_scan_run_id=SCAN_ID,
            source_scan_run_status=ScanRunStatus.COMPLETED,
            file_id=FILE_ID,
            observation_id=OBSERVATION_ID,
            format_label="EPUB",
            expected_presence_state=PresenceState.PRESENT,
            expected_full_sha256=expected_full_sha256,
            expected_size_bytes=expected_size_bytes,
            expected_modified_at=NOW,
            expected_observed_at=NOW,
            metadata_evidence_fingerprint=_sha("9"),
            target=target,
            field_corrections=(field,),
            dependencies=dependencies,
            writer_requirement=build_metadata_writer_requirement(
                format_label="EPUB",
                target_carrier=MetadataTargetCarrier.SOURCE_METADATA,
            ),
            evidence_refs=(
                _evidence("FILE_OBSERVATION", OBSERVATION_ID, "b"),
                _evidence("VALUE_ASSERTION", OBSERVED_ASSERTION_ID, "1"),
            ),
        ),
        clock=lambda: created_at,
    )


def _review_item(candidate, *, created_at: datetime = NOW) -> ReviewItem:
    return ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.METADATA_CORRECTION,
        subject_kind=EntityKind.FILE,
        subject_id=candidate.file_id,
        candidate_kind=ReviewCandidateKind.METADATA_CORRECTION_CANDIDATE,
        candidate_id=candidate.id,
        producer_name=METADATA_CORRECTION_PRODUCER_NAME,
        producer_version=METADATA_CORRECTION_PRODUCER_VERSION,
        decision_compatibility_version=METADATA_CORRECTION_DECISION_COMPATIBILITY,
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.content_hash,
        state=ReviewItemState.PENDING,
        created_at=created_at,
    )


def _plan(candidate, review, *, created_at: datetime = NOW):
    return build_metadata_correction_plan(
        MetadataCorrectionPlanInputs(
            candidate=candidate,
            review=review,
            preserved_fields_fingerprint=_sha("c"),
            analysis_profile="ebook-analysis-workflow/v3",
            lineage_matches=True,
            source_evidence_complete=True,
            field_selection_valid=True,
            target_carrier_valid=True,
            writer_requirement_valid=True,
            preconditions_complete=True,
            verification_contract_complete=True,
        ),
        clock=lambda: created_at,
    )


def test_migration_0026_preserves_review_history_and_downgrades_when_empty(
    tmp_path: Path,
) -> None:
    database = tmp_path / "metadata-correction-review-migration.db"
    migrate(database, "0025_library_health")
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
    assert revision == "0033_local_surface_foundation"
    assert retained == str(decision_id)
    assert retained_plan_review == str(plan_id)
    assert "METADATA_CORRECTION" in review_ddl
    assert {table.name for table in mc_schema.METADATA_CORRECTION_TABLES} <= set(
        inspect(upgraded).get_table_names()
    )
    upgraded.dispose()

    command.downgrade(alembic_config(database), "0025_library_health")
    downgraded = create_sqlite_engine(database)
    with downgraded.connect() as connection:
        retained_after = connection.execute(
            select(review_schema.review_decisions.c.id).where(
                review_schema.review_decisions.c.id == str(decision_id)
            )
        ).scalar_one()
        retained_plan_review_after = connection.execute(
            select(consolidation_schema.consolidation_plan_reviews.c.plan_id).where(
                consolidation_schema.consolidation_plan_reviews.c.plan_id == str(plan_id)
            )
        ).scalar_one()
        review_ddl_after = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='review_items'")
        ).scalar_one()
    assert retained_after == str(decision_id)
    assert retained_plan_review_after == str(plan_id)
    assert "METADATA_CORRECTION" not in review_ddl_after
    downgraded.dispose()


def test_candidate_roundtrip_retry_immutability_and_downgrade_guard(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    store = SQLiteMetadataCorrectionStore(engine)
    candidate = _candidate()

    assert store.create_or_get_candidate(candidate) == candidate
    assert store.get_candidate(candidate.id) == candidate
    retry = _candidate(created_at=NOW + timedelta(hours=1))
    assert retry.id == candidate.id
    assert store.create_or_get_candidate(retry) == candidate

    with engine.begin() as connection:
        with pytest.raises(Exception, match="metadata correction rows are immutable"):
            connection.execute(
                mc_schema.metadata_correction_values.update()
                .where(mc_schema.metadata_correction_values.c.candidate_id == str(candidate.id))
                .values(value="changed private value")
            )
        with pytest.raises(Exception, match="child exceeds parent count"):
            connection.execute(
                insert(mc_schema.metadata_correction_evidence),
                {
                    "candidate_id": str(candidate.id),
                    "ordinal": len(candidate.evidence_refs),
                    "kind": "FILE_OBSERVATION",
                    "ref_id": str(OBSERVATION_ID),
                    "material_fingerprint": _sha("d"),
                },
            )

        connection.execute(
            schema.value_assertions.delete().where(
                schema.value_assertions.c.id == str(SELECTED_ASSERTION_ID)
            )
        )
    with pytest.raises(MetadataCorrectionStoreError, match="evidence"):
        store.get_candidate(candidate.id)

    engine.dispose()
    with pytest.raises(RuntimeError, match="metadata correction data prevents"):
        command.downgrade(alembic_config(head_database), "0025_library_health")


def test_review_and_plan_roundtrip_bind_the_latest_compatible_decision(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    correction_store = SQLiteMetadataCorrectionStore(engine)
    candidate = correction_store.create_or_get_candidate(_candidate())
    review_store = SQLiteResolutionReviewStore(engine)
    item = review_store.enqueue_or_get_review(_review_item(candidate))

    pending = correction_store.get_latest_review(candidate.id)
    assert pending.state is MetadataCorrectionReviewState.PENDING
    assert pending.review_item_id == item.id
    pending_plan = _plan(candidate, pending)
    assert pending_plan.status is MetadataCorrectionPlanStatus.REVIEW_REQUIRED
    assert correction_store.create_or_get_plan(pending_plan) == pending_plan

    decision = ReviewDecision(
        id=EntityId.new(),
        review_item_id=item.id,
        sequence_no=1,
        decision=ReviewDecisionValue.ACCEPT,
        decision_reason="USER_CONFIRMED",
        evidence_fingerprint=candidate.evidence_fingerprint,
        candidate_set_fingerprint=candidate.content_hash,
        decision_compatibility_version=METADATA_CORRECTION_DECISION_COMPATIBILITY,
        actor_kind=ReviewActorKind.USER,
        decided_at=NOW + timedelta(minutes=1),
    )
    review_store.append_decision(decision, expected_latest_decision_id=None)
    assert correction_store.get_plan(pending_plan.id) == pending_plan
    accepted = correction_store.get_latest_review(candidate.id)
    assert accepted.state is MetadataCorrectionReviewState.ACCEPTED
    assert accepted.decision_id == decision.id

    approved = _plan(candidate, accepted, created_at=NOW + timedelta(minutes=2))
    assert approved.status is MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
    assert correction_store.create_or_get_plan(approved) == approved
    assert correction_store.get_plan(approved.id) == approved
    retry = _plan(candidate, accepted, created_at=NOW + timedelta(hours=1))
    assert correction_store.create_or_get_plan(retry) == approved
    changed_precondition = replace(
        approved.preconditions[0],
        expected_fingerprint=_sha("f"),
    )
    invalid_draft = replace(
        approved,
        preconditions=(changed_precondition, *approved.preconditions[1:]),
        content_hash=_sha("0"),
    )
    invalid_hash = metadata_correction_plan_content_hash(invalid_draft)
    invalid_plan = replace(
        invalid_draft,
        id=metadata_correction_plan_id(invalid_hash),
        content_hash=invalid_hash,
    )
    with pytest.raises(MetadataCorrectionStoreError, match="canonical reducer"):
        correction_store.create_or_get_plan(invalid_plan)
    with pytest.raises(MetadataCorrectionStoreError, match="latest compatible review"):
        correction_store.create_or_get_plan(pending_plan)

    queued = review_store.list_queue(review_type=ReviewType.METADATA_CORRECTION)
    assert queued.items == ()


def test_missing_lineage_rolls_back_without_leaking_private_metadata(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    with engine.begin() as connection:
        connection.execute(
            schema.value_assertions.delete().where(
                schema.value_assertions.c.id == str(SELECTED_ASSERTION_ID)
            )
        )
    store = SQLiteMetadataCorrectionStore(engine)
    with pytest.raises(MetadataCorrectionStoreError) as failure:
        store.create_or_get_candidate(_candidate())
    message = str(failure.value)
    assert SELECTED_TITLE not in message
    assert PRIVATE_PATH not in message
    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(mc_schema.metadata_correction_candidates)
        ).scalar_one()
    assert count == 0


def test_metadata_review_literals_require_the_exact_candidate_contract(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_source(engine)
    candidate = SQLiteMetadataCorrectionStore(engine).create_or_get_candidate(_candidate())
    store = SQLiteResolutionReviewStore(engine)
    valid = _review_item(candidate)
    assert store.enqueue_or_get_review(valid) == valid
    invalid = replace(valid, id=EntityId.new(), producer_name="foreign-producer")
    with pytest.raises(Exception, match="does not match candidate"):
        store.enqueue_or_get_review(invalid)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(review_schema.review_items),
                {
                    "id": str(EntityId.new()),
                    "review_type": "CLASSIFICATION",
                    "subject_kind": "FILE",
                    "subject_id": str(FILE_ID),
                    "candidate_kind": "METADATA_CORRECTION_CANDIDATE",
                    "candidate_id": str(candidate.id),
                    "producer_name": METADATA_CORRECTION_PRODUCER_NAME,
                    "producer_version": METADATA_CORRECTION_PRODUCER_VERSION,
                    "decision_compatibility_version": (METADATA_CORRECTION_DECISION_COMPATIBILITY),
                    "evidence_fingerprint": candidate.evidence_fingerprint,
                    "candidate_set_fingerprint": candidate.content_hash,
                    "state": "PENDING",
                    "created_at": NOW.isoformat(),
                },
            )


def _persisted_report_plan(database: Path):
    engine = create_sqlite_engine(database)
    _seed_source(engine)
    store = SQLiteMetadataCorrectionStore(engine)
    candidate = store.create_or_get_candidate(_candidate())
    plan = _plan(candidate, store.get_latest_review(candidate.id))
    persisted = store.create_or_get_plan(plan)
    engine.dispose()
    return persisted


@pytest.mark.parametrize("output", ["json", "text"])
def test_metadata_correction_report_cli_is_strictly_read_only_and_private(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    output: str,
) -> None:
    plan = _persisted_report_plan(head_database)
    before = head_database.read_bytes()
    original_read = SQLiteMetadataCorrectionPlanReportReader.read

    def _read_with_query_only_assertion(
        reader: SQLiteMetadataCorrectionPlanReportReader,
        plan_id: EntityId,
    ):
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
        SQLiteMetadataCorrectionPlanReportReader,
        "read",
        _read_with_query_only_assertion,
    )

    assert (
        main(
            [
                "ebook-metadata-correction-report",
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
        PRIVATE_PATH,
        OBSERVED_TITLE,
        SELECTED_TITLE,
        FULL_HASH,
        str(ROOT_ID),
        str(SCAN_ID),
        str(FILE_ID),
        str(OBSERVATION_ID),
        _sha("8"),
        _sha("9"),
    ):
        assert private_material not in rendered

    if output == "text":
        assert f"Plan: {plan.id}" in rendered
        assert f"Candidate: {plan.candidate.id}" in rendered
        assert "Status: BLOCKED" in rendered
        assert "Execution state: NOT_EXECUTABLE" in rendered
        assert "Target carrier: SOURCE_METADATA" in rendered
        assert "Format: EPUB" in rendered
        assert "Review status: MISSING" in rendered
        assert "Field: title operation=REPLACE" in rendered
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
        "status",
        "execution_state",
        "content_hash",
        "target_carrier",
        "format",
        "review_status",
        "fields",
        "counts",
        "blocker_codes",
    }
    assert payload["command"] == "ebook-metadata-correction-report"
    assert payload["plan_id"] == str(plan.id)
    assert payload["candidate_id"] == str(plan.candidate.id)
    assert payload["plan_profile"] == plan.profile
    assert payload["candidate_profile"] == plan.candidate.profile
    assert payload["status"] == "BLOCKED"
    assert payload["execution_state"] == "NOT_EXECUTABLE"
    assert payload["content_hash"] == plan.content_hash
    assert payload["target_carrier"] == "SOURCE_METADATA"
    assert payload["format"] == "EPUB"
    assert payload["review_status"] == "MISSING"
    assert payload["fields"] == [
        {
            "field_path": "title",
            "operation": "REPLACE",
            "observed_value_count": 1,
            "selected_value_count": 1,
            "evidence_ref_count": 2,
        }
    ]
    assert payload["counts"] == {
        "fields": 1,
        "observed_values": 1,
        "selected_values": 1,
        "field_evidence_refs": 2,
        "candidate_evidence_refs": 2,
        "dependencies": 3,
        "preconditions": 10,
        "verification_fields": 1,
        "verification_dependencies": 0,
        "blockers": 1,
        "blocker_evidence_refs": 2,
        "review_items": 0,
        "decisions": 0,
    }
    assert payload["blocker_codes"] == ["REVIEW_MISSING"]


def test_metadata_correction_report_rejects_invalid_plan_token() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ebook-metadata-correction-report", "--plan", "not-a-uuid"])


def test_metadata_correction_report_missing_plan_is_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "ebook-metadata-correction-report",
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
        "command": "ebook-metadata-correction-report",
        "ok": False,
        "error": {"code": "PLAN_UNAVAILABLE"},
    }


def test_metadata_correction_report_older_schema_is_not_migrated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "older-metadata-correction-schema.db"
    migrate(database, "0025_library_health")
    monkeypatch.setattr(
        "foliotone.cli.main.migrate",
        lambda _path: pytest.fail("read-only report must not migrate"),
    )

    assert (
        main(
            [
                "ebook-metadata-correction-report",
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
        "command": "ebook-metadata-correction-report",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }


def test_metadata_correction_report_internal_failure_does_not_leak_details(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(
        _reader: SQLiteMetadataCorrectionPlanReportReader,
        _plan_id: EntityId,
    ) -> object:
        raise RuntimeError(f"synthetic private failure: {PRIVATE_PATH}")

    monkeypatch.setattr(SQLiteMetadataCorrectionPlanReportReader, "read", _boom)
    assert (
        main(
            [
                "ebook-metadata-correction-report",
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
    assert PRIVATE_PATH not in rendered
    assert json.loads(rendered) == {
        "schema_version": 1,
        "command": "ebook-metadata-correction-report",
        "ok": False,
        "error": {"code": "INTERNAL_READ_ERROR"},
    }


def _approved_plan_for_metadata_write(
    engine,
    *,
    source_sha256: str = FULL_HASH,
    source_size_bytes: int = 4096,
):
    _seed_source(
        engine,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
    )
    correction_store = SQLiteMetadataCorrectionStore(engine)
    candidate = correction_store.create_or_get_candidate(
        _candidate(
            expected_full_sha256=source_sha256,
            expected_size_bytes=source_size_bytes,
        )
    )
    review_store = SQLiteResolutionReviewStore(engine)
    item = review_store.enqueue_or_get_review(_review_item(candidate))
    review_store.append_decision(
        ReviewDecision(
            id=EntityId.new(),
            review_item_id=item.id,
            sequence_no=1,
            decision=ReviewDecisionValue.ACCEPT,
            decision_reason="USER_CONFIRMED",
            evidence_fingerprint=candidate.evidence_fingerprint,
            candidate_set_fingerprint=candidate.content_hash,
            decision_compatibility_version=METADATA_CORRECTION_DECISION_COMPATIBILITY,
            actor_kind=ReviewActorKind.USER,
            decided_at=NOW + timedelta(minutes=1),
        ),
        expected_latest_decision_id=None,
    )
    review = correction_store.get_latest_review(candidate.id)
    plan = _plan(candidate, review, created_at=NOW + timedelta(minutes=2))
    return correction_store.create_or_get_plan(plan)


def _metadata_write_authorization(engine, plan):
    authorized_at = NOW + timedelta(minutes=3)
    prepared_at = authorized_at + timedelta(seconds=1)
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION,
        PREPARATION_OWNER_ID,
        lease_token="synthetic-metadata-write-preparation",
        acquired_at=authorized_at - timedelta(seconds=1),
        lease_expires_at=authorized_at + timedelta(minutes=5),
    )
    material = {
        "preparation_owner_id": PREPARATION_OWNER_ID,
        "preparation_fence_epoch": lease.fence_epoch,
        "plan_id": plan.id,
        "plan_content_hash": plan.content_hash,
        "scan_root_id": ROOT_ID,
        "file_id": FILE_ID,
        "observation_id": OBSERVATION_ID,
        "source_sha256": FULL_HASH,
        "source_size_bytes": 4096,
        "expected_output_sha256": EXPECTED_OUTPUT_HASH,
        "expected_output_size_bytes": 4097,
        "metadata_write_capability_id": METADATA_WRITE_CAPABILITY_ID,
        "dcterms_modified": "2026-08-22T18:03:01Z",
        "authorized_at": authorized_at,
        "prepared_at": prepared_at,
        "metadata_tool_version": "ebook-meta calibre 9.13",
        "epubcheck_tool_version": "EPUBCheck v5.3.0",
        "text_tool_version": "ebook-convert calibre 9.13.0",
        "cover_tool_version": "calibre-debug calibre 9.13",
        "validator_set_fingerprint": _sha("d"),
    }
    content_hash = _preparation_hash_from_material(material)
    preparation = EpubTitleWritePreparationSnapshot(
        id=_preparation_id(content_hash),
        content_hash=content_hash,
        **material,
    )
    authorization = build_metadata_write_authorization(
        preparation,
        expires_at=authorized_at + timedelta(minutes=10),
    )
    return authorization, lease, prepared_at


def _persist_metadata_write_run(database: Path):
    engine = create_sqlite_engine(database)
    plan = _approved_plan_for_metadata_write(engine)
    authorization, preparation_lease, prepared_at = _metadata_write_authorization(
        engine,
        plan,
    )
    store = SQLiteMetadataWriteStore(engine)
    assert (
        store.create_or_get_authorization(
            authorization,
            plan,
            preparation_lease,
            persisted_at=prepared_at + timedelta(seconds=1),
        )
        == authorization
    )
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.release(
        preparation_lease,
        released_at=prepared_at + timedelta(seconds=2),
    )
    run_created_at = prepared_at + timedelta(seconds=3)
    run_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        METADATA_WRITE_RUN_ID,
        lease_token="synthetic-metadata-write-run",
        acquired_at=run_created_at,
        lease_expires_at=run_created_at + timedelta(minutes=5),
    )
    source_root = database.parent / "synthetic-source-root"
    recovery = database.parent / "synthetic-recovery"
    source_root.mkdir(exist_ok=True)
    recovery.mkdir(exist_ok=True)
    capability = ResolvedMetadataWriteCapability(
        METADATA_WRITE_CAPABILITY_ID,
        ROOT_ID,
        source_root,
        recovery,
    )
    run = build_metadata_write_run(
        authorization,
        capability,
        run_lease,
        run_id=METADATA_WRITE_RUN_ID,
        created_at=run_created_at,
    )
    assert (
        store.create_run(
            run,
            authorization,
            plan,
            run_lease,
            confirmation_digest=metadata_write_confirmation_digest(
                authorization,
                metadata_write_confirmation_text(authorization),
            ),
        )
        == run
    )
    return engine, plan, authorization, run, run_lease


def test_metadata_write_retry_requires_the_original_second_confirmation(
    head_database: Path,
) -> None:
    engine, _plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    prompt = metadata_write_confirmation_text(authorization)
    confirmation_digest = metadata_write_confirmation_digest(authorization, prompt)

    assert prompt == f"CONFIRM METADATA WRITE {authorization.id}"
    store.require_execution_confirmation(
        run,
        authorization,
        run_lease,
        confirmation_digest=confirmation_digest,
        checked_at=run.created_at + timedelta(seconds=1),
    )
    with pytest.raises(MetadataWriteStoreError, match="CREATED event differs"):
        store.require_execution_confirmation(
            run,
            authorization,
            run_lease,
            confirmation_digest=_sha("0"),
            checked_at=run.created_at + timedelta(seconds=2),
        )
    assert store.events_for_run(run.id)[0].confirmation_digest == confirmation_digest
    engine.dispose()


def test_metadata_write_reconciliation_atomically_verifies_one_new_collection_state(
    head_database: Path,
) -> None:
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    store.bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=run.created_at + timedelta(seconds=1),
    )
    for sequence_no, status in enumerate(
        (
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        ),
        start=2,
    ):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                sequence_no,
                status,
                run.created_at + timedelta(seconds=sequence_no),
                run_lease.fence_epoch,
                confirmation_digest=_sha(str(sequence_no)),
            ),
            run_lease,
        )
    preserved_at = run.created_at + timedelta(seconds=4)
    lease_store.release(
        run_lease,
        released_at=preserved_at + timedelta(seconds=1),
    )

    scan_run_id = EntityId.new()
    observation_id = EntityId.new()
    scan_started_at = preserved_at + timedelta(seconds=2)
    scan_completed_at = scan_started_at + timedelta(seconds=1)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(scan_run_id),
                "scan_root_id": str(ROOT_ID),
                "started_at": scan_started_at.isoformat(),
                "status": ScanRunStatus.COMPLETED.value,
                "completed_at": scan_completed_at.isoformat(),
            },
        )
        connection.execute(
            schema.file_records.update()
            .where(schema.file_records.c.id == str(FILE_ID))
            .values(
                size_bytes=authorization.expected_output_size_bytes,
                modified_at=NOW.isoformat(),
                last_seen_at=scan_completed_at.isoformat(),
                presence_state=PresenceState.PRESENT.value,
                missing_since_at=None,
                consecutive_missing_scans=0,
            )
        )
        connection.execute(
            insert(schema.file_observations),
            {
                "id": str(observation_id),
                "file_id": str(FILE_ID),
                "scan_run_id": str(scan_run_id),
                "relative_path": PRIVATE_PATH,
                "size_bytes": authorization.expected_output_size_bytes,
                "modified_at": NOW.isoformat(),
                "observed_at": scan_completed_at.isoformat(),
            },
        )
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(EntityId.new()),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(observation_id),
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": authorization.expected_output_sha256,
                "created_at": scan_completed_at.isoformat(),
                "tool_execution_id": None,
            },
        )

    collection_report = CollectionStateBuildService(engine).build(
        scan_run_id,
        scan_completed_at + timedelta(seconds=1),
    )
    fresh_lease_at = collection_report.snapshot.created_at + timedelta(seconds=1)
    fresh_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        run.id,
        lease_token="synthetic-metadata-write-reconciliation",
        acquired_at=fresh_lease_at,
        lease_expires_at=fresh_lease_at + timedelta(minutes=5),
    )
    reconciliation = build_metadata_write_reconciliation(
        run_id=run.id,
        authorization_id=authorization.id,
        authorization_content_hash=authorization.content_hash,
        outcome=MetadataWriteReconciliationOutcome.VERIFIED,
        scan_run_id=scan_run_id,
        observation_id=observation_id,
        collection_state_snapshot_id=collection_report.snapshot.id,
        collection_state_content_digest=collection_report.snapshot.content_digest,
        physical_confirmation_digest=_sha("f"),
        reconciled_at=fresh_lease_at + timedelta(seconds=1),
    )

    with engine.begin() as connection:
        connection.execute(
            schema.scan_runs.update()
            .where(schema.scan_runs.c.id == str(scan_run_id))
            .values(started_at=preserved_at.isoformat())
        )
    with pytest.raises(MetadataWriteStoreError, match="evidence differs"):
        store.record_reconciliation(
            reconciliation,
            run,
            authorization,
            fresh_lease,
        )
    with engine.begin() as connection:
        connection.execute(
            schema.scan_runs.update()
            .where(schema.scan_runs.c.id == str(scan_run_id))
            .values(started_at=scan_started_at.isoformat())
        )

    assert (
        store.record_reconciliation(
            reconciliation,
            run,
            authorization,
            fresh_lease,
        )
        == reconciliation
    )
    assert (
        store.record_reconciliation(
            reconciliation,
            run,
            authorization,
            fresh_lease,
        )
        == reconciliation
    )
    assert [event.status for event in store.events_for_run(run.id)] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        MetadataWriteRunStatus.VERIFIED,
    ]
    payload = SQLiteMetadataWriteStatusReportReader(store).read(run.id).payload()
    assert payload["status"] == "VERIFIED"
    assert payload["reconciliation"] == {
        "outcome": "VERIFIED",
        "scan_run_id": str(scan_run_id),
        "observation_id": str(observation_id),
        "collection_state_snapshot_id": str(collection_report.snapshot.id),
        "reconciled_at": reconciliation.reconciled_at.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert authorization.expected_output_sha256 not in encoded
    assert reconciliation.physical_confirmation_digest not in encoded
    assert reconciliation.content_hash not in encoded
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="immutable metadata write reconciliation"):
            connection.execute(
                metadata_write_reconciliations.update().values(outcome_status="RECOVERED")
            )
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="immutable metadata write reconciliation"):
            connection.execute(metadata_write_reconciliations.delete())
    engine.dispose()
    with pytest.raises(RuntimeError, match="reconciliation prevents migration downgrade"):
        command.downgrade(
            alembic_config(head_database),
            "0028_metadata_write_backend",
        )


def _synthetic_epub() -> bytes:
    package = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" '
        'unique-identifier="book-id">\n'
        "  <metadata>\n"
        '    <dc:identifier id="book-id">urn:uuid:synthetic</dc:identifier>\n'
        f'    <dc:title id="main-title">{OBSERVED_TITLE}</dc:title>\n'
        '    <meta property="dcterms:modified">2026-08-22T18:00:00Z</meta>\n'
        "  </metadata>\n"
        '  <manifest><item id="chapter" href="chapter.xhtml" '
        'media-type="application/xhtml+xml"/></manifest>\n'
        '  <spine><itemref idref="chapter"/></spine>\n'
        "</package>\n"
    ).encode()
    container = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        b'version="1.0"><rootfiles><rootfile full-path="OEBPS/package.opf" '
        b'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )

    def info(name: str, compression: int) -> zipfile.ZipInfo:
        value = zipfile.ZipInfo(name, date_time=(2026, 8, 22, 18, 0, 0))
        value.compress_type = compression
        value.create_system = 3
        value.external_attr = 0o100644 << 16
        return value

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.comment = b"synthetic-mw04"
        archive.writestr(info("mimetype", zipfile.ZIP_STORED), b"application/epub+zip")
        archive.writestr(
            info("META-INF/container.xml", zipfile.ZIP_DEFLATED),
            container,
        )
        archive.writestr(
            info("OEBPS/package.opf", zipfile.ZIP_DEFLATED),
            package,
        )
        archive.writestr(
            info("OEBPS/chapter.xhtml", zipfile.ZIP_DEFLATED),
            b'<html xmlns="http://www.w3.org/1999/xhtml"><body>synthetic</body></html>',
        )
    return output.getvalue()


def _synthetic_stage_validation(stage) -> EpubTitleStagedValidation:
    return EpubTitleStagedValidation(
        plan_id=stage.plan_id,
        input_sha256=stage.input_sha256,
        output_sha256=stage.output_sha256,
        preserved_fields_sha256="a" * 64,
        normalized_text_sha256="b" * 64,
        cover_identity_sha256="c" * 64,
        cover_status="NO_EMBEDDED_COVER",
        metadata_tool_version="ebook-meta calibre 9.13.0",
        epubcheck_tool_version="EPUBCheck v5.3.0",
        text_tool_version="ebook-convert calibre 9.13.0",
        cover_tool_version="calibre-debug calibre 9.13.0",
        validator_set_fingerprint="d" * 64,
    )


class _SyntheticBoundStageValidator:
    def validate(
        self,
        stage,
        _preflight,
        _patch,
        *,
        validation_directory_name: str = "validators",
    ) -> EpubTitleStagedValidation:
        assert validation_directory_name in {"validators", "postwrite-validators"}
        return _synthetic_stage_validation(stage)

    def validate_input_conformance(self, _stage) -> str:
        return "EPUBCheck v5.3.0"


class _SyntheticCapabilityResolver:
    def __init__(self, capability: ResolvedMetadataWriteCapability) -> None:
        self._capability = capability

    def resolve(self, capability_id: EntityId) -> ResolvedMetadataWriteCapability:
        assert capability_id == self._capability.metadata_write_capability_id
        return self._capability


class _SyntheticPreparationSourceReader:
    def __init__(self, source_path: Path) -> None:
        self._source_path = source_path

    def read_source(
        self,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
        **_kwargs,
    ) -> bytes:
        value = self._source_path.read_bytes()
        assert hashlib.sha256(value).hexdigest() == expected_sha256
        assert len(value) == expected_size_bytes
        return value


class _SyntheticMetadataWriteSession:
    def __init__(
        self,
        source_path: Path,
        original: bytes,
        *,
        fail_preserve: bool = False,
    ) -> None:
        self._source_path = source_path
        self._original = original
        self._output: bytes | None = None
        self._fail_preserve = fail_preserve
        self.state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def read_source_bytes(self) -> bytes:
        value = self._source_path.read_bytes()
        assert hashlib.sha256(value).hexdigest() == hashlib.sha256(self._original).hexdigest()
        return value

    def read_output_bytes(self) -> bytes:
        assert self._output is not None
        value = self._source_path.read_bytes()
        assert value == self._output
        return value

    def prepare_output(self, staged_output: Path) -> LinuxMetadataWritePhysicalSnapshot:
        self._output = staged_output.read_bytes()
        self.state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        return self.classify()

    def revalidate_prepared(self) -> LinuxMetadataWritePhysicalSnapshot:
        return self.classify()

    def exchange(self) -> LinuxMetadataWritePhysicalSnapshot:
        assert self._output is not None
        self._source_path.write_bytes(self._output)
        os.utime(self._source_path, (NOW.timestamp(), NOW.timestamp()))
        self.state = LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        return self.classify()

    def preserve_original(self) -> LinuxMetadataWritePhysicalSnapshot:
        if self._fail_preserve:
            raise LinuxMetadataWriteBackendError(
                LinuxMetadataWriteBackendErrorCode.IO_FAILED,
                mutation_may_have_occurred=True,
            )
        self.state = LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
        return self.classify()

    def restore_original(self) -> LinuxMetadataWritePhysicalSnapshot:
        self._source_path.write_bytes(self._original)
        os.utime(self._source_path, (NOW.timestamp(), NOW.timestamp()))
        self.state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        return self.classify()

    def classify(self) -> LinuxMetadataWritePhysicalSnapshot:
        return self.confirmation_for(self.state)

    def confirmation_for(
        self,
        state: LinuxMetadataWritePhysicalState,
    ) -> LinuxMetadataWritePhysicalSnapshot:
        return LinuxMetadataWritePhysicalSnapshot(
            state,
            hashlib.sha256(f"synthetic:{state.value}".encode()).hexdigest(),
        )


class _SyntheticMetadataWriteBackend:
    def __init__(self, session: _SyntheticMetadataWriteSession) -> None:
        self._session = session

    def open_session(self, **_kwargs) -> _SyntheticMetadataWriteSession:
        return self._session


class _OperatorClock:
    def __init__(self) -> None:
        self._next = NOW + timedelta(minutes=3)

    def __call__(self) -> datetime:
        value = self._next
        self._next += timedelta(seconds=1)
        return value


def _metadata_write_operator_context(
    head_database: Path,
    *,
    label: str,
    fail_preserve: bool = False,
):
    source = _synthetic_epub()
    source_sha256 = hashlib.sha256(source).hexdigest()
    source_root = head_database.parent / f"{label}-source"
    recovery_root = head_database.parent / f"{label}-recovery"
    stage_root = head_database.parent / f"{label}-stage"
    for directory in (source_root, recovery_root, stage_root):
        directory.mkdir(mode=0o700)
    source_path = source_root / PRIVATE_PATH
    source_path.parent.mkdir(mode=0o700)
    source_path.write_bytes(source)
    os.utime(source_path, (NOW.timestamp(), NOW.timestamp()))

    engine = create_sqlite_engine(head_database)
    plan = _approved_plan_for_metadata_write(
        engine,
        source_sha256=source_sha256,
        source_size_bytes=len(source),
    )
    capability = ResolvedMetadataWriteCapability(
        METADATA_WRITE_CAPABILITY_ID,
        ROOT_ID,
        source_root,
        recovery_root,
    )
    session = _SyntheticMetadataWriteSession(
        source_path,
        source,
        fail_preserve=fail_preserve,
    )
    service = MetadataWriteOperatorService(
        engine,
        stage_root,
        capability_resolver=_SyntheticCapabilityResolver(capability),  # type: ignore[arg-type]
        source_reader=_SyntheticPreparationSourceReader(source_path),  # type: ignore[arg-type]
        validator=_SyntheticBoundStageValidator(),  # type: ignore[arg-type]
        backend=_SyntheticMetadataWriteBackend(session),
        clock=_OperatorClock(),
    )
    return engine, plan, capability, source_path, source, service


def test_metadata_write_operator_completes_authorize_execute_scan_and_reconciliation(
    head_database: Path,
) -> None:
    engine, plan, capability, source_path, _source, service = _metadata_write_operator_context(
        head_database,
        label="operator-success",
    )

    authorized = service.authorize(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
    )
    with pytest.raises(MetadataWriteOperatorError) as invalid_confirmation:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=capability.metadata_write_capability_id,
            authorization_id=authorized.authorization_id,
            confirmation_text="CONFIRM METADATA WRITE invalid",
        )
    assert invalid_confirmation.value.code is MetadataWriteOperatorErrorCode.CONFIRMATION_INVALID
    assert (
        SQLiteMetadataWriteStore(engine).get_run_for_authorization(authorized.authorization_id)
        is None
    )
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
        authorization_id=authorized.authorization_id,
    )
    result = service.execute(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
        authorization_id=authorized.authorization_id,
        confirmation_text=prompt,
    )

    assert result.status is MetadataWriteRunStatus.VERIFIED
    assert result.scan_run_id is not None
    assert result.observation_id is not None
    assert result.collection_state_snapshot_id is not None
    authorization = SQLiteMetadataWriteStore(engine).get_authorization(authorized.authorization_id)
    assert authorization is not None
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
        authorization.expected_output_sha256
    )
    report = SQLiteMetadataWriteStatusReportReader(SQLiteMetadataWriteStore(engine)).read(
        result.run_id
    )
    assert report.status is MetadataWriteRunStatus.VERIFIED
    assert report.reconciliation is not None
    assert report.reconciliation.scan_run_id == result.scan_run_id
    assert SQLiteScanRootWriteLeaseStore(engine).current(ROOT_ID) is None
    engine.dispose()


def test_metadata_write_operator_reconciles_an_automatically_restored_original(
    head_database: Path,
) -> None:
    engine, plan, capability, source_path, source, service = _metadata_write_operator_context(
        head_database,
        label="operator-recovery",
        fail_preserve=True,
    )
    authorized = service.authorize(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
    )
    prompt = service.confirmation_prompt(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
        authorization_id=authorized.authorization_id,
    )
    with pytest.raises(MetadataWriteOperatorError) as raised:
        service.execute(
            plan_id=plan.id,
            plan_content_hash=plan.content_hash,
            capability_id=capability.metadata_write_capability_id,
            authorization_id=authorized.authorization_id,
            confirmation_text=prompt,
        )
    assert raised.value.code is MetadataWriteOperatorErrorCode.VALIDATION_FAILED
    assert source_path.read_bytes() == source

    recovered = service.recover(
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.metadata_write_capability_id,
        authorization_id=authorized.authorization_id,
    )

    assert recovered.status is MetadataWriteRunStatus.RECOVERED
    assert recovered.scan_run_id is not None
    report = SQLiteMetadataWriteStatusReportReader(SQLiteMetadataWriteStore(engine)).read(
        recovered.run_id
    )
    assert report.status is MetadataWriteRunStatus.RECOVERED
    assert report.reconciliation is not None
    assert report.reconciliation.outcome is MetadataWriteReconciliationOutcome.RECOVERED
    assert all(event.status is not MetadataWriteRunStatus.VERIFIED for event in report.events)
    assert SQLiteScanRootWriteLeaseStore(engine).current(ROOT_ID) is None
    engine.dispose()


def test_linux_tmpfs_metadata_write_execution_and_recovery_end_to_end(
    head_database: Path,
) -> None:
    tmpfs = Path("/dev/shm")
    if sys.platform != "linux" or not tmpfs.is_dir() or not os.access(tmpfs, os.W_OK):
        pytest.skip("Linux tmpfs is required for the MW04 execution gate")
    sandbox = tmpfs / f"foliotone-mw04-e2e-{uuid4()}"
    source_root = sandbox / "source"
    recovery_root = sandbox / "recovery"
    stage_root = sandbox / "stage"
    preparation_stage = sandbox / "preparation-stage"
    engine = None
    try:
        for directory in (
            sandbox,
            source_root,
            recovery_root,
            stage_root,
            preparation_stage,
        ):
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
        source_path = source_root / PRIVATE_PATH
        source_path.parent.mkdir(parents=True, mode=0o700)
        source = _synthetic_epub()
        source_path.write_bytes(source)
        source_path.chmod(0o640)
        os.utime(source_path, (NOW.timestamp(), NOW.timestamp()))
        source_hash = hashlib.sha256(source).hexdigest()

        engine = create_sqlite_engine(head_database)
        plan = _approved_plan_for_metadata_write(
            engine,
            source_sha256=source_hash,
            source_size_bytes=len(source),
        )
        capability = ResolvedMetadataWriteCapability(
            METADATA_WRITE_CAPABILITY_ID,
            ROOT_ID,
            source_root,
            recovery_root,
        )
        authorized_at = NOW + timedelta(minutes=3)
        prepared_at = authorized_at + timedelta(seconds=1)
        lease_store = SQLiteScanRootWriteLeaseStore(engine)
        preparation_lease = lease_store.acquire(
            ROOT_ID,
            ScanRootWriteOwnerKind.METADATA_WRITE_PREPARATION,
            PREPARATION_OWNER_ID,
            lease_token="synthetic-linux-preparation",
            acquired_at=authorized_at - timedelta(seconds=1),
            lease_expires_at=authorized_at + timedelta(minutes=5),
        )
        preflight = preflight_epub3_title_write(
            plan,
            source,
            EpubInputConformance(
                source_hash,
                EpubPublicationKind.EPUB3,
                EpubConformanceStatus.CONFORMANT,
            ),
        )
        patch = build_epub3_title_package_patch(
            preflight,
            authorized_at=authorized_at,
        )
        staged = build_private_epub3_title_stage(
            preparation_stage / "prepared",
            io.BytesIO(source),
            preflight,
            patch,
        )
        verified = EpubTitleVerifiedStage(
            staged,
            _synthetic_stage_validation(staged),
        )
        preparation = build_epub3_title_write_preparation(
            plan=plan,
            preflight=preflight,
            patch=patch,
            verified_stage=verified,
            capability=capability,
            preparation_lease=preparation_lease,
            authorized_at=authorized_at,
            prepared_at=prepared_at,
        )
        authorization = build_metadata_write_authorization(
            preparation,
            expires_at=authorized_at + timedelta(minutes=10),
        )
        store = SQLiteMetadataWriteStore(engine)
        store.create_or_get_authorization(
            authorization,
            plan,
            preparation_lease,
            persisted_at=prepared_at + timedelta(seconds=1),
        )
        lease_store.release(
            preparation_lease,
            released_at=prepared_at + timedelta(seconds=2),
        )
        run_created_at = prepared_at + timedelta(seconds=3)
        run_lease = lease_store.acquire(
            ROOT_ID,
            ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
            METADATA_WRITE_RUN_ID,
            lease_token="synthetic-linux-execution",
            acquired_at=run_created_at,
            lease_expires_at=run_created_at + timedelta(minutes=5),
        )
        run = build_metadata_write_run(
            authorization,
            capability,
            run_lease,
            run_id=METADATA_WRITE_RUN_ID,
            created_at=run_created_at,
        )
        store.create_run(
            run,
            authorization,
            plan,
            run_lease,
            confirmation_digest=metadata_write_confirmation_digest(
                authorization,
                metadata_write_confirmation_text(authorization),
            ),
        )

        result = execute_epub3_title_metadata_write(
            store=store,
            run=run,
            authorization=authorization,
            plan=plan,
            capability=capability,
            lease=run_lease,
            private_stage_root=stage_root,
            clock=lambda: run_created_at + timedelta(seconds=1),
            validator=_SyntheticBoundStageValidator(),  # type: ignore[arg-type]
        )
        assert result.status is MetadataWriteRunStatus.ORIGINAL_PRESERVED
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
            authorization.expected_output_sha256
        )

        recovered = recover_epub3_title_metadata_write(
            store=store,
            run=run,
            authorization=authorization,
            plan=plan,
            capability=capability,
            lease=run_lease,
            clock=lambda: run_created_at + timedelta(seconds=2),
        )
        assert recovered.status is MetadataWriteRunStatus.RECOVERED
        assert source_path.read_bytes() == source
        assert [event.status for event in store.events_for_run(run.id)] == [
            MetadataWriteRunStatus.CREATED,
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            MetadataWriteRunStatus.RECOVERED,
        ]
    finally:
        if engine is not None:
            engine.dispose()
        if sandbox.exists():
            shutil.rmtree(sandbox)


def test_metadata_write_backend_binding_and_private_source_are_fenced(
    head_database: Path,
) -> None:
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    bound_at = run.created_at + timedelta(seconds=1)

    binding = store.bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=bound_at,
    )
    retry = store.bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=bound_at + timedelta(seconds=1),
    )
    source = store.require_execution_source(
        run,
        authorization,
        plan,
        run_lease,
        checked_at=bound_at,
    )

    assert retry == binding
    assert store.get_backend_binding(run.id) == binding
    assert source.relative_path == PRIVATE_PATH
    assert source.source_sha256 == FULL_HASH
    assert source.expected_modified_at == NOW
    assert PRIVATE_PATH not in repr(source)
    assert FULL_HASH not in repr(source)

    for sequence, status in enumerate(
        (
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            MetadataWriteRunStatus.VERIFIED,
        ),
        start=2,
    ):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                sequence,
                status,
                run.created_at + timedelta(seconds=sequence),
                run_lease.fence_epoch,
                confirmation_digest=_sha("f"),
            ),
            run_lease,
        )
    with pytest.raises(MetadataWriteStoreError, match="run status is unavailable"):
        store.require_recovery_source(
            run,
            authorization,
            plan,
            run_lease,
            checked_at=run.created_at + timedelta(seconds=7),
        )

    for statement in (
        "UPDATE metadata_write_backend_bindings SET bound_at='2026-01-01T00:00:00+00:00'",
        "DELETE FROM metadata_write_backend_bindings",
    ):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement))
    engine.dispose()


def test_metadata_write_recovery_uses_historical_locator_after_expiry(
    head_database: Path,
) -> None:
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    store.bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=run.created_at + timedelta(seconds=1),
    )
    with engine.begin() as connection:
        connection.execute(
            schema.file_records.update()
            .where(schema.file_records.c.id == str(FILE_ID))
            .values(
                relative_path="changed/current-location.epub",
                size_bytes=5000,
                modified_at=(NOW + timedelta(hours=1)).isoformat(),
            )
        )
    with pytest.raises(MetadataWriteStoreError, match="execution source is unavailable"):
        store.require_execution_source(
            run,
            authorization,
            plan,
            run_lease,
            checked_at=run.created_at + timedelta(seconds=2),
        )

    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.release(
        run_lease,
        released_at=run.created_at + timedelta(seconds=3),
    )
    recovery_at = authorization.expires_at + timedelta(seconds=1)
    recovery_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        run.id,
        lease_token="synthetic-metadata-write-recovery",
        acquired_at=recovery_at,
        lease_expires_at=recovery_at + timedelta(minutes=5),
    )
    recovered_source = store.require_recovery_source(
        run,
        authorization,
        plan,
        recovery_lease,
        checked_at=recovery_at + timedelta(seconds=1),
    )

    assert recovered_source.relative_path == PRIVATE_PATH
    assert recovered_source.expected_modified_at == NOW
    assert recovered_source.source_size_bytes == 4096
    engine.dispose()


def test_prepared_source_gate_expires_but_recovery_remains_available(
    head_database: Path,
) -> None:
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    store.bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=run.created_at + timedelta(seconds=1),
    )
    store.append_event(
        MetadataWriteExecutionEvent(
            run.id,
            2,
            MetadataWriteRunStatus.PREPARED,
            run.created_at + timedelta(seconds=2),
            run_lease.fence_epoch,
        ),
        run_lease,
    )
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.release(
        run_lease,
        released_at=run.created_at + timedelta(seconds=3),
    )
    recovery_at = authorization.expires_at + timedelta(seconds=1)
    recovery_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        run.id,
        lease_token="synthetic-expired-prepared-recovery",
        acquired_at=recovery_at,
        lease_expires_at=recovery_at + timedelta(minutes=5),
    )

    with pytest.raises(MetadataWriteStoreError, match="authorization is unavailable"):
        store.require_prepared_execution_source(
            run,
            authorization,
            plan,
            recovery_lease,
            checked_at=recovery_at + timedelta(seconds=1),
        )
    recovered_source = store.require_recovery_source(
        run,
        authorization,
        plan,
        recovery_lease,
        checked_at=recovery_at + timedelta(seconds=2),
    )

    assert recovered_source.relative_path == PRIVATE_PATH
    engine.dispose()


def test_migration_0028_refuses_to_drop_a_backend_binding(
    head_database: Path,
) -> None:
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(head_database)
    SQLiteMetadataWriteStore(engine).bind_backend(
        run,
        authorization,
        plan,
        run_lease,
        bound_at=run.created_at + timedelta(seconds=1),
    )
    with engine.connect() as connection:
        assert connection.execute(
            select(metadata_write_backend_bindings.c.run_id)
        ).scalar_one() == str(run.id)
    engine.dispose()

    with pytest.raises(RuntimeError, match="backend binding prevents migration downgrade"):
        command.downgrade(
            alembic_config(head_database),
            "0027_metadata_write_operations",
        )


def test_migration_0027_persists_one_use_fenced_metadata_write_journal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "metadata-write.db"
    migrate(database, "0026_metadata_correction_plans")
    migrate(database)
    engine, plan, authorization, run, run_lease = _persist_metadata_write_run(database)
    store = SQLiteMetadataWriteStore(engine)
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.release(run_lease, released_at=run.created_at + timedelta(seconds=1))
    refreshed_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        run.id,
        lease_token="synthetic-refreshed-metadata-write-run",
        acquired_at=run.created_at + timedelta(seconds=2),
        lease_expires_at=run.created_at + timedelta(minutes=5),
    )
    with pytest.raises(MetadataWriteStoreError):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                2,
                MetadataWriteRunStatus.PREPARED,
                run.created_at + timedelta(seconds=3),
                run_lease.fence_epoch,
            ),
            run_lease,
        )
    with pytest.raises(MetadataWriteStoreError, match="requires its run lease"):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                2,
                MetadataWriteRunStatus.PREPARED,
                run.created_at + timedelta(seconds=1, milliseconds=500),
                refreshed_lease.fence_epoch,
            ),
            refreshed_lease,
        )
    run_lease = refreshed_lease
    for sequence, status in enumerate(
        (
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
            MetadataWriteRunStatus.VERIFIED,
        ),
        start=2,
    ):
        store.append_event(
            MetadataWriteExecutionEvent(
                run_id=run.id,
                sequence_no=sequence,
                status=status,
                occurred_at=run.created_at + timedelta(seconds=sequence + 2),
                fence_epoch=run_lease.fence_epoch,
                confirmation_digest=(None if sequence == 2 else _sha(str(sequence))),
            ),
            run_lease,
        )

    assert store.get_authorization(authorization.id) == authorization
    assert store.get_run(run.id) == run
    assert [event.status for event in store.events_for_run(run.id)] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        MetadataWriteRunStatus.VERIFIED,
    ]
    with pytest.raises(MetadataWriteStoreError, match="transition"):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                6,
                MetadataWriteRunStatus.CANCELLED,
                run.created_at + timedelta(seconds=6),
                run_lease.fence_epoch,
            ),
            run_lease,
        )
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="immutable metadata write record"):
            connection.execute(text("UPDATE metadata_write_authorizations SET source_size_bytes=1"))
        with pytest.raises(IntegrityError, match="immutable metadata write event"):
            connection.execute(text("DELETE FROM metadata_write_events"))
        with pytest.raises(IntegrityError, match="gapless"):
            connection.execute(
                text(
                    "INSERT INTO metadata_write_events "
                    "(run_id, sequence_no, status, occurred_at, fence_epoch) "
                    "VALUES (:run, 7, 'CANCELLED', :at, :fence)"
                ),
                {
                    "run": str(run.id),
                    "at": run.created_at.isoformat(),
                    "fence": run_lease.fence_epoch,
                },
            )

    lease_store.release(
        run_lease,
        released_at=run.created_at + timedelta(seconds=10),
    )
    second_run_id = EntityId.new()
    second_created = run.created_at + timedelta(seconds=11)
    second_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        second_run_id,
        lease_token="synthetic-second-run",
        acquired_at=second_created,
        lease_expires_at=second_created + timedelta(minutes=2),
    )
    capability = ResolvedMetadataWriteCapability(
        METADATA_WRITE_CAPABILITY_ID,
        ROOT_ID,
        tmp_path / "synthetic-source-root",
        tmp_path / "synthetic-recovery",
    )
    second_run = build_metadata_write_run(
        authorization,
        capability,
        second_lease,
        run_id=second_run_id,
        created_at=second_created,
    )
    with pytest.raises(MetadataWriteStoreError, match="already consumed"):
        store.create_run(
            second_run,
            authorization,
            plan,
            second_lease,
            confirmation_digest=metadata_write_confirmation_digest(
                authorization,
                metadata_write_confirmation_text(authorization),
            ),
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="metadata write state prevents"):
        command.downgrade(alembic_config(database), "0026_metadata_correction_plans")


def test_metadata_write_status_uses_true_read_only_private_projection(
    head_database: Path,
) -> None:
    database = head_database
    engine, _plan_value, authorization, run, run_lease = _persist_metadata_write_run(database)
    store = SQLiteMetadataWriteStore(engine)
    store.append_event(
        MetadataWriteExecutionEvent(
            run.id,
            2,
            MetadataWriteRunStatus.PREPARED,
            run.created_at + timedelta(seconds=2),
            run_lease.fence_epoch,
            "PRIVATE_SYNTHETIC_FINDING",
            _sha("f"),
        ),
        run_lease,
    )
    engine.dispose()
    before = database.read_bytes()

    read_only_engine = create_sqlite_read_only_engine(database)
    with read_only_engine.connect() as connection:
        assert connection.execute(text("PRAGMA query_only")).scalar_one() == 1
    report = SQLiteMetadataWriteStatusReportReader(SQLiteMetadataWriteStore(read_only_engine)).read(
        run.id
    )
    payload = report.payload()
    read_only_engine.dispose()

    assert database.read_bytes() == before
    assert payload["command"] == "metadata-write-status"
    assert payload["status"] == "PREPARED"
    assert [event["status"] for event in payload["events"]] == [
        "CREATED",
        "PREPARED",
    ]
    encoded = json.dumps(payload, sort_keys=True)
    for private_material in (
        PRIVATE_PATH,
        OBSERVED_TITLE,
        SELECTED_TITLE,
        FULL_HASH,
        EXPECTED_OUTPUT_HASH,
        str(FILE_ID),
        str(OBSERVATION_ID),
        str(METADATA_WRITE_CAPABILITY_ID),
        "PRIVATE_SYNTHETIC_FINDING",
        _sha("f"),
        authorization.dcterms_modified,
    ):
        assert private_material not in encoded
    assert "fence_epoch" not in encoded


def test_metadata_write_persists_manual_recovery_from_prepared(
    head_database: Path,
) -> None:
    engine, _plan, _authorization, run, run_lease = _persist_metadata_write_run(head_database)
    store = SQLiteMetadataWriteStore(engine)
    store.append_event(
        MetadataWriteExecutionEvent(
            run.id,
            2,
            MetadataWriteRunStatus.PREPARED,
            run.created_at + timedelta(seconds=2),
            run_lease.fence_epoch,
        ),
        run_lease,
    )
    store.append_event(
        MetadataWriteExecutionEvent(
            run.id,
            3,
            MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
            run.created_at + timedelta(seconds=3),
            run_lease.fence_epoch,
            "STATE_AMBIGUOUS",
            _sha("d"),
        ),
        run_lease,
    )

    assert [event.status for event in store.events_for_run(run.id)] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED,
    ]
    engine.dispose()


def test_metadata_write_status_rejects_an_invalid_persisted_transition(
    head_database: Path,
) -> None:
    database = head_database
    engine, _plan_value, _authorization, run, run_lease = _persist_metadata_write_run(database)
    store = SQLiteMetadataWriteStore(engine)
    store.append_event(
        MetadataWriteExecutionEvent(
            run.id,
            2,
            MetadataWriteRunStatus.VALIDATION_FAILED,
            run.created_at + timedelta(seconds=2),
            run_lease.fence_epoch,
        ),
        run_lease,
    )
    with pytest.raises(MetadataWriteStoreError, match="transition"):
        store.append_event(
            MetadataWriteExecutionEvent(
                run.id,
                3,
                MetadataWriteRunStatus.RECOVERED,
                run.created_at + timedelta(seconds=3),
                run_lease.fence_epoch,
            ),
            run_lease,
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO metadata_write_events "
                "(run_id, sequence_no, status, occurred_at, fence_epoch) "
                "VALUES (:run, 3, 'RECOVERED', :at, :fence)"
            ),
            {
                "run": str(run.id),
                "at": (run.created_at + timedelta(seconds=3)).isoformat(),
                "fence": run_lease.fence_epoch,
            },
        )
    engine.dispose()

    read_only_engine = create_sqlite_read_only_engine(database)
    reader = SQLiteMetadataWriteStatusReportReader(SQLiteMetadataWriteStore(read_only_engine))
    with pytest.raises(
        MetadataWriteStatusReportError,
        match="^METADATA_WRITE_STATUS_UNAVAILABLE$",
    ):
        reader.read(run.id)
    read_only_engine.dispose()


def test_metadata_write_run_revalidates_the_latest_approved_review(
    head_database: Path,
) -> None:
    database = head_database
    engine = create_sqlite_engine(database)
    plan = _approved_plan_for_metadata_write(engine)
    assert plan.review is not None
    assert plan.review.review_item_id is not None
    assert plan.review.decision_id is not None
    assert plan.review.decision_sequence_no is not None
    authorization, preparation_lease, prepared_at = _metadata_write_authorization(
        engine,
        plan,
    )
    store = SQLiteMetadataWriteStore(engine)
    store.create_or_get_authorization(
        authorization,
        plan,
        preparation_lease,
        persisted_at=prepared_at + timedelta(seconds=1),
    )
    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    lease_store.release(
        preparation_lease,
        released_at=prepared_at + timedelta(seconds=2),
    )
    SQLiteResolutionReviewStore(engine).append_decision(
        ReviewDecision(
            id=EntityId.new(),
            review_item_id=plan.review.review_item_id,
            sequence_no=plan.review.decision_sequence_no + 1,
            decision=ReviewDecisionValue.REJECT,
            decision_reason="USER_REJECTED_AFTER_AUTHORIZATION",
            evidence_fingerprint=plan.candidate.evidence_fingerprint,
            candidate_set_fingerprint=plan.candidate.content_hash,
            decision_compatibility_version=METADATA_CORRECTION_DECISION_COMPATIBILITY,
            actor_kind=ReviewActorKind.USER,
            decided_at=prepared_at + timedelta(seconds=3),
        ),
        expected_latest_decision_id=plan.review.decision_id,
    )
    run_created_at = prepared_at + timedelta(seconds=4)
    run_id = EntityId.new()
    run_lease = lease_store.acquire(
        ROOT_ID,
        ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        run_id,
        lease_token="synthetic-stale-review-run",
        acquired_at=run_created_at,
        lease_expires_at=run_created_at + timedelta(minutes=2),
    )
    source_root = database.parent / "synthetic-source-root"
    recovery = database.parent / "synthetic-recovery"
    source_root.mkdir()
    recovery.mkdir()
    run = build_metadata_write_run(
        authorization,
        ResolvedMetadataWriteCapability(
            METADATA_WRITE_CAPABILITY_ID,
            ROOT_ID,
            source_root,
            recovery,
        ),
        run_lease,
        run_id=run_id,
        created_at=run_created_at,
    )

    with pytest.raises(MetadataWriteStoreError, match="could not be created"):
        store.create_run(
            run,
            authorization,
            plan,
            run_lease,
            confirmation_digest=metadata_write_confirmation_digest(
                authorization,
                metadata_write_confirmation_text(authorization),
            ),
        )
    assert store.get_run(run.id) is None
    assert store.events_for_run(run.id) == ()
    engine.dispose()


def test_migration_0027_empty_downgrade_restores_previous_lease_contract(
    tmp_path: Path,
) -> None:
    database = tmp_path / "metadata-write-empty-downgrade.db"
    migrate(database, "0026_metadata_correction_plans")
    migrate(database)
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        lease_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scan_root_write_leases'"
            )
        ).scalar_one()
    assert version == "0033_local_surface_foundation"
    assert "METADATA_WRITE_PREPARATION" in lease_sql
    assert "METADATA_WRITE_RUN" in lease_sql
    engine.dispose()

    command.downgrade(alembic_config(database), "0026_metadata_correction_plans")
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        lease_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='scan_root_write_leases'"
            )
        ).scalar_one()
    assert "metadata_write_authorizations" not in tables
    assert "metadata_write_runs" not in tables
    assert "metadata_write_events" not in tables
    assert "metadata_write_backend_bindings" not in tables
    assert "CONSOLIDATION_QUARANTINE_RUN" in lease_sql
    assert "METADATA_WRITE_PREPARATION" not in lease_sql
    assert "METADATA_WRITE_RUN" not in lease_sql
    engine.dispose()
