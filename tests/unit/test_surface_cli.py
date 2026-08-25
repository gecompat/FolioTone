from __future__ import annotations

import time
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

import foliotone.cli.main as cli_main
import foliotone.surface.cli as surface_cli
from foliotone.application.contracts import (
    EbookFixityAnalysisJobProfile,
    EbookFixityBaselineActivationResult,
    EbookFixityBaselineStatus,
    EbookFixityExpectationRevisionResult,
    EbookFixityReviewCommand,
    EbookFixityReviewResult,
    EbookFixityVerificationStatus,
)
from foliotone.cli.main import build_parser
from foliotone.core import EntityId
from foliotone.surface.contracts import JobStatus, Scope

_ROOT_ID = "00000000-0000-4000-8000-000000000001"
_RESULT_ID = EntityId.parse("00000000-0000-4000-8000-000000000002")


class _AnalysisStore:
    def __init__(
        self,
        profile: EbookFixityAnalysisJobProfile,
        *,
        heartbeat: bool = True,
        terminal: bool = True,
    ) -> None:
        self.profile = profile
        self.heartbeat = heartbeat
        self.terminal = terminal
        self.claim = SimpleNamespace(
            id="job-id",
            actor_id="actor-id",
            fence_epoch=1,
            lease_token="lease",
        )
        self.completions: list[tuple[str, object]] = []

    def claim_next_job(self, _role, _lease_token):
        return self.claim

    def ebook_fixity_analysis_job_binder(self, _job_id):
        return SimpleNamespace(profile=self.profile, scan_root_id=_ROOT_ID, worker_count=1)

    def heartbeat_claimed_job(self, _claim):
        return self.heartbeat

    def complete_ebook_fixity_analysis_job(self, _claim, **result):
        self.completions.append(("result", result))
        return self.terminal

    def complete_claimed_job(self, _claim, *, status, finding_code):
        self.completions.append(("terminal", (status, finding_code)))
        return self.terminal

    def abandon_claimed_job_for_recovery(self, _claim, *, finding_code):
        self.completions.append(("abandon", finding_code))
        return self.terminal


