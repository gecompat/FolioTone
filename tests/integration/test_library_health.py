from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import insert, select, text
from sqlalchemy.engine import Engine

from foliotone.cli.main import main
from foliotone.collection_state import (
    LIBRARY_HEALTH_DIMENSION_ORDER,
    LibraryHealthDimension,
    LibraryHealthFindingCode,
)
from foliotone.core import EntityId
from foliotone.persistence import alembic_config, create_sqlite_engine, migrate, schema
from foliotone.persistence.collection_query_schema import collection_query_indexes
from foliotone.persistence.collection_state import SQLiteCollectionStateStore
from foliotone.persistence.collection_state_schema import collection_state_snapshots
from foliotone.persistence.library_health import (
    LibraryHealthStoreError,
    SQLiteLibraryHealthStore,
)
from foliotone.persistence.library_health_schema import (
    library_health_dimensions,
    library_health_findings,
    library_health_samples,
    library_health_snapshots,
)
from foliotone.workflows.library_health import SQLiteLibraryHealthReportReader

NOW = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("80000000-0000-0000-0000-000000000001")
FIRST_SCAN_ID = EntityId.parse("81000000-0000-0000-0000-000000000001")
SECOND_SCAN_ID = EntityId.parse("81000000-0000-0000-0000-000000000002")


def _seed_scan(
    engine: Engine,
    scan_id: EntityId,
    *,
    completed_at: datetime = NOW,
) -> None:
    with engine.begin() as connection:
        if (
            connection.execute(
                select(schema.scan_roots.c.id).where(schema.scan_roots.c.id == str(ROOT_ID))
            ).scalar_one_or_none()
            is None
        ):
            connection.execute(
                insert(schema.scan_roots),
                {
                    "id": str(ROOT_ID),
                    "name": "synthetic-library-health",
                    "media_type": "EBOOK",
                    "enabled": True,
                },
            )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(scan_id),
                "scan_root_id": str(ROOT_ID),
                "started_at": (completed_at - timedelta(minutes=1)).isoformat(),
                "status": "COMPLETED",
                "completed_at": completed_at.isoformat(),
            },
        )


def _seed_observation(
    engine: Engine,
    scan_id: EntityId,
    file_number: int,
    observation_number: int,
) -> tuple[EntityId, EntityId]:
    file_id = EntityId.parse(f"82000000-0000-0000-0000-{file_number:012d}")
    observation_id = EntityId.parse(f"83000000-0000-0000-0000-{observation_number:012d}")
    private_path = f"private/secret-title-{file_number}.epub"
    with engine.begin() as connection:
        if (
            connection.execute(
                select(schema.file_records.c.id).where(schema.file_records.c.id == str(file_id))
            ).scalar_one_or_none()
            is None
        ):
            connection.execute(
                insert(schema.file_records),
                {
                    "id": str(file_id),
                    "scan_root_id": str(ROOT_ID),
                    "relative_path": private_path,
                    "size_bytes": 100 + file_number,
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
                "id": str(observation_id),
                "file_id": str(file_id),
                "scan_run_id": str(scan_id),
                "relative_path": private_path,
                "size_bytes": 100 + file_number,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            },
        )
    return file_id, observation_id


def _seed_metadata(engine: Engine, observation_id: EntityId, title: str) -> None:
    execution_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(execution_id),
                "provider_id": "synthetic-health-metadata",
                "tool_version": "1",
                "adapter_version": "fixture/1",
                "capability": "READ_METADATA",
                "input_identity": f"file-observation:{observation_id}",
                "config_identity": "synthetic-health-fixture",
                "started_at": NOW.isoformat(),
                "finished_at": NOW.isoformat(),
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            },
        )
        connection.execute(
            insert(schema.tool_results),
            (
                {
                    "id": str(EntityId.new()),
                    "execution_id": str(execution_id),
                    "result_type": "ebook_metadata_candidate",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(observation_id),
                    "key": "title",
                    "value": title,
                    "confidence": 1.0,
                    "explanation": "synthetic title candidate",
                },
                {
                    "id": str(EntityId.new()),
                    "execution_id": str(execution_id),
                    "result_type": "ebook_metadata_candidate",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(observation_id),
                    "key": "contributor.1.name",
                    "value": "Private Synthetic Author",
                    "confidence": 1.0,
                    "explanation": "synthetic contributor candidate",
                },
            ),
        )


