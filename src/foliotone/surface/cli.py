"""Owner-local CLI adapters for the local-single-operator runtime roles."""

from __future__ import annotations

import argparse
import getpass
import hmac
import json
import secrets
import sys
import threading
from pathlib import Path

import uvicorn

from foliotone.application import (
    EbookFixityAnalysisJobCommand,
    EbookFixityAnalysisJobProfile,
    EbookFixityBaselineActivationCommand,
    EbookFixityExpectationRevisionCommand,
    EbookFixityReviewCommand,
    EbookRenameOperatorJobProfile,
    create_application,
)
from foliotone.core import EntityId
from foliotone.ebook_rename.dependency_scopes import EbookRenameDependencyScopeResolver
from foliotone.persistence.fixity import (
    SQLiteEbookFixityBaselineProjection,
    SQLiteEbookFixityBaselineStore,
)
from foliotone.persistence.fixity_commands import SQLiteEbookFixityCommandOperation
from foliotone.persistence.fixity_surface import SQLiteEbookFixityBaselineActivationOperation
from foliotone.persistence.fixity_verification import SQLiteEbookFixityVerificationStore
from foliotone.persistence.resolution_review import SQLiteResolutionReviewStore
from foliotone.persistence.sqlite import (
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
)
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.persistence.surface_read import SQLiteEbookSurfaceReadModel
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import (
    JobStatus,
    ProcessRole,
    Scope,
    SurfaceRuntimeConfig,
)
from foliotone.surface.security import secret_digest
from foliotone.surface.service import LocalSurfaceService
from foliotone.workflows.collection_state import SQLiteCollectionStateReportReader
from foliotone.workflows.collection_state_query import CollectionQueryService
from foliotone.workflows.ebook_rename_operation import (
    EbookRenameOperatorError,
    create_ebook_rename_operator_service,
)
from foliotone.workflows.ebook_rename_planning import EbookRenamePlanningService
from foliotone.workflows.fixity_baseline import EbookFixityBaselineBuilder
from foliotone.workflows.fixity_verification import EbookFixityVerifier
from foliotone.workflows.library_health import SQLiteLibraryHealthReportReader

_CONTAINER_RUNTIME_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))
_ANALYSIS_HEARTBEAT_INTERVAL_SECONDS = 30.0
_FIXITY_RETRY_ID_MAX_LENGTH = 128


