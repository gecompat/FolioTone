from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import insert, select, text, update
from sqlalchemy.engine import Engine

from foliotone.cli.main import build_parser, main
from foliotone.core import EntityId
from foliotone.persistence import (
    alembic_config,
    create_sqlite_engine,
    migrate,
    schema,
    w3_schema,
)
from foliotone.persistence.collection_state import (
    CollectionStateStoreError,
    SQLiteCollectionStateStore,
)
from foliotone.persistence.collection_state_schema import (
    collection_state_components,
    collection_state_counts,
    collection_state_items,
    collection_state_snapshots,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _seed_root_and_scan(
    engine: Engine,
    *,
    root_id: EntityId | None = None,
    scan_id: EntityId | None = None,
    completed_at: datetime = NOW,
    media_type: str = "EBOOK",
    status: str = "COMPLETED",
) -> tuple[EntityId, EntityId]:
    root_id = root_id or EntityId.new()
    scan_id = scan_id or EntityId.new()
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
                    "name": f"synthetic-{root_id}",
                    "media_type": media_type,
                    "enabled": True,
                },
            )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(scan_id),
                "scan_root_id": str(root_id),
                "started_at": (completed_at - timedelta(minutes=1)).isoformat(),
                "status": status,
                "completed_at": completed_at.isoformat() if status == "COMPLETED" else None,
            },
        )
    return root_id, scan_id


def _seed_observation(
    engine: Engine,
    root_id: EntityId,
    scan_id: EntityId,
    *,
    file_id: EntityId | None = None,
    observation_id: EntityId | None = None,
    relative_path: str = "private/synthetic.epub",
    size_bytes: int = 100,
) -> tuple[EntityId, EntityId]:
    file_id = file_id or EntityId.new()
    observation_id = observation_id or EntityId.new()
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


def test_migration_0023_is_additive_and_collection_state_is_insert_only(
    tmp_path: Path,
) -> None:
    database = tmp_path / "collection-state-migration.db"
    migrate(database, "0022_quarantine_execution_persistence")
    migrate(database)
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0023_collection_state"
        )
        tables = {
            str(row[0])
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        triggers = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' AND name LIKE 'collection_state_%'"
                )
            )
        }
    assert {
        "collection_state_snapshots",
        "collection_state_components",
        "collection_state_counts",
        "collection_state_items",
    } <= tables
    assert triggers == {
        f"{table}_{operation}"
        for table in (
            "collection_state_snapshots",
            "collection_state_components",
            "collection_state_counts",
            "collection_state_items",
        )
        for operation in ("no_update", "no_delete")
    }
    root_id, scan_id = _seed_root_and_scan(engine)
    _seed_observation(engine, root_id, scan_id)
    snapshot = SQLiteCollectionStateStore(engine).build(scan_id, NOW).snapshot
    with engine.begin() as connection:
        with pytest.raises(Exception, match="immutable collection state"):
            connection.execute(
                text("UPDATE collection_state_snapshots SET item_count=0 WHERE id=:id"),
                {"id": str(snapshot.id)},
            )
        with pytest.raises(Exception, match="immutable collection state"):
            connection.execute(
                text("DELETE FROM collection_state_items WHERE snapshot_id=:id"),
                {"id": str(snapshot.id)},
            )
    engine.dispose()
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(database), "0022_quarantine_execution_persistence")


def test_build_is_keyset_bounded_idempotent_and_changes_with_evidence(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    observations: list[EntityId] = []
    for ordinal, suffix in enumerate(("epub", "pdf", "mobi"), start=1):
        _file_id, observation_id = _seed_observation(
            engine,
            root_id,
            scan_id,
            relative_path=f"private/book-{ordinal}.{suffix}",
            size_bytes=ordinal * 100,
        )
        observations.append(observation_id)
    store = SQLiteCollectionStateStore(engine, batch_size=2)

    first = store.build(scan_id, NOW)
    repeat = store.build(scan_id, NOW + timedelta(hours=1))

    assert first.created is True
    assert repeat.created is False
    assert repeat.snapshot.id == first.snapshot.id
    assert repeat.snapshot.created_at == NOW
    assert first.snapshot.item_count == 3
    assert first.snapshot.total_size_bytes == 600
    assert (
        dict((count.key, count.value) for count in first.snapshot.counts)["physical.format.pdf"]
        == 1
    )
    with engine.begin() as connection:
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(EntityId.new()),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(observations[0]),
                "kind": "SYNTHETIC_TECHNICAL",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": "a" * 64,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            },
        )
    changed = store.build(scan_id, NOW + timedelta(hours=2))
    assert changed.created is True
    assert changed.snapshot.id != first.snapshot.id
    with engine.connect() as connection:
        assert {
            str(row[0]) for row in connection.execute(select(collection_state_snapshots.c.id))
        } == {str(first.snapshot.id), str(changed.snapshot.id)}
    engine.dispose()