def _patch_analysis_runtime(monkeypatch, store: _AnalysisStore) -> None:
    monkeypatch.setattr(surface_cli, "migrate", lambda _path: None)
    monkeypatch.setattr(surface_cli, "create_sqlite_engine", lambda _path: object())
    monkeypatch.setattr(surface_cli, "create_sqlite_read_only_engine", lambda _path: object())
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda _engine: store)
    monkeypatch.setattr(surface_cli, "SQLiteEbookFixityBaselineStore", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteEbookFixityVerificationStore", lambda _engine: object())
    monkeypatch.setattr(
        surface_cli,
        "SQLiteEbookFixityBaselineProjection",
        lambda _engine: SimpleNamespace(enabled_ebook_root_id=lambda: EntityId.parse(_ROOT_ID)),
    )


@pytest.mark.parametrize(
    ("profile", "result_key"),
    (
        (EbookFixityAnalysisJobProfile.BASELINE_BUILD, "manifest_id"),
        (EbookFixityAnalysisJobProfile.VERIFICATION, "verification_run_id"),
    ),
)
def test_analysis_worker_dispatches_only_fixed_fixity_profiles(
    monkeypatch, tmp_path: Path, profile: EbookFixityAnalysisJobProfile, result_key: str
) -> None:
    store = _AnalysisStore(profile)
    _patch_analysis_runtime(monkeypatch, store)
    product = SimpleNamespace(manifest_id=_RESULT_ID, run_id=_RESULT_ID)
    builder = SimpleNamespace(build=lambda _root, worker_count: product)
    verifier = SimpleNamespace(verify=lambda _root, worker_count: product)
    monkeypatch.setattr(surface_cli, "EbookFixityBaselineBuilder", lambda *_args: builder)
    monkeypatch.setattr(surface_cli, "EbookFixityVerifier", lambda *_args: verifier)

    result = surface_cli.run_analysis_worker(
        Namespace(database=tmp_path / "surface.sqlite", ebook_root=tmp_path, once=True)
    )

    assert result == 0
    assert store.completions == [("result", {result_key: str(_RESULT_ID)})]


def test_analysis_worker_workflow_failure_is_terminal_and_has_no_result(
    monkeypatch, tmp_path: Path
) -> None:
    store = _AnalysisStore(EbookFixityAnalysisJobProfile.BASELINE_BUILD)
    _patch_analysis_runtime(monkeypatch, store)

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic workflow failure")

    monkeypatch.setattr(
        surface_cli,
        "EbookFixityBaselineBuilder",
        lambda *_args: SimpleNamespace(build=fail),
    )

    result = surface_cli.run_analysis_worker(
        Namespace(database=tmp_path / "surface.sqlite", ebook_root=tmp_path, once=True)
    )

    assert result == 2
    assert store.completions == [
        ("terminal", (JobStatus.FAILED, "FIXITY_JOB_FAILED"))
    ]


def test_analysis_worker_heartbeat_loss_never_binds_a_stale_result(
    monkeypatch, tmp_path: Path
) -> None:
    store = _AnalysisStore(EbookFixityAnalysisJobProfile.BASELINE_BUILD, heartbeat=False)
    _patch_analysis_runtime(monkeypatch, store)
    monkeypatch.setattr(surface_cli, "_ANALYSIS_HEARTBEAT_INTERVAL_SECONDS", 0.001)

    def slow_success(_root, worker_count):
        time.sleep(0.02)
        return SimpleNamespace(manifest_id=_RESULT_ID)

    monkeypatch.setattr(
        surface_cli,
        "EbookFixityBaselineBuilder",
        lambda *_args: SimpleNamespace(build=slow_success),
    )

    result = surface_cli.run_analysis_worker(
        Namespace(database=tmp_path / "surface.sqlite", ebook_root=tmp_path, once=True)
    )

    assert result == 2
    assert store.completions == [("abandon", "JOB_LEASE_LOST")]


def test_analysis_worker_terminalization_failure_remains_fail_closed(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    store = _AnalysisStore(
        EbookFixityAnalysisJobProfile.BASELINE_BUILD,
        terminal=False,
    )
    _patch_analysis_runtime(monkeypatch, store)

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic workflow failure")

    monkeypatch.setattr(
        surface_cli,
        "EbookFixityBaselineBuilder",
        lambda *_args: SimpleNamespace(build=fail),
    )

    result = surface_cli.run_analysis_worker(
        Namespace(database=tmp_path / "surface.sqlite", ebook_root=tmp_path, once=True)
    )

    assert result == 2
    assert store.completions == [
        ("terminal", (JobStatus.FAILED, "FIXITY_JOB_FAILED")),
        ("abandon", "JOB_LEASE_LOST"),
    ]
    assert all(kind != "result" for kind, _value in store.completions)
    assert "JOB_TERMINALIZATION_FAILED" in capsys.readouterr().out


def _arguments(tmp_path: Path, *, container: bool) -> Namespace:
    return Namespace(
        database=tmp_path / "surface.sqlite",
        host="127.0.0.1",
        port=8765,
        container_loopback_publish=container,
    )


def test_container_listener_is_rejected_outside_a_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(surface_cli, "_container_runtime_detected", lambda: False)

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=True)) == 2
    assert "requires an IPv4 Docker or Podman container" in capsys.readouterr().err
    assert not (tmp_path / "surface.sqlite").exists()


def test_container_listener_keeps_public_origin_on_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(surface_cli, "_container_runtime_detected", lambda: True)
    monkeypatch.setattr(surface_cli, "migrate", lambda _database: None)
    monkeypatch.setattr(surface_cli, "create_sqlite_engine", lambda _database: object())
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda _engine: object())
    monkeypatch.setattr(
        surface_cli, "LocalSurfaceService", lambda _store, **_kwargs: object()
    )
    monkeypatch.setattr(surface_cli, "SQLiteCollectionStateReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteLibraryHealthReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "CollectionQueryService", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteEbookSurfaceReadModel", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "EbookRenamePlanningService", lambda *_args: object())
    monkeypatch.setattr(surface_cli, "EbookRenameDependencyScopeResolver", lambda: object())

    def fake_app(_service: object, **values: object) -> object:
        captured["config"] = values["config"]
        return object()

    def fake_run(_app: object, **values: object) -> None:
        captured.update(values)

    monkeypatch.setattr(surface_cli, "create_surface_app", fake_app)
    monkeypatch.setattr(surface_cli.uvicorn, "run", fake_run)

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=True)) == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8765
    assert captured["proxy_headers"] is False
    assert captured["config"].origin == "http://127.0.0.1:8765"  # type: ignore[union-attr]