def add_surface_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register local-only surface commands without modifying existing media commands."""
    for name, help_text in (
        ("auth-bootstrap", "Create one local bootstrap code on the owner terminal."),
        ("auth-reset", "Reset the only local account through the owner terminal."),
        ("surface-api", "Run the loopback-only local API and same-origin shell."),
        ("analysis-worker", "Poll only read-only analysis jobs without a network listener."),
        ("operator-worker", "Run the capability-free operator role without a network listener."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--database", type=Path, required=True, help="Owner-protected SQLite path."
        )
        if name == "surface-api":
            command.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
            command.add_argument("--port", default=8765, type=int)
            command.add_argument(
                "--container-loopback-publish",
                action="store_true",
                help=(
                    "Listen on the container namespace for a host-loopback-only "
                    "published port; rejected outside Docker or Podman."
                ),
            )
        if name == "analysis-worker":
            command.add_argument(
                "--once", action="store_true", help="Claim at most one read-only job."
            )
            command.add_argument(
                "--ebook-root",
                type=Path,
                default=Path("/media/ebooks"),
                help="Owner-local absolute read-only E-Book root; never persisted.",
            )

    for name, help_text in (
        (
            "ebook-fixity-baseline-build",
            "Queue one authenticated, read-only E-Book fixity baseline build.",
        ),
        (
            "ebook-fixity-baseline-status",
            "Read one authenticated, path-free E-Book fixity baseline status.",
        ),
        (
            "ebook-fixity-baseline-activate",
            "Activate one E-Book fixity baseline after fresh REVIEW reauthentication.",
        ),
        (
            "ebook-fixity-verification-run",
            "Queue one authenticated, read-only E-Book fixity verification.",
        ),
        (
            "ebook-fixity-verification-status",
            "Read one authenticated, path-free E-Book fixity verification status.",
        ),
        (
            "ebook-fixity-result-review",
            "Review one fixity result after fresh REVIEW reauthentication.",
        ),
        (
            "ebook-fixity-expectation-revise",
            "Revise one fixity expectation after fresh REVIEW reauthentication.",
        ),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--database", type=Path, required=True, help="Owner-protected SQLite path."
        )
        if name in {"ebook-fixity-baseline-build", "ebook-fixity-verification-run"}:
            command.add_argument("--scan-root-id", required=True)
            command.add_argument("--worker-count", type=int, choices=(1, 2), default=1)
        elif name.startswith("ebook-fixity-baseline-"):
            command.add_argument("manifest_id")
        elif name.startswith("ebook-fixity-verification-"):
            command.add_argument("run_id")
        elif name == "ebook-fixity-result-review":
            command.add_argument("result_id")
            command.add_argument("--decision", required=True, choices=("ACCEPT", "REJECT", "DEFER"))
        else:
            command.add_argument("result_id")
            command.add_argument(
                "--action", required=True, choices=("ACCEPT_CURRENT", "RETIRE_MISSING")
            )
        if name not in {
            "ebook-fixity-baseline-status",
            "ebook-fixity-verification-status",
        }:
            command.add_argument(
                "--retry-id",
                type=_retry_id,
                required=True,
                help="Bounded owner retry identifier; never persisted or displayed as plaintext.",
            )


def _service(database: Path) -> LocalSurfaceService:
    migrate(database)
    return LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))


def _fixity_service(database: Path) -> LocalSurfaceService:
    """Compose the complete production fixity port without direct CLI persistence access."""
    migrate(database)
    engine = create_sqlite_engine(database)
    return LocalSurfaceService(
        SQLiteSurfaceStore(engine),
        fixity_baseline_store=SQLiteEbookFixityBaselineStore(engine),
        fixity_verification_store=SQLiteEbookFixityVerificationStore(engine),
        fixity_activation_operation=SQLiteEbookFixityBaselineActivationOperation(engine),
        fixity_review_store=SQLiteResolutionReviewStore(engine),
        fixity_command_operation=SQLiteEbookFixityCommandOperation(engine),
    )


def _owner_session(
    service: LocalSurfaceService, *, review: bool
) -> tuple[str, str] | None:
    """Authenticate locally and optionally rotate into one fresh REVIEW grant."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    username = _hidden_input("Username: ", maximum_length=64)
    password = _hidden_input("Password: ", maximum_length=4096)
    if username is None or password is None:
        if password is not None:
            del password
        return None
    try:
        login = service.login(username=username, password=password)
        if login is None:
            return None
        _token, _csrf, session = login
        if review:
            rotated = service.reauthenticate(session, password, scope=Scope.REVIEW)
            if rotated is None:
                return None
            _token, _csrf, session = rotated
            if not service.has_active_grant(session, Scope.REVIEW):
                return None
        return session.user_id, session.id
    except Exception:
        return None
    finally:
        del password


def _hidden_input(prompt: str, *, maximum_length: int) -> str | None:
    """Accept one terminal-only secret without retaining unbounded input."""
    try:
        value = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception:
        return None
    return value if 1 <= len(value) <= maximum_length else None


def _retry_id(value: str) -> str:
    """Accept a bounded non-secret retry identifier without storing its plaintext."""
    if not 1 <= len(value) <= _FIXITY_RETRY_ID_MAX_LENGTH or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        for character in value
    ):
        raise argparse.ArgumentTypeError("retry ID is invalid")
    return value


