"""Owner-local CLI adapters for the local-single-operator runtime roles."""

from __future__ import annotations

import argparse
import getpass
import hmac
import secrets
import sys
import threading
from pathlib import Path

import uvicorn

from foliotone.application.contracts import EbookRenameOperatorJobProfile
from foliotone.core import EntityId
from foliotone.ebook_rename.dependency_scopes import EbookRenameDependencyScopeResolver
from foliotone.persistence.sqlite import create_sqlite_engine, migrate
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.persistence.surface_read import SQLiteEbookSurfaceReadModel
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import (
    JobStatus,
    ProcessRole,
    SurfaceRuntimeConfig,
)
from foliotone.surface.service import LocalSurfaceService
from foliotone.workflows.collection_state import SQLiteCollectionStateReportReader
from foliotone.workflows.collection_state_query import CollectionQueryService
from foliotone.workflows.ebook_rename_operation import (
    EbookRenameOperatorError,
    create_ebook_rename_operator_service,
)
from foliotone.workflows.ebook_rename_planning import EbookRenamePlanningService
from foliotone.workflows.library_health import SQLiteLibraryHealthReportReader


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
        if name == "analysis-worker":
            command.add_argument(
                "--once", action="store_true", help="Claim at most one read-only job."
            )


def _service(database: Path) -> LocalSurfaceService:
    migrate(database)
    return LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))


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
    """Start only an explicit loopback listener, never a wildcard listener."""
    config = SurfaceRuntimeConfig(bind_host=args.host, port=args.port)
    migrate(args.database)
    engine = create_sqlite_engine(args.database)
    surface_store = SQLiteSurfaceStore(engine)
    app = create_surface_app(
        LocalSurfaceService(surface_store),
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
    uvicorn.run(app, host=config.bind_host, port=config.port, proxy_headers=False, access_log=False)
    return 0


def run_analysis_worker(args: argparse.Namespace) -> int:
    """Claim at most read-only analysis jobs; job execution stays explicitly unregistered."""
    store = SQLiteSurfaceStore(create_sqlite_engine(args.database))
    migrate(args.database)
    claim = store.claim_next_job(ProcessRole.ANALYSIS_WORKER, "analysis-worker-local-lease")
    if claim is None:
        print("analysis-worker: IDLE")
        return 0
    print(f"analysis-worker: CLAIMED {claim.id} fence={claim.fence_epoch}")
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