def test_surface_api_migrates_before_opening_its_listener(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    database = tmp_path / "surface.sqlite"

    monkeypatch.setattr(
        surface_cli, "migrate", lambda path: events.append(f"migrate:{path}")
    )
    monkeypatch.setattr(
        surface_cli, "create_sqlite_engine", lambda path: events.append(f"engine:{path}")
    )
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "LocalSurfaceService", lambda store, **_kwargs: store)
    monkeypatch.setattr(
        surface_cli, "SQLiteCollectionStateReportReader", lambda engine: engine
    )
    monkeypatch.setattr(
        surface_cli, "SQLiteLibraryHealthReportReader", lambda engine: engine
    )
    monkeypatch.setattr(surface_cli, "CollectionQueryService", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "SQLiteEbookSurfaceReadModel", lambda engine: engine)
    monkeypatch.setattr(surface_cli, "EbookRenamePlanningService", lambda *_args: object())
    monkeypatch.setattr(
        surface_cli, "EbookRenameDependencyScopeResolver", lambda: object()
    )
    monkeypatch.setattr(surface_cli, "create_surface_app", lambda *args, **kwargs: "app")
    monkeypatch.setattr(
        surface_cli.uvicorn,
        "run",
        lambda app, **kwargs: events.append(f"run:{app}"),
    )

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=False)) == 0
    assert events[:2] == [f"migrate:{database}", f"engine:{database}"]
    assert events[-1] == "run:app"


