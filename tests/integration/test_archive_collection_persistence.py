"""Focused persistence coverage for restartable archive collection runs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from foliotone.archive.signatures import observe_archive_signature_v2
from foliotone.core import (
    ArchiveCollectionDisposition,
    ArchiveCollectionItem,
    ArchiveCollectionItemSource,
    ArchiveCollectionItemStatus,
    ArchiveCollectionPlanFindingCounts,
    ArchiveCollectionRun,
    ArchiveCollectionRunStatus,
    EntityId,
)
from foliotone.persistence import alembic_config, archive_schema, create_sqlite_engine, migrate
from foliotone.persistence.archive_collection import (
    ArchiveCollectionPlanEntry,
    ArchiveCollectionStoreError,
    SQLiteArchiveCollectionStore,
    archive_collection_plan_content_hash,
)

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("00000000-0000-0000-0000-000000000301")
SCAN_ID = EntityId.parse("00000000-0000-0000-0000-000000000302")
FILE_ID = EntityId.parse("00000000-0000-0000-0000-000000000303")
FILE_OBSERVATION_ID = EntityId.parse("00000000-0000-0000-0000-000000000304")
FILE_HASH = "b" * 64


def _seed_source(database: Path) -> None:
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id, name, media_type, enabled) "
                "VALUES (:id, 'synthetic-root', 'EBOOK', 1)"
            ),
            {"id": str(ROOT_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs (id, scan_root_id, started_at, status, completed_at) "
                "VALUES (:id, :root, :now, 'COMPLETED', :now)"
            ),
            {"id": str(SCAN_ID), "root": str(ROOT_ID), "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO file_records (id, scan_root_id, relative_path, size_bytes, "
                "modified_at, media_type, presence_state, first_seen_at, last_seen_at, "
                "consecutive_missing_scans) VALUES (:id, :root, 'synthetic.zip', 8, :now, "
                "'EBOOK', 'PRESENT', :now, :now, 0)"
            ),
            {"id": str(FILE_ID), "root": str(ROOT_ID), "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO file_observations (id, file_id, scan_run_id, relative_path, "
                "size_bytes, modified_at, observed_at) VALUES (:id, :file, :run, "
                "'synthetic.zip', 8, :now, :now)"
            ),
            {
                "id": str(FILE_OBSERVATION_ID),
                "file": str(FILE_ID),
                "run": str(SCAN_ID),
                "now": NOW.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO fingerprints (id, target_kind, target_id, kind, algorithm, "
                "algorithm_version, value, created_at) VALUES (:id, 'FILE_OBSERVATION', "
                ":target, 'FILE_SHA256', 'sha256', '1', :value, :now)"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000305",
                "target": str(FILE_OBSERVATION_ID),
                "value": FILE_HASH,
                "now": NOW.isoformat(),
            },
        )
    engine.dispose()


def _entry(run_id: EntityId) -> ArchiveCollectionPlanEntry:
    item_id = EntityId.parse("00000000-0000-0000-0000-000000000306")
    item = ArchiveCollectionItem(
        id=item_id,
        run_id=run_id,
        primary_file_observation_id=FILE_OBSERVATION_ID,
        plan_ordinal=0,
        signature=observe_archive_signature_v2("synthetic.zip", b"PK\x03\x04data"),
    )
    source = ArchiveCollectionItemSource(
        run_id=run_id,
        item_id=item_id,
        source_ordinal=0,
        file_observation_id=FILE_OBSERVATION_ID,
        full_sha256=FILE_HASH,
        size_bytes=8,
        staging_name="archive",
    )
    return ArchiveCollectionPlanEntry(item, (source,))


def _planning_run(database: Path) -> tuple[SQLiteArchiveCollectionStore, ArchiveCollectionRun]:
    _seed_source(database)
    store = SQLiteArchiveCollectionStore(create_sqlite_engine(database))
    run = store.create_planning_run(
        ROOT_ID,
        worker_count=1,
        plan_limit=None,
        started_at=NOW,
        lease_token="owner-one",
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    return store, run


def _insert_archive_graph(
    database: Path,
    run: ArchiveCollectionRun,
    entry: ArchiveCollectionPlanEntry,
    observation_id: EntityId,
) -> None:
    signature = entry.item.signature
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            archive_schema.archive_observations.insert().values(
                id=str(observation_id),
                profile="archive-observation/v1",
                content_hash="1" * 64,
                scan_root_id=str(run.scan_root_id),
                source_scan_run_id=str(run.source_scan_run_id),
                observed_at=NOW.isoformat(),
                archive_full_sha256=FILE_HASH,
                archive_content_fingerprint="2" * 64,
                volume_group_fingerprint="3" * 64,
                signature_profile=signature.profile,
                compatibility_profile=signature.compatibility,
                container_class=signature.container_class.value,
                suffix_kind=signature.suffix_kind.value,
                publication_kind=signature.publication_kind.value,
                storage_family=signature.storage_family.value,
                outer_compression_kind=signature.outer_compression_kind.value,
                recognition_status=signature.recognition_status.value,
                inspected_bytes=signature.inspected_bytes,
                structural_confirmation_required=signature.structural_confirmation_required,
                provider_profile="archive-7zip-provider/v1",
                runner_profile="archive-linux-container-runner/v1",
                parser_profile="archive-7zip-slt-parser/v3",
                parser_status="PARSED",
                format_case_kind="PLAINTEXT_REGULAR",
                format_lock_profile="archive-7zip-format-lock/v1",
                format_lock_sha256=(
                    "4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061"
                ),
                listing_profile="archive-listing/v1",
                integrity_profile="archive-integrity/v1",
                extraction_profile="archive-extraction/v1",
                safety_profile="archive-safety-policy/v1",
                secret_version="NONE",
                listing_status="LISTED",
                encryption_status="NONE",
                integrity_status="PASSED",
                extraction_status="NOT_ATTEMPTED",
                password_attempt_status="NOT_ATTEMPTED",
                extraction_policy_status="ACCEPTED",
                member_count=0,
                writer_owner_kind="ARCHIVE_COLLECTION_RUN",
                writer_owner_run_id=str(run.id),
                writer_fence_epoch=run.fence_epoch,
            )
        )
        connection.execute(
            archive_schema.archive_observation_sources.insert().values(
                archive_observation_id=str(observation_id),
                source_ordinal=0,
                file_observation_id=str(FILE_OBSERVATION_ID),
                source_full_sha256=FILE_HASH,
                source_size_bytes=8,
                staging_name="archive",
            )
        )
    engine.dispose()


def test_migration_0020_upgrades_0019_with_closed_tables_and_writer_checks(
    tmp_path: Path,
) -> None:
    database = tmp_path / "archive-collection-upgrade.db"
    migrate(database, "0019_archive_evidence")
    migrate(database)
    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        archive_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='archive_observations'"
            )
        ).scalar_one()
        claim_plan = " ".join(
            str(row[-1])
            for row in connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM archive_collection_items "
                    "WHERE run_id=:run AND status='PENDING' ORDER BY plan_ordinal LIMIT 2"
                ),
                {"run": str(EntityId.new())},
            ).all()
        )
    assert revision == "0020_archive_collection_runs"
    assert {
        "archive_collection_runs",
        "archive_collection_items",
        "archive_collection_item_sources",
    } <= set(inspector.get_table_names())
    assert "ARCHIVE_COLLECTION_RUN" in archive_sql
    assert "ix_archive_collection_items_claim" in claim_plan
    engine.dispose()
    command.downgrade(alembic_config(database), "0019_archive_evidence")
    downgraded = create_sqlite_engine(database)
    with downgraded.connect() as connection:
        restored_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='archive_observations'"
            )
        ).scalar_one()
    assert not (
        {
            "archive_collection_runs",
            "archive_collection_items",
            "archive_collection_item_sources",
        }
        & set(inspect(downgraded).get_table_names())
    )
    assert "ARCHIVE_COLLECTION_RUN" not in restored_sql
    downgraded.dispose()


def test_plan_claim_error_and_finish_are_atomic_and_retry_safe(
    head_database: Path,
) -> None:
    store, run = _planning_run(head_database)
    entry = _entry(run.id)
    assert store.append_plan_batch(run.id, "owner-one", (entry,), now=NOW) == 1
    assert (
        store.append_plan_batch(
            run.id, "owner-one", (entry,), now=NOW + timedelta(seconds=1)
        )
        == 1
    )
    with pytest.raises(ArchiveCollectionStoreError, match="hash drifted"):
        store.seal_plan(
            run.id,
            "owner-one",
            planned_count=1,
            findings=ArchiveCollectionPlanFindingCounts(),
            plan_content_hash="c" * 64,
            sealed_at=NOW + timedelta(seconds=2),
        )
    running = store.seal_plan(
        run.id,
        "owner-one",
        planned_count=1,
        findings=ArchiveCollectionPlanFindingCounts(),
        plan_content_hash=archive_collection_plan_content_hash(
            run, (entry,), ArchiveCollectionPlanFindingCounts()
        ),
        sealed_at=NOW + timedelta(seconds=2),
    )
    assert running.status is ArchiveCollectionRunStatus.RUNNING
    with pytest.raises(ArchiveCollectionStoreError, match="worker bound"):
        store.claim_pending(
            run.id,
            "owner-one",
            limit=3,
            started_at=NOW + timedelta(seconds=3),
        )
    claimed = store.claim_pending(
        run.id,
        "owner-one",
        limit=2,
        started_at=NOW + timedelta(seconds=3),
    )
    assert len(claimed) == 1
    completed = store.complete_item(
        claimed[0].item,
        "owner-one",
        status=ArchiveCollectionItemStatus.ERROR,
        completed_at=NOW + timedelta(seconds=4),
        archive_observation_id=None,
        disposition=None,
        error_code="ADAPTER_ERROR",
    )
    assert completed.status is ArchiveCollectionItemStatus.ERROR
    finished = store.finish_invocation(
        run.id, "owner-one", finished_at=NOW + timedelta(seconds=5)
    )
    assert finished.status is ArchiveCollectionRunStatus.COMPLETED_WITH_FAILURES
    assert finished.lease_token is None


def test_stale_takeover_resets_only_running_item_and_fences_old_owner(
    head_database: Path,
) -> None:
    store, run = _planning_run(head_database)
    entry = _entry(run.id)
    store.append_plan_batch(run.id, "owner-one", (entry,), now=NOW)
    store.seal_plan(
        run.id,
        "owner-one",
        planned_count=1,
        findings=ArchiveCollectionPlanFindingCounts(),
        plan_content_hash=archive_collection_plan_content_hash(
            run, (entry,), ArchiveCollectionPlanFindingCounts()
        ),
        sealed_at=NOW + timedelta(seconds=1),
    )
    claimed = store.claim_pending(
        run.id,
        "owner-one",
        limit=1,
        started_at=NOW + timedelta(seconds=2),
    )[0]
    resumed = store.acquire_resume(
        run.id,
        lease_token="owner-two",
        now=NOW + timedelta(minutes=31),
        lease_expires_at=NOW + timedelta(minutes=61),
    )
    assert resumed.fence_epoch == run.fence_epoch + 1
    with pytest.raises(ArchiveCollectionStoreError):
        store.complete_item(
            claimed.item,
            "owner-one",
            status=ArchiveCollectionItemStatus.ERROR,
            completed_at=NOW + timedelta(minutes=31, seconds=1),
            archive_observation_id=None,
            disposition=None,
            error_code="STALE_WORKER",
        )
    reclaimed = store.claim_pending(
        run.id,
        "owner-two",
        limit=1,
        started_at=NOW + timedelta(minutes=31, seconds=2),
    )[0]
    assert reclaimed.item.attempt_count == 2


def test_successful_item_requires_exact_current_archive_graph(head_database: Path) -> None:
    store, run = _planning_run(head_database)
    entry = _entry(run.id)
    store.append_plan_batch(run.id, "owner-one", (entry,), now=NOW)
    store.seal_plan(
        run.id,
        "owner-one",
        planned_count=1,
        findings=ArchiveCollectionPlanFindingCounts(),
        plan_content_hash=archive_collection_plan_content_hash(
            run, (entry,), ArchiveCollectionPlanFindingCounts()
        ),
        sealed_at=NOW + timedelta(seconds=1),
    )
    claimed = store.claim_pending(
        run.id,
        "owner-one",
        limit=1,
        started_at=NOW + timedelta(seconds=2),
    )[0]
    observation_id = EntityId.parse("00000000-0000-0000-0000-000000000307")
    _insert_archive_graph(head_database, run, entry, observation_id)
    completed = store.complete_item(
        claimed.item,
        "owner-one",
        status=ArchiveCollectionItemStatus.SUCCEEDED,
        completed_at=NOW + timedelta(seconds=3),
        archive_observation_id=observation_id,
        disposition=ArchiveCollectionDisposition.EXECUTED,
        error_code=None,
    )
    assert completed.archive_observation_id == observation_id
    finished = store.finish_invocation(
        run.id, "owner-one", finished_at=NOW + timedelta(seconds=4)
    )
    assert finished.status is ArchiveCollectionRunStatus.COMPLETED


def test_direct_dto_and_ddl_shapes_fail_closed(head_database: Path) -> None:
    store, run = _planning_run(head_database)
    entry = _entry(run.id)
    wrong_primary = EntityId.parse("00000000-0000-0000-0000-000000000399")
    with pytest.raises(ValueError):
        ArchiveCollectionPlanEntry(
            replace(entry.item, primary_file_observation_id=wrong_primary), entry.sources
        )
    wrong_material = ArchiveCollectionPlanEntry(
        entry.item, (replace(entry.sources[0], full_sha256="e" * 64),)
    )
    with pytest.raises(ArchiveCollectionStoreError):
        store.append_plan_batch(run.id, "owner-one", (wrong_material,), now=NOW)
    store.append_plan_batch(run.id, "owner-one", (entry,), now=NOW)
    engine = create_sqlite_engine(head_database)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE archive_collection_items SET status='ERROR', attempt_count=1, "
                "started_at=:now, completed_at=:now, error_code='_INVALID' WHERE id=:id"
            ),
            {"now": NOW.isoformat(), "id": str(entry.item.id)},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE archive_collection_item_sources SET staging_name='archivefoo' "
                "WHERE item_id=:id"
            ),
            {"id": str(entry.item.id)},
        )
    engine.dispose()


def test_populated_archive_collection_blocks_downgrade(head_database: Path) -> None:
    _planning_run(head_database)
    with pytest.raises(RuntimeError, match="archive collection state"):
        command.downgrade(alembic_config(head_database), "0019_archive_evidence")


def test_archive_collection_disposition_is_closed() -> None:
    assert {item.value for item in ArchiveCollectionDisposition} == {"EXECUTED", "REUSED"}