def _seed_full_fixity(engine: Engine, observation_id: EntityId, value: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(EntityId.new()),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(observation_id),
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": value,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            },
        )


def test_migration_0025_is_additive_insert_only_and_downgrade_safe(
    tmp_path: Path,
) -> None:
    database = tmp_path / "library-health-migration.db"
    migrate(database, "0024_collection_state_diff_query")
    migrate(database)
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0025_library_health"
        )
        objects = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                text("SELECT name, type FROM sqlite_master WHERE name LIKE 'library_health_%'")
            )
        }
    assert {
        ("library_health_snapshots", "table"),
        ("library_health_dimensions", "table"),
        ("library_health_findings", "table"),
        ("library_health_samples", "table"),
        ("library_health_dimensions_bounded_insert", "trigger"),
        ("library_health_findings_bounded_insert", "trigger"),
        ("library_health_samples_bounded_insert", "trigger"),
    } <= objects

    _seed_scan(engine, FIRST_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, FIRST_SCAN_ID, 1, 1)
    _seed_full_fixity(engine, observation_id, "a" * 64)
    state = SQLiteCollectionStateStore(engine).build(FIRST_SCAN_ID, NOW).snapshot
    health_id = SQLiteLibraryHealthStore(engine).get_for_collection_state(state.id)
    assert health_id is not None
    with engine.begin() as connection:
        with pytest.raises(Exception, match="Library Health rows are immutable"):
            connection.execute(
                text("UPDATE library_health_snapshots SET item_count=0 WHERE id=:id"),
                {"id": str(health_id.id)},
            )
    engine.dispose()
    with pytest.raises(RuntimeError, match="Refusing to drop non-empty"):
        command.downgrade(alembic_config(database), "0024_collection_state_diff_query")


def test_empty_migration_0025_downgrades_and_reupgrades(tmp_path: Path) -> None:
    database = tmp_path / "empty-library-health.db"
    migrate(database)
    command.downgrade(alembic_config(database), "0024_collection_state_diff_query")
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        names = {str(row[0]) for row in connection.execute(text("SELECT name FROM sqlite_master"))}
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "0024_collection_state_diff_query"
    assert not any(name.startswith("library_health_") for name in names)
    engine.dispose()
    migrate(database)