def test_surface_api_composes_fixity_review_and_command_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = object()
    review_store = SimpleNamespace(
        list_fixity_queue_by_id=lambda **_kwargs: ((), None),
    )
    command_result = object()
    command_operation = SimpleNamespace(
        review_result=lambda *_args, **_kwargs: command_result,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(surface_cli, "migrate", lambda _database: None)
    monkeypatch.setattr(surface_cli, "create_sqlite_engine", lambda _database: engine)
    monkeypatch.setattr(surface_cli, "SQLiteSurfaceStore", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteEbookFixityBaselineStore", lambda _engine: object())
    monkeypatch.setattr(
        surface_cli, "SQLiteEbookFixityVerificationStore", lambda _engine: object()
    )
    monkeypatch.setattr(
        surface_cli, "SQLiteEbookFixityBaselineActivationOperation", lambda _engine: object()
    )

    def build_review_store(received_engine: object) -> object:
        captured["review_engine"] = received_engine
        return review_store

    def build_command_operation(received_engine: object) -> object:
        captured["command_engine"] = received_engine
        return command_operation

    monkeypatch.setattr(surface_cli, "SQLiteResolutionReviewStore", build_review_store)
    monkeypatch.setattr(
        surface_cli, "SQLiteEbookFixityCommandOperation", build_command_operation
    )

    monkeypatch.setattr(surface_cli, "SQLiteCollectionStateReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteLibraryHealthReportReader", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "CollectionQueryService", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "SQLiteEbookSurfaceReadModel", lambda _engine: object())
    monkeypatch.setattr(surface_cli, "EbookRenamePlanningService", lambda *_args: object())
    monkeypatch.setattr(surface_cli, "EbookRenameDependencyScopeResolver", lambda: object())
    def build_app(service: object, **_kwargs: object) -> object:
        captured["service"] = service
        return object()

    monkeypatch.setattr(surface_cli, "create_surface_app", build_app)
    monkeypatch.setattr(surface_cli.uvicorn, "run", lambda *_args, **_kwargs: None)

    assert surface_cli.run_surface_api(_arguments(tmp_path, container=False)) == 0
    assert captured["review_engine"] is engine
    assert captured["command_engine"] is engine
    service = captured["service"]
    assert isinstance(service, surface_cli.LocalSurfaceService)
    assert service.fixity_review_queue(after_id=None, limit=1) == ((), None)
    assert service.review_fixity_result_command(
        EbookFixityReviewCommand(result_id=_RESULT_ID, decision="DEFER"),
        actor_id="synthetic-actor",
        session_id="synthetic-session",
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
    ) is command_result


@pytest.mark.parametrize(
    ("command", "arguments"),
    (
        (
            "ebook-fixity-baseline-build",
            ["--scan-root-id", _ROOT_ID, "--retry-id", "retry-1"],
        ),
        (
            "ebook-fixity-verification-run",
            ["--scan-root-id", _ROOT_ID, "--retry-id", "retry-1"],
        ),
        ("ebook-fixity-baseline-status", [str(_RESULT_ID)]),
        ("ebook-fixity-baseline-activate", [str(_RESULT_ID), "--retry-id", "retry-1"]),
        ("ebook-fixity-verification-status", [str(_RESULT_ID)]),
        (
            "ebook-fixity-result-review",
            [str(_RESULT_ID), "--decision", "ACCEPT", "--retry-id", "retry-1"],
        ),
        (
            "ebook-fixity-expectation-revise",
            [str(_RESULT_ID), "--action", "ACCEPT_CURRENT", "--retry-id", "retry-1"],
        ),
    ),
)
def test_fixity_owner_commands_are_registered(command: str, arguments: list[str]) -> None:
    parsed = build_parser().parse_args([command, "--database", "surface.sqlite", *arguments])

    assert parsed.command == command


@pytest.mark.parametrize(
    ("command", "arguments", "runner_name"),
    (
        (
            "ebook-fixity-baseline-build",
            ["--scan-root-id", _ROOT_ID, "--retry-id", "retry-1"],
            "run_ebook_fixity_baseline_build",
        ),
        (
            "ebook-fixity-baseline-status",
            [str(_RESULT_ID)],
            "run_ebook_fixity_baseline_status",
        ),
        (
            "ebook-fixity-baseline-activate",
            [str(_RESULT_ID), "--retry-id", "retry-1"],
            "run_ebook_fixity_baseline_activate",
        ),
        (
            "ebook-fixity-verification-run",
            ["--scan-root-id", _ROOT_ID, "--retry-id", "retry-1"],
            "run_ebook_fixity_verification_run",
        ),
        (
            "ebook-fixity-verification-status",
            [str(_RESULT_ID)],
            "run_ebook_fixity_verification_status",
        ),
        (
            "ebook-fixity-result-review",
            [str(_RESULT_ID), "--decision", "ACCEPT", "--retry-id", "retry-1"],
            "run_ebook_fixity_result_review",
        ),
        (
            "ebook-fixity-expectation-revise",
            [str(_RESULT_ID), "--action", "ACCEPT_CURRENT", "--retry-id", "retry-1"],
            "run_ebook_fixity_expectation_revise",
        ),
    ),
)
def test_fixity_owner_commands_dispatch_to_their_adapter(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    arguments: list[str],
    runner_name: str,
) -> None:
    captured: list[Namespace] = []
    monkeypatch.setattr(cli_main, runner_name, lambda args: captured.append(args) or 17)

    assert cli_main.main([command, "--database", "surface.sqlite", *arguments]) == 17
    assert captured[0].command == command


@pytest.mark.parametrize("worker_count", (0, 3))
def test_fixity_owner_parser_rejects_out_of_bounds_worker_count(worker_count: int) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "ebook-fixity-baseline-build",
                "--database",
                "surface.sqlite",
                "--scan-root-id",
                _ROOT_ID,
                "--worker-count",
                str(worker_count),
                "--retry-id",
                "retry-1",
            ]
        )


class _AuthenticatedService:
    def __init__(self) -> None:
        self.login_arguments: tuple[str, str] | None = None
        self.reauth_arguments: tuple[object, str, Scope] | None = None
        self.session = SimpleNamespace(user_id="actor-id", id="session-id")
        self.rotated = SimpleNamespace(user_id="actor-id", id="review-session-id")

    def login(self, *, username: str, password: str):
        self.login_arguments = (username, password)
        return "token", "csrf", self.session

    def reauthenticate(self, session: object, password: str, *, scope: Scope):
        self.reauth_arguments = (session, password, scope)
        return "rotated-token", "rotated-csrf", self.rotated

    def has_active_grant(self, session: object, scope: Scope) -> bool:
        return session is self.rotated and scope is Scope.REVIEW


