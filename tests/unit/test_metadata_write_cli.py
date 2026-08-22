from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import foliotone.cli.main as cli
from foliotone.core import EntityId
from foliotone.metadata_write.authorization import MetadataWriteRunStatus
from foliotone.workflows.metadata_write_operation import (
    MetadataWriteAuthorizationResult,
    MetadataWriteOperationResult,
)

NOW = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)
PLAN_ID = EntityId.parse("ca000000-0000-0000-0000-000000000001")
CAPABILITY_ID = EntityId.parse("ca000000-0000-0000-0000-000000000002")
AUTHORIZATION_ID = EntityId.parse("ca000000-0000-0000-0000-000000000003")
RUN_ID = EntityId.parse("ca000000-0000-0000-0000-000000000004")
ROOT_ID = EntityId.parse("ca000000-0000-0000-0000-000000000005")
SCAN_ID = EntityId.parse("ca000000-0000-0000-0000-000000000006")
OBSERVATION_ID = EntityId.parse("ca000000-0000-0000-0000-000000000007")
COLLECTION_STATE_ID = EntityId.parse("ca000000-0000-0000-0000-000000000008")
PLAN_HASH = "a" * 64


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _ExecuteService:
    def __init__(self) -> None:
        self.executed_confirmation: str | None = None

    def confirmation_prompt(self, **_kwargs: object) -> str:
        return f"CONFIRM METADATA WRITE {AUTHORIZATION_ID}"

    def execute(self, *, confirmation_text: str, **_kwargs: object) -> MetadataWriteOperationResult:
        self.executed_confirmation = confirmation_text
        return MetadataWriteOperationResult(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
            scan_root_id=ROOT_ID,
            status=MetadataWriteRunStatus.VERIFIED,
            scan_run_id=SCAN_ID,
            observation_id=OBSERVATION_ID,
            collection_state_snapshot_id=COLLECTION_STATE_ID,
        )


def _bound_arguments(command: str) -> list[str]:
    values = [
        command,
        "--plan-id",
        str(PLAN_ID),
        "--plan-content-hash",
        PLAN_HASH,
        "--capability-id",
        str(CAPABILITY_ID),
    ]
    if command != "metadata-write-authorize":
        values.extend(("--authorization-id", str(AUTHORIZATION_ID)))
    return values


def test_metadata_write_execute_accepts_only_the_exact_stdin_line_and_stays_private(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    monkeypatch.setattr(cli, "_open_metadata_write_operator", lambda: (engine, service))
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(f"CONFIRM METADATA WRITE {AUTHORIZATION_ID}\n"),
    )

    assert cli.main([*_bound_arguments("metadata-write-execute"), "--output", "json"]) == 0

    captured = capsys.readouterr()
    assert captured.err == f"CONFIRM METADATA WRITE {AUTHORIZATION_ID}\n"
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": 1,
        "command": "metadata-write-execute",
        "ok": True,
        "profile": "metadata-write-operator/v1",
        "authorization_id": str(AUTHORIZATION_ID),
        "run_id": str(RUN_ID),
        "plan_id": str(PLAN_ID),
        "scan_root_id": str(ROOT_ID),
        "status": "VERIFIED",
        "scan_run_id": str(SCAN_ID),
        "observation_id": str(OBSERVATION_ID),
        "collection_state_snapshot_id": str(COLLECTION_STATE_ID),
    }
    assert service.executed_confirmation == f"CONFIRM METADATA WRITE {AUTHORIZATION_ID}"
    assert PLAN_HASH not in captured.out
    assert engine.disposed is True


def test_metadata_write_execute_rejects_a_wrong_confirmation_before_run_creation(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    monkeypatch.setattr(cli, "_open_metadata_write_operator", lambda: (engine, service))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("CONFIRM SOMETHING ELSE\n"))

    assert cli.main([*_bound_arguments("metadata-write-execute"), "--output", "json"]) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == {"code": "CONFIRMATION_INVALID"}
    assert captured.err == f"CONFIRM METADATA WRITE {AUTHORIZATION_ID}\n"
    assert service.executed_confirmation is None
    assert engine.disposed is True


