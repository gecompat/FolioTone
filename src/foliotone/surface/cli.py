"""Owner-local CLI adapters for the local-single-operator runtime roles."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import uvicorn

from foliotone.persistence.sqlite import create_sqlite_engine, migrate
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import ProcessRole, SurfaceRuntimeConfig
from foliotone.surface.service import LocalSurfaceService


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
    app = create_surface_app(_service(args.database), config=config)
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
    """Expose a process role that intentionally owns no W10 capability in this wave."""
    migrate(args.database)
    print("operator-worker: IDLE_NO_REGISTERED_CAPABILITY")
    return 0