def test_owner_session_uses_hidden_credential_and_fresh_review_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AuthenticatedService()
    prompts: list[str] = []
    monkeypatch.setattr(surface_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(surface_cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        surface_cli.getpass,
        "getpass",
        lambda prompt: prompts.append(prompt)
        or {"Username: ": "owner", "Password: ": "secret"}[prompt],
    )

    assert surface_cli._owner_session(service, review=True) == ("actor-id", "review-session-id")
    assert service.login_arguments == ("owner", "secret")
    assert service.reauth_arguments == (service.session, "secret", Scope.REVIEW)
    assert prompts == ["Username: ", "Password: "]


def test_owner_session_fails_closed_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _AuthenticatedService()
    monkeypatch.setattr(surface_cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(surface_cli.sys.stdout, "isatty", lambda: False)

    assert surface_cli._owner_session(service, review=False) is None
    assert service.login_arguments is None


def test_owner_session_fails_closed_when_review_grant_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AuthenticatedService()
    values = iter(("owner", "secret"))
    monkeypatch.setattr(surface_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(surface_cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(surface_cli.getpass, "getpass", lambda _prompt: next(values))
    monkeypatch.setattr(service, "has_active_grant", lambda _session, _scope: False)

    assert surface_cli._owner_session(service, review=True) is None
    assert service.reauth_arguments == (service.session, "secret", Scope.REVIEW)


class _FixityApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, dict[str, object]]] = []

    def enqueue_ebook_fixity_job(self, port: object, command: object, **kwargs: object) -> str:
        self.calls.append(("enqueue", command, kwargs))
        assert port is _FIXITY_PORT
        return "00000000-0000-4000-8000-000000000003"

    def ebook_fixity_baseline_status(self, port: object, manifest_id: EntityId):
        self.calls.append(("baseline-status", manifest_id, {"port": port}))
        return EbookFixityBaselineStatus(
            manifest_id=manifest_id,
            scan_root_id=EntityId.parse(_ROOT_ID),
            source_scan_run_id=_RESULT_ID,
            status="PREPARED",
            started_at="2026-08-25T00:00:00+00:00",
            prepared_at="2026-08-25T00:01:00+00:00",
            expires_at="2026-08-25T00:16:00+00:00",
            item_count=2,
            activated_at=None,
        )

    def ebook_fixity_verification_status(self, port: object, run_id: EntityId):
        self.calls.append(("verification-status", run_id, {"port": port}))
        return EbookFixityVerificationStatus(
            run_id=run_id,
            scan_root_id=EntityId.parse(_ROOT_ID),
            baseline_activation_id=_RESULT_ID,
            source_scan_run_id=_RESULT_ID,
            expectation_revision_no=1,
            status="COMPLETED",
            started_at="2026-08-25T00:00:00+00:00",
            completed_at="2026-08-25T00:02:00+00:00",
            expected_result_count=2,
            result_count=2,
            failure_code=None,
        )

    def activate_ebook_fixity_baseline(self, port: object, command: object, **kwargs: object):
        self.calls.append(("activate", command, kwargs))
        return EbookFixityBaselineActivationResult(activation_id=_RESULT_ID, manifest_id=_RESULT_ID)

    def review_ebook_fixity_result(self, port: object, command: object, **kwargs: object):
        self.calls.append(("review", command, kwargs))
        return EbookFixityReviewResult(
            result_id=_RESULT_ID,
            review_item_id=_RESULT_ID,
            decision_id=_RESULT_ID,
            decision="ACCEPT",
            sequence_no=1,
        )

    def revise_ebook_fixity_expectation(self, port: object, command: object, **kwargs: object):
        self.calls.append(("revise", command, kwargs))
        return EbookFixityExpectationRevisionResult(
            result_id=_RESULT_ID,
            revision_id=_RESULT_ID,
            action="ACCEPT_CURRENT",
            revision_no=2,
        )


_FIXITY_PORT = object()


def _fixity_arguments(command: str, **values: object) -> Namespace:
    if command not in {
        "ebook-fixity-baseline-status",
        "ebook-fixity-verification-status",
    }:
        values.setdefault("retry_id", "retry-1")
    return Namespace(command=command, database=Path("surface.sqlite"), **values)


def _patch_fixity_command(
    monkeypatch: pytest.MonkeyPatch, application: _FixityApplication, *, review: bool
) -> None:
    expected_review = review

    def authenticated(_args: Namespace, *, review: bool) -> tuple[object, str, str]:
        assert review is expected_review
        return _FIXITY_PORT, "actor-id", "review-session-id"

    monkeypatch.setattr(surface_cli, "create_application", lambda: application)
    monkeypatch.setattr(surface_cli, "_fixity_authenticated", authenticated)


@pytest.mark.parametrize(
    ("runner", "command", "profile"),
    (
        (
            surface_cli.run_ebook_fixity_baseline_build,
            "ebook-fixity-baseline-build",
            EbookFixityAnalysisJobProfile.BASELINE_BUILD,
        ),
        (
            surface_cli.run_ebook_fixity_verification_run,
            "ebook-fixity-verification-run",
            EbookFixityAnalysisJobProfile.VERIFICATION,
        ),
    ),
)
def test_fixity_enqueue_commands_use_application_without_source_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runner,
    command: str,
    profile: EbookFixityAnalysisJobProfile,
) -> None:
    application = _FixityApplication()
    _patch_fixity_command(monkeypatch, application, review=False)

    assert runner(_fixity_arguments(command, scan_root_id=_ROOT_ID, worker_count=2)) == 0
    call, request, kwargs = application.calls[0]
    assert call == "enqueue"
    assert request.profile is profile
    assert request.worker_count == 2
    assert kwargs["actor_id"] == "actor-id"
    assert len(str(kwargs["input_digest"])) == 64
    assert len(str(kwargs["idempotency_digest"])) == 64
    output = capsys.readouterr().out
    assert _ROOT_ID not in output
    assert "surface.sqlite" not in output


@pytest.mark.parametrize(
    ("runner", "command", "identifier"),
    (
        (
            surface_cli.run_ebook_fixity_baseline_status,
            "ebook-fixity-baseline-status",
            "manifest_id",
        ),
        (
            surface_cli.run_ebook_fixity_verification_status,
            "ebook-fixity-verification-status",
            "run_id",
        ),
    ),
)
def test_fixity_status_commands_are_path_and_hash_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runner,
    command: str,
    identifier: str,
) -> None:
    application = _FixityApplication()
    _patch_fixity_command(monkeypatch, application, review=False)

    assert runner(_fixity_arguments(command, **{identifier: str(_RESULT_ID)})) == 0
    output = capsys.readouterr().out
    assert str(_RESULT_ID) in output
    assert "/media" not in output
    assert "a" * 64 not in output


