"""Command-line interface for safe FolioTone analysis workflows."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from foliotone import __version__
from foliotone.core import FileChangeState, MediaType
from foliotone.index import (
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import create_sqlite_engine, migrate

_MEDIA_TYPES = {
    "ebook": MediaType.EBOOK,
    "music": MediaType.MUSIC,
    "unknown": MediaType.UNKNOWN,
}
_HASH_MODES = {
    "none": HashMode.NONE,
    "quick": HashMode.QUICK,
    "full": HashMode.FULL,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="foliotone",
        description=(
            "Orchestrate specialist tools to analyze and reconcile e-book and music collections."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show the current implementation status.")

    scan = subparsers.add_parser(
        "scan",
        help="Run a read-only incremental filesystem scan for one logical source root.",
    )
    scan.add_argument("--name", required=True, help="Stable logical ScanRoot name.")
    scan.add_argument("--path", required=True, type=Path, help="Runtime path to scan read-only.")
    scan.add_argument(
        "--media-type",
        required=True,
        choices=tuple(_MEDIA_TYPES),
        help="Media family represented by the logical ScanRoot.",
    )
    scan.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    scan.add_argument(
        "--hash",
        dest="hash_mode",
        choices=tuple(_HASH_MODES),
        default="quick",
        help="Hashing level for new/modified/reappeared files.",
    )
    scan.add_argument(
        "--suffix",
        action="append",
        default=None,
        help="Optional file suffix filter; may be repeated, for example --suffix epub.",
    )
    scan.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="Maximum discovery batch size; must be between 1 and 500.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the FolioTone CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print(
            "FolioTone W2: incremental indexing and read-only ToolProvider runtime "
            "are in progress."
        )
        print("A read-only scan CLI is available for controlled smoke tests.")
        print("Source-media and external-tool mutation commands are not implemented.")
        return 0

    if args.command == "scan":
        return _run_scan(args)

    parser.print_help()
    return 0


def _run_scan(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    media_type = _MEDIA_TYPES[args.media_type]
    root = store.get_or_create_root(args.name, media_type)
    hash_mode = _HASH_MODES[args.hash_mode]
    fingerprint_writer = None if hash_mode is HashMode.NONE else FingerprintWriter(engine)
    scanner = IncrementalScanner(
        store,
        batch_size=args.batch_size,
        hash_mode=hash_mode,
        fingerprint_writer=fingerprint_writer,
    )
    suffixes = None if args.suffix is None else frozenset(args.suffix)
    summary = scanner.scan(root, ScanRootBinding(args.path, include_suffixes=suffixes))

    print(f"ScanRoot: {root.name}")
    print(f"ScanRun: {summary.run.id}")
    print(f"Status: {summary.run.status.value}")
    print(f"Observed files: {summary.observed_files}")
    for state in FileChangeState:
        count = summary.counts.get(state, 0)
        if count:
            print(f"{state.value}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
