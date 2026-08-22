from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import pytest
from alembic import command
from sqlalchemy import insert, select, text
from sqlalchemy.engine import Engine

from foliotone.cli.main import build_parser, main
from foliotone.collection_state import (
    CollectionQuerySpec,
    CollectionStateDiffCategory,
    CollectionStateDiffRequest,
    parse_collection_query_spec,
)
from foliotone.core import EntityId
from foliotone.persistence import (
    alembic_config,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    schema,
    w3_schema,
)
from foliotone.persistence.collection_query import SQLiteCollectionQueryStore
from foliotone.persistence.collection_query_schema import (
    collection_query_documents,
    collection_query_indexes,
    collection_query_values,
)
from foliotone.persistence.collection_state import SQLiteCollectionStateStore
from foliotone.persistence.collection_state_diff import SQLiteCollectionStateDiffReader
from foliotone.persistence.collection_state_schema import collection_state_snapshots
from foliotone.workflows.collection_state_query import CollectionQueryReport, CollectionQueryService

NOW = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("40000000-0000-0000-0000-000000000001")
OLD_SCAN_ID = EntityId.parse("41000000-0000-0000-0000-000000000001")
NEW_SCAN_ID = EntityId.parse("41000000-0000-0000-0000-000000000002")


def _seed_root_scan(
    engine: Engine,
    scan_id: EntityId,
    *,
    root_id: EntityId = ROOT_ID,
    completed_at: datetime = NOW,
) -> None:
    with engine.begin() as connection:
        if (
            connection.execute(
                select(schema.scan_roots.c.id).where(schema.scan_roots.c.id == str(root_id))
            ).scalar_one_or_none()
            is None
        ):
            connection.execute(
                insert(schema.scan_roots),
                {
                    "id": str(root_id),
                    "name": "synthetic-query-root",
                    "media_type": "EBOOK",
                    "enabled": True,
                },
            )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(scan_id),
                "scan_root_id": str(root_id),
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
    *,
    root_id: EntityId = ROOT_ID,
    suffix: str = "epub",
    size_bytes: int = 100,
) -> tuple[EntityId, EntityId]:
    file_id = EntityId.parse(f"50000000-0000-0000-0000-{file_number:012d}")
    observation_id = EntityId.parse(f"60000000-0000-0000-0000-{observation_number:012d}")
    relative_path = f"private/hidden-book-{file_number}.{suffix}"
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
                    "scan_root_id": str(root_id),
                    "relative_path": relative_path,
                    "size_bytes": size_bytes,
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
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            },
        )
    return file_id, observation_id


def _seed_metadata(
    engine: Engine,
    observation_id: EntityId,
    values: tuple[tuple[str, str], ...],
) -> None:
    execution_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(execution_id),
                "provider_id": "synthetic-metadata",
                "tool_version": "1",
                "adapter_version": "fixture/1",
                "capability": "READ_METADATA",
                "input_identity": f"file-observation:{observation_id}",
                "config_identity": "synthetic-query-fixture",
                "started_at": NOW.isoformat(),
                "finished_at": NOW.isoformat(),
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            },
        )
        connection.execute(
            insert(schema.tool_results),
            [
                {
                    "id": str(EntityId.new()),
                    "execution_id": str(execution_id),
                    "result_type": "ebook_metadata_candidate",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(observation_id),
                    "key": key,
                    "value": value,
                    "confidence": 1.0,
                    "explanation": "synthetic metadata candidate, not canonical",
                }
                for key, value in values
            ],
        )