def test_fixity_activation_is_hidden_and_does_not_echo_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    application = _FixityApplication()
    _patch_fixity_command(monkeypatch, application, review=True)
    confirmation = f"ACCEPT FIXITY BASELINE {_RESULT_ID}"
    monkeypatch.setattr(surface_cli.getpass, "getpass", lambda _prompt: confirmation)

    assert surface_cli.run_ebook_fixity_baseline_activate(
        _fixity_arguments("ebook-fixity-baseline-activate", manifest_id=str(_RESULT_ID))
    ) == 0
    assert application.calls[0][0] == "activate"
    assert confirmation not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("runner", "command", "argument", "value", "expected_call"),
    (
        (
            surface_cli.run_ebook_fixity_result_review,
            "ebook-fixity-result-review",
            "decision",
            "ACCEPT",
            "review",
        ),
        (
            surface_cli.run_ebook_fixity_expectation_revise,
            "ebook-fixity-expectation-revise",
            "action",
            "ACCEPT_CURRENT",
            "revise",
        ),
    ),
)
def test_fixity_review_commands_use_fresh_session_and_application_port(
    monkeypatch: pytest.MonkeyPatch,
    runner,
    command: str,
    argument: str,
    value: str,
    expected_call: str,
) -> None:
    application = _FixityApplication()
    _patch_fixity_command(monkeypatch, application, review=True)

    assert runner(
        _fixity_arguments(command, result_id=str(_RESULT_ID), **{argument: value})
    ) == 0
    call, _request, kwargs = application.calls[0]
    assert call == expected_call
    assert kwargs["actor_id"] == "actor-id"
    assert kwargs["session_id"] == "review-session-id"


