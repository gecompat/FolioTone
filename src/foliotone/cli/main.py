"""Command-line interface for safe FolioTone analysis workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from foliotone import __version__
from foliotone.adapters.calibre import (
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    CalibreTextAnalyzer,
    CalibreTextError,
)
from foliotone.adapters.epubcheck import EpubCheckAnalyzer, EpubCheckError
from foliotone.adapters.poppler import PopplerPdfAnalyzer, PopplerPdfError
from foliotone.core import (
    EntityId,
    FileChangeState,
    FileObservation,
    MediaType,
    RelocationCandidateKind,
    ToolExecutionStatus,
)
from foliotone.index import (
    DeletionConfirmationPolicy,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    RelocationCandidateDetector,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.tooling.runtime import ToolRuntime

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
    scan.add_argument(
        "--resume-run",
        type=EntityId.parse,
        default=None,
        help="Resume from a persisted INTERRUPTED ScanRun ID for the same logical ScanRoot.",
    )
    scan.add_argument(
        "--confirm-deleted-after-missing-scans",
        type=int,
        default=None,
        help=(
            "Opt in to DELETED confirmation after at least this many consecutive successful "
            "MISSING scans; minimum 2. Disabled when omitted."
        ),
    )
    scan.add_argument(
        "--confirm-deleted-after-hours",
        type=float,
        default=None,
        help=(
            "Minimum elapsed MISSING age before DELETED confirmation. Requires "
            "--confirm-deleted-after-missing-scans; defaults to 24 hours when enabled."
        ),
    )

    ebook_metadata = subparsers.add_parser(
        "ebook-metadata",
        help="Extract raw e-book metadata and versioned candidates with calibre ebook-meta.",
    )
    ebook_metadata.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the already recorded file observation.",
    )
    ebook_metadata.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted FileObservation ID to analyze.",
    )
    ebook_metadata.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_metadata.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_metadata.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_metadata.add_argument(
        "--ebook-meta-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
        help="ebook-meta executable or absolute executable path.",
    )

    ebook_text = subparsers.add_parser(
        "ebook-text",
        help=(
            "Extract EPUB/MOBI/AZW/AZW3 text read-only and calculate a normalized "
            "SHA-256 fingerprint."
        ),
    )
    ebook_text.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the recorded e-book observation.",
    )
    ebook_text.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted EPUB/MOBI/AZW/AZW3 FileObservation ID to analyze.",
    )
    ebook_text.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_text.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_text.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_text.add_argument(
        "--ebook-convert-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_CONVERT", "ebook-convert"),
        help="ebook-convert executable or absolute executable path.",
    )

    pdf_analyze = subparsers.add_parser(
        "pdf-analyze",
        help="Analyze PDF metadata, page count, and text read-only with Poppler.",
    )
    pdf_analyze.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the already recorded PDF observation.",
    )
    pdf_analyze.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted PDF FileObservation ID to analyze.",
    )
    pdf_analyze.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    pdf_analyze.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    pdf_analyze.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    pdf_analyze.add_argument(
        "--pdfinfo-executable",
        default=os.environ.get("FOLIOTONE_PDFINFO", "pdfinfo"),
        help="pdfinfo executable or absolute executable path.",
    )
    pdf_analyze.add_argument(
        "--pdftotext-executable",
        default=os.environ.get("FOLIOTONE_PDFTOTEXT", "pdftotext"),
        help="pdftotext executable or absolute executable path.",
    )

    epub_validate = subparsers.add_parser(
        "epub-validate",
        help="Validate one recorded EPUB structurally read-only with EPUBCheck.",
    )
    epub_validate.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the already recorded EPUB observation.",
    )
    epub_validate.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted EPUB FileObservation ID to validate.",
    )
    epub_validate.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    epub_validate.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    epub_validate.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    epub_validate.add_argument(
        "--java-executable",
        default=os.environ.get("FOLIOTONE_JAVA", "java"),
        help="Java executable or absolute executable path.",
    )
    epub_validate.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")),
        help="EPUBCheck JAR path; defaults to epubcheck.jar.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the FolioTone CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print("FolioTone W2 foundation is complete; W3 e-book analysis is in progress.")
        print("The initial product surface is CLI-only.")
        print("A read-only scan CLI is available for controlled smoke tests.")
        print(
            "Read-only calibre metadata observations and versioned candidates are available "
            "through ebook-metadata."
        )
        print(
            "Read-only EPUB/MOBI/AZW/AZW3 text fingerprints are available through "
            "ebook-text."
        )
        print("Read-only PDF metadata and text analysis is available through pdf-analyze.")
        print("Read-only EPUB conformance evidence is available through epub-validate.")
        print("Source-media and external-tool mutation commands are not implemented.")
        return 0

    if args.command == "scan":
        deletion_policy = _deletion_policy(parser, args)
        return _run_scan(args, deletion_policy)

    if args.command == "ebook-metadata":
        return _run_ebook_metadata(args)

    if args.command == "ebook-text":
        return _run_ebook_text(args)

    if args.command == "pdf-analyze":
        return _run_pdf_analyze(args)

    if args.command == "epub-validate":
        return _run_epub_validate(args)

    parser.print_help()
    return 0


def _deletion_policy(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> DeletionConfirmationPolicy | None:
    missing_scans = args.confirm_deleted_after_missing_scans
    missing_hours = args.confirm_deleted_after_hours
    if missing_scans is None:
        if missing_hours is not None:
            parser.error(
                "--confirm-deleted-after-hours requires "
                "--confirm-deleted-after-missing-scans"
            )
        return None

    hours = 24.0 if missing_hours is None else missing_hours
    if hours <= 0:
        parser.error("--confirm-deleted-after-hours must be greater than zero")
    try:
        return DeletionConfirmationPolicy(
            min_consecutive_missing_scans=missing_scans,
            min_missing_age=timedelta(hours=hours),
        )
    except ValueError as exc:
        parser.error(str(exc))


def _run_scan(
    args: argparse.Namespace,
    deletion_policy: DeletionConfirmationPolicy | None,
) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    media_type = _MEDIA_TYPES[args.media_type]
    root = store.get_or_create_root(args.name, media_type)
    resume_from = (
        None if args.resume_run is None else store.get_resumable_run(root, args.resume_run)
    )
    hash_mode = _HASH_MODES[args.hash_mode]
    fingerprint_writer = None if hash_mode is HashMode.NONE else FingerprintWriter(engine)
    relocation_detector = (
        None if hash_mode is HashMode.NONE else RelocationCandidateDetector(engine)
    )
    scanner = IncrementalScanner(
        store,
        batch_size=args.batch_size,
        hash_mode=hash_mode,
        fingerprint_writer=fingerprint_writer,
        deletion_policy=deletion_policy,
        relocation_detector=relocation_detector,
    )
    suffixes = None if args.suffix is None else frozenset(args.suffix)
    summary = scanner.scan(
        root,
        ScanRootBinding(args.path, include_suffixes=suffixes),
        resume_from=resume_from,
    )

    print(f"ScanRoot: {root.name}")
    print(f"ScanRun: {summary.run.id}")
    if summary.run.resumed_from_run_id is not None:
        print(f"Resumed from: {summary.run.resumed_from_run_id}")
    print(f"Status: {summary.run.status.value}")
    print(f"Observed files: {summary.observed_files}")
    for state in FileChangeState:
        count = summary.counts.get(state, 0)
        if count:
            print(f"{state.value}: {count}")
    if summary.relocation_candidates:
        print(f"Relocation candidates: {len(summary.relocation_candidates)}")
        candidate_counts = Counter(candidate.kind for candidate in summary.relocation_candidates)
        for kind in RelocationCandidateKind:
            count = candidate_counts.get(kind, 0)
            if count:
                print(f"{kind.value}_CANDIDATE: {count}")
    return 0


def _run_ebook_metadata(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("Metadata analysis failed: FileObservation does not exist.")
        return 2

    runtime = ToolRuntime(
        engine,
        args.artifact_root,
        work_root=args.work_root,
    )
    try:
        analyzer = CalibreMetadataAnalyzer(
            engine,
            runtime,
            executable=args.ebook_meta_executable,
        )
        outcome = analyzer.analyze(args.root, observation)
    except (CalibreMetadataError, ValueError) as error:
        print(f"Metadata analysis failed: {error}")
        return 1

    execution = outcome.run.execution
    print(f"ToolExecution: {execution.id}")
    print(f"Status: {execution.status.value}")
    print(f"Tool version: {json.dumps(execution.tool_version, ensure_ascii=False)}")
    if execution.error_summary is not None:
        print(f"Error: {json.dumps(execution.error_summary, ensure_ascii=False)}")
    print(f"Metadata observations: {len(outcome.results)}")
    for result in outcome.results:
        print(f"{result.key}: {json.dumps(result.value, ensure_ascii=False)}")
    print(f"Metadata candidates: {len(outcome.candidates)}")
    for candidate in outcome.candidates:
        print(f"candidate {candidate.key}: {json.dumps(candidate.value, ensure_ascii=False)}")
    return 0 if execution.status is ToolExecutionStatus.SUCCEEDED else 1


def _run_ebook_text(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("Text analysis failed: FileObservation does not exist.")
        return 2

    runtime = ToolRuntime(
        engine,
        args.artifact_root,
        work_root=args.work_root,
    )
    try:
        analyzer = CalibreTextAnalyzer(
            engine,
            runtime,
            executable=args.ebook_convert_executable,
        )
        outcome = analyzer.analyze(args.root, observation)
    except (CalibreTextError, ValueError) as error:
        print(f"Text analysis failed: {error}")
        return 1

    execution = outcome.run.execution
    print(f"ToolExecution: {execution.id}")
    print(f"Status: {execution.status.value}")
    print(f"Tool version: {json.dumps(execution.tool_version, ensure_ascii=False)}")
    if execution.error_summary is not None:
        print(f"Error: {json.dumps(execution.error_summary, ensure_ascii=False)}")
    for result in outcome.results:
        print(f"{result.key}: {result.value}")
    if outcome.fingerprint is not None:
        print(f"Normalized text fingerprint: {outcome.fingerprint.value}")
    return 0 if execution.status is ToolExecutionStatus.SUCCEEDED else 1


def _run_pdf_analyze(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("PDF analysis failed: FileObservation does not exist.")
        return 2

    runtime = ToolRuntime(
        engine,
        args.artifact_root,
        work_root=args.work_root,
    )
    try:
        analyzer = PopplerPdfAnalyzer(
            engine,
            runtime,
            pdfinfo_executable=args.pdfinfo_executable,
            pdftotext_executable=args.pdftotext_executable,
        )
        outcome = analyzer.analyze(args.root, observation)
    except (PopplerPdfError, ValueError) as error:
        print(f"PDF analysis failed: {error}")
        return 1

    for label, run in (("pdfinfo", outcome.info_run), ("pdftotext", outcome.text_run)):
        execution = run.execution
        print(f"{label} ToolExecution: {execution.id}")
        print(f"{label} status: {execution.status.value}")
        print(
            f"{label} version: "
            f"{json.dumps(execution.tool_version, ensure_ascii=False)}"
        )
        if execution.error_summary is not None:
            print(
                f"{label} error: "
                f"{json.dumps(execution.error_summary, ensure_ascii=False)}"
            )

    print(f"PDF metadata observations: {len(outcome.metadata_results)}")
    for result in outcome.metadata_results:
        print(f"{result.key}: {json.dumps(result.value, ensure_ascii=False)}")
    for result in outcome.text_results:
        print(f"{result.key}: {result.value}")
    if outcome.fingerprint is not None:
        print(f"Normalized text fingerprint: {outcome.fingerprint.value}")

    succeeded = (
        outcome.info_run.execution.status is ToolExecutionStatus.SUCCEEDED
        and outcome.text_run.execution.status is ToolExecutionStatus.SUCCEEDED
    )
    return 0 if succeeded else 1


def _run_epub_validate(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("EPUB validation failed: FileObservation does not exist.")
        return 2

    runtime = ToolRuntime(
        engine,
        args.artifact_root,
        work_root=args.work_root,
    )
    try:
        analyzer = EpubCheckAnalyzer(
            engine,
            runtime,
            java_executable=args.java_executable,
            epubcheck_jar=args.epubcheck_jar,
        )
        outcome = analyzer.analyze(args.root, observation)
    except (EpubCheckError, ValueError) as error:
        print(f"EPUB validation failed: {error}")
        return 1

    execution = outcome.run.execution
    print(f"ToolExecution: {execution.id}")
    print(f"Status: {execution.status.value}")
    print(f"Tool version: {json.dumps(execution.tool_version, ensure_ascii=False)}")
    if execution.error_summary is not None:
        print(f"Error: {json.dumps(execution.error_summary, ensure_ascii=False)}")
    if outcome.conformance_status is not None:
        print(f"Conformance: {outcome.conformance_status}")
    for result in outcome.results:
        if result.key != "conformance_status":
            print(f"{result.key}: {result.value}")
    return 0 if execution.status is ToolExecutionStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