def _seed_analysis_findings(
    engine: Engine,
    scan_id: EntityId,
    observation_id: EntityId,
    codes: tuple[str, ...] = ("METADATA_TITLE_MISSING",),
) -> None:
    run_id = EntityId.new()
    item_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(w3_schema.ebook_collection_runs),
            {
                "id": str(run_id),
                "scan_root_id": str(ROOT_ID),
                "source_scan_run_id": str(scan_id),
                "profile": "ebook-collection-analysis/v1",
                "analysis_profile": "ebook-analysis-workflow/v3",
                "fresh": True,
                "worker_count": 1,
                "started_at": NOW.isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
                "lease_token": None,
                "lease_expires_at": None,
            },
        )
        connection.execute(
            insert(w3_schema.ebook_collection_items),
            {
                "id": str(item_id),
                "run_id": str(run_id),
                "observation_id": str(observation_id),
                "ordinal": 0,
                "format_name": "EPUB",
                "status": "SUCCEEDED",
                "attempt_count": 1,
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
                "quality_status": "REVIEW",
                "reused_step_count": 0,
                "executed_step_count": 1,
                "finding_count": len(codes),
                "error_code": None,
            },
        )
        connection.execute(
            insert(w3_schema.ebook_collection_findings),
            [
                {
                    "id": str(EntityId.new()),
                    "item_id": str(item_id),
                    "ordinal": ordinal,
                    "code": code,
                    "dimension": "METADATA",
                    "severity": "REVIEW",
                }
                for ordinal, code in enumerate(codes)
            ],
        )


def _query(value: dict[str, object]) -> CollectionQuerySpec:
    return parse_collection_query_spec(value)


def test_migration_0024_adds_insert_only_query_index_and_fts(tmp_path: Path) -> None:
    database = tmp_path / "collection-query-migration.db"
    migrate(database, "0023_collection_state")
    migrate(database)
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0024_collection_state_diff_query"
        )
        objects = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                text("SELECT name, type FROM sqlite_master WHERE name LIKE 'collection_query_%'")
            )
        }
        values_ddl = str(
            connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name='collection_query_values'")
            ).scalar_one()
        )
    assert {
        ("collection_query_indexes", "table"),
        ("collection_query_documents", "table"),
        ("collection_query_values", "table"),
        ("collection_query_values_fts", "table"),
        ("collection_query_values_fts_insert", "trigger"),
        ("collection_query_documents_bounded_insert", "trigger"),
        ("collection_query_values_bounded_insert", "trigger"),
    } <= objects
    assert "ck_collection_query_values_field_kind" in values_ddl

    _seed_root_scan(engine, OLD_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, OLD_SCAN_ID, 1, 1)
    _seed_metadata(engine, observation_id, (("title", "Synthetic Lantern"),))
    snapshot = SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW).snapshot
    with engine.begin() as connection:
        document_value_count = int(
            connection.execute(
                select(collection_query_documents.c.value_count).where(
                    collection_query_documents.c.snapshot_id == str(snapshot.id),
                    collection_query_documents.c.ordinal == 0,
                )
            ).scalar_one()
        )
        with pytest.raises(Exception, match="immutable collection query index"):
            connection.execute(
                text("UPDATE collection_query_indexes SET value_count=0 WHERE snapshot_id=:id"),
                {"id": str(snapshot.id)},
            )
        with pytest.raises(Exception, match="immutable collection query index"):
            connection.execute(
                text("DELETE FROM collection_query_values WHERE snapshot_id=:id"),
                {"id": str(snapshot.id)},
            )
        with pytest.raises(Exception, match="sealed collection query value range"):
            connection.execute(
                insert(collection_query_values),
                {
                    "snapshot_id": str(snapshot.id),
                    "document_ordinal": 0,
                    "ordinal": document_value_count,
                    "field_name": "title",
                    "value_kind": "METADATA_CANDIDATE",
                    "value": "late-value",
                    "normalized_value": "late-value",
                    "value_digest": "a" * 64,
                },
            )
    engine.dispose()
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(database), "0023_collection_state")


def test_empty_0024_migration_downgrade_and_reupgrade_are_clean(tmp_path: Path) -> None:
    database = tmp_path / "empty-query-migration.db"
    migrate(database, "0023_collection_state")
    migrate(database)
    command.downgrade(alembic_config(database), "0023_collection_state")
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0023_collection_state"
        )
        names = {str(row[0]) for row in connection.execute(text("SELECT name FROM sqlite_master"))}
    assert not any(name.startswith("collection_query_") for name in names)
    engine.dispose()
    migrate(database)
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0024_collection_state_diff_query"
        )
    engine.dispose()


