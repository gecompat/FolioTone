"""Command-line interface for safe FolioTone analysis workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Engine

from foliotone import __version__
from foliotone.adapters.calibre import (
    CalibreCoverAnalyzer,
    CalibreCoverError,
    CalibreMetadataAnalyzer,
    CalibreMetadataError,
    CalibreTextAnalyzer,
    CalibreTextError,
)
from foliotone.adapters.epubcheck import EpubCheckAnalyzer, EpubCheckError
from foliotone.adapters.poppler import PopplerPdfAnalyzer, PopplerPdfError
from foliotone.core import (
    MAX_EBOOK_COLLECTION_WORKERS,
    EbookCollectionRunStatus,
    EntityId,
    FileChangeState,
    FileObservation,
    MediaType,
    RelocationCandidateKind,
    ScanRoot,
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
from foliotone.persistence import (
    EbookCollectionStoreError,
    SQLiteEbookCollectionStore,
    create_sqlite_engine,
    migrate,
    repository,
)
from foliotone.tooling.runtime import ToolRuntime
from foliotone.workflows import (
    EbookAnalysisError,
    EbookAnalysisOrchestrator,
    EbookAnalysisReuseService,
    EbookAnalysisStatus,
    EbookAnalysisTools,
    EbookCollectionError,
    EbookCollectionInterrupted,
    EbookCollectionService,
    EbookComparisonError,
    EbookComparisonService,
    ebook_analysis_format,
)

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

    ebook_cover = subparsers.add_parser(
        "ebook-cover",
        help=(
            "Extract an embedded EPUB/MOBI/AZW/AZW3 cover read-only and calculate "
            "a perceptual dHash fingerprint."
        ),
    )
    ebook_cover.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the recorded e-book observation.",
    )
    ebook_cover.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted EPUB/MOBI/AZW/AZW3 FileObservation ID to analyze.",
    )
    ebook_cover.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_cover.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_cover.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_cover.add_argument(
        "--calibre-debug-executable",
        default=os.environ.get("FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"),
        help="calibre-debug executable or absolute executable path.",
    )

    ebook_analyze = subparsers.add_parser(
        "ebook-analyze",
        help=(
            "Run every applicable read-only analyzer for one recorded EPUB, MOBI, "
            "AZW, AZW3, or PDF observation."
        ),
    )
    ebook_analyze.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root containing the recorded e-book observation.",
    )
    ebook_analyze.add_argument(
        "--observation-id",
        required=True,
        type=EntityId.parse,
        help="Persisted EPUB/MOBI/AZW/AZW3/PDF FileObservation ID to analyze.",
    )
    ebook_analyze.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Bypass exact successful evidence reuse and execute every applicable "
            "analyzer step."
        ),
    )
    ebook_analyze.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_analyze.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_analyze.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_analyze.add_argument(
        "--ebook-meta-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
        help="ebook-meta executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--ebook-convert-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_CONVERT", "ebook-convert"),
        help="ebook-convert executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--calibre-debug-executable",
        default=os.environ.get("FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"),
        help="calibre-debug executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--pdfinfo-executable",
        default=os.environ.get("FOLIOTONE_PDFINFO", "pdfinfo"),
        help="pdfinfo executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--pdftotext-executable",
        default=os.environ.get("FOLIOTONE_PDFTOTEXT", "pdftotext"),
        help="pdftotext executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--java-executable",
        default=os.environ.get("FOLIOTONE_JAVA", "java"),
        help="Java executable or absolute executable path.",
    )
    ebook_analyze.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")),
        help="EPUBCheck JAR path; defaults to epubcheck.jar.",
    )

    ebook_collection = subparsers.add_parser(
        "ebook-collection-analyze",
        help=(
            "Analyze a stable completed e-book scan in bounded, resumable, "
            "read-only batches."
        ),
    )
    ebook_collection.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root for the persisted e-book observations.",
    )
    ebook_collection.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name whose latest scan defines the plan.",
    )
    ebook_collection.add_argument(
        "--resume-run",
        type=EntityId.parse,
        default=None,
        help="Resume an interrupted collection run without replanning its snapshot.",
    )
    ebook_collection.add_argument(
        "--fresh",
        action="store_true",
        help="Bypass exact successful evidence reuse for a newly planned run.",
    )
    ebook_collection.add_argument(
        "--workers",
        type=int,
        choices=range(1, MAX_EBOOK_COLLECTION_WORKERS + 1),
        default=None,
        metavar=f"1..{MAX_EBOOK_COLLECTION_WORKERS}",
        help=(
            "Bounded analyzer worker count for a new run; defaults to 1 and is "
            "preserved on resume."
        ),
    )
    ebook_collection.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Process at most this many planned observations in this invocation.",
    )
    ebook_collection.add_argument(
        "--plan-limit",
        type=int,
        default=None,
        help="New runs only: deterministically plan at most this many observations.",
    )
    ebook_collection.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_collection.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_collection.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_collection.add_argument(
        "--ebook-meta-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
        help="ebook-meta executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--ebook-convert-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_CONVERT", "ebook-convert"),
        help="ebook-convert executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--calibre-debug-executable",
        default=os.environ.get("FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"),
        help="calibre-debug executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--pdfinfo-executable",
        default=os.environ.get("FOLIOTONE_PDFINFO", "pdfinfo"),
        help="pdfinfo executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--pdftotext-executable",
        default=os.environ.get("FOLIOTONE_PDFTOTEXT", "pdftotext"),
        help="pdftotext executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--java-executable",
        default=os.environ.get("FOLIOTONE_JAVA", "java"),
        help="Java executable or absolute executable path.",
    )
    ebook_collection.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")),
        help="EPUBCheck JAR path; defaults to epubcheck.jar.",
    )

    ebook_compare = subparsers.add_parser(
        "ebook-compare",
        help=(
            "Compare persisted file, text, metadata, structure, and cover Evidence "
            "for two recorded e-book observations."
        ),
    )
    ebook_compare.add_argument(
        "--left-observation-id",
        required=True,
        type=EntityId.parse,
        help="First persisted EPUB/MOBI/AZW/AZW3/PDF FileObservation ID.",
    )
    ebook_compare.add_argument(
        "--right-observation-id",
        required=True,
        type=EntityId.parse,
        help="Second persisted EPUB/MOBI/AZW/AZW3/PDF FileObservation ID.",
    )
    ebook_compare.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
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
        print(
            "Read-only embedded-cover facts and perceptual fingerprints are available "
            "through ebook-cover."
        )
        print(
            "Unified format-aware read-only e-book orchestration is available through "
            "ebook-analyze."
        )
        print(
            "Versioned multi-dimensional e-book quality findings are available through "
            "ebook-analyze."
        )
        print(
            "Provider-neutral persisted e-book Evidence comparison is available through "
            "ebook-compare."
        )
        print(
            "Bounded resumable e-book collection analysis is available through "
            "ebook-collection-analyze."
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

    if args.command == "ebook-cover":
        return _run_ebook_cover(args)

    if args.command == "ebook-analyze":
        return _run_ebook_analyze(args)

    if args.command == "ebook-collection-analyze":
        return _run_ebook_collection_analyze(args)

    if args.command == "ebook-compare":
        return _run_ebook_compare(args)

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


def _run_ebook_analyze(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("E-book analysis failed: FileObservation does not exist.")
        return 2

    try:
        ebook_analysis_format(observation.relative_path)
        runtime = ToolRuntime(
            engine,
            args.artifact_root,
            work_root=args.work_root,
        )
        outcome = _ebook_analysis_orchestrator(engine, runtime, args).analyze(
            args.root,
            observation,
            fresh=args.fresh,
        )
    except (EbookAnalysisError, ValueError) as error:
        print(f"E-book analysis failed: {error}")
        return 1

    print(f"FileObservation: {outcome.observation_id}")
    print(f"Format: {outcome.format_name}")
    print(f"Analysis profile: {outcome.profile}")
    print(f"Evidence policy: {'FRESH' if args.fresh else 'REUSE_EXACT'}")
    for step in outcome.steps:
        print(f"{step.name} status: {step.state.value}")
        print(f"{step.name} evidence action: {step.disposition.value}")
        if step.error is not None:
            print(
                f"{step.name} adapter error: "
                f"{json.dumps(step.error, ensure_ascii=False)}"
            )
        for index, execution in enumerate(step.executions, start=1):
            label = step.name if len(step.executions) == 1 else f"{step.name}.{index}"
            print(f"{label} ToolExecution: {execution.id}")
            print(f"{label} execution status: {execution.status.value}")
            print(
                f"{label} tool version: "
                f"{json.dumps(execution.tool_version, ensure_ascii=False)}"
            )
            if execution.error_summary is not None:
                print(
                    f"{label} execution error: "
                    f"{json.dumps(execution.error_summary, ensure_ascii=False)}"
                )
        for key, value in step.facts:
            print(f"{step.name}.{key}: {json.dumps(value, ensure_ascii=False)}")
    print(f"Quality profile: {outcome.quality.profile}")
    print(f"Quality status: {outcome.quality.status.value}")
    for dimension in outcome.quality.dimensions:
        print(f"Quality dimension {dimension.name.value}: {dimension.status.value}")
    print(f"Quality findings: {len(outcome.quality.findings)}")
    for finding in outcome.quality.findings:
        sources = ",".join(map(str, finding.source_execution_ids)) or "none"
        print(
            f"Quality finding {finding.code}: severity={finding.severity.value}; "
            f"dimension={finding.dimension.value}; ToolExecutions={sources}"
        )
    print(f"Overall status: {outcome.status.value}")
    return 0 if outcome.status is EbookAnalysisStatus.SUCCEEDED else 1


def _run_ebook_collection_analyze(args: argparse.Namespace) -> int:
    if not args.root.is_dir():
        print("E-book collection analysis failed: source root is unavailable.")
        return 2
    try:
        _validate_collection_storage_paths(
            args.root,
            args.database,
            args.artifact_root,
            args.work_root,
        )
    except ValueError as error:
        print(f"E-book collection analysis failed: {error}")
        return 2

    if args.resume_run is not None and (
        args.fresh or args.workers is not None or args.plan_limit is not None
    ):
        print(
            "E-book collection analysis failed: --fresh, --workers, and --plan-limit "
            "cannot change a resumed run."
        )
        return 2

    database: Path = args.database
    try:
        migrate(database)
        engine = create_sqlite_engine(database)
        roots = tuple(
            root
            for root in repository(engine, ScanRoot).list_all()
            if root.name == args.scan_root.strip()
        )
        if len(roots) != 1:
            print(
                "E-book collection analysis failed: logical ScanRoot does not exist."
            )
            return 2
        root = roots[0]
        if root.media_type is not MediaType.EBOOK or not root.enabled:
            print(
                "E-book collection analysis failed: ScanRoot must be an enabled "
                "EBOOK root."
            )
            return 2

        store = SQLiteEbookCollectionStore(engine)
        if args.resume_run is not None:
            persisted = store.get_run(args.resume_run)
            if persisted is None or persisted.scan_root_id != root.id:
                print(
                    "E-book collection analysis failed: resume run does not belong "
                    "to the requested ScanRoot."
                )
                return 2

        runtime = ToolRuntime(
            engine,
            args.artifact_root,
            work_root=args.work_root,
            cache_local_probes=True,
        )
        orchestrator = _ebook_analysis_orchestrator(engine, runtime, args)
        service = EbookCollectionService(
            store,
            lambda observation, fresh: orchestrator.analyze(
                args.root,
                observation,
                fresh=fresh,
            ),
        )
        if args.resume_run is None:
            outcome = service.start(
                root.id,
                fresh=args.fresh,
                worker_count=args.workers or 1,
                max_items=args.max_items,
                plan_limit=args.plan_limit,
            )
        else:
            outcome = service.resume(
                args.resume_run,
                max_items=args.max_items,
            )
    except EbookCollectionInterrupted as error:
        print(f"E-book collection run: {error.run_id}")
        print("Status: INTERRUPTED")
        print("Resume is safe with --resume-run and the same logical ScanRoot.")
        return 130
    except (EbookCollectionError, EbookCollectionStoreError, ValueError) as error:
        print(f"E-book collection analysis failed: {error}")
        if isinstance(error, EbookCollectionError) and error.run_id is not None:
            print(f"E-book collection run: {error.run_id}")
        return 2
    except OSError:
        print("E-book collection analysis failed: runtime storage is unavailable.")
        return 2
    except KeyboardInterrupt:
        print("E-book collection analysis interrupted before a run was acquired.")
        return 130
    except Exception:
        print("E-book collection analysis failed: internal persistence error.")
        return 2

    print(f"ScanRoot: {root.name}")
    print(f"E-book collection run: {outcome.run.id}")
    print(f"Source ScanRun: {outcome.run.source_scan_run_id}")
    print(f"Collection profile: {outcome.profile}")
    print(f"Analysis profile: {outcome.run.analysis_profile}")
    print(f"Evidence policy: {'FRESH' if outcome.run.fresh else 'REUSE_EXACT'}")
    print(f"Workers: {outcome.run.worker_count}")
    print(f"Processed this invocation: {outcome.processed_this_invocation}")
    print(f"Planned: {outcome.counts.planned}")
    print(f"Pending: {outcome.counts.pending}")
    print(f"Succeeded: {outcome.counts.succeeded}")
    print(f"Partial failures: {outcome.counts.partial_failure}")
    print(f"Failed: {outcome.counts.failed}")
    print(f"Errors: {outcome.counts.error}")
    print(f"Reused steps: {outcome.counts.reused_steps}")
    print(f"Executed steps: {outcome.counts.executed_steps}")
    print(f"Quality findings: {outcome.counts.findings}")
    print(f"Status: {outcome.run.status.value}")
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED:
        return 0
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED_WITH_FAILURES:
        return 1
    if outcome.run.status is EbookCollectionRunStatus.INTERRUPTED:
        return 3
    return 2


def _ebook_analysis_orchestrator(
    engine: Engine,
    runtime: ToolRuntime,
    args: argparse.Namespace,
) -> EbookAnalysisOrchestrator:
    reuse = EbookAnalysisReuseService(engine, runtime)
    metadata_analyzer = CalibreMetadataAnalyzer(
        engine,
        runtime,
        executable=args.ebook_meta_executable,
    )
    text_analyzer = CalibreTextAnalyzer(
        engine,
        runtime,
        executable=args.ebook_convert_executable,
    )
    cover_analyzer = CalibreCoverAnalyzer(
        engine,
        runtime,
        executable=args.calibre_debug_executable,
    )
    validation_analyzer = EpubCheckAnalyzer(
        engine,
        runtime,
        java_executable=args.java_executable,
        epubcheck_jar=args.epubcheck_jar,
    )
    pdf_analyzer = PopplerPdfAnalyzer(
        engine,
        runtime,
        pdfinfo_executable=args.pdfinfo_executable,
        pdftotext_executable=args.pdftotext_executable,
    )
    return EbookAnalysisOrchestrator(
        EbookAnalysisTools(
            metadata=metadata_analyzer.analyze,
            text=text_analyzer.analyze,
            cover=cover_analyzer.analyze,
            validation=validation_analyzer.analyze,
            pdf=pdf_analyzer.analyze,
            metadata_reuse=lambda _root, current: reuse.metadata(
                metadata_analyzer.reuse_request(current),
                current,
            ),
            text_reuse=lambda _root, current: reuse.text(
                text_analyzer.reuse_request(current),
                current,
            ),
            cover_reuse=lambda _root, current: reuse.cover(
                cover_analyzer.reuse_request(current),
                current,
            ),
            validation_reuse=lambda _root, current: reuse.validation(
                validation_analyzer.reuse_request(current),
                current,
            ),
            pdf_reuse=lambda _root, current: reuse.pdf(
                pdf_analyzer.reuse_requests(current),
                current,
            ),
        )
    )


def _validate_collection_storage_paths(
    source_root: Path,
    database: Path,
    artifact_root: Path,
    work_root: Path,
) -> None:
    source = source_root.resolve()
    for destination in (database, artifact_root, work_root):
        if destination.resolve().is_relative_to(source):
            raise ValueError("database, artifact, and work paths must be outside source root")


def _run_ebook_compare(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    try:
        outcome = EbookComparisonService(engine).compare(
            args.left_observation_id,
            args.right_observation_id,
        )
    except (EbookComparisonError, ValueError) as error:
        print(f"E-book comparison failed: {error}")
        return 1

    print(f"Left FileObservation: {outcome.left_observation_id}")
    print(f"Right FileObservation: {outcome.right_observation_id}")
    print(f"Left format: {outcome.left_format}")
    print(f"Right format: {outcome.right_format}")
    print(f"Comparison profile: {outcome.profile}")
    print(f"Comparison status: {outcome.status.value}")
    for dimension in outcome.dimensions:
        label = dimension.name.value
        print(f"Comparison dimension {label}: {dimension.state.value}")
        print(f"Comparison coverage {label}: {dimension.coverage.value}")
        print(f"Comparison {label} left Evidence count: {len(dimension.left_evidence_ids)}")
        print(f"Comparison {label} right Evidence count: {len(dimension.right_evidence_ids)}")
        for execution_id in dimension.source_execution_ids:
            print(f"Comparison {label} ToolExecution: {execution_id}")
        for key, value in dimension.facts:
            print(f"Comparison {label}.{key}: {json.dumps(value, ensure_ascii=False)}")
    print("Identity verdict: NOT_PRODUCED")
    print("Relation records written: 0")
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


def _run_ebook_cover(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("Cover analysis failed: FileObservation does not exist.")
        return 2

    runtime = ToolRuntime(
        engine,
        args.artifact_root,
        work_root=args.work_root,
    )
    try:
        analyzer = CalibreCoverAnalyzer(
            engine,
            runtime,
            executable=args.calibre_debug_executable,
        )
        outcome = analyzer.analyze(args.root, observation)
    except (CalibreCoverError, ValueError) as error:
        print(f"Cover analysis failed: {error}")
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
        print(f"Cover perceptual fingerprint: {outcome.fingerprint.value}")
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