def test_health_projection_is_bounded_idempotent_comparable_and_fail_closed(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_scan(engine, FIRST_SCAN_ID)
    first_file, first_observation = _seed_observation(engine, FIRST_SCAN_ID, 1, 1)
    _seed_metadata(engine, first_observation, "Private Synthetic First Title")
    _seed_full_fixity(engine, first_observation, "b" * 64)
    first_state = (
        SQLiteCollectionStateStore(engine, batch_size=1).build(FIRST_SCAN_ID, NOW).snapshot
    )
    first_health = SQLiteLibraryHealthStore(engine, batch_size=1).get_for_collection_state(
        first_state.id
    )
    assert first_health is not None
    assert tuple(value.dimension for value in first_health.dimensions) == (
        LIBRARY_HEALTH_DIMENSION_ORDER
    )
    assert first_health.item_count == 1

    repeated = SQLiteCollectionStateStore(engine, batch_size=1).build(
        FIRST_SCAN_ID, NOW + timedelta(minutes=5)
    )
    repeated_health = SQLiteLibraryHealthStore(engine).get_for_collection_state(
        repeated.snapshot.id
    )
    assert repeated.created is False
    assert repeated_health == first_health

    _seed_scan(engine, SECOND_SCAN_ID, completed_at=NOW + timedelta(hours=1))
    second_first_file, second_first_observation = _seed_observation(engine, SECOND_SCAN_ID, 1, 2)
    second_file, second_observation = _seed_observation(engine, SECOND_SCAN_ID, 2, 3)
    assert second_first_file == first_file
    _seed_metadata(engine, second_first_observation, "Private Synthetic Revised Title")
    _seed_metadata(engine, second_observation, "Private Synthetic Second Title")
    _seed_full_fixity(engine, second_first_observation, "c" * 64)
    second_state = (
        SQLiteCollectionStateStore(engine, batch_size=1)
        .build(SECOND_SCAN_ID, NOW + timedelta(hours=1))
        .snapshot
    )
    report = SQLiteLibraryHealthReportReader(engine).read(
        second_state.id,
        baseline_snapshot_id=first_state.id,
        sample_limit=1,
    )
    second_health = report.snapshot
    fixity = next(
        value
        for value in second_health.dimensions
        if value.dimension is LibraryHealthDimension.SCAN_FIXITY
    )
    missing = next(
        finding
        for finding in fixity.findings
        if finding.code is LibraryHealthFindingCode.FULL_FIXITY_MISSING
    )
    assert missing.item_count == 1
    assert tuple(sample.file_id for sample in missing.samples) == (second_file,)
    assert all(
        dimension.affected_item_count <= second_health.item_count
        for dimension in second_health.dimensions
    )
    assert report.comparison is not None
    assert report.comparison.before_health_snapshot_id == first_health.id
    assert report.comparison.after_health_snapshot_id == second_health.id

    health_id = second_health.id
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER library_health_dimensions_no_update"))
        connection.execute(
            text(
                "UPDATE library_health_dimensions SET dimension_digest=:digest "
                "WHERE snapshot_id=:snapshot AND ordinal=0"
            ),
            {"digest": "0" * 64, "snapshot": str(health_id)},
        )
    with pytest.raises(LibraryHealthStoreError, match="read failed"):
        SQLiteLibraryHealthStore(engine).get_for_collection_state(second_state.id)
    engine.dispose()


def test_projection_failure_rolls_back_state_query_and_health(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_scan(engine, FIRST_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, FIRST_SCAN_ID, 1, 1)
    _seed_metadata(engine, observation_id, "Private Atomic Title")
    original = SQLiteLibraryHealthStore._insert

    def fail_after_insert(
        store: SQLiteLibraryHealthStore,
        connection: object,
        snapshot: object,
    ) -> None:
        original(store, connection, snapshot)  # type: ignore[arg-type]
        raise RuntimeError("synthetic Health projection failure")

    monkeypatch.setattr(SQLiteLibraryHealthStore, "_insert", fail_after_insert)
    with pytest.raises(RuntimeError, match="synthetic Health projection failure"):
        SQLiteCollectionStateStore(engine).build(FIRST_SCAN_ID, NOW)
    with engine.connect() as connection:
        assert connection.execute(select(collection_state_snapshots.c.id)).all() == []
        assert connection.execute(select(collection_query_indexes.c.snapshot_id)).all() == []
        assert connection.execute(select(library_health_snapshots.c.id)).all() == []
        assert connection.execute(select(library_health_dimensions.c.snapshot_id)).all() == []
        assert connection.execute(select(library_health_findings.c.snapshot_id)).all() == []
        assert connection.execute(select(library_health_samples.c.snapshot_id)).all() == []
    monkeypatch.undo()
    retry = SQLiteCollectionStateStore(engine).build(FIRST_SCAN_ID, NOW + timedelta(minutes=1))
    assert retry.created is True
    engine.dispose()


def test_cli_report_is_truly_read_only_and_privacy_bounded(
    head_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_scan(engine, FIRST_SCAN_ID)
    file_id, observation_id = _seed_observation(engine, FIRST_SCAN_ID, 1, 1)
    _seed_metadata(engine, observation_id, "Private CLI Title")
    _seed_full_fixity(engine, observation_id, "d" * 64)
    state = SQLiteCollectionStateStore(engine).build(FIRST_SCAN_ID, NOW).snapshot
    engine.dispose()
    before_digest = sha256(head_database.read_bytes()).hexdigest()

    assert (
        main(
            [
                "library-health-report",
                "--snapshot",
                str(state.id),
                "--database",
                str(head_database),
                "--output",
                "json",
            ]
        )
        == 0
    )
    payload_text = capsys.readouterr().out.strip()
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["health_profile"] == "library-health/v1"
    assert payload["collection_state_snapshot_id"] == str(state.id)
    assert str(file_id) in payload_text
    assert str(observation_id) in payload_text
    assert "private/secret-title" not in payload_text
    assert "Private CLI Title" not in payload_text
    assert "Private Synthetic Author" not in payload_text
    assert "d" * 64 not in payload_text
    assert "content_digest" not in payload_text
    assert sha256(head_database.read_bytes()).hexdigest() == before_digest

    missing_database = tmp_path / "must-not-exist" / "foliotone.db"
    assert (
        main(
            [
                "library-health-report",
                "--snapshot",
                str(state.id),
                "--database",
                str(missing_database),
                "--output",
                "json",
            ]
        )
        == 2
    )
    capsys.readouterr()
    assert not missing_database.parent.exists()