def test_pre_0024_migration_snapshot_is_backfilled_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "query-backfill.db"
    migrate(database, "0023_collection_state")
    engine = create_sqlite_engine(database)
    _seed_root_scan(engine, OLD_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, OLD_SCAN_ID, 1, 1)
    _seed_metadata(engine, observation_id, (("title", "Backfilled Lantern"),))
    legacy_store = SQLiteCollectionStateStore(engine)
    monkeypatch.setattr(legacy_store, "_ensure_query_index", lambda *_args: None)
    legacy_snapshot = legacy_store.build(OLD_SCAN_ID, NOW).snapshot
    engine.dispose()

    migrate(database)
    engine = create_sqlite_engine(database)
    rebuilt = SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW + timedelta(hours=1))
    assert rebuilt.created is False
    assert rebuilt.snapshot.id == legacy_snapshot.id
    with engine.connect() as connection:
        assert connection.execute(
            select(collection_query_indexes.c.snapshot_id)
        ).scalar_one() == str(legacy_snapshot.id)
    engine.dispose()


def test_query_projection_failure_rolls_back_new_state_and_retries(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_root_scan(engine, OLD_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, OLD_SCAN_ID, 1, 1)
    _seed_metadata(engine, observation_id, (("title", "Atomic Lantern"),))
    original = SQLiteCollectionQueryStore._insert_projection

    def fail_after_insert(
        store: SQLiteCollectionQueryStore,
        connection: object,
        snapshot: object,
        summary: object,
    ) -> None:
        original(store, connection, snapshot, summary)  # type: ignore[arg-type]
        raise RuntimeError("synthetic query projection failure")

    monkeypatch.setattr(SQLiteCollectionQueryStore, "_insert_projection", fail_after_insert)
    with pytest.raises(RuntimeError, match="synthetic query projection failure"):
        SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW)
    with engine.connect() as connection:
        assert connection.execute(select(collection_state_snapshots.c.id)).all() == []
        assert connection.execute(select(collection_query_indexes.c.snapshot_id)).all() == []
        assert connection.execute(select(collection_query_values.c.row_id)).all() == []
        assert connection.execute(text("SELECT rowid FROM collection_query_values_fts")).all() == []
    monkeypatch.undo()
    retry = SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW + timedelta(minutes=1))
    assert retry.created is True
    engine.dispose()


