"""Read-only and privacy-safe archive collection status coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from foliotone.archive.signatures import observe_archive_signature_v2
from foliotone.cli.main import build_parser, main
from foliotone.core import (
    ArchiveCollectionItem,
    ArchiveCollectionItemSource,
    ArchiveCollectionItemStatus,
    ArchiveCollectionPlanFindingCounts,
    ArchiveCollectionRun,
    ArchiveCollectionRunStatus,
    EntityId,
)
from foliotone.persistence import create_sqlite_engine, migrate
from foliotone.persistence.archive_collection import (
    ArchiveCollectionPlanEntry,
    SQLiteArchiveCollectionStore,
    _ArchiveCollectionLiteralCount,
    _ArchiveCollectionReportSnapshot,
    archive_collection_plan_content_hash,
)
from foliotone.workflows.archive_collection_report import ArchiveCollectionStatusReport

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("00000000-0000-0000-0000-000000000801")
SCAN_ID = EntityId.parse("00000000-0000-0000-0000-000000000802")
FILE_ID = EntityId.parse("00000000-0000-0000-0000-000000000803")
OBSERVATION_ID = EntityId.parse("00000000-0000-0000-0000-000000000804")
FILE_HASH = "b" * 64


def _persisted_report_run(database: Path) -> ArchiveCollectionRun:
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id,name,media_type,enabled) "
                "VALUES (:id,'synthetic-private-root','EBOOK',1)"
            ),
            {"id": str(ROOT_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs (id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:now,'COMPLETED',:now)"
            ),
            {"id": str(SCAN_ID), "root": str(ROOT_ID), "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO file_records (id,scan_root_id,relative_path,size_bytes,"
                "modified_at,media_type,presence_state,first_seen_at,last_seen_at,"
                "consecutive_missing_scans) VALUES (:id,:root,'private/book.zip',8,:now,"
                "'EBOOK','PRESENT',:now,:now,0)"
            ),
            {"id": str(FILE_ID), "root": str(ROOT_ID), "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO file_observations (id,file_id,scan_run_id,relative_path,"
                "size_bytes,modified_at,observed_at) VALUES (:id,:file,:scan,"
                "'private/book.zip',8,:now,:now)"
            ),
            {
                "id": str(OBSERVATION_ID),
                "file": str(FILE_ID),
                "scan": str(SCAN_ID),
                "now": NOW.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO fingerprints (id,target_kind,target_id,kind,algorithm,"
                "algorithm_version,value,created_at) VALUES (:id,'FILE_OBSERVATION',"
                ":target,'FILE_SHA256','sha256','1',:value,:now)"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000805",
                "target": str(OBSERVATION_ID),
                "value": FILE_HASH,
                "now": NOW.isoformat(),
            },
        )
    store = SQLiteArchiveCollectionStore(engine)
    planning = store.create_planning_run(
        ROOT_ID,
        worker_count=1,
        plan_limit=None,
        started_at=NOW,
        lease_token="private-lease-token",
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    item_id = EntityId.parse("00000000-0000-0000-0000-000000000806")
    item = ArchiveCollectionItem(
        item_id,
        planning.id,
        OBSERVATION_ID,
        0,
        observe_archive_signature_v2("book.zip", b"PK\x03\x04data"),
    )
    source = ArchiveCollectionItemSource(
        planning.id,
        item_id,
        0,
        OBSERVATION_ID,
        FILE_HASH,
        8,
        "archive",
    )
    entry = ArchiveCollectionPlanEntry(item, (source,))
    findings = ArchiveCollectionPlanFindingCounts(missing_volume=2)
    store.append_plan_batch(planning.id, "private-lease-token", (entry,), now=NOW)
    store.seal_plan(
        planning.id,
        "private-lease-token",
        planned_count=1,
        findings=findings,
        plan_content_hash=archive_collection_plan_content_hash(
            planning, (entry,), findings
        ),
        sealed_at=NOW + timedelta(seconds=1),
    )
    claimed = store.claim_pending(
        planning.id,
        "private-lease-token",
        limit=1,
        started_at=NOW + timedelta(seconds=2),
    )[0]
    store.complete_item(
        claimed.item,
        "private-lease-token",
        status=ArchiveCollectionItemStatus.ERROR,
        completed_at=NOW + timedelta(seconds=3),
        archive_observation_id=None,
        disposition=None,
        error_code="ORCHESTRATION_ERROR",
    )
    result = store.finish_invocation(
        planning.id,
        "private-lease-token",
        finished_at=NOW + timedelta(seconds=4),
    )
    engine.dispose()
    return result


def test_archive_collection_status_is_read_only_complete_and_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _persisted_report_run(head_database)
    before = head_database.read_bytes()
    monkeypatch.setattr("foliotone.cli.main.migrate", lambda _path: pytest.fail("must not migrate"))
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("must not open a writable engine"),
    )

    assert main(
        [
            "archive-collection-status",
            "--run-id",
            str(run.id),
            "--database",
            str(head_database),
            "--output",
            "json",
        ]
    ) == 0

    assert head_database.read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    encoded = json.dumps(payload, sort_keys=True)
    assert payload == {
        "command": "archive-collection-status",
        "counts": {
            "error": 1,
            "executed": 0,
            "failed": 0,
            "pending": 0,
            "planned": 1,
            "reused": 0,
            "running": 0,
            "succeeded": 0,
        },
        "encryption_statuses": [],
        "error_codes": [{"count": 1, "literal": "ORCHESTRATION_ERROR"}],
        "integrity_statuses": [],
        "listing_statuses": [],
        "ok": True,
        "plan_findings": {
            "ambiguous_volume": 0,
            "hash_evidence_missing": 0,
            "missing_volume": 2,
            "name_collision": 0,
            "orphan_volume": 0,
            "unsupported_volume": 0,
        },
        "profile": "archive-collection-orchestration/v1",
        "recognition_statuses": [],
        "run_id": str(run.id),
        "schema_version": 1,
        "source_scan_run_id": str(SCAN_ID),
        "status": "COMPLETED_WITH_FAILURES",
        "storage_families": [],
        "truncated": False,
    }
    assert "private" not in encoded
    assert FILE_HASH not in encoded
    assert str(head_database) not in encoded
    assert "plan_content_hash" not in encoded


def test_archive_collection_status_rejects_invalid_run_token() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["archive-collection-status", "--run-id", "not-a-uuid"]
        )


def test_archive_collection_status_aggregates_fixed_archive_literals() -> None:
    run = ArchiveCollectionRun(
        EntityId.new(),
        ROOT_ID,
        SCAN_ID,
        1,
        NOW,
        ArchiveCollectionRunStatus.COMPLETED,
        1,
        planned_count=1,
        plan_content_hash="a" * 64,
        completed_at=NOW + timedelta(seconds=1),
    )
    def one(literal: str) -> tuple[_ArchiveCollectionLiteralCount, ...]:
        return (_ArchiveCollectionLiteralCount(literal, 1),)

    report = ArchiveCollectionStatusReport.from_snapshot(
        _ArchiveCollectionReportSnapshot(
            run,
            one("SUCCEEDED"),
            one("EXECUTED"),
            one("LISTED"),
            one("PASSED"),
            one("NONE"),
            one("MATCHED"),
            one("ZIP"),
            (),
        )
    )
    payload = report.payload()
    assert payload["listing_statuses"] == [{"literal": "LISTED", "count": 1}]
    assert payload["integrity_statuses"] == [{"literal": "PASSED", "count": 1}]
    assert payload["encryption_statuses"] == [{"literal": "NONE", "count": 1}]
    assert payload["recognition_statuses"] == [{"literal": "MATCHED", "count": 1}]
    assert payload["storage_families"] == [{"literal": "ZIP", "count": 1}]
    with pytest.raises(ValueError, match="error code"):
        replace(report, error_codes=one("Ä_PRIVATE"))
    with pytest.raises(ValueError, match="aggregates"):
        replace(report, listing_statuses=())
    with pytest.raises(ValueError, match="aggregates"):
        _ArchiveCollectionReportSnapshot(
            run,
            one("SUCCEEDED"),
            one("EXECUTED"),
            one("LISTED") + one("LISTED"),
            one("PASSED"),
            one("NONE"),
            one("MATCHED"),
            one("ZIP"),
            (),
        )


@pytest.mark.parametrize("kind", ("missing", "old", "corrupt"))
def test_archive_collection_status_errors_are_generic_and_path_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    database = tmp_path / f"private-{kind}.db"
    expected = "DATABASE_UNAVAILABLE"
    if kind == "old":
        migrate(database, "0019_archive_evidence")
        expected = "RUN_UNAVAILABLE"
    elif kind == "corrupt":
        database.write_text("private/path/hash/secret", encoding="utf-8")
        expected = "RUN_UNAVAILABLE"
    assert main(
        [
            "archive-collection-status",
            "--run-id",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "archive-collection-status",
        "ok": False,
        "error": {"code": expected},
    }
