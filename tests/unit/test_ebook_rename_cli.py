from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import foliotone.cli.main as cli
from foliotone.core import EntityId
from foliotone.ebook_rename import EbookRenameRunStatus
from foliotone.workflows.ebook_rename_operation import (
    EbookRenameAuthorizationResult,
    EbookRenameOperationResult,
)

NOW = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)
PLAN_ID = EntityId.parse("cb000000-0000-0000-0000-000000000001")
CAPABILITY_ID = EntityId.parse("cb000000-0000-0000-0000-000000000002")
AUTHORIZATION_ID = EntityId.parse("cb000000-0000-0000-0000-000000000003")
RUN_ID = EntityId.parse("cb000000-0000-0000-0000-000000000004")
ROOT_ID = EntityId.parse("cb000000-0000-0000-0000-000000000005")
PROBE_ID = EntityId.parse("cb000000-0000-0000-0000-000000000006")
SCAN_ID = EntityId.parse("cb000000-0000-0000-0000-000000000007")
TARGET_OBSERVATION_ID = EntityId.parse("cb000000-0000-0000-0000-000000000008")
COLLECTION_STATE_ID = EntityId.parse("cb000000-0000-0000-0000-000000000009")
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
        return f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}"

    def execute(self, *, confirmation_text: str, **_kwargs: object) -> EbookRenameOperationResult:
        self.executed_confirmation = confirmation_text
        return EbookRenameOperationResult(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
            scan_root_id=ROOT_ID,
            status=EbookRenameRunStatus.VERIFIED,
            scan_run_id=SCAN_ID,
            target_observation_id=TARGET_OBSERVATION_ID,
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
    if command == "ebook-rename-execute":
        values.extend(("--authorization-id", str(AUTHORIZATION_ID)))
    return values


def test_execute_accepts_only_the_exact_stdin_line_and_stays_path_free(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    monkeypatch.setattr(cli, "_open_ebook_rename_operator", lambda: (engine, service))
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}\n"),
    )

    assert cli.main([*_bound_arguments("ebook-rename-execute"), "--output", "json"]) == 0

    captured = capsys.readouterr()
    assert captured.err == f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}\n"
    assert json.loads(captured.out) == {
        "schema_version": 1,
        "command": "ebook-rename-execute",
        "ok": True,
        "profile": "ebook-file-rename-operator/v1",
        "authorization_id": str(AUTHORIZATION_ID),
        "run_id": str(RUN_ID),
        "plan_id": str(PLAN_ID),
        "scan_root_id": str(ROOT_ID),
        "status": "VERIFIED",
        "scan_run_id": str(SCAN_ID),
        "source_observation_id": None,
        "target_observation_id": str(TARGET_OBSERVATION_ID),
        "collection_state_snapshot_id": str(COLLECTION_STATE_ID),
    }
    assert service.executed_confirmation == f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}"
    assert PLAN_HASH not in captured.out
    assert engine.disposed is True


@pytest.mark.parametrize(
    "supplied",
    (
        "CONFIRM SOMETHING ELSE\n",
        f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID} \n",
        f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}",
        "x" * 257,
    ),
)
def test_execute_rejects_invalid_confirmation_before_run_creation(
    supplied: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    monkeypatch.setattr(cli, "_open_ebook_rename_operator", lambda: (engine, service))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(supplied))

    assert cli.main([*_bound_arguments("ebook-rename-execute"), "--output", "json"]) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == {"code": "CONFIRMATION_INVALID"}
    assert captured.err == f"CONFIRM EBOOK RENAME {AUTHORIZATION_ID}\n"
    assert service.executed_confirmation is None
    assert engine.disposed is True


def test_authorize_and_recover_expose_only_opaque_identifiers(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = EbookRenameAuthorizationResult(
        authorization_id=AUTHORIZATION_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        capability_id=CAPABILITY_ID,
        probe_id=PROBE_ID,
        authorized_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    recovery = EbookRenameOperationResult(
        authorization_id=AUTHORIZATION_ID,
        run_id=RUN_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        status=EbookRenameRunStatus.RECOVERED,
        scan_run_id=SCAN_ID,
        source_observation_id=TARGET_OBSERVATION_ID,
        collection_state_snapshot_id=COLLECTION_STATE_ID,
    )
    service = SimpleNamespace(
        authorize=lambda **_kwargs: authorization,
        recover=lambda **_kwargs: recovery,
    )
    engines: list[_Engine] = []

    def open_operator() -> tuple[_Engine, object]:
        engine = _Engine()
        engines.append(engine)
        return engine, service

    monkeypatch.setattr(cli, "_open_ebook_rename_operator", open_operator)

    assert cli.main([*_bound_arguments("ebook-rename-authorize"), "--output", "json"]) == 0
    authorize_payload = json.loads(capsys.readouterr().out)
    assert authorize_payload["status"] == "AUTHORIZED"
    assert cli.main(["ebook-rename-recover", "--run-id", str(RUN_ID), "--output", "json"]) == 0
    recover_payload = json.loads(capsys.readouterr().out)
    assert recover_payload["status"] == "RECOVERED"
    assert all(engine.disposed for engine in engines)
    assert all(
        "database" not in vars(cli.build_parser().parse_args(arguments))
        for arguments in (
            _bound_arguments("ebook-rename-authorize"),
            _bound_arguments("ebook-rename-execute"),
            ["ebook-rename-recover", "--run-id", str(RUN_ID)],
        )
    )


def test_status_opens_the_database_strictly_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "ebook-rename-status.db"
    database.touch()
    engine = _Engine()
    payload = {
        "schema_version": 1,
        "command": "ebook-rename-status",
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
        "SQLiteEbookRenameStatusReportReader",
        lambda _store: SimpleNamespace(
            read=lambda _run_id: SimpleNamespace(payload=lambda: payload)
        ),
    )

    assert cli.main(["ebook-rename-status", "--run-id", str(RUN_ID), "--output", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert engine.disposed is True


def test_parser_rejects_non_lowercase_plan_hashes() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "ebook-rename-authorize",
                "--plan-id",
                str(PLAN_ID),
                "--plan-content-hash",
                "A" * 64,
                "--capability-id",
                str(CAPABILITY_ID),
            ]
        )


def test_operator_disposes_the_engine_when_composition_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    database = tmp_path / "ebook-rename.db"
    monkeypatch.setenv("FOLIOTONE_DATABASE", str(database))
    monkeypatch.setattr(cli, "migrate", lambda path: None)
    monkeypatch.setattr(cli, "create_sqlite_engine", lambda path: engine)

    def fail_composition(*_args: object, **_kwargs: object) -> object:
        raise ValueError("unavailable")

    monkeypatch.setattr(cli, "create_ebook_rename_operator_service", fail_composition)

    with pytest.raises(ValueError, match="unavailable"):
        cli._open_ebook_rename_operator()

    assert engine.disposed is True
