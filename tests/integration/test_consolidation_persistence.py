"""Synthetic migration coverage for S-EB08-06 consolidation persistence."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, func, insert, inspect, select
from sqlalchemy.exc import IntegrityError

from foliotone.consolidation.contracts import (
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationCandidateSnapshot,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationIntentCode,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    ConsolidationQualityDimension,
    ConsolidationQualityEvidence,
    ConsolidationQualityExecutionDisposition,
    ConsolidationQualityFinding,
    ConsolidationQualityItemExecution,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
    KeepPreferenceOutcome,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
    consolidation_quality_evidence_fingerprint,
)
from foliotone.consolidation.serialization import consolidation_plan_content_hash
from foliotone.core import (
    EbookCollectionItemStatus,
    EntityId,
    EntityKind,
    MatchStatus,
    MediaType,
    PresenceState,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    alembic_config,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
    w3_schema,
)
from foliotone.persistence import calibre_library_schema as calibre
from foliotone.persistence import consolidation_schema as cs
from foliotone.persistence import relation_candidate_schema as relation_schema
from foliotone.persistence.consolidation import ConsolidationStoreError, SQLiteConsolidationStore
from foliotone.workflows.quality import (
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityFindingSeverity,
    EbookQualityStatus,
)

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _hashed(plan: ConsolidationPlan) -> ConsolidationPlan:
    return replace(plan, content_hash=consolidation_plan_content_hash(plan))


def _quality_pair(
    engine: Engine,
    root: ScanRoot,
    scan: ScanRun,
    *,
    persist: bool = True,
) -> tuple[
    tuple[EntityId, EntityId],
    tuple[EntityId, EntityId],
    tuple[ConsolidationQualityEvidence, ConsolidationQualityEvidence],
]:
    file_ids = tuple(sorted((EntityId.new(), EntityId.new()), key=str))
    observation_ids = (EntityId.new(), EntityId.new())
    collection_run_id = EntityId.new()
    item_ids = (EntityId.new(), EntityId.new())
    dimensions = tuple(
        ConsolidationQualityDimension(name, EbookQualityDimensionStatus.OK)
        for name in EbookQualityDimensionName
    )
    with engine.begin() as connection:
        for ordinal, (file_id, observation_id) in enumerate(
            zip(file_ids, observation_ids, strict=True)
        ):
            connection.execute(insert(schema.file_records).values(
                id=str(file_id), scan_root_id=str(root.id),
                relative_path=f"Synthetic/Book-{ordinal}.epub", size_bytes=10,
                modified_at=NOW.isoformat(), media_type=MediaType.EBOOK.value,
                presence_state="PRESENT", first_seen_at=NOW.isoformat(),
                last_seen_at=NOW.isoformat(), consecutive_missing_scans=0,
            ))
            connection.execute(insert(schema.file_observations).values(
                id=str(observation_id), file_id=str(file_id), scan_run_id=str(scan.id),
                relative_path=f"Synthetic/Book-{ordinal}.epub", size_bytes=10,
                modified_at=NOW.isoformat(), observed_at=NOW.isoformat(),
            ))
        connection.execute(insert(w3_schema.ebook_collection_runs).values(
            id=str(collection_run_id), scan_root_id=str(root.id),
            source_scan_run_id=str(scan.id), profile="ebook-collection-analysis/v1",
            analysis_profile="ebook-analysis-workflow/v3", fresh=False, worker_count=1,
            started_at=NOW.isoformat(), status="COMPLETED", completed_at=NOW.isoformat(),
        ))
        for ordinal, (item_id, observation_id) in enumerate(
            zip(item_ids, observation_ids, strict=True)
        ):
            connection.execute(insert(w3_schema.ebook_collection_items).values(
                id=str(item_id), run_id=str(collection_run_id),
                observation_id=str(observation_id), ordinal=ordinal, format_name="EPUB",
                status="SUCCEEDED", attempt_count=1, started_at=NOW.isoformat(),
                completed_at=NOW.isoformat(), quality_status="OK",
                reused_step_count=0, executed_step_count=0, finding_count=0,
            ))
    values = []
    execution_sets: list[tuple[ConsolidationQualityItemExecution, ...]] = []
    step_specs = (
        ("metadata", "READ_METADATA"),
        ("text", "EXTRACT_TEXT"),
        ("cover", "READ_METADATA"),
        ("structural-validation", "STRUCTURAL_VALIDATION"),
    )
    with engine.begin() as connection:
        for item_id, observation_id in zip(item_ids, observation_ids, strict=True):
            item_execution_values = []
            for ordinal, (step_name, capability) in enumerate(step_specs):
                execution_id = EntityId.new()
                connection.execute(insert(schema.tool_executions).values(
                    id=str(execution_id), provider_id="synthetic-quality",
                    tool_version="1", adapter_version="1", capability=capability,
                    input_identity=f"file-observation:{observation_id}",
                    started_at=NOW.isoformat(), finished_at=NOW.isoformat(),
                    status="SUCCEEDED", exit_code=0,
                ))
                connection.execute(insert(w3_schema.ebook_collection_item_executions).values(
                    id=str(EntityId.new()), item_id=str(item_id), ordinal=ordinal,
                    step_name=step_name, disposition="EXECUTED",
                    execution_id=str(execution_id),
                ))
                item_execution_values.append(ConsolidationQualityItemExecution(
                    ordinal, step_name, ConsolidationQualityExecutionDisposition.EXECUTED,
                    execution_id,
                ))
                result_values: tuple[tuple[str, str, str], ...]
                if step_name == "metadata":
                    result_values = (
                        ("calibre_metadata", "title", "Synthetic Book"),
                        ("calibre_metadata", "language", "en"),
                        ("calibre_metadata", "publisher", "Synthetic Press"),
                        ("calibre_metadata", "publication_date", "2026"),
                        ("ebook_metadata_candidate", "contributor.0.name", "Synthetic Author"),
                        ("ebook_metadata_candidate", "contributor.0.role", "author"),
                        ("ebook_metadata_candidate", "identifier.0.value", "synthetic-id"),
                    )
                elif step_name == "text":
                    result_values = (
                        ("calibre_text_analysis", "text_status", "TEXT_EXTRACTED"),
                        ("calibre_text_analysis", "normalized_character_count", "3000"),
                    )
                elif step_name == "cover":
                    result_values = (("calibre_cover_analysis", "cover_status", "COVER_EXTRACTED"),)
                else:
                    result_values = (
                        ("epubcheck_validation", "conformance_status", "CONFORMANT"),
                        ("epubcheck_validation", "fatal_count", "0"),
                        ("epubcheck_validation", "error_count", "0"),
                        ("epubcheck_validation", "warning_count", "0"),
                    )
                connection.execute(insert(schema.tool_results), [
                    {
                        "id": str(EntityId.new()), "execution_id": str(execution_id),
                        "result_type": result_type,
                        "target_kind": EntityKind.FILE_OBSERVATION.value,
                        "target_id": str(observation_id), "key": key, "value": result_value,
                    }
                    for result_type, key, result_value in result_values
                ])
            execution_sets.append(tuple(item_execution_values))
            connection.execute(w3_schema.ebook_collection_items.update().where(
                w3_schema.ebook_collection_items.c.id == str(item_id)
            ).values(executed_step_count=4))
    for item_id, observation_id, item_executions in zip(
        item_ids, observation_ids, execution_sets, strict=True
    ):
        material: dict[str, object] = {
            "profile": "consolidation-quality-evidence/v1",
            "collection_run_id": collection_run_id,
            "collection_item_id": item_id,
            "observation_id": observation_id,
            "scan_root_id": root.id,
            "source_scan_run_id": scan.id,
            "collection_profile": "ebook-collection-analysis/v1",
            "analysis_profile": "ebook-analysis-workflow/v3",
            "quality_profile": "ebook-quality/v1",
            "format_label": "EPUB",
            "item_status": EbookCollectionItemStatus.SUCCEEDED,
            "aggregate_quality_status": EbookQualityStatus.OK,
            "reused_step_count": 0,
            "executed_step_count": 4,
            "finding_count": 0,
            "dimensions": dimensions,
            "item_executions": item_executions,
            "findings": (),
        }
        values.append(ConsolidationQualityEvidence(
            EntityId.new(), **material,
            assessment_fingerprint=consolidation_quality_evidence_fingerprint(**material),
            created_at=NOW,
        ))
    persisted = (
        tuple(SQLiteConsolidationStore(engine).create_or_get_quality(value) for value in values)
        if persist
        else tuple(values)
    )
    return file_ids, observation_ids, (persisted[0], persisted[1])


def test_migration_0016_and_nonempty_downgrade_guard(tmp_path: Path) -> None:
    database = tmp_path / "consolidation.db"
    migrate(database, "0015_calibre_library_reconciliation")
    before = create_sqlite_engine(database)
    assert cs.consolidation_plans.name not in inspect(before).get_table_names()
    before.dispose()

    migrate(database)
    engine = create_sqlite_engine(database)
    assert {table.name for table in cs.CONSOLIDATION_TABLES} <= set(
        inspect(engine).get_table_names()
    )
    root = ScanRoot(EntityId.new(), "synthetic-consolidation", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    with engine.begin() as connection:
        connection.execute(
            insert(cs.consolidation_plans).values(
                id=str(EntityId.new()),
                profile="consolidation-plan/v1",
                plan_version=1,
                serializer_version="canonical-json/v1",
                scan_root_id=str(root.id),
                source_scan_run_id=str(scan.id),
                status="BLOCKED",
                execution_state="NOT_EXECUTABLE",
                content_hash="a" * 64,
                created_at=NOW.isoformat(),
            )
        )
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(
            alembic_config(database),
            "0015_calibre_library_reconciliation",
        )


def test_blocked_plan_roundtrips_through_a_fresh_store(tmp_path: Path) -> None:
    database = tmp_path / "roundtrip.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-roundtrip", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    plan = ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1",
        root.id, scan.id, None, None, None, None, None, (), (), (), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE),),
        ConsolidationPlanStatus.BLOCKED,
        ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64,
        NOW,
    )
    plan = _hashed(plan)
    assert SQLiteConsolidationStore(engine).create_or_get_plan(plan) == plan
    engine.dispose()
    fresh = SQLiteConsolidationStore(create_sqlite_engine(database))
    assert fresh.get_plan(plan.id) == plan
    assert fresh.create_or_get_plan(plan) == plan
    changed = _hashed(
        replace(
            plan,
            blockers=(
                ConsolidationBlocker(ConsolidationBlockerCode.IDENTITY_NOT_CONFIRMED),
            ),
        )
    )
    with pytest.raises(ConsolidationStoreError, match="retry payload differs"):
        fresh.create_or_get_plan(changed)
    bounded_engine = create_sqlite_engine(database)
    with bounded_engine.begin() as connection:
        connection.execute(insert(cs.consolidation_plan_blockers), [
            {
                "plan_id": str(plan.id),
                "ordinal": ordinal,
                "code": ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE.value,
            }
            for ordinal in range(1, 33)
        ])
    with pytest.raises(ConsolidationStoreError, match="bounded and contiguous"):
        SQLiteConsolidationStore(bounded_engine).get_plan(plan.id)


def test_missing_polymorphic_references_roll_back_atomically(tmp_path: Path) -> None:
    database = tmp_path / "invalid-reference.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-invalid", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    missing = str(EntityId.new())
    evidence = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.CALIBRE_SNAPSHOT,
        missing,
        ConsolidationEvidenceRole.DEPENDENCY,
        "a" * 64,
    )
    dependency = ConsolidationDependency(
        ConsolidationFileRole.CANDIDATE,
        ConsolidationDependencyKind.CALIBRE,
        ConsolidationDependencyState.KNOWN_PRESENT,
        "b" * 64,
        "CALIBRE_SNAPSHOT",
        EntityId.parse(missing),
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1",
        root.id, scan.id, None, None, None, None, None, (dependency,), (), (), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.CALIBRE_OWNERSHIP_PRESENT, (evidence,)),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match="unknown or missing"):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(cs.consolidation_plans)
        ).scalar_one() == 0


def test_foreign_polymorphic_reference_rolls_back_atomically(tmp_path: Path) -> None:
    database = tmp_path / "foreign-reference.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-local", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    foreign_root = ScanRoot(EntityId.new(), "synthetic-foreign", MediaType.EBOOK)
    foreign_scan = ScanRun(
        EntityId.new(), foreign_root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW
    )
    for value in (root, foreign_root):
        repository(engine, ScanRoot).save(value)
    for value in (scan, foreign_scan):
        repository(engine, ScanRun).save(value)
    snapshot_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(insert(calibre.calibre_library_snapshots).values(
            id=str(snapshot_id), scan_root_id=str(foreign_root.id),
            source_scan_run_id=str(foreign_scan.id), profile="calibre-library-snapshot/v1",
            adapter_version="calibredb-library/1", tool_version="synthetic/1",
            parser_version="calibre-library-parser/1", library_identity_digest="d" * 64,
            status="COMPLETED", started_at=NOW.isoformat(), completed_at=NOW.isoformat(),
        ))
    evidence = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.CALIBRE_SNAPSHOT, str(snapshot_id),
        ConsolidationEvidenceRole.DEPENDENCY, "a" * 64,
    )
    dependency = ConsolidationDependency(
        ConsolidationFileRole.CANDIDATE, ConsolidationDependencyKind.CALIBRE,
        ConsolidationDependencyState.KNOWN_PRESENT, "b" * 64,
        "CALIBRE_SNAPSHOT", snapshot_id,
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1",
        root.id, scan.id, None, None, None, None, None, (dependency,), (), (), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.CALIBRE_OWNERSHIP_PRESENT, (evidence,)),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match="foreign lineage"):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(cs.consolidation_plans)
        ).scalar_one() == 0


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (KeepPreferenceStatus.TIED, KeepPreferenceReasonCode.TIED),
        (KeepPreferenceStatus.BLOCKED, KeepPreferenceReasonCode.HARD_CONSTRAINT),
    ],
)
def test_undirected_preference_preserves_left_right_quality_slots(
    tmp_path: Path,
    status: KeepPreferenceStatus,
    reason: KeepPreferenceReasonCode,
) -> None:
    database = tmp_path / f"slots-{status.value.lower()}.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-slots", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, evidence = _quality_pair(engine, root, scan)
    quality = (
        evidence[0].snapshot(ConsolidationFileRole.KEEPER),
        evidence[1].snapshot(ConsolidationFileRole.CANDIDATE),
    )
    preference = KeepPreferenceOutcome(
        EntityId.new(), "ebook-keep-preference/v1", "1",
        file_ids[0], observation_ids[0], file_ids[1], observation_ids[1],
        status, None, None, (reason,), "a" * 64, "b" * 64, quality, "c" * 64,
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1",
        root.id, scan.id, None, None, None, preference, None, (), quality, (), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    store = SQLiteConsolidationStore(engine)
    assert store.create_or_get_plan(plan) == plan
    engine.dispose()
    fresh = SQLiteConsolidationStore(create_sqlite_engine(database))
    assert fresh.get_plan(plan.id) == plan
    assert fresh.create_or_get_plan(plan) == plan


def test_full_plan_graph_roundtrips_losslessly_in_a_fresh_process(tmp_path: Path) -> None:
    database = tmp_path / "full-graph.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-full-graph", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, evidence = _quality_pair(engine, root, scan)
    full_sha256 = "f" * 64
    relation_id = EntityId.new()
    relation_fingerprint = "1" * 64
    relation_candidate_set = "2" * 64
    calibre_snapshot_id = EntityId.new()
    with engine.begin() as connection:
        for observation_id in observation_ids:
            connection.execute(insert(schema.fingerprints).values(
                id=str(EntityId.new()), target_kind=EntityKind.FILE_OBSERVATION.value,
                target_id=str(observation_id), kind="FILE_SHA256", algorithm="sha256",
                algorithm_version="1", value=full_sha256, created_at=NOW.isoformat(),
            ))
        connection.execute(insert(relation_schema.relation_candidates).values(
            id=str(relation_id), scan_root_id=str(root.id), source_scan_run_id=str(scan.id),
            left_kind=EntityKind.FILE.value, left_id=str(file_ids[0]),
            right_kind=EntityKind.FILE.value, right_id=str(file_ids[1]),
            relation_type=RelationType.EXACT_DUPLICATE.value, matcher_name="synthetic",
            matcher_version="synthetic/1", decision_compatibility_version="synthetic-decision/1",
            evidence_fingerprint=relation_fingerprint,
            candidate_set_fingerprint=relation_candidate_set, confidence=1.0,
            status=MatchStatus.CONFIRMED.value, created_at=NOW.isoformat(),
        ))
        connection.execute(insert(calibre.calibre_library_snapshots).values(
            id=str(calibre_snapshot_id), scan_root_id=str(root.id),
            source_scan_run_id=str(scan.id), profile="calibre-library-snapshot/v1",
            adapter_version="calibredb-library/1", tool_version="synthetic/1",
            parser_version="calibre-library-parser/1", library_identity_digest="3" * 64,
            status="COMPLETED", started_at=NOW.isoformat(), completed_at=NOW.isoformat(),
        ))
    identity = ConsolidationIdentitySnapshot(
        relation_id, RelationType.EXACT_DUPLICATE, EntityKind.FILE, EntityKind.FILE,
        file_ids[0], file_ids[1], root.id, scan.id, MatchStatus.CONFIRMED,
        "synthetic/1", "synthetic-decision/1", relation_fingerprint,
        relation_candidate_set,
    )
    quality = (
        evidence[0].snapshot(ConsolidationFileRole.KEEPER),
        evidence[1].snapshot(ConsolidationFileRole.CANDIDATE),
    )
    preference = KeepPreferenceOutcome(
        EntityId.new(), "ebook-keep-preference/v1", "1", file_ids[0], observation_ids[0],
        file_ids[1], observation_ids[1], KeepPreferenceStatus.PREFERRED, file_ids[0],
        file_ids[1], (KeepPreferenceReasonCode.PREFERRED_FORMAT,), "4" * 64, "5" * 64,
        quality, "6" * 64,
    )
    endpoints = tuple(
        ConsolidationFileEndpoint(
            role, file_id, observation_id, root.id, scan.id, PresenceState.PRESENT,
            full_sha256, 10, NOW, NOW, "EPUB",
        )
        for role, file_id, observation_id in zip(
            ConsolidationFileRole, file_ids, observation_ids, strict=True
        )
    )
    dependency = ConsolidationDependency(
        ConsolidationFileRole.CANDIDATE, ConsolidationDependencyKind.CALIBRE,
        ConsolidationDependencyState.KNOWN_PRESENT, "7" * 64,
        "CALIBRE_SNAPSHOT", calibre_snapshot_id,
    )
    review = ConsolidationReviewSnapshot(
        ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.MISSING, "5" * 64,
        "6" * 64, ReviewCandidateKind.KEEP_PREFERENCE, "ebook-keep-preference",
        "ebook-keep-preference-decision/v1",
    )
    preconditions = tuple(
        ConsolidationFilePreconditionSnapshot(
            endpoint.role, ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
            endpoint.file_id, endpoint.observation_id, root.id, scan.id,
            PresenceState.PRESENT, full_sha256, 10, NOW, NOW,
        )
        for endpoint in endpoints
    )
    intents = (
        ConsolidationFutureOperationIntent(
            0, ConsolidationIntentCode.KEEP, ConsolidationFileRole.KEEPER
        ),
        ConsolidationFutureOperationIntent(
            1, ConsolidationIntentCode.PURGE, ConsolidationFileRole.CANDIDATE
        ),
    )
    candidate = ConsolidationCandidateSnapshot(
        EntityId.new(), "ebook-consolidation-candidate/v1", root.id, scan.id,
        relation_id, relation_fingerprint, preference.preference_id,
        preference.evidence_fingerprint, file_ids[0], file_ids[1], "8" * 64,
        "9" * 64, "a" * 64, "b" * 64, intents, None,
    )
    reference = ConsolidationEvidenceReference(
        ConsolidationEvidenceKind.RELATION_CANDIDATE, str(relation_id),
        ConsolidationEvidenceRole.IDENTITY, relation_fingerprint,
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1", root.id,
        scan.id, identity, endpoints[0], endpoints[1], preference, candidate,
        (dependency,), quality, (review,), preconditions, intents,
        (ConsolidationBlocker(ConsolidationBlockerCode.PROTECTED_SOURCE_ROOT, (reference,)),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    normalized = replace(
        plan,
        consolidation_candidate=replace(plan.consolidation_candidate, created_at=NOW),
    )
    assert SQLiteConsolidationStore(engine).create_or_get_plan(plan) == normalized
    engine.dispose()
    fresh = SQLiteConsolidationStore(create_sqlite_engine(database))
    assert fresh.get_plan(plan.id) == normalized
    assert fresh.create_or_get_plan(plan) == normalized


@pytest.mark.parametrize("foreign_kind", ["FILE", "FOREIGN_OBSERVATION"])
def test_precondition_requires_observation_bound_full_hash(
    tmp_path: Path,
    foreign_kind: str,
) -> None:
    database = tmp_path / f"hash-{foreign_kind.lower()}.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-hash", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, evidence = _quality_pair(engine, root, scan)
    full_hash = "e" * 64
    with engine.begin() as connection:
        connection.execute(insert(schema.fingerprints).values(
            id=str(EntityId.new()),
            target_kind=(
                EntityKind.FILE.value
                if foreign_kind == "FILE"
                else EntityKind.FILE_OBSERVATION.value
            ),
            target_id=str(file_ids[0] if foreign_kind == "FILE" else observation_ids[1]),
            kind="FILE_SHA256", algorithm="sha256", algorithm_version="1",
            value=full_hash, created_at=NOW.isoformat(),
        ))
    endpoint = ConsolidationFileEndpoint(
        ConsolidationFileRole.KEEPER, file_ids[0], observation_ids[0], root.id,
        scan.id, PresenceState.PRESENT, full_hash, 10, NOW, NOW, "EPUB",
    )
    candidate_endpoint = ConsolidationFileEndpoint(
        ConsolidationFileRole.CANDIDATE, file_ids[1], observation_ids[1], root.id,
        scan.id, PresenceState.PRESENT, full_hash, 10, NOW, NOW, "EPUB",
    )
    precondition = ConsolidationFilePreconditionSnapshot(
        ConsolidationFileRole.KEEPER,
        ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
        file_ids[0], observation_ids[0], root.id, scan.id, PresenceState.PRESENT,
        full_hash, 10, NOW, NOW,
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1", root.id,
        scan.id, None, endpoint, candidate_endpoint, None, None, (),
        (
            evidence[0].snapshot(ConsolidationFileRole.KEEPER),
            evidence[1].snapshot(ConsolidationFileRole.CANDIDATE),
        ), (), (precondition,), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.PRECONDITION_INCOMPLETE),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match="full hash evidence is missing"):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)


def test_quality_rejects_same_aggregate_with_different_dimension_projection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quality-projection.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-quality-projection", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    _, _, evidence = _quality_pair(engine, root, scan, persist=False)
    value = evidence[0]
    metadata_execution = value.item_executions[0].execution_id
    text_execution = value.item_executions[1].execution_id
    finding_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(schema.tool_results.update().where(
            schema.tool_results.c.execution_id == str(text_execution),
            schema.tool_results.c.key == "normalized_character_count",
        ).values(value="100"))
        connection.execute(w3_schema.ebook_collection_items.update().where(
            w3_schema.ebook_collection_items.c.id == str(value.collection_item_id)
        ).values(quality_status="REVIEW", finding_count=1))
        connection.execute(insert(w3_schema.ebook_collection_findings).values(
            id=str(finding_id), item_id=str(value.collection_item_id), ordinal=0,
            code="METADATA_TITLE_MISSING", dimension="METADATA", severity="WARNING",
        ))
        connection.execute(insert(w3_schema.ebook_collection_finding_executions).values(
            id=str(EntityId.new()), finding_id=str(finding_id), ordinal=0,
            execution_id=str(metadata_execution),
        ))
    dimensions = (
        ConsolidationQualityDimension(
            EbookQualityDimensionName.METADATA, EbookQualityDimensionStatus.REVIEW
        ),
        *value.dimensions[1:],
    )
    findings = (
        ConsolidationQualityFinding(
            0, "METADATA_TITLE_MISSING", EbookQualityDimensionName.METADATA,
            EbookQualityFindingSeverity.WARNING, (metadata_execution,),
        ),
    )
    material = {
        "profile": value.profile,
        "collection_run_id": value.collection_run_id,
        "collection_item_id": value.collection_item_id,
        "observation_id": value.observation_id,
        "scan_root_id": value.scan_root_id,
        "source_scan_run_id": value.source_scan_run_id,
        "collection_profile": value.collection_profile,
        "analysis_profile": value.analysis_profile,
        "quality_profile": value.quality_profile,
        "format_label": value.format_label,
        "item_status": value.item_status,
        "aggregate_quality_status": EbookQualityStatus.REVIEW,
        "reused_step_count": value.reused_step_count,
        "executed_step_count": value.executed_step_count,
        "finding_count": 1,
        "dimensions": dimensions,
        "item_executions": value.item_executions,
        "findings": findings,
    }
    mismatched = ConsolidationQualityEvidence(
        value.id, **material,
        assessment_fingerprint=consolidation_quality_evidence_fingerprint(**material),
        created_at=NOW,
    )
    with pytest.raises(ConsolidationStoreError, match="persisted tool projection"):
        SQLiteConsolidationStore(engine).create_or_get_quality(mismatched)


def test_quality_finding_execution_ordinals_must_be_contiguous(tmp_path: Path) -> None:
    database = tmp_path / "finding-ordinal.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-finding-ordinal", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    _, _, evidence = _quality_pair(engine, root, scan)
    value = evidence[0]
    finding_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(insert(w3_schema.ebook_collection_findings).values(
            id=str(finding_id), item_id=str(value.collection_item_id), ordinal=0,
            code="SYNTHETIC_GAP", dimension="TEXT", severity="WARNING",
        ))
        connection.execute(insert(w3_schema.ebook_collection_finding_executions).values(
            id=str(EntityId.new()), finding_id=str(finding_id), ordinal=1,
            execution_id=str(value.item_executions[0].execution_id),
        ))
    with pytest.raises(ConsolidationStoreError, match="references are invalid"):
        SQLiteConsolidationStore(engine).get_quality(value.id)


def test_candidate_requires_full_directed_cross_binding(tmp_path: Path) -> None:
    database = tmp_path / "candidate-cross-binding.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-candidate-binding", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    candidate = ConsolidationCandidateSnapshot(
        EntityId.new(), "ebook-consolidation-candidate/v1", root.id, scan.id,
        EntityId.new(), "1" * 64, EntityId.new(), "2" * 64, EntityId.new(),
        EntityId.new(), "3" * 64, "4" * 64, "5" * 64, "6" * 64, (), None,
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1", root.id,
        scan.id, None, None, None, None, candidate, (), (), (), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match="fully directed"):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)


def test_keep_preference_review_rejects_undirected_preference(tmp_path: Path) -> None:
    database = tmp_path / "undirected-review.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-undirected-review", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, evidence = _quality_pair(engine, root, scan)
    quality = (
        evidence[0].snapshot(ConsolidationFileRole.KEEPER),
        evidence[1].snapshot(ConsolidationFileRole.CANDIDATE),
    )
    preference = KeepPreferenceOutcome(
        EntityId.new(), "ebook-keep-preference/v1", "1", file_ids[0], observation_ids[0],
        file_ids[1], observation_ids[1], KeepPreferenceStatus.TIED, None, None,
        (KeepPreferenceReasonCode.TIED,), "1" * 64, "2" * 64, quality, "3" * 64,
    )
    review = ConsolidationReviewSnapshot(
        ReviewType.KEEP_PREFERENCE, ConsolidationReviewState.MISSING, "2" * 64,
        "3" * 64, ReviewCandidateKind.KEEP_PREFERENCE, "ebook-keep-preference",
        "ebook-keep-preference-decision/v1",
    )
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1", root.id,
        scan.id, None, None, None, preference, None, (), quality, (review,), (), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.KEEP_PREFERENCE_UNRESOLVED),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match="exact preferred direction"):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)


@pytest.mark.parametrize("binding", ["DEPENDENCY", "WRONG_KIND", "REVIEW"])
def test_precondition_binding_is_role_specific(tmp_path: Path, binding: str) -> None:
    database = tmp_path / f"precondition-{binding.lower()}.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-precondition-binding", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, _ = _quality_pair(engine, root, scan)
    full_hash = "c" * 64
    snapshot_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(insert(schema.fingerprints).values(
            id=str(EntityId.new()), target_kind=EntityKind.FILE_OBSERVATION.value,
            target_id=str(observation_ids[0]), kind="FILE_SHA256", algorithm="sha256",
            algorithm_version="1", value=full_hash, created_at=NOW.isoformat(),
        ))
        connection.execute(insert(calibre.calibre_library_snapshots).values(
            id=str(snapshot_id), scan_root_id=str(root.id), source_scan_run_id=str(scan.id),
            profile="calibre-library-snapshot/v1", adapter_version="calibredb-library/1",
            tool_version="synthetic/1", parser_version="calibre-library-parser/1",
            library_identity_digest="7" * 64, status="COMPLETED",
            started_at=NOW.isoformat(), completed_at=NOW.isoformat(),
        ))
    endpoints = tuple(
        ConsolidationFileEndpoint(
            role, file_id, observation_id, root.id, scan.id, PresenceState.PRESENT,
            full_hash, 10, NOW, NOW, "EPUB",
        )
        for role, file_id, observation_id in zip(
            ConsolidationFileRole, file_ids, observation_ids, strict=True
        )
    )
    dependency = ConsolidationDependency(
        (
            ConsolidationFileRole.KEEPER
            if binding == "WRONG_KIND"
            else ConsolidationFileRole.CANDIDATE
        ),
        (
            ConsolidationDependencyKind.SIDECAR
            if binding == "WRONG_KIND"
            else ConsolidationDependencyKind.CALIBRE
        ),
        ConsolidationDependencyState.UNKNOWN, "8" * 64,
        "CALIBRE_SNAPSHOT", snapshot_id,
    )
    review = ConsolidationReviewSnapshot(
        ReviewType.CONSOLIDATION_CANDIDATE, ConsolidationReviewState.ACCEPTED,
        "9" * 64, "a" * 64, ReviewCandidateKind.CONSOLIDATION_CANDIDATE,
        "ebook-consolidation-candidate", "ebook-consolidation-candidate-decision/v1",
        EntityId.new(), EntityId.new(), 1,
    )
    if binding in {"DEPENDENCY", "WRONG_KIND"}:
        precondition = ConsolidationFilePreconditionSnapshot(
            ConsolidationFileRole.KEEPER,
            ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
            file_ids[0], observation_ids[0], root.id, scan.id, PresenceState.PRESENT,
            full_hash, 10, NOW, NOW, dependency.kind,
            ConsolidationDependencyState.UNKNOWN, dependency.material_fingerprint,
            dependency.snapshot_kind, dependency.snapshot_id,
        )
        reviews: tuple[ConsolidationReviewSnapshot, ...] = ()
        match = (
            "relationship code and dependency kind differ"
            if binding == "WRONG_KIND"
            else "dependency binding differs"
        )
    else:
        precondition = ConsolidationFilePreconditionSnapshot(
            ConsolidationFileRole.KEEPER,
            ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
            file_ids[0], observation_ids[0], root.id, scan.id, PresenceState.PRESENT,
            full_hash, 10, NOW, NOW, review_item_id=review.review_item_id,
            review_decision_id=review.decision_id,
            review_decision_sequence_no=review.decision_sequence_no,
            review_decision_compatibility_version=review.decision_compatibility_version,
            review_evidence_fingerprint=review.evidence_fingerprint,
            review_candidate_set_fingerprint=review.candidate_set_fingerprint,
        )
        reviews = (review,)
        match = "review binding is stale"
    plan = _hashed(ConsolidationPlan(
        EntityId.new(), "consolidation-plan/v1", 1, "canonical-json/v1", root.id,
        scan.id, None, endpoints[0], endpoints[1], None, None,
        (dependency,), (), reviews, (precondition,), (),
        (ConsolidationBlocker(ConsolidationBlockerCode.PRECONDITION_INCOMPLETE),),
        ConsolidationPlanStatus.BLOCKED, ConsolidationExecutionState.NOT_EXECUTABLE,
        "0" * 64, NOW,
    ))
    with pytest.raises(ConsolidationStoreError, match=match):
        SQLiteConsolidationStore(engine).create_or_get_plan(plan)


def test_schema_rejects_invalid_direction_review_sum_type_and_nullable_hash(
    tmp_path: Path,
) -> None:
    database = tmp_path / "schema-negatives.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(EntityId.new(), "synthetic-schema-negative", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    file_ids, observation_ids, evidence = _quality_pair(engine, root, scan)
    plan_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(insert(cs.consolidation_plans).values(
            id=str(plan_id), profile="consolidation-plan/v1", plan_version=1,
            serializer_version="canonical-json/v1", scan_root_id=str(root.id),
            source_scan_run_id=str(scan.id), status="BLOCKED",
            execution_state="NOT_EXECUTABLE", content_hash="d" * 64,
            created_at=NOW.isoformat(),
        ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(cs.consolidation_keep_preferences).values(
                id=str(EntityId.new()), profile="ebook-keep-preference/v1",
                profile_version="1", left_file_id=str(file_ids[0]),
                left_observation_id=str(observation_ids[0]), right_file_id=str(file_ids[1]),
                right_observation_id=str(observation_ids[1]),
                left_quality_evidence_id=str(evidence[0].id),
                right_quality_evidence_id=str(evidence[1].id), status="PREFERRED",
                configuration_fingerprint="1" * 64, evidence_fingerprint="2" * 64,
                candidate_set_fingerprint="3" * 64, created_at=NOW.isoformat(),
            ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(cs.consolidation_plan_reviews).values(
                plan_id=str(plan_id), ordinal=0, review_type="KEEP_PREFERENCE",
                state="ACCEPTED", producer_name="ebook-keep-preference",
                producer_version="1",
                decision_compatibility_version="ebook-keep-preference-decision/v1",
                evidence_fingerprint="1" * 64, candidate_set_fingerprint="2" * 64,
            ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(cs.consolidation_plan_preconditions).values(
                plan_id=str(plan_id), ordinal=0, file_role="KEEPER",
                code="CALIBRE_RELATIONSHIP_UNCHANGED",
                expected_file_id=str(file_ids[0]),
                expected_observation_id=str(observation_ids[0]),
                expected_scan_root_id=str(root.id), expected_scan_run_id=str(scan.id),
                expected_presence_state="PRESENT", expected_full_sha256="f" * 64,
                expected_size_bytes=10, expected_modified_at=NOW.isoformat(),
                expected_observed_at=NOW.isoformat(), dependency_kind="CALIBRE",
                dependency_state="UNKNOWN", dependency_fingerprint="not-a-sha",
                dependency_snapshot_kind="CALIBRE_SNAPSHOT",
                dependency_snapshot_id=str(EntityId.new()),
            ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(cs.consolidation_plan_preconditions).values(
                plan_id=str(plan_id), ordinal=0, file_role="KEEPER",
                code="CALIBRE_RELATIONSHIP_UNCHANGED",
                expected_file_id=str(file_ids[0]),
                expected_observation_id=str(observation_ids[0]),
                expected_scan_root_id=str(root.id), expected_scan_run_id=str(scan.id),
                expected_presence_state="PRESENT", expected_full_sha256="f" * 64,
                expected_size_bytes=10, expected_modified_at=NOW.isoformat(),
                expected_observed_at=NOW.isoformat(), dependency_kind="SIDECAR",
                dependency_state="UNKNOWN", dependency_fingerprint="4" * 64,
                dependency_snapshot_kind="CALIBRE_SNAPSHOT",
                dependency_snapshot_id=str(EntityId.new()),
            ))