def test_rebuild_of_one_scan_ignores_later_mutable_file_record_state(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    file_id, _observation_id = _seed_observation(engine, root_id, scan_id)
    store = SQLiteCollectionStateStore(engine)
    first = store.build(scan_id, NOW)

    with engine.begin() as connection:
        connection.execute(
            update(schema.file_records)
            .where(schema.file_records.c.id == str(file_id))
            .values(
                relative_path="private/later-location.pdf",
                size_bytes=999,
                modified_at=(NOW + timedelta(days=1)).isoformat(),
                presence_state="MISSING",
            )
        )

    repeat = store.build(scan_id, NOW + timedelta(hours=1))
    assert repeat.created is False
    assert repeat.snapshot == first.snapshot
    engine.dispose()


def test_build_requires_one_completed_book_scan(head_database: Path) -> None:
    engine = create_sqlite_engine(head_database)
    _root_id, running_scan = _seed_root_and_scan(engine, status="RUNNING")
    with pytest.raises(CollectionStateStoreError, match="not completed"):
        SQLiteCollectionStateStore(engine).build(running_scan, NOW)

    _music_root, music_scan = _seed_root_and_scan(engine, media_type="MUSIC")
    with pytest.raises(CollectionStateStoreError, match="not book-only"):
        SQLiteCollectionStateStore(engine).build(music_scan, NOW)
    engine.dispose()


def test_stale_analysis_and_missing_coverage_remain_explicit(head_database: Path) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, old_scan = _seed_root_and_scan(engine, completed_at=NOW - timedelta(days=1))
    file_id, old_observation = _seed_observation(engine, root_id, old_scan)
    _same_root, new_scan = _seed_root_and_scan(
        engine,
        root_id=root_id,
        completed_at=NOW,
    )
    _same_file, new_observation = _seed_observation(
        engine,
        root_id,
        new_scan,
        file_id=file_id,
        relative_path="private/synthetic.epub",
    )
    _seed_observation(
        engine,
        root_id,
        new_scan,
        relative_path="private/without-analysis.pdf",
    )
    run_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(w3_schema.ebook_collection_runs),
            {
                "id": str(run_id),
                "scan_root_id": str(root_id),
                "source_scan_run_id": str(old_scan),
                "profile": "ebook-collection-analysis/v1",
                "analysis_profile": "ebook-analysis-workflow/v3",
                "fresh": False,
                "worker_count": 1,
                "started_at": (NOW - timedelta(days=1)).isoformat(),
                "status": "COMPLETED",
                "completed_at": (NOW - timedelta(days=1)).isoformat(),
                "lease_token": None,
                "lease_expires_at": None,
            },
        )
        connection.execute(
            insert(w3_schema.ebook_collection_items),
            {
                "id": str(EntityId.new()),
                "run_id": str(run_id),
                "observation_id": str(old_observation),
                "ordinal": 0,
                "format_name": "EPUB",
                "status": "SUCCEEDED",
                "attempt_count": 1,
                "started_at": (NOW - timedelta(days=1)).isoformat(),
                "completed_at": (NOW - timedelta(days=1)).isoformat(),
                "quality_status": "OK",
                "reused_step_count": 1,
                "executed_step_count": 0,
                "finding_count": 0,
                "error_code": None,
            },
        )
    snapshot = SQLiteCollectionStateStore(engine).build(new_scan, NOW).snapshot
    analysis = next(
        component for component in snapshot.components if component.component.value == "ANALYSIS"
    )
    assert analysis.current_item_count == 0
    assert analysis.stale_item_count == 1
    assert analysis.missing_item_count == 1
    assert analysis.coverage_state.value == "NONE"
    assert analysis.freshness_state.value == "STALE"
    assert analysis.profile_versions == (
        "ebook-analysis-workflow/v3",
        "ebook-collection-analysis/v1",
    )
    engine.dispose()