def _fixity_digests(
    material: dict[str, object], *, command_profile: str, retry_id: str
) -> tuple[str, str]:
    """Create bounded, command-separated request and retry digests."""
    retry_id = _retry_id(retry_id)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return (
        secret_digest(encoded, purpose=f"{command_profile}:input"),
        secret_digest(retry_id, purpose=f"{command_profile}:retry-id"),
    )


def _fixity_failure(command: str, code: str) -> int:
    print(f"{command}: FAILED {code}", file=sys.stderr)
    return 2


def _fixity_authenticated(
    args: argparse.Namespace, *, review: bool
) -> tuple[LocalSurfaceService, str, str] | None:
    try:
        service = _fixity_service(args.database)
    except Exception:
        _fixity_failure(args.command, "DATABASE_UNAVAILABLE")
        return None
    try:
        owner = _owner_session(service, review=review)
    except Exception:
        owner = None
    if owner is None:
        _fixity_failure(args.command, "LOCAL_AUTH_REQUIRED")
        return None
    actor_id, session_id = owner
    return service, actor_id, session_id


def run_ebook_fixity_baseline_build(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=False)
    if authenticated is None:
        return 2
    service, actor_id, _session_id = authenticated
    try:
        scan_root_id = EntityId.parse(args.scan_root_id)
        command = EbookFixityAnalysisJobCommand(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=scan_root_id,
            worker_count=args.worker_count,
        )
        input_digest, idempotency_digest = _fixity_digests(
            {
                "profile": command.profile.value,
                "scan_root_id": str(scan_root_id),
                "worker_count": command.worker_count,
            },
            command_profile=command.profile.value,
            retry_id=args.retry_id,
        )
        job_id = create_application().enqueue_ebook_fixity_job(
            service,
            command,
            actor_id=actor_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        response = f"{args.command}: WAITING {job_id}"
    except Exception:
        return _fixity_failure(args.command, "FIXITY_JOB_REJECTED")
    print(response)
    return 0


def run_ebook_fixity_verification_run(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=False)
    if authenticated is None:
        return 2
    service, actor_id, _session_id = authenticated
    try:
        scan_root_id = EntityId.parse(args.scan_root_id)
        command = EbookFixityAnalysisJobCommand(
            profile=EbookFixityAnalysisJobProfile.VERIFICATION,
            scan_root_id=scan_root_id,
            worker_count=args.worker_count,
        )
        input_digest, idempotency_digest = _fixity_digests(
            {
                "profile": command.profile.value,
                "scan_root_id": str(scan_root_id),
                "worker_count": command.worker_count,
            },
            command_profile=command.profile.value,
            retry_id=args.retry_id,
        )
        job_id = create_application().enqueue_ebook_fixity_job(
            service,
            command,
            actor_id=actor_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        response = f"{args.command}: WAITING {job_id}"
    except Exception:
        return _fixity_failure(args.command, "FIXITY_JOB_REJECTED")
    print(response)
    return 0


def run_ebook_fixity_baseline_status(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=False)
    if authenticated is None:
        return 2
    service, _actor_id, _session_id = authenticated
    try:
        status = create_application().ebook_fixity_baseline_status(
            service, EntityId.parse(args.manifest_id)
        )
        if status is None:
            raise ValueError("fixity baseline status is unavailable")
        response = (
            f"{args.command}: {status.status} {status.manifest_id} "
            f"items={status.item_count if status.item_count is not None else 'UNKNOWN'} "
            f"started_at={status.started_at} "
            f"prepared_at={status.prepared_at if status.prepared_at is not None else 'NONE'} "
            f"expires_at={status.expires_at if status.expires_at is not None else 'NONE'} "
            f"activated_at={status.activated_at if status.activated_at is not None else 'NONE'}"
        )
    except Exception:
        return _fixity_failure(args.command, "FIXITY_BASELINE_UNAVAILABLE")
    print(response)
    return 0


def run_ebook_fixity_verification_status(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=False)
    if authenticated is None:
        return 2
    service, _actor_id, _session_id = authenticated
    try:
        status = create_application().ebook_fixity_verification_status(
            service, EntityId.parse(args.run_id)
        )
        if status is None:
            raise ValueError("fixity verification status is unavailable")
        response = (
            f"{args.command}: {status.status} {status.run_id} "
            f"expected={status.expected_result_count} results={status.result_count} "
            f"started_at={status.started_at} "
            f"completed_at={status.completed_at if status.completed_at is not None else 'NONE'} "
            f"failure_code={status.failure_code if status.failure_code is not None else 'NONE'}"
        )
    except Exception:
        return _fixity_failure(args.command, "FIXITY_VERIFICATION_UNAVAILABLE")
    print(response)
    return 0


def run_ebook_fixity_baseline_activate(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=True)
    if authenticated is None:
        return 2
    service, actor_id, session_id = authenticated
    confirmation = _hidden_input("Confirmation: ", maximum_length=256)
    if confirmation is None:
        return _fixity_failure(args.command, "FIXITY_BASELINE_ACTIVATION_REJECTED")
    try:
        manifest_id = EntityId.parse(args.manifest_id)
        command = EbookFixityBaselineActivationCommand(
            manifest_id=manifest_id,
            confirmation=confirmation,
        )
        input_digest, idempotency_digest = _fixity_digests(
            {"manifest_id": str(manifest_id), "confirmation": confirmation},
            command_profile="ebook-fixity-baseline-activation/v1",
            retry_id=args.retry_id,
        )
        result = create_application().activate_ebook_fixity_baseline(
            service,
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        response = f"{args.command}: ACTIVE {result.activation_id} {result.manifest_id}"
    except Exception:
        return _fixity_failure(args.command, "FIXITY_BASELINE_ACTIVATION_REJECTED")
    finally:
        del confirmation
    print(response)
    return 0


def run_ebook_fixity_result_review(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=True)
    if authenticated is None:
        return 2
    service, actor_id, session_id = authenticated
    try:
        result_id = EntityId.parse(args.result_id)
        command = EbookFixityReviewCommand(result_id=result_id, decision=args.decision)
        input_digest, idempotency_digest = _fixity_digests(
            {"result_id": str(result_id), "decision": command.decision},
            command_profile="ebook-fixity-result-review/v1",
            retry_id=args.retry_id,
        )
        result = create_application().review_ebook_fixity_result(
            service,
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        response = (
            f"{args.command}: {result.decision} {result.result_id} {result.review_item_id} "
            f"{result.decision_id} sequence={result.sequence_no}"
        )
    except Exception:
        return _fixity_failure(args.command, "FIXITY_REVIEW_REJECTED")
    print(response)
    return 0


def run_ebook_fixity_expectation_revise(args: argparse.Namespace) -> int:
    authenticated = _fixity_authenticated(args, review=True)
    if authenticated is None:
        return 2
    service, actor_id, session_id = authenticated
    try:
        result_id = EntityId.parse(args.result_id)
        command = EbookFixityExpectationRevisionCommand(result_id=result_id, action=args.action)
        input_digest, idempotency_digest = _fixity_digests(
            {"result_id": str(result_id), "action": command.action},
            command_profile="ebook-fixity-expectation-revision/v1",
            retry_id=args.retry_id,
        )
        result = create_application().revise_ebook_fixity_expectation(
            service,
            command,
            actor_id=actor_id,
            session_id=session_id,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        response = (
            f"{args.command}: {result.action} {result.result_id} {result.revision_id} "
            f"revision={result.revision_no}"
        )
    except Exception:
        return _fixity_failure(args.command, "FIXITY_EXPECTATION_REJECTED")
    print(response)
    return 0


def run_auth_bootstrap(args: argparse.Namespace) -> int:
    """Emit the one-time bootstrap value solely to an interactive local terminal."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "auth-bootstrap failed: an owner-local interactive terminal is required.",
            file=sys.stderr,
        )
        return 2
    print(_service(args.database).bootstrap())
    return 0


def run_auth_reset(args: argparse.Namespace) -> int:
    """Reset credentials through hidden TTY input; argv and environment are excluded."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "auth-reset failed: an owner-local interactive terminal is required.", file=sys.stderr
        )
        return 2
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second or not _service(args.database).reset(first):
        print("auth-reset failed.", file=sys.stderr)
        return 2
    print("auth-reset completed.")
    return 0


def run_surface_api(args: argparse.Namespace) -> int:
    """Start the local surface directly or behind a fixed host-loopback publish."""
    config = SurfaceRuntimeConfig(bind_host=args.host, port=args.port)
    listener_host = config.bind_host
    if args.container_loopback_publish:
        if config.bind_host != "127.0.0.1" or not _container_runtime_detected():
            print(
                "surface-api failed: container loopback publishing requires an "
                "IPv4 Docker or Podman container.",
                file=sys.stderr,
            )
            return 2
        listener_host = "0.0.0.0"  # noqa: S104 - isolated namespace, host publish is fixed loopback
    migrate(args.database)
    engine = create_sqlite_engine(args.database)
    surface_store = SQLiteSurfaceStore(engine)
    app = create_surface_app(
        LocalSurfaceService(
            surface_store,
            fixity_baseline_store=SQLiteEbookFixityBaselineStore(engine),
            fixity_verification_store=SQLiteEbookFixityVerificationStore(engine),
            fixity_activation_operation=SQLiteEbookFixityBaselineActivationOperation(engine),
            fixity_review_store=SQLiteResolutionReviewStore(engine),
            fixity_command_operation=SQLiteEbookFixityCommandOperation(engine),
        ),
        config=config,
        collection_state_reader=SQLiteCollectionStateReportReader(engine),
        library_health_reader=SQLiteLibraryHealthReportReader(engine),
        collection_search_reader=CollectionQueryService(engine),
        surface_read_model=surface_store,
        ebook_read_model=SQLiteEbookSurfaceReadModel(engine),
        ebook_rename_planning=EbookRenamePlanningService(
            engine,
            EbookRenameDependencyScopeResolver(),
        ),
    )
    uvicorn.run(app, host=listener_host, port=config.port, proxy_headers=False, access_log=False)
    return 0


def _container_runtime_detected() -> bool:
    """Recognize the standard Docker and Podman in-container marker files."""

    return any(path.is_file() for path in _CONTAINER_RUNTIME_MARKERS)


def run_analysis_worker(args: argparse.Namespace) -> int:
    """Execute only fixed read-only fixity profiles with an owner-local root."""
    if not args.ebook_root.is_absolute():
        print("analysis-worker: FAILED EBOOK_ROOT_INVALID", file=sys.stderr)
        return 2
    migrate(args.database)
    engine = create_sqlite_engine(args.database)
    store = SQLiteSurfaceStore(engine)
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, secrets.token_urlsafe(32))
    if claim is None:
        print("analysis-worker: IDLE")
        return 0

    def abandon_fail_closed(finding_code: str) -> bool:
        try:
            return store.abandon_claimed_job_for_recovery(
                claim, finding_code=finding_code
            )
        except Exception:
            return False

    def terminalize_failure(finding_code: str) -> bool:
        try:
            if store.complete_claimed_job(
                claim, status=JobStatus.FAILED, finding_code=finding_code
            ):
                return True
        except Exception:
            pass
        return abandon_fail_closed("JOB_LEASE_LOST")

    binder = store.ebook_fixity_analysis_job_binder(claim.id)
    if binder is None:
        terminalized = terminalize_failure("JOB_BINDER_UNAVAILABLE")
        code = "JOB_BINDER_UNAVAILABLE" if terminalized else "JOB_TERMINALIZATION_FAILED"
        print(f"analysis-worker: FAILED {code}")
        return 2
    stopped = threading.Event()
    lease_lost = threading.Event()

    def keep_job_lease() -> None:
        while not stopped.wait(_ANALYSIS_HEARTBEAT_INTERVAL_SECONDS):
            try:
                heartbeat_ok = store.heartbeat_claimed_job(claim)
            except Exception:
                heartbeat_ok = False
            if not heartbeat_ok:
                lease_lost.set()
                return

    keeper = threading.Thread(target=keep_job_lease, daemon=True)
    keeper.start()
    try:
        root_id = EntityId.parse(binder.scan_root_id)
        projection = SQLiteEbookFixityBaselineProjection(
            create_sqlite_read_only_engine(args.database)
        )
        # Builder/verifier retain authority for enabled-root, lease, snapshot, and fencing.
        if projection.enabled_ebook_root_id() != root_id:
            raise ValueError("scan root binder differs from enabled root")
        if binder.profile is EbookFixityAnalysisJobProfile.BASELINE_BUILD:
            manifest = EbookFixityBaselineBuilder(
                projection, SQLiteEbookFixityBaselineStore(engine)
            ).build(args.ebook_root, worker_count=binder.worker_count)
            result = {"manifest_id": str(manifest.manifest_id)}
        elif binder.profile is EbookFixityAnalysisJobProfile.VERIFICATION:
            run = EbookFixityVerifier(
                projection, SQLiteEbookFixityVerificationStore(engine)
            ).verify(args.ebook_root, worker_count=binder.worker_count)
            result = {"verification_run_id": str(run.run_id)}
        else:  # Defensive even though the immutable binder validates it.
            raise ValueError("unregistered analysis profile")
    except Exception:
        stopped.set()
        keeper.join()
        terminalized = terminalize_failure("FIXITY_JOB_FAILED")
        code = "FIXITY_JOB_FAILED" if terminalized else "JOB_TERMINALIZATION_FAILED"
        print(f"analysis-worker: FAILED {code}")
        return 2
    stopped.set()
    keeper.join()
    completed = False
    if not lease_lost.is_set():
        try:
            completed = store.complete_ebook_fixity_analysis_job(claim, **result)
        except Exception:
            completed = False
    if not completed:
        visible = abandon_fail_closed("JOB_LEASE_LOST")
        code = "JOB_LEASE_LOST" if visible else "JOB_TERMINALIZATION_FAILED"
        print(f"analysis-worker: FAILED {code}")
        return 2
    print("analysis-worker: SUCCEEDED")
    return 0


def run_operator_worker(args: argparse.Namespace) -> int:
    """Claim only fixed ADR-0069 jobs and resolve W10 material in this process."""
    migrate(args.database)
    engine = create_sqlite_engine(args.database)
    store = SQLiteSurfaceStore(engine)
    claim = store.claim_next_job(ProcessRole.OPERATOR_WORKER, secrets.token_urlsafe(32))
    if claim is None:
        print("operator-worker: IDLE")
        return 0
    binder = store.ebook_rename_operator_job_binder(claim.id)
    if binder is None:
        store.complete_claimed_job(
            claim,
            status=JobStatus.FAILED,
            finding_code="JOB_BINDER_UNAVAILABLE",
        )
        print("operator-worker: FAILED JOB_BINDER_UNAVAILABLE")
        return 2
    if not store.has_active_operate_grant(
        grant_id=binder.operate_grant_id,
        actor_id=claim.actor_id,
    ):
        store.complete_claimed_job(
            claim,
            status=JobStatus.FAILED,
            finding_code="OPERATE_GRANT_UNAVAILABLE",
        )
        print("operator-worker: FAILED OPERATE_GRANT_UNAVAILABLE")
        return 2
    stopped = threading.Event()
    lease_lost = threading.Event()

    def keep_job_lease() -> None:
        while not stopped.wait(30):
            if not store.heartbeat_claimed_job(claim):
                lease_lost.set()
                return

    keeper = threading.Thread(target=keep_job_lease, daemon=True)
    keeper.start()
    operator = create_ebook_rename_operator_service(engine)
    try:
        if binder.profile is EbookRenameOperatorJobProfile.AUTHORIZE:
            plan_id = EntityId.parse(binder.plan_id or "")
            capability_id = EntityId.parse(binder.capability_id or "")
            plan_content_hash = binder.plan_content_hash or ""
            authorization_result = operator.authorize(
                plan_id=plan_id,
                plan_content_hash=plan_content_hash,
                capability_id=capability_id,
            )
            store.record_ebook_rename_operator_job_result(
                job_id=claim.id,
                outcome=authorization_result.status,
                authorization_id=str(authorization_result.authorization_id),
            )
        elif binder.profile is EbookRenameOperatorJobProfile.EXECUTE:
            if binder.authorization_id is None or binder.confirmation_digest is None:
                raise ValueError("execute binder is incomplete")
            plan_id = EntityId.parse(binder.plan_id or "")
            capability_id = EntityId.parse(binder.capability_id or "")
            plan_content_hash = binder.plan_content_hash or ""
            authorization_id = EntityId.parse(binder.authorization_id)
            confirmation = operator.confirmation_prompt(
                plan_id=plan_id,
                plan_content_hash=plan_content_hash,
                capability_id=capability_id,
                authorization_id=authorization_id,
            )
            expected_digest = operator.confirmation_digest(
                plan_id=plan_id,
                plan_content_hash=plan_content_hash,
                capability_id=capability_id,
                authorization_id=authorization_id,
                confirmation_text=confirmation,
            )
            if not hmac.compare_digest(expected_digest, binder.confirmation_digest):
                raise ValueError("confirmation digest differs")
            execution_result = operator.execute(
                plan_id=plan_id,
                plan_content_hash=plan_content_hash,
                capability_id=capability_id,
                authorization_id=authorization_id,
                confirmation_text=confirmation,
            )
            store.record_ebook_rename_operator_job_result(
                job_id=claim.id,
                outcome=execution_result.status.value,
                run_id=str(execution_result.run_id),
            )
        elif binder.profile is EbookRenameOperatorJobProfile.RECOVER:
            if binder.run_id is None:
                raise ValueError("recover binder is incomplete")
            recovery_result = operator.recover(run_id=EntityId.parse(binder.run_id))
            store.record_ebook_rename_operator_job_result(
                job_id=claim.id,
                outcome=recovery_result.status.value,
                run_id=str(recovery_result.run_id),
            )
        else:  # pragma: no cover - binder validation makes this unreachable
            raise ValueError("operator profile is invalid")
    except EbookRenameOperatorError as error:
        status = (
            JobStatus.RECOVERY_REQUIRED
            if error.code.value in {"RECOVERY_REQUIRED", "MANUAL_RECOVERY_REQUIRED"}
            else JobStatus.FAILED
        )
        store.complete_claimed_job(claim, status=status, finding_code=error.code.value)
        print(f"operator-worker: {status.value} {error.code.value}")
        return 2
    except (TypeError, ValueError):
        store.complete_claimed_job(
            claim,
            status=JobStatus.FAILED,
            finding_code="JOB_BINDER_INVALID",
        )
        print("operator-worker: FAILED JOB_BINDER_INVALID")
        return 2
    except Exception:
        status = (
            JobStatus.RECOVERY_REQUIRED
            if binder.profile is EbookRenameOperatorJobProfile.EXECUTE
            else JobStatus.FAILED
        )
        store.complete_claimed_job(claim, status=status, finding_code="JOB_RUNTIME_UNAVAILABLE")
        print(f"operator-worker: {status.value} JOB_RUNTIME_UNAVAILABLE")
        return 2
    finally:
        stopped.set()
        keeper.join(timeout=1)
    if lease_lost.is_set() or not store.complete_claimed_job(claim, status=JobStatus.SUCCEEDED):
        store.abandon_claimed_job_for_recovery(claim, finding_code="JOB_LEASE_LOST")
        print("operator-worker: RECOVERY_REQUIRED JOB_LEASE_LOST")
        return 2
    print("operator-worker: SUCCEEDED")
    return 0