def test_fixity_command_fails_closed_when_authentication_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(surface_cli, "_fixity_service", lambda _database: object())
    monkeypatch.setattr(surface_cli, "_owner_session", lambda _service, *, review: None)

    assert surface_cli.run_ebook_fixity_baseline_build(
        _fixity_arguments(
            "ebook-fixity-baseline-build", scan_root_id=_ROOT_ID, worker_count=1
        )
    ) == 2
    assert "LOCAL_AUTH_REQUIRED" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "arguments"),
    (
        ("ebook-fixity-baseline-build", ["--scan-root-id", _ROOT_ID]),
        ("ebook-fixity-verification-run", ["--scan-root-id", _ROOT_ID]),
        ("ebook-fixity-baseline-activate", [str(_RESULT_ID)]),
        ("ebook-fixity-result-review", [str(_RESULT_ID), "--decision", "ACCEPT"]),
        (
            "ebook-fixity-expectation-revise",
            [str(_RESULT_ID), "--action", "ACCEPT_CURRENT"],
        ),
    ),
)
def test_mutating_fixity_commands_require_a_bounded_retry_id(
    command: str, arguments: list[str]
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([command, "--database", "surface.sqlite", *arguments])


@pytest.mark.parametrize("retry_id", ("", "invalid/retry", "x" * 129))
def test_fixity_retry_id_parser_rejects_invalid_values(retry_id: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "ebook-fixity-baseline-build",
                "--database",
                "surface.sqlite",
                "--scan-root-id",
                _ROOT_ID,
                "--retry-id",
                retry_id,
            ]
        )


class _UnexpectedFixityAdapterError(RuntimeError):
    pass