def test_injected_item_failure_rolls_back_the_whole_snapshot(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    _seed_observation(engine, root_id, scan_id)
    store = SQLiteCollectionStateStore(engine)

    def fail_items(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic injected failure")

    monkeypatch.setattr(store, "_insert_items", fail_items)
    with pytest.raises(RuntimeError, match="synthetic injected failure"):
        store.build(scan_id, NOW)
    with engine.connect() as connection:
        assert connection.execute(select(collection_state_snapshots.c.id)).all() == []
        assert connection.execute(select(collection_state_components.c.snapshot_id)).all() == []
        assert connection.execute(select(collection_state_counts.c.snapshot_id)).all() == []
        assert connection.execute(select(collection_state_items.c.snapshot_id)).all() == []
    monkeypatch.undo()
    retry = store.build(scan_id, NOW + timedelta(minutes=1))
    assert retry.created is True
    assert retry.snapshot.item_count == 1
    engine.dispose()


def test_content_id_collision_fails_atomically(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    _file_id, observation_id = _seed_observation(engine, root_id, scan_id)
    store = SQLiteCollectionStateStore(engine)
    first = store.build(scan_id, NOW).snapshot
    with engine.begin() as connection:
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(EntityId.new()),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(observation_id),
                "kind": "SYNTHETIC_TECHNICAL",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": "b" * 64,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            },
        )
    monkeypatch.setattr(
        "foliotone.persistence.collection_state.collection_state_snapshot_id",
        lambda _digest: first.id,
    )
    monkeypatch.setattr(
        "foliotone.collection_state.contracts.collection_state_snapshot_id",
        lambda _digest: first.id,
    )

    with pytest.raises(CollectionStateStoreError, match="content collision"):
        store.build(scan_id, NOW + timedelta(minutes=1))
    with engine.connect() as connection:
        assert connection.execute(select(collection_state_snapshots.c.id)).all() == [
            (str(first.id),)
        ]
    engine.dispose()


def test_build_cli_is_idempotent_and_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    _seed_observation(engine, root_id, scan_id, relative_path="private/hidden-title.epub")
    engine.dispose()

    arguments = [
        "collection-state-build",
        "--scan-run-id",
        str(scan_id),
        "--database",
        str(head_database),
        "--output",
        "json",
    ]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["created"] is True
    assert first["counts"]["physical.item_count"] == 1
    assert "hidden-title" not in json.dumps(first, sort_keys=True)
    assert "technical_digest" not in first
    assert "evidence_digest" not in first

    assert main(arguments) == 0
    repeat = json.loads(capsys.readouterr().out)
    assert repeat["created"] is False
    assert repeat["snapshot_id"] == first["snapshot_id"]


def test_report_cli_is_true_read_only_path_free_and_bounded(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_sqlite_engine(head_database)
    root_id, scan_id = _seed_root_and_scan(engine)
    _seed_observation(
        engine,
        root_id,
        scan_id,
        relative_path="private/secret-title.epub",
    )
    snapshot = SQLiteCollectionStateStore(engine).build(scan_id, NOW).snapshot
    engine.dispose()
    before = head_database.read_bytes()
    monkeypatch.setattr("foliotone.cli.main.migrate", lambda _path: pytest.fail("must not migrate"))
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("must not open writable SQLite"),
    )

    assert (
        main(
            [
                "collection-state-report",
                "--snapshot",
                str(snapshot.id),
                "--database",
                str(head_database),
                "--output",
                "json",
            ]
        )
        == 0
    )

    assert head_database.read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["command"] == "collection-state-report"
    assert payload["snapshot_id"] == str(snapshot.id)
    assert payload["truncated"] is False
    assert payload["counts"]["physical.item_count"] == 1
    for private_value in (
        "private/secret-title.epub",
        "secret-title",
        str(head_database),
        snapshot.items_digest,
    ):
        assert private_value not in encoded
    assert "technical_digest" not in encoded
    assert "evidence_digest" not in encoded


def test_report_on_pre_0023_schema_fails_path_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "old.db"
    migrate(database, "0022_quarantine_execution_persistence")
    assert (
        main(
            [
                "collection-state-report",
                "--snapshot",
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
        "command": "collection-state-report",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }


def test_collection_state_cli_rejects_invalid_opaque_ids() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["collection-state-build", "--scan-run-id", "not-a-uuid"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["collection-state-report", "--snapshot", "not-a-uuid"])
