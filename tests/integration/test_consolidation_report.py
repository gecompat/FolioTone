from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert

from foliotone.cli.main import build_parser, main
from foliotone.consolidation import (
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    CONSOLIDATION_PLAN_VERSION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    consolidation_plan_content_hash,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    SQLiteConsolidationStore,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
)
from foliotone.persistence.consolidation_report import SQLiteConsolidationPlanReportReader

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _persisted_plan(path: Path) -> tuple[str, str]:
    engine = create_sqlite_engine(path)
    root = ScanRoot(EntityId.new(), "synthetic-eb08", MediaType.EBOOK)
    scan = ScanRun(EntityId.new(), root.id, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    file_id = EntityId.new()
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    repository(engine, FileRecord).save(
        FileRecord(
            id=file_id,
            scan_root_id=root.id,
            relative_path="synthetic/book.epub",
            size_bytes=123,
            modified_at=NOW,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    repository(engine, FileObservation).save(
        FileObservation(
            id=EntityId.new(),
            file_id=file_id,
            scan_run_id=scan.id,
            relative_path="synthetic/book.epub",
            size_bytes=123,
            modified_at=NOW,
            observed_at=NOW,
        )
    )
    plan = ConsolidationPlan(
        id=EntityId.new(),
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=CONSOLIDATION_PLAN_VERSION,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=root.id,
        source_scan_run_id=scan.id,
        identity=None,
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
            ConsolidationBlocker(
                ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,
                (
                    ConsolidationEvidenceReference(
                        ConsolidationEvidenceKind.FINGERPRINT,
                        "zeta",
                        ConsolidationEvidenceRole.IDENTITY,
                        "b" * 64,
                    ),
                    ConsolidationEvidenceReference(
                        ConsolidationEvidenceKind.FINGERPRINT,
                        "private/path/book.epub",
                        ConsolidationEvidenceRole.IDENTITY,
                        "c" * 64,
                    ),
                ),
            ),
            ConsolidationBlocker(
                ConsolidationBlockerCode.IDENTITY_NOT_ACTIONABLE,
                (
                    ConsolidationEvidenceReference(
                        ConsolidationEvidenceKind.FINGERPRINT,
                        "alpha",
                        ConsolidationEvidenceRole.IDENTITY,
                        "d" * 64,
                    ),
                ),
            ),
            ConsolidationBlocker(ConsolidationBlockerCode.QUALITY_EVIDENCE_INCOMPLETE),
        ),
        status=ConsolidationPlanStatus.BLOCKED,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash="0" * 64,
        created_at=NOW,
    )
    plan = replace(plan, content_hash=consolidation_plan_content_hash(plan))
    with engine.begin() as connection:
        connection.execute(
            insert(schema.fingerprints).values(
                id="private/path/book.epub",
                target_kind=EntityKind.FILE.value,
                target_id=str(file_id),
                kind="SYNTHETIC_BLOCKER",
                algorithm="sha256",
                algorithm_version="1",
                value="c" * 64,
                created_at=NOW.isoformat(),
            )
        )
        connection.execute(
            insert(schema.fingerprints).values(
                id="alpha",
                target_kind=EntityKind.FILE.value,
                target_id=str(file_id),
                kind="SYNTHETIC_BLOCKER",
                algorithm="sha256",
                algorithm_version="1",
                value="d" * 64,
                created_at=NOW.isoformat(),
            )
        )
        connection.execute(
            insert(schema.fingerprints).values(
                id="zeta",
                target_kind=EntityKind.FILE.value,
                target_id=str(file_id),
                kind="SYNTHETIC_BLOCKER",
                algorithm="sha256",
                algorithm_version="1",
                value="b" * 64,
                created_at=NOW.isoformat(),
            )
        )
    SQLiteConsolidationStore(engine).create_or_get_plan(plan)
    engine.dispose()
    return str(plan.id), plan.content_hash


def test_consolidation_report_cli_is_read_only_and_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = head_database
    plan_id, content_hash = _persisted_plan(database)
    before = database.read_bytes()
    monkeypatch.setattr("foliotone.cli.main.migrate", lambda _path: pytest.fail("must not migrate"))
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("must not open a writable engine"),
    )

    result = main(
        [
            "ebook-consolidation-report",
            "--plan",
            plan_id,
            "--database",
            str(database),
            "--output",
            "json",
        ]
    )

    assert result == 0
    assert database.read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["command"] == "ebook-consolidation-report"
    assert payload["plan_id"] == plan_id
    assert payload["profile"] == CONSOLIDATION_PLAN_PROFILE
    assert payload["status"] == "BLOCKED"
    assert payload["execution_state"] == "NOT_EXECUTABLE"
    assert payload["content_hash"] == content_hash
    assert payload["counts"]["blockers"] == 3
    assert payload["counts"]["blocker_evidence_refs"] == 3
    assert payload["blocker_codes"] == [
        "IDENTITY_NOT_ACTIONABLE",
        "IDENTITY_NOT_ACTIONABLE",
        "QUALITY_EVIDENCE_INCOMPLETE",
    ]
    assert "private/path" not in encoded
    assert ("b" * 64) not in encoded
    assert ("c" * 64) not in encoded
    assert str(database) not in encoded
    assert "scan_root_id" not in payload
    assert "source_scan_run_id" not in payload
    assert payload["keeper_file_id"] is None
    assert payload["candidate_file_id"] is None


def test_consolidation_report_rejects_invalid_plan_token() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ebook-consolidation-report", "--plan", "not-a-uuid"])


def test_consolidation_report_missing_plan_returns_path_free_error(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = head_database

    assert main(
        [
            "ebook-consolidation-report",
            "--plan",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-consolidation-report",
        "ok": False,
        "error": {"code": "PLAN_UNAVAILABLE"},
    }


def test_consolidation_report_json_is_path_free_on_older_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "older-schema.db"
    migrate(database, "0015_calibre_library_reconciliation")

    assert main(
        [
            "ebook-consolidation-report",
            "--plan",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-consolidation-report",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }


def test_consolidation_report_internal_error_is_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = head_database

    def _boom(_self: SQLiteConsolidationPlanReportReader, _plan: EntityId) -> object:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(SQLiteConsolidationPlanReportReader, "read", _boom)

    assert main(
        [
            "ebook-consolidation-report",
            "--plan",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-consolidation-report",
        "ok": False,
        "error": {"code": "INTERNAL_READ_ERROR"},
    }


def test_consolidation_report_corrupt_db_is_path_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "corrupt.db"
    database.write_text("not a sqlite database", encoding="utf-8")

    assert main(
        [
            "ebook-consolidation-report",
            "--plan",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "ebook-consolidation-report",
        "ok": False,
        "error": {"code": "INTERNAL_READ_ERROR"},
    }