@pytest.mark.parametrize(
    ("runner", "command", "values", "method", "failure_code"),
    (
        (
            surface_cli.run_ebook_fixity_baseline_build,
            "ebook-fixity-baseline-build",
            {"scan_root_id": _ROOT_ID, "worker_count": 1},
            "enqueue_ebook_fixity_job",
            "FIXITY_JOB_REJECTED",
        ),
        (
            surface_cli.run_ebook_fixity_verification_run,
            "ebook-fixity-verification-run",
            {"scan_root_id": _ROOT_ID, "worker_count": 1},
            "enqueue_ebook_fixity_job",
            "FIXITY_JOB_REJECTED",
        ),
        (
            surface_cli.run_ebook_fixity_baseline_status,
            "ebook-fixity-baseline-status",
            {"manifest_id": str(_RESULT_ID)},
            "ebook_fixity_baseline_status",
            "FIXITY_BASELINE_UNAVAILABLE",
        ),
        (
            surface_cli.run_ebook_fixity_verification_status,
            "ebook-fixity-verification-status",
            {"run_id": str(_RESULT_ID)},
            "ebook_fixity_verification_status",
            "FIXITY_VERIFICATION_UNAVAILABLE",
        ),
        (
            surface_cli.run_ebook_fixity_baseline_activate,
            "ebook-fixity-baseline-activate",
            {"manifest_id": str(_RESULT_ID)},
            "activate_ebook_fixity_baseline",
            "FIXITY_BASELINE_ACTIVATION_REJECTED",
        ),
        (
            surface_cli.run_ebook_fixity_result_review,
            "ebook-fixity-result-review",
            {"result_id": str(_RESULT_ID), "decision": "ACCEPT"},
            "review_ebook_fixity_result",
            "FIXITY_REVIEW_REJECTED",
        ),
        (
            surface_cli.run_ebook_fixity_expectation_revise,
            "ebook-fixity-expectation-revise",
            {"result_id": str(_RESULT_ID), "action": "ACCEPT_CURRENT"},
            "revise_ebook_fixity_expectation",
            "FIXITY_EXPECTATION_REJECTED",
        ),
    ),
)
def test_fixity_adapters_map_unexpected_failures_to_safe_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runner,
    command: str,
    values: dict[str, object],
    method: str,
    failure_code: str,
) -> None:
    application = _FixityApplication()
    _patch_fixity_command(
        monkeypatch,
        application,
        review=command
        in {
            "ebook-fixity-baseline-activate",
            "ebook-fixity-result-review",
            "ebook-fixity-expectation-revise",
        },
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise _UnexpectedFixityAdapterError("private-path SQL fence capability")

    monkeypatch.setattr(application, method, fail)
    if command == "ebook-fixity-baseline-activate":
        monkeypatch.setattr(
            surface_cli.getpass,
            "getpass",
            lambda _prompt: f"ACCEPT FIXITY BASELINE {_RESULT_ID}",
        )

    assert runner(_fixity_arguments(command, **values)) == 2
    output = capsys.readouterr()
    assert failure_code in output.err
    assert "private-path SQL fence capability" not in output.err + output.out


class _RetryingFixityApplication(_FixityApplication):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: dict[str, tuple[str, str]] = {}
        self.idempotency_digests: list[str] = []
        self.insert_count = 0

    def enqueue_ebook_fixity_job(self, port: object, command: object, **kwargs: object) -> str:
        assert port is _FIXITY_PORT
        input_digest = str(kwargs["input_digest"])
        idempotency_digest = str(kwargs["idempotency_digest"])
        self.idempotency_digests.append(idempotency_digest)
        existing = self.jobs.get(idempotency_digest)
        if existing is not None:
            if existing[0] != input_digest:
                raise ValueError("divergent retry input")
            return existing[1]
        self.insert_count += 1
        job_id = f"00000000-0000-4000-8000-{self.insert_count:012d}"
        self.jobs[idempotency_digest] = (input_digest, job_id)
        return job_id


def test_fixity_retry_id_replays_one_identical_job_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    application = _RetryingFixityApplication()
    _patch_fixity_command(monkeypatch, application, review=False)
    arguments = _fixity_arguments(
        "ebook-fixity-baseline-build",
        scan_root_id=_ROOT_ID,
        worker_count=1,
        retry_id="repeat-1",
    )

    assert surface_cli.run_ebook_fixity_baseline_build(arguments) == 0
    first = capsys.readouterr().out
    assert surface_cli.run_ebook_fixity_baseline_build(arguments) == 0
    assert capsys.readouterr().out == first
    assert "repeat-1" not in first
    assert application.insert_count == 1


def test_fixity_retry_id_rejects_divergent_reuse(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    application = _RetryingFixityApplication()
    _patch_fixity_command(monkeypatch, application, review=False)

    assert surface_cli.run_ebook_fixity_baseline_build(
        _fixity_arguments(
            "ebook-fixity-baseline-build",
            scan_root_id=_ROOT_ID,
            worker_count=1,
            retry_id="repeat-1",
        )
    ) == 0
    assert surface_cli.run_ebook_fixity_baseline_build(
        _fixity_arguments(
            "ebook-fixity-baseline-build",
            scan_root_id=_ROOT_ID,
            worker_count=2,
            retry_id="repeat-1",
        )
    ) == 2
    assert "FIXITY_JOB_REJECTED" in capsys.readouterr().err
    assert application.insert_count == 1


def test_fixity_retry_id_is_domain_separated_per_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _RetryingFixityApplication()
    _patch_fixity_command(monkeypatch, application, review=False)

    assert surface_cli.run_ebook_fixity_baseline_build(
        _fixity_arguments(
            "ebook-fixity-baseline-build",
            scan_root_id=_ROOT_ID,
            worker_count=1,
            retry_id="same-retry",
        )
    ) == 0
    assert surface_cli.run_ebook_fixity_verification_run(
        _fixity_arguments(
            "ebook-fixity-verification-run",
            scan_root_id=_ROOT_ID,
            worker_count=1,
            retry_id="same-retry",
        )
    ) == 0
    assert application.insert_count == 2
    assert application.idempotency_digests[0] != application.idempotency_digests[1]
