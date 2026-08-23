"""Focused CLI coverage for path-free quarantine authorization."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import foliotone.cli.main as cli
from foliotone.core import EntityId
from foliotone.quarantine import QuarantineAuthorizationBlockerCode, QuarantineRunStatus
from foliotone.workflows.quarantine_operation import (
    QuarantineAuthorizationResult,
    QuarantineOperationResult,
    QuarantineOperatorError,
    QuarantineOperatorErrorCode,
)

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
PLAN_ID = EntityId.parse("dd000000-0000-0000-0000-000000000001")
CAPABILITY_ID = EntityId.parse("dd000000-0000-0000-0000-000000000002")
AUTHORIZATION_ID = EntityId.parse("dd000000-0000-0000-0000-000000000003")
ROOT_ID = EntityId.parse("dd000000-0000-0000-0000-000000000004")
RUN_ID = EntityId.parse("dd000000-0000-0000-0000-000000000005")
PLAN_HASH = "a" * 64


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _arguments(command: str = "quarantine-authorize") -> list[str]:
    values = [
        command,
        "--plan-id",
        str(PLAN_ID),
        "--plan-content-hash",
        PLAN_HASH,
        "--capability-id",
        str(CAPABILITY_ID),
    ]
    if command == "quarantine-execute":
        values.extend(("--authorization-id", str(AUTHORIZATION_ID)))
    values.extend(("--output", "json"))
    return values


def _recovery_arguments() -> list[str]:
    return [
        "quarantine-recover",
        "--run-id",
        str(RUN_ID),
        "--output",
        "json",
    ]


def test_quarantine_authorize_emits_only_opaque_public_material(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    result = QuarantineAuthorizationResult(
        authorization_id=AUTHORIZATION_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        authorized_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    service = SimpleNamespace(authorize=lambda **_kwargs: result)
    monkeypatch.setattr(cli, "_open_quarantine_operator", lambda: (engine, service))

    assert cli.main(_arguments()) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": 1,
        "command": "quarantine-authorize",
        "ok": True,
        "profile": "quarantine-operator/v1",
        "authorization_id": str(AUTHORIZATION_ID),
        "plan_id": str(PLAN_ID),
        "scan_root_id": str(ROOT_ID),
        "authorized_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
        "status": "AUTHORIZED",
    }
    assert PLAN_HASH not in json.dumps(payload, sort_keys=True)
    assert "candidate.epub" not in json.dumps(payload, sort_keys=True)
    assert engine.disposed is True
    assert "database" not in vars(cli.build_parser().parse_args(_arguments()))


def test_quarantine_authorize_reports_only_public_blocker_codes(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()

    def blocked(**_kwargs: object) -> None:
        raise QuarantineOperatorError(
            QuarantineOperatorErrorCode.AUTHORIZATION_BLOCKED,
            (QuarantineAuthorizationBlockerCode.REVIEWS_NOT_ACCEPTED,),
        )

    monkeypatch.setattr(
        cli,
        "_open_quarantine_operator",
        lambda: (engine, SimpleNamespace(authorize=blocked)),
    )

    assert cli.main(_arguments()) == 2

    assert json.loads(capsys.readouterr().out)["error"] == {
        "code": "AUTHORIZATION_BLOCKED",
        "blockers": ["REVIEWS_NOT_ACCEPTED"],
    }
    assert engine.disposed is True


class _ExecuteService:
    def __init__(self) -> None:
        self.executed_confirmation: str | None = None

    def confirmation_prompt(self, **_kwargs: object) -> str:
        return f"CONFIRM QUARANTINE {AUTHORIZATION_ID} {PLAN_ID}"

    def execute(self, *, confirmation_text: str, **_kwargs: object) -> QuarantineOperationResult:
        self.executed_confirmation = confirmation_text
        return QuarantineOperationResult(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
            scan_root_id=ROOT_ID,
            status=QuarantineRunStatus.COMPLETED,
        )


def test_quarantine_execute_accepts_only_the_exact_stdin_line_and_stays_private(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    confirmation = f"CONFIRM QUARANTINE {AUTHORIZATION_ID} {PLAN_ID}"
    monkeypatch.setattr(cli, "_open_quarantine_operator", lambda: (engine, service))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{confirmation}\n"))

    assert cli.main(_arguments("quarantine-execute")) == 0

    captured = capsys.readouterr()
    assert captured.err == f"{confirmation}\n"
    assert json.loads(captured.out) == {
        "schema_version": 1,
        "command": "quarantine-execute",
        "ok": True,
        "profile": "quarantine-operator/v1",
        "authorization_id": str(AUTHORIZATION_ID),
        "run_id": str(RUN_ID),
        "plan_id": str(PLAN_ID),
        "scan_root_id": str(ROOT_ID),
        "status": "COMPLETED",
    }
    assert service.executed_confirmation == confirmation
    assert PLAN_HASH not in captured.out
    assert "candidate.epub" not in captured.out
    assert engine.disposed is True
    assert "database" not in vars(
        cli.build_parser().parse_args(_arguments("quarantine-execute"))
    )


@pytest.mark.parametrize(
    "supplied",
    ("CONFIRM SOMETHING ELSE\n", "x" * 257, ""),
)
def test_quarantine_execute_rejects_noncanonical_or_unbounded_stdin(
    supplied: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    service = _ExecuteService()
    prompt = f"CONFIRM QUARANTINE {AUTHORIZATION_ID} {PLAN_ID}"
    monkeypatch.setattr(cli, "_open_quarantine_operator", lambda: (engine, service))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(supplied))

    assert cli.main(_arguments("quarantine-execute")) == 2

    captured = capsys.readouterr()
    assert captured.err == f"{prompt}\n"
    assert json.loads(captured.out)["error"] == {"code": "CONFIRMATION_INVALID"}
    assert service.executed_confirmation is None
    assert engine.disposed is True


def test_quarantine_execute_failure_exposes_only_the_opaque_existing_run(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    prompt = f"CONFIRM QUARANTINE {AUTHORIZATION_ID} {PLAN_ID}"

    def consumed(**_kwargs: object) -> None:
        raise QuarantineOperatorError(
            QuarantineOperatorErrorCode.AUTHORIZATION_CONSUMED,
            run_id=RUN_ID,
        )

    service = SimpleNamespace(
        confirmation_prompt=lambda **_kwargs: prompt,
        execute=consumed,
    )
    monkeypatch.setattr(cli, "_open_quarantine_operator", lambda: (engine, service))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f"{prompt}\n"))

    assert cli.main(_arguments("quarantine-execute")) == 2

    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == {
        "code": "AUTHORIZATION_CONSUMED",
        "run_id": str(RUN_ID),
    }
    assert PLAN_HASH not in captured.out
    assert "candidate.epub" not in captured.out
    assert engine.disposed is True


def test_quarantine_recover_accepts_only_one_opaque_run_and_stays_private(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    received: dict[str, object] = {}

    def recover(*, run_id: EntityId) -> QuarantineOperationResult:
        received["run_id"] = run_id
        return QuarantineOperationResult(
            authorization_id=AUTHORIZATION_ID,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
            scan_root_id=ROOT_ID,
            status=QuarantineRunStatus.CANCELLED,
        )

    monkeypatch.setattr(
        cli,
        "_open_quarantine_operator",
        lambda: (engine, SimpleNamespace(recover=recover)),
    )

    assert cli.main(_recovery_arguments()) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": 1,
        "command": "quarantine-recover",
        "ok": True,
        "profile": "quarantine-operator/v1",
        "authorization_id": str(AUTHORIZATION_ID),
        "run_id": str(RUN_ID),
        "plan_id": str(PLAN_ID),
        "scan_root_id": str(ROOT_ID),
        "status": "CANCELLED",
    }
    assert received == {"run_id": RUN_ID}
    assert PLAN_HASH not in json.dumps(payload, sort_keys=True)
    assert "candidate.epub" not in json.dumps(payload, sort_keys=True)
    assert engine.disposed is True
    assert set(vars(cli.build_parser().parse_args(_recovery_arguments()))) == {
        "command",
        "run_id",
        "output",
    }


def test_quarantine_recover_failure_exposes_only_the_opaque_existing_run(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()

    def blocked(**_kwargs: object) -> None:
        raise QuarantineOperatorError(
            QuarantineOperatorErrorCode.MANUAL_REVIEW,
            run_id=RUN_ID,
        )

    monkeypatch.setattr(
        cli,
        "_open_quarantine_operator",
        lambda: (engine, SimpleNamespace(recover=blocked)),
    )

    assert cli.main(_recovery_arguments()) == 2

    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "quarantine-recover",
        "ok": False,
        "error": {"code": "MANUAL_REVIEW", "run_id": str(RUN_ID)},
    }
    assert engine.disposed is True


@pytest.mark.parametrize(
    "forbidden",
    (
        ("--plan-id", str(PLAN_ID)),
        ("--plan-content-hash", PLAN_HASH),
        ("--capability-id", str(CAPABILITY_ID)),
        ("--authorization-id", str(AUTHORIZATION_ID)),
        ("--database", "private.db"),
    ),
)
def test_quarantine_recover_parser_rejects_additional_operator_material(
    forbidden: tuple[str, str],
) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*_recovery_arguments(), *forbidden])


def test_quarantine_authorize_parser_rejects_non_lowercase_plan_hashes() -> None:
    arguments = _arguments()
    arguments[arguments.index(PLAN_HASH)] = "A" * 64
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(arguments)


def test_quarantine_operator_uses_only_the_configured_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "quarantine.db"
    engine = _Engine()
    captured: dict[str, object] = {}
    service = SimpleNamespace()
    monkeypatch.setenv("FOLIOTONE_DATABASE", str(database))
    monkeypatch.setattr(cli, "migrate", lambda path: captured.update(database=path))
    monkeypatch.setattr(cli, "create_sqlite_engine", lambda path: engine)
    monkeypatch.setattr(
        cli,
        "create_quarantine_operator_service",
        lambda configured: captured.update(engine=configured) or service,
    )

    opened_engine, opened_service = cli._open_quarantine_operator()

    assert opened_engine is engine
    assert opened_service is service
    assert captured == {"database": database, "engine": engine}