def test_metadata_write_authorize_and_recover_use_only_opaque_binders(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_result = MetadataWriteAuthorizationResult(
        authorization_id=AUTHORIZATION_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        authorized_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    recovery_result = MetadataWriteOperationResult(
        authorization_id=AUTHORIZATION_ID,
        run_id=RUN_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        status=MetadataWriteRunStatus.RECOVERED,
        scan_run_id=SCAN_ID,
        observation_id=OBSERVATION_ID,
        collection_state_snapshot_id=COLLECTION_STATE_ID,
    )
    service = SimpleNamespace(
        authorize=lambda **_kwargs: authorization_result,
        recover=lambda **_kwargs: recovery_result,
    )
    engines: list[_Engine] = []

    def open_operator() -> tuple[_Engine, object]:
        engine = _Engine()
        engines.append(engine)
        return engine, service

    monkeypatch.setattr(cli, "_open_metadata_write_operator", open_operator)
    assert cli.main([*_bound_arguments("metadata-write-authorize"), "--output", "json"]) == 0
    authorize_payload = json.loads(capsys.readouterr().out)
    assert authorize_payload["status"] == "AUTHORIZED"
    assert cli.main([*_bound_arguments("metadata-write-recover"), "--output", "json"]) == 0
    recover_payload = json.loads(capsys.readouterr().out)
    assert recover_payload["status"] == "RECOVERED"
    assert all(engine.disposed for engine in engines)
    assert all(
        "database" not in vars(cli.build_parser().parse_args(arguments))
        for arguments in (
            _bound_arguments("metadata-write-authorize"),
            _bound_arguments("metadata-write-execute"),
            _bound_arguments("metadata-write-recover"),
        )
    )


def test_metadata_write_status_opens_the_database_strictly_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "metadata-write-status.db"
    database.touch()
    engine = _Engine()
    payload = {
        "schema_version": 1,
        "command": "metadata-write-status",
        "ok": True,
        "run_id": str(RUN_ID),
        "status": "VERIFIED",
    }
    monkeypatch.setenv("FOLIOTONE_DATABASE", str(database))
    monkeypatch.setattr(cli, "migrate", lambda _path: pytest.fail("status must not migrate"))
    monkeypatch.setattr(
        cli,
        "create_sqlite_engine",
        lambda _path: pytest.fail("status must not open a writable database"),
    )
    monkeypatch.setattr(cli, "create_sqlite_read_only_engine", lambda _path: engine)
    monkeypatch.setattr(
        cli,
        "SQLiteMetadataWriteStatusReportReader",
        lambda _store: SimpleNamespace(
            read=lambda _run_id: SimpleNamespace(payload=lambda: payload)
        ),
    )

    assert cli.main(["metadata-write-status", "--run-id", str(RUN_ID), "--output", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert engine.disposed is True


def test_metadata_write_parser_rejects_non_lowercase_plan_hashes() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "metadata-write-authorize",
                "--plan-id",
                str(PLAN_ID),
                "--plan-content-hash",
                "A" * 64,
                "--capability-id",
                str(CAPABILITY_ID),
            ]
        )


def test_metadata_write_operator_uses_the_established_runtime_tool_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "metadata-write.db"
    stage_root = tmp_path / "stage"
    engine = _Engine()
    captured: dict[str, object] = {}

    monkeypatch.setenv("FOLIOTONE_DATABASE", str(database))
    monkeypatch.setenv("FOLIOTONE_METADATA_WRITE_STAGE_ROOT", str(stage_root))
    monkeypatch.setenv("FOLIOTONE_EBOOK_META", "configured-ebook-meta")
    monkeypatch.setenv("FOLIOTONE_EBOOK_CONVERT", "configured-ebook-convert")
    monkeypatch.setenv("FOLIOTONE_CALIBRE_DEBUG", "configured-calibre-debug")
    monkeypatch.setenv("FOLIOTONE_JAVA", "configured-java")
    monkeypatch.setenv("FOLIOTONE_EPUBCHECK_JAR", "configured-epubcheck.jar")
    monkeypatch.setattr(cli, "migrate", lambda path: captured.update(database=path))
    monkeypatch.setattr(cli, "create_sqlite_engine", lambda path: engine)

    service = SimpleNamespace()

    def create_service(
        configured_engine: object,
        configured_stage_root: Path,
        **kwargs: object,
    ) -> object:
        captured.update(
            engine=configured_engine,
            stage_root=configured_stage_root,
            validator=kwargs,
        )
        return service

    monkeypatch.setattr(cli, "create_metadata_write_operator_service", create_service)

    opened_engine, _service = cli._open_metadata_write_operator()

    assert opened_engine is engine
    assert captured["database"] == database
    assert captured["stage_root"] == stage_root
    assert captured["validator"] == {
        "metadata_executable": "configured-ebook-meta",
        "text_executable": "configured-ebook-convert",
        "cover_executable": "configured-calibre-debug",
        "java_executable": "configured-java",
        "epubcheck_jar": Path("configured-epubcheck.jar"),
    }
    assert _service is service


def test_metadata_write_operator_disposes_the_engine_when_composition_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    monkeypatch.setenv("FOLIOTONE_DATABASE", str(tmp_path / "metadata-write.db"))
    monkeypatch.setattr(cli, "migrate", lambda _path: None)
    monkeypatch.setattr(cli, "create_sqlite_engine", lambda _path: engine)

    def fail_composition(*_args: object, **_kwargs: object) -> object:
        raise ValueError("unavailable")

    monkeypatch.setattr(
        cli,
        "create_metadata_write_operator_service",
        fail_composition,
    )

    with pytest.raises(ValueError, match="unavailable"):
        cli._open_metadata_write_operator()

    assert engine.disposed is True