def test_metadata_index_is_snapshot_bound_deterministic_and_searchable(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_root_scan(engine, OLD_SCAN_ID)
    file_ids: list[EntityId] = []
    observations: list[EntityId] = []
    for number in range(1, 4):
        file_id, observation_id = _seed_observation(
            engine,
            OLD_SCAN_ID,
            number,
            number,
            suffix="pdf" if number == 3 else "epub",
        )
        file_ids.append(file_id)
        observations.append(observation_id)
    _seed_metadata(
        engine,
        observations[0],
        (
            ("title", "The Lantern Book"),
            ("contributor.1.name", "Synthetic Author"),
            ("identifier.1.value", "9780000000001"),
            ("language", "en"),
        ),
    )
    _seed_metadata(engine, observations[1], (("title", "Lantern Archive"),))
    _seed_metadata(engine, observations[2], (("title", "Unrelated Volume"),))
    _seed_analysis_findings(engine, OLD_SCAN_ID, observations[0])

    state_store = SQLiteCollectionStateStore(engine, batch_size=2)
    built = state_store.build(OLD_SCAN_ID, NOW)
    repeated = state_store.build(OLD_SCAN_ID, NOW + timedelta(hours=1))
    assert repeated.created is False
    assert repeated.snapshot.id == built.snapshot.id

    with engine.connect() as connection:
        index_row = (
            connection.execute(
                select(collection_query_indexes).where(
                    collection_query_indexes.c.snapshot_id == str(built.snapshot.id)
                )
            )
            .mappings()
            .one()
        )
        assert int(index_row["document_count"]) == 3
        assert int(index_row["metadata_value_count"]) == 6
        assert int(index_row["finding_value_count"]) == 1
        assert len(
            connection.execute(
                text(
                    "SELECT rowid FROM collection_query_values_fts "
                    "WHERE collection_query_values_fts MATCH :query"
                ),
                {"query": '"lantern"'},
            ).all()
        ) == 2
        assert connection.execute(
            text(
                "SELECT rowid FROM collection_query_values_fts "
                "WHERE collection_query_values_fts MATCH :query"
            ),
            {"query": '"current"'},
        ).all() == []

    query_store = SQLiteCollectionQueryStore(engine)
    first_spec = _query(
        {
            "where": {"field": "title", "operator": "MATCH", "value": "lantern"},
            "limit": 1,
        }
    )
    first = query_store.search(built.snapshot.id, first_spec)
    assert tuple(hit.file_id for hit in first.hits) == (file_ids[0],)
    assert first.truncated is True
    assert first.next_after_file_id == file_ids[0]
    assert first.hits[0].private_values == ()

    second = query_store.search(
        built.snapshot.id,
        _query(
            {
                "where": {"field": "title", "operator": "MATCH", "value": "lantern"},
                "limit": 1,
                "after_file_id": str(first.next_after_file_id),
            }
        ),
    )
    assert tuple(hit.file_id for hit in second.hits) == (file_ids[1],)
    assert second.truncated is False

    finding = query_store.search(
        built.snapshot.id,
        _query(
            {
                "where": {
                    "and": [
                        {
                            "field": "finding_code",
                            "operator": "EQ",
                            "value": "METADATA_TITLE_MISSING",
                        },
                        {"field": "format", "operator": "EQ", "value": "EPUB"},
                    ]
                }
            }
        ),
    )
    assert tuple(hit.file_id for hit in finding.hits) == (file_ids[0],)
    engine.dispose()


def test_query_index_value_limits_are_explicit_and_memory_bounded(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_root_scan(engine, OLD_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, OLD_SCAN_ID, 1, 1)
    metadata = tuple(
        (f"contributor.{ordinal}.name", f"Synthetic Contributor {ordinal:03d}")
        for ordinal in range(260)
    ) + (("title", "x" * 4097),)
    findings = tuple(f"SYNTHETIC_FINDING_{ordinal:03d}" for ordinal in range(130)) + (
        "X" * 129,
    )
    _seed_metadata(engine, observation_id, metadata)
    _seed_analysis_findings(engine, OLD_SCAN_ID, observation_id, findings)

    snapshot = SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW).snapshot
    with engine.connect() as connection:
        index_row = (
            connection.execute(
                select(collection_query_indexes).where(
                    collection_query_indexes.c.snapshot_id == str(snapshot.id)
                )
            )
            .mappings()
            .one()
        )
    assert int(index_row["metadata_value_count"]) == 256
    assert int(index_row["finding_value_count"]) == 128
    assert int(index_row["truncated_value_count"]) == 8
    assert str(index_row["coverage_state"]) == "PARTIAL"
    assert str(index_row["truncation_state"]) == "VALUE_LIMIT"
    engine.dispose()


def test_query_report_and_cli_keep_private_values_opt_in_and_paths_out(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_root_scan(engine, OLD_SCAN_ID)
    _file_id, observation_id = _seed_observation(engine, OLD_SCAN_ID, 1, 1)
    _seed_metadata(
        engine,
        observation_id,
        (
            ("title", "Private Lantern Title"),
            ("publisher", "C:\\private\\publisher"),
        ),
    )
    snapshot = SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW).snapshot
    report: CollectionQueryReport = CollectionQueryService(engine).search(
        snapshot.id,
        _query(
            {
                "where": {
                    "or": [
                        {"field": "title", "operator": "MATCH", "value": "lantern"},
                        {"field": "publisher", "operator": "PREFIX", "value": "c:"},
                    ]
                }
            }
        ),
        private_details=True,
    )
    safe_payload = report.payload()
    private_values = report.private_values(report.page.hits[0])
    assert "Private Lantern Title" not in json.dumps(safe_payload, sort_keys=True)
    assert tuple(value.value for value in private_values) == ("Private Lantern Title",)
    assert "C:\\private\\publisher" not in tuple(value.value for value in private_values)
    engine.dispose()

    before = head_database.read_bytes()
    monkeypatch.setattr("foliotone.cli.main.migrate", lambda _path: pytest.fail("must not migrate"))
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("must not open writable SQLite"),
    )
    query_json = json.dumps({"where": {"field": "title", "operator": "MATCH", "value": "lantern"}})
    arguments = [
        "collection-search",
        "--snapshot",
        str(snapshot.id),
        "--query",
        query_json,
        "--database",
        str(head_database),
    ]
    assert main([*arguments, "--output", "json"]) == 0
    machine = capsys.readouterr().out
    assert "Private Lantern Title" not in machine
    assert "hidden-book" not in machine
    assert main([*arguments, "--private-details", "--output", "text"]) == 0
    interactive = capsys.readouterr().out
    assert "Private Lantern Title" in interactive
    assert "hidden-book" not in interactive
    assert main([*arguments, "--private-details", "--output", "json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == ("PRIVATE_DETAILS_REQUIRE_TEXT")
    assert head_database.read_bytes() == before


def test_diff_is_deterministic_bounded_path_free_and_read_only(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = create_sqlite_engine(head_database)
    _seed_root_scan(engine, OLD_SCAN_ID, completed_at=NOW - timedelta(days=1))
    file_one, _old_one = _seed_observation(engine, OLD_SCAN_ID, 1, 1, size_bytes=100)
    file_two, _old_two = _seed_observation(engine, OLD_SCAN_ID, 2, 2, size_bytes=200)
    old_snapshot = (
        SQLiteCollectionStateStore(engine).build(OLD_SCAN_ID, NOW - timedelta(days=1)).snapshot
    )

    _seed_root_scan(engine, NEW_SCAN_ID, completed_at=NOW)
    _same_file_one, new_one = _seed_observation(
        engine,
        NEW_SCAN_ID,
        1,
        11,
        size_bytes=101,
    )
    file_three, _new_three = _seed_observation(engine, NEW_SCAN_ID, 3, 13, size_bytes=300)
    _seed_analysis_findings(engine, NEW_SCAN_ID, new_one)
    new_snapshot = SQLiteCollectionStateStore(engine).build(NEW_SCAN_ID, NOW).snapshot
    engine.dispose()

    read_engine = create_sqlite_read_only_engine(head_database)
    request = CollectionStateDiffRequest(old_snapshot.id, new_snapshot.id, limit=2)
    first = SQLiteCollectionStateDiffReader(read_engine, batch_size=1).read(request)
    repeated = SQLiteCollectionStateDiffReader(read_engine, batch_size=2).read(request)
    assert first == repeated
    assert first.total_changed_items == 3
    assert dict(first.category_counts) == {
        CollectionStateDiffCategory.ADDED: 1,
        CollectionStateDiffCategory.DISAPPEARED: 1,
        CollectionStateDiffCategory.TECHNICALLY_CHANGED: 1,
        CollectionStateDiffCategory.NEWLY_ANALYZED: 1,
        CollectionStateDiffCategory.NEWLY_RESOLVED: 0,
        CollectionStateDiffCategory.NEWLY_REVIEWED: 0,
        CollectionStateDiffCategory.NEWLY_BLOCKED: 0,
    }
    assert tuple(entry.file_id for entry in first.entries) == (file_one, file_two)
    assert first.truncated is True
    second = SQLiteCollectionStateDiffReader(read_engine).read(
        CollectionStateDiffRequest(
            old_snapshot.id,
            new_snapshot.id,
            limit=2,
            after_file_id=first.next_after_file_id,
        )
    )
    assert tuple(entry.file_id for entry in second.entries) == (file_three,)
    read_engine.dispose()

    before = head_database.read_bytes()
    assert (
        main(
            [
                "collection-state-diff",
                "--before",
                str(old_snapshot.id),
                "--after",
                str(new_snapshot.id),
                "--database",
                str(head_database),
                "--output",
                "json",
            ]
        )
        == 0
    )
    encoded = capsys.readouterr().out
    payload = json.loads(encoded)
    assert payload["total_changed_items"] == 3
    assert "hidden-book" not in encoded
    assert "private/" not in encoded
    assert head_database.read_bytes() == before


def test_cli_rejects_invalid_query_ast_and_diff_ids_without_echoing_sql(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "collection-search",
                "--snapshot",
                "00000000-0000-0000-0000-000000000001",
                "--query",
                '{"where":{"field":"title; DROP TABLE files","operator":"EQ","value":"x"}}',
            ]
        )
    assert "DROP TABLE" not in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["collection-state-diff", "--before", "invalid", "--after", str(NEW_SCAN_ID)]
        )


def test_synthetic_metadata_fts_scale_is_bounded_and_indexed(head_database: Path) -> None:
    engine = create_sqlite_engine(head_database)
    scale_scan = EntityId.parse("41000000-0000-0000-0000-000000000099")
    _seed_root_scan(engine, scale_scan)
    document_count = 600
    execution_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(schema.file_records),
            [
                {
                    "id": f"51000000-0000-0000-0000-{ordinal:012d}",
                    "scan_root_id": str(ROOT_ID),
                    "relative_path": f"synthetic/scale-{ordinal:04d}.epub",
                    "size_bytes": 100 + ordinal,
                    "modified_at": NOW.isoformat(),
                    "media_type": "EBOOK",
                    "presence_state": "PRESENT",
                    "first_seen_at": NOW.isoformat(),
                    "last_seen_at": NOW.isoformat(),
                    "missing_since_at": None,
                    "consecutive_missing_scans": 0,
                }
                for ordinal in range(1, document_count + 1)
            ],
        )
        connection.execute(
            insert(schema.file_observations),
            [
                {
                    "id": f"61000000-0000-0000-0000-{ordinal:012d}",
                    "file_id": f"51000000-0000-0000-0000-{ordinal:012d}",
                    "scan_run_id": str(scale_scan),
                    "relative_path": f"synthetic/scale-{ordinal:04d}.epub",
                    "size_bytes": 100 + ordinal,
                    "modified_at": NOW.isoformat(),
                    "observed_at": NOW.isoformat(),
                }
                for ordinal in range(1, document_count + 1)
            ],
        )
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(execution_id),
                "provider_id": "synthetic-scale",
                "tool_version": "1",
                "adapter_version": "fixture/1",
                "capability": "READ_METADATA",
                "input_identity": "synthetic-scale-collection",
                "config_identity": "synthetic-scale-query",
                "started_at": NOW.isoformat(),
                "finished_at": NOW.isoformat(),
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            },
        )
        connection.execute(
            insert(schema.tool_results),
            [
                {
                    "id": f"71000000-0000-0000-0000-{ordinal:012d}",
                    "execution_id": str(execution_id),
                    "result_type": "ebook_metadata_candidate",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": f"61000000-0000-0000-0000-{ordinal:012d}",
                    "key": "title",
                    "value": (
                        f"Synthetic Needle Volume {ordinal}"
                        if ordinal % 75 == 0
                        else f"Synthetic Scale Volume {ordinal}"
                    ),
                    "confidence": 1.0,
                    "explanation": "synthetic scale metadata, not canonical",
                }
                for ordinal in range(1, document_count + 1)
            ],
        )
    snapshot = SQLiteCollectionStateStore(engine, batch_size=250).build(scale_scan, NOW).snapshot
    spec = _query(
        {
            "where": {"field": "title", "operator": "MATCH", "value": "needle"},
            "limit": 25,
        }
    )
    started = perf_counter()
    page = SQLiteCollectionQueryStore(engine).search(snapshot.id, spec)
    elapsed = perf_counter() - started
    assert len(page.hits) == 8
    assert page.truncated is False
    assert elapsed < 3.0
    with engine.connect() as connection:
        plan = " ".join(
            str(row[-1])
            for row in connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT v.document_ordinal "
                    "FROM collection_query_values_fts AS f "
                    "JOIN collection_query_values AS v ON v.row_id=f.rowid "
                    "WHERE v.snapshot_id=:snapshot AND v.field_name='title' "
                    "AND f.normalized_value MATCH '\"needle\"'"
                ),
                {"snapshot": str(snapshot.id)},
            )
        )
    assert "VIRTUAL TABLE INDEX" in plan.upper()
    engine.dispose()
