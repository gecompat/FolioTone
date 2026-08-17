"""Command-line interface for safe FolioTone analysis workflows."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

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
    FileRecord,
    MediaType,
    RelocationCandidateKind,
    ScanRoot,
    ScanRun,
    ToolExecutionStatus,
)
from foliotone.index import (
    MAX_DUPLICATE_HASH_BATCH_SIZE,
    MAX_DUPLICATE_HASH_WORKERS,
    MAX_SCAN_HASH_WORKERS,
    DeletionConfirmationPolicy,
    DuplicateHashCandidateError,
    DuplicateHashCandidateService,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    RelocationCandidateDetector,
    ScanLeaseError,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import (
    EbookCollectionReportStoreError,
    EbookCollectionStoreError,
    EbookInventoryReportStoreError,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteEbookCandidateHashRunStore,
    SQLiteEbookCollectionReportStore,
    SQLiteEbookCollectionStore,
    SQLiteEbookInventoryReportStore,
    SQLiteScanRootWriteLeaseStore,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    repository,
    scan_root_write_scope,
)
from foliotone.tooling.runtime import ToolRuntime
from foliotone.workflows import (
    DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
    DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
    DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT,
    EbookAnalysisError,
    EbookAnalysisOrchestrator,
    EbookAnalysisReuseService,
    EbookAnalysisStatus,
    EbookAnalysisTools,
    EbookCollectionError,
    EbookCollectionInterrupted,
    EbookCollectionOutcome,
    EbookCollectionReportError,
    EbookCollectionReportLimits,
    EbookCollectionReportService,
    EbookCollectionService,
    EbookComparisonError,
    EbookComparisonService,
    EbookInventoryReportError,
    EbookInventoryReportLimits,
    EbookInventoryReportService,
    PostscanCompletionVerifier,
    candidate_hash_status_payload,
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
        help=(
            "Required hashing level. Unchanged files reuse complete latest evidence "
            "and are opened only when that evidence is missing."
        ),
    )
    scan.add_argument(
        "--hash-workers",
        type=int,
        choices=range(1, MAX_SCAN_HASH_WORKERS + 1),
        default=1,
        metavar=f"1..{MAX_SCAN_HASH_WORKERS}",
        help=(
            "Bounded file-hash worker count; defaults to 1. Fingerprints are "
            "persisted atomically per discovery batch."
        ),
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
    resume_group = scan.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume-run",
        type=EntityId.parse,
        default=None,
        help="Resume from a persisted INTERRUPTED ScanRun ID for the same logical ScanRoot.",
    )
    resume_group.add_argument(
        "--resume-last-interrupted",
        action="store_true",
        help="Resume from the latest persisted INTERRUPTED ScanRun for the same ScanRoot.",
    )
    resume_group.add_argument(
        "--recover-stale-running",
        action="store_true",
        help=(
            "Atomically mark the latest unleased or expired RUNNING ScanRun as "
            "INTERRUPTED and resume it. Verify that its process is no longer active first."
        ),
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        help=("Bypass exact successful evidence reuse and execute every applicable analyzer step."),
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        help=("Analyze a stable completed e-book scan in bounded, resumable, read-only batches."),
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
    collection_resume_group = ebook_collection.add_mutually_exclusive_group()
    collection_resume_group.add_argument(
        "--resume-run",
        type=EntityId.parse,
        default=None,
        help="Resume an interrupted collection run without replanning its snapshot.",
    )
    collection_resume_group.add_argument(
        "--resume-last-interrupted",
        action="store_true",
        help="Resume the latest interrupted collection run.",
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
            "Bounded analyzer worker count for a new run; defaults to 1 and is preserved on resume."
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
        "--plan-per-format",
        type=int,
        default=None,
        help=(
            "New runs only: deterministically plan at most this many observations "
            "from each supported e-book format."
        ),
    )

    duplicate_hash = subparsers.add_parser(
        "ebook-hash-candidates",
        help=("Confirm quick duplicate candidates with bounded full SHA-256 hashing."),
    )
    duplicate_hash.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Runtime source root for the persisted e-book observations.",
    )
    duplicate_hash.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name whose latest scan defines candidates.",
    )
    duplicate_hash.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    duplicate_hash.add_argument(
        "--workers",
        type=int,
        choices=range(1, MAX_DUPLICATE_HASH_WORKERS + 1),
        default=1,
        metavar=f"1..{MAX_DUPLICATE_HASH_WORKERS}",
        help="Bounded full-hash worker count; defaults to 1.",
    )
    duplicate_hash.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help=(
            f"Atomic fingerprint batch size; must be between 1 and {MAX_DUPLICATE_HASH_BATCH_SIZE}."
        ),
    )
    duplicate_hash.add_argument(
        "--max-items",
        type=int,
        default=None,
        help=("Attempt at most this many pending candidates; rerun the same command to continue."),
    )
    duplicate_hash_status = subparsers.add_parser(
        "ebook-hash-status",
        help="Read the latest path-free candidate-hash heartbeat and progress.",
    )
    duplicate_hash_status.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name to inspect.",
    )
    duplicate_hash_status.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; defaults to /data/foliotone.db.",
    )
    duplicate_hash_status.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    ebook_collection_maintain = subparsers.add_parser(
        "ebook-collection-maintain",
        help=(
            "Run resumable collection analysis and optional duplicate hashing and "
            "inventory reporting against one EBOOK ScanRoot."
        ),
    )
    ebook_collection_maintain.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Source root used for collection analysis and duplicate hashing.",
    )
    ebook_collection_maintain.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name.",
    )
    maintain_resume_group = ebook_collection_maintain.add_mutually_exclusive_group()
    maintain_resume_group.add_argument(
        "--resume-run",
        type=EntityId.parse,
        default=None,
        help="Resume an interrupted collection run without replanning its snapshot.",
    )
    maintain_resume_group.add_argument(
        "--resume-last-interrupted",
        action="store_true",
        help="Resume the latest interrupted collection run for this ScanRoot.",
    )
    ebook_collection_maintain.add_argument(
        "--fresh",
        action="store_true",
        help="Bypass exact successful evidence reuse for a newly planned run.",
    )
    ebook_collection_maintain.add_argument(
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
    ebook_collection_maintain.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Process at most this many planned observations.",
    )
    ebook_collection_maintain.add_argument(
        "--plan-limit",
        type=int,
        default=None,
        help="New runs only: deterministically plan at most this many observations.",
    )
    ebook_collection_maintain.add_argument(
        "--plan-per-format",
        type=int,
        default=None,
        help=(
            "New runs only: deterministically plan at most this many observations "
            "from each supported format."
        ),
    )
    ebook_collection_maintain.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_collection_maintain.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")
        ),
        help="Durable private tool-artifact root; defaults to /data/tool-artifacts.",
    )
    ebook_collection_maintain.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_TOOL_WORK_ROOT", "/tmp/foliotone-tools")),
        help="Ephemeral isolated tool-work root; defaults to /tmp/foliotone-tools.",
    )
    ebook_collection_maintain.add_argument(
        "--ebook-meta-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
        help="ebook-meta executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--ebook-convert-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_CONVERT", "ebook-convert"),
        help="ebook-convert executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--calibre-debug-executable",
        default=os.environ.get("FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"),
        help="calibre-debug executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--pdfinfo-executable",
        default=os.environ.get("FOLIOTONE_PDFINFO", "pdfinfo"),
        help="pdfinfo executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--pdftotext-executable",
        default=os.environ.get("FOLIOTONE_PDFTOTEXT", "pdftotext"),
        help="pdftotext executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--java-executable",
        default=os.environ.get("FOLIOTONE_JAVA", "java"),
        help="Java executable or absolute executable path.",
    )
    ebook_collection_maintain.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")),
        help="EPUBCheck JAR path; defaults to epubcheck.jar.",
    )
    ebook_collection_maintain.add_argument(
        "--run-hash-candidates",
        action="store_true",
        help="Run bounded full-SHA duplicate-hash candidates after collection analysis.",
    )
    ebook_collection_maintain.add_argument(
        "--hash-workers",
        type=int,
        choices=range(1, MAX_DUPLICATE_HASH_WORKERS + 1),
        default=1,
        metavar=f"1..{MAX_DUPLICATE_HASH_WORKERS}",
        help="Bounded full-hash worker count for duplicate candidates.",
    )
    ebook_collection_maintain.add_argument(
        "--hash-batch-size",
        type=int,
        default=64,
        help=(
            "Atomic hash batch size for duplicate candidates; must be between 1 and "
            f"{MAX_DUPLICATE_HASH_BATCH_SIZE}."
        ),
    )
    ebook_collection_maintain.add_argument(
        "--hash-max-items",
        type=int,
        default=None,
        help="Attempt at most this many candidate hashes; rerun to continue.",
    )
    ebook_collection_maintain.add_argument(
        "--run-inventory-report",
        action="store_true",
        help="Generate a deterministic inventory report after analysis.",
    )
    ebook_collection_maintain.add_argument(
        "--inventory-report-root",
        type=Path,
        default=Path(
            os.environ.get(
                "FOLIOTONE_INVENTORY_REPORT_ROOT",
                "/data/inventory-reports",
            )
        ),
        help="Durable private inventory report root.",
    )
    ebook_collection_maintain.add_argument(
        "--run-collection-report",
        action="store_true",
        help="Generate a deterministic collection report after successful collection run.",
    )
    ebook_collection_maintain.add_argument(
        "--collection-report-root",
        type=Path,
        default=Path(
            os.environ.get(
                "FOLIOTONE_COLLECTION_REPORT_ROOT",
                "/data/collection-reports",
            )
        ),
        help="Durable private collection report root.",
    )
    ebook_collection_maintain.add_argument(
        "--review-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT,
        help="Maximum prioritized review items emitted; totals remain complete.",
    )
    ebook_collection_maintain.add_argument(
        "--report-group-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
        help="Maximum exact-duplicate/content-variant/group and inventory groups emitted.",
    )
    ebook_collection_maintain.add_argument(
        "--report-member-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
        help="Maximum members emitted for each candidate group.",
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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

    ebook_collection_report = subparsers.add_parser(
        "ebook-collection-report",
        help=(
            "Write deterministic private JSON/CSV summaries and review sets for a "
            "persisted e-book collection run."
        ),
    )
    ebook_collection_report.add_argument(
        "--run",
        required=True,
        type=EntityId.parse,
        help="Persisted EbookCollectionRun ID to report.",
    )
    ebook_collection_report.add_argument(
        "--source-root",
        required=True,
        type=Path,
        help="Source root used only to enforce separate writable report storage.",
    )
    ebook_collection_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_collection_report.add_argument(
        "--report-root",
        type=Path,
        default=Path(
            os.environ.get(
                "FOLIOTONE_COLLECTION_REPORT_ROOT",
                "/data/collection-reports",
            )
        ),
        help="Durable private report root; defaults to /data/collection-reports.",
    )
    ebook_collection_report.add_argument(
        "--review-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT,
        help="Maximum prioritized review items emitted; totals remain complete.",
    )
    ebook_collection_report.add_argument(
        "--group-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
        help="Maximum exact-duplicate and content-variant groups emitted per basis.",
    )
    ebook_collection_report.add_argument(
        "--group-member-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
        help="Maximum members emitted for each candidate group.",
    )

    ebook_inventory_report = subparsers.add_parser(
        "ebook-inventory-report",
        help=(
            "Write a deterministic private scan-wide format, size, hash-coverage, "
            "and exact-duplicate report."
        ),
    )
    ebook_inventory_report.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name whose latest scan is reported.",
    )
    ebook_inventory_report.add_argument(
        "--source-root",
        required=True,
        type=Path,
        help="Source root used only to enforce separate writable report storage.",
    )
    ebook_inventory_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_inventory_report.add_argument(
        "--report-root",
        type=Path,
        default=Path(
            os.environ.get(
                "FOLIOTONE_INVENTORY_REPORT_ROOT",
                "/data/inventory-reports",
            )
        ),
        help="Durable private report root; defaults to /data/inventory-reports.",
    )
    ebook_inventory_report.add_argument(
        "--group-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
        help="Maximum exact-duplicate groups emitted; totals remain complete.",
    )
    ebook_inventory_report.add_argument(
        "--group-member-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
        help="Maximum members emitted for each exact-duplicate group.",
    )

    postscan_verify = subparsers.add_parser(
        "ebook-postscan-verify",
        help=(
            "Verify the completed hash, inventory, and bounded collection chain "
            "without opening source media."
        ),
    )
    postscan_verify.add_argument(
        "--scan-root",
        required=True,
        help="Existing logical EBOOK ScanRoot name to verify.",
    )
    postscan_verify.add_argument(
        "--database",
        required=True,
        type=Path,
        help="Existing SQLite database path opened strictly read-only.",
    )
    postscan_verify.add_argument(
        "--inventory-report-root",
        required=True,
        type=Path,
        help="Existing private inventory report root.",
    )
    postscan_verify.add_argument(
        "--inventory-report-sha256",
        required=True,
        help="Expected deterministic inventory report identifier.",
    )
    postscan_verify.add_argument(
        "--inventory-group-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
        help="Candidate-group limit used when the inventory report was rendered.",
    )
    postscan_verify.add_argument(
        "--inventory-member-limit",
        type=int,
        default=DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
        help="Members-per-group limit used when the inventory report was rendered.",
    )
    postscan_verify.add_argument(
        "--collection-run",
        required=True,
        type=EntityId.parse,
        help="Opaque bounded collection run identifier to verify.",
    )
    postscan_verify.add_argument(
        "--plan-per-format",
        required=True,
        type=int,
        help="Bound applied independently to every supported e-book format.",
    )
    postscan_verify.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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
        print("Read-only EPUB/MOBI/AZW/AZW3 text fingerprints are available through ebook-text.")
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
        print(
            "Deterministic private collection summaries and review sets are available "
            "through ebook-collection-report."
        )
        print(
            "Read-only resumable collection maintenance (analyze + optional hash/enhance "
            "reports) is available through ebook-collection-maintain."
        )
        print(
            "Quick duplicate candidates can be selectively confirmed with full SHA-256 "
            "through ebook-hash-candidates."
        )
        print(
            "Path-free candidate-hash leases and heartbeats can be inspected through "
            "ebook-hash-status."
        )
        print(
            "Scan-wide format, size, hash-coverage, and exact-duplicate reports are "
            "available through ebook-inventory-report."
        )
        print(
            "The bounded postscan lineage can be verified read-only through "
            "ebook-postscan-verify."
        )
        print("Read-only PDF metadata and text analysis is available through pdf-analyze.")
        print("Read-only EPUB conformance evidence is available through epub-validate.")
        print("Source-media and external-tool mutation commands are not implemented.")
        return 0

    if args.command == "scan":
        deletion_policy = _deletion_policy(parser, args)
        return _run_scan(args, deletion_policy)

    if args.command == "ebook-collection-maintain":
        return _run_ebook_collection_maintain(args)

    if args.command == "ebook-hash-candidates":
        return _run_ebook_hash_candidates(args)

    if args.command == "ebook-hash-status":
        return _run_ebook_hash_status(args)

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

    if args.command == "ebook-collection-report":
        return _run_ebook_collection_report(args)

    if args.command == "ebook-inventory-report":
        return _run_ebook_inventory_report(args)

    if args.command == "ebook-postscan-verify":
        return _run_ebook_postscan_verify(args)

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
                "--confirm-deleted-after-hours requires --confirm-deleted-after-missing-scans"
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
    recovered_run: ScanRun | None = None
    resume_from: ScanRun | None
    try:
        if args.resume_run is not None:
            resume_from = store.get_resumable_run(root, args.resume_run)
        elif args.resume_last_interrupted:
            resume_from = store.latest_interrupted_run(root)
            if resume_from is None:
                print("Scan failed: no INTERRUPTED ScanRun exists for this ScanRoot.")
                return 2
        elif args.recover_stale_running:
            recovered_run = store.recover_latest_stale_run(root, datetime.now(UTC))
            resume_from = recovered_run
        else:
            resume_from = None
    except (ScanLeaseError, ValueError) as error:
        print(f"Scan failed: {error}")
        return 2
    hash_mode = _HASH_MODES[args.hash_mode]
    fingerprint_writer = None if hash_mode is HashMode.NONE else FingerprintWriter(engine)
    relocation_detector = (
        None if hash_mode is HashMode.NONE else RelocationCandidateDetector(engine)
    )
    scanner = IncrementalScanner(
        store,
        batch_size=args.batch_size,
        hash_mode=hash_mode,
        hash_workers=args.hash_workers,
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
    if recovered_run is not None:
        print(f"Recovered stale ScanRun: {recovered_run.id}")
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
    if summary.hash_failures:
        print(f"Hash failures: {summary.hash_failures}")
        return 1
    return 0


def _run_ebook_hash_candidates(args: argparse.Namespace) -> int:
    if not args.root.is_dir():
        print("E-book candidate hashing failed: source root is unavailable.")
        return 2
    try:
        _validate_hash_candidate_paths(args.root, args.database)
        print(
            "Candidate hashing progress: preparing database schema.",
            flush=True,
        )
        migrate(args.database)
        engine = create_sqlite_engine(args.database)
        roots = tuple(
            root
            for root in repository(engine, ScanRoot).list_all()
            if root.name == args.scan_root.strip()
        )
        if len(roots) != 1:
            print("E-book candidate hashing failed: logical ScanRoot does not exist.")
            return 2
        root = roots[0]
        summary = DuplicateHashCandidateService(engine).enrich(
            root,
            args.root,
            worker_count=args.workers,
            batch_size=args.batch_size,
            max_items=args.max_items,
            progress=lambda message: print(
                f"Candidate hashing progress: {message}.",
                flush=True,
            ),
        )
    except (DuplicateHashCandidateError, ValueError) as error:
        print(f"E-book candidate hashing failed: {error}")
        return 2
    except OSError:
        print("E-book candidate hashing failed: runtime storage is unavailable.")
        return 2
    except KeyboardInterrupt:
        print("E-book candidate hashing interrupted; rerun the same command to continue.")
        return 130
    except Exception:
        print("E-book candidate hashing failed: internal persistence error.")
        return 2

    print(f"ScanRoot: {root.name}")
    print(f"Candidate hash run: {summary.run_id}")
    print(f"Source ScanRun: {summary.scan_run_id}")
    print(f"Candidate hash profile: {summary.profile}")
    print(f"Quick candidate groups: {summary.candidate_groups}")
    print(f"Quick candidate observations: {summary.candidate_observations}")
    print(f"Already full-hashed: {summary.already_hashed}")
    print(f"Full-hashed this invocation: {summary.hashed_this_invocation}")
    print(f"Hash failures: {summary.hash_failures}")
    print(f"Remaining candidates: {summary.remaining}")
    if summary.hash_failures:
        print("Status: COMPLETED_WITH_FAILURES")
        return 1
    if summary.remaining:
        print("Status: INTERRUPTED")
        return 3
    print("Status: COMPLETED")
    return 0


def _run_ebook_hash_status(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _ebook_hash_status_error(
            args,
            "DATABASE_UNAVAILABLE",
            "E-book candidate hash status failed: database is unavailable.",
        )
    engine = create_sqlite_read_only_engine(database)
    try:
        try:
            roots = tuple(
                root
                for root in repository(engine, ScanRoot).list_all()
                if root.name == args.scan_root.strip()
            )
            if len(roots) != 1:
                return _ebook_hash_status_error(
                    args,
                    "SCAN_ROOT_NOT_FOUND",
                    "E-book candidate hash status failed: logical ScanRoot does not exist.",
                )
            run = SQLiteEbookCandidateHashRunStore(engine).latest(roots[0].id)
        except OperationalError:
            return _ebook_hash_status_error(
                args,
                "SCHEMA_UNAVAILABLE",
                "E-book candidate hash status failed: database schema is unavailable.",
            )
    finally:
        engine.dispose()
    if args.output == "json":
        print(
            json.dumps(
                candidate_hash_status_payload(roots[0].name, run, datetime.now(UTC)),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    if run is None:
        print(f"ScanRoot: {roots[0].name}")
        print("Candidate hash run: NONE")
        return 0

    print(f"ScanRoot: {roots[0].name}")
    print(f"Candidate hash run: {run.id}")
    print(f"Source ScanRun: {run.source_scan_run_id}")
    print(f"Status: {run.status.value}")
    print(f"Phase: {run.phase.value}")
    print(f"Heartbeat UTC: {run.heartbeat_at.isoformat()}")
    if run.lease_expires_at is not None:
        print(f"Lease expires UTC: {run.lease_expires_at.isoformat()}")
    if run.candidate_groups is None:
        print("Candidate selection: PENDING")
    else:
        print(f"Quick candidate groups: {run.candidate_groups}")
        print(f"Quick candidate observations: {run.candidate_observations}")
        print(f"Already full-hashed: {run.already_hashed}")
        print(f"Processed: {run.processed_count}")
        print(f"Full-hashed: {run.hashed_count}")
        print(f"Hash failures: {run.failure_count}")
        print(f"Remaining candidates: {run.remaining_count}")
    return 0


def _ebook_hash_status_error(
    args: argparse.Namespace,
    error_code: str,
    message: str,
) -> int:
    if args.output == "json":
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "ebook-hash-status",
                    "ok": False,
                    "error": {"code": error_code},
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        print(message)
    return 2


def _run_ebook_analyze(args: argparse.Namespace) -> int:
    database: Path = args.database
    migrate(database)
    engine = create_sqlite_engine(database)
    observation = repository(engine, FileObservation).get(args.observation_id)
    if observation is None:
        print("E-book analysis failed: FileObservation does not exist.")
        return 2
    record = repository(engine, FileRecord).get(observation.file_id)
    if record is None:
        print("E-book analysis failed: FileRecord does not exist.")
        return 2

    lease_store = SQLiteScanRootWriteLeaseStore(engine)
    started_at = datetime.now(UTC)
    lease_token = str(EntityId.new())
    try:
        write_lease = lease_store.acquire(
            record.scan_root_id,
            ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
            observation.id,
            lease_token=lease_token,
            acquired_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=30),
        )
    except ScanRootWriteLeaseError:
        print("E-book analysis failed: another write workflow owns this ScanRoot.")
        return 2

    try:
        ebook_analysis_format(observation.relative_path)
        runtime = ToolRuntime(
            engine,
            args.artifact_root,
            work_root=args.work_root,
        )
        with scan_root_write_scope(write_lease, lambda: datetime.now(UTC)):
            outcome = _ebook_analysis_orchestrator(engine, runtime, args).analyze(
                args.root,
                observation,
                fresh=args.fresh,
            )
    except (EbookAnalysisError, ValueError) as error:
        print(f"E-book analysis failed: {error}")
        return 1
    except ScanRootWriteLeaseError:
        print("E-book analysis failed: ScanRoot write ownership was lost.")
        return 2
    finally:
        try:
            lease_store.release(write_lease, released_at=datetime.now(UTC))
        except ScanRootWriteLeaseError:
            pass

    print(f"FileObservation: {outcome.observation_id}")
    print(f"Format: {outcome.format_name}")
    print(f"Analysis profile: {outcome.profile}")
    print(f"Evidence policy: {'FRESH' if args.fresh else 'REUSE_EXACT'}")
    for step in outcome.steps:
        print(f"{step.name} status: {step.state.value}")
        print(f"{step.name} evidence action: {step.disposition.value}")
        if step.error is not None:
            print(f"{step.name} adapter error: {json.dumps(step.error, ensure_ascii=False)}")
        for index, execution in enumerate(step.executions, start=1):
            label = step.name if len(step.executions) == 1 else f"{step.name}.{index}"
            print(f"{label} ToolExecution: {execution.id}")
            print(f"{label} execution status: {execution.status.value}")
            print(f"{label} tool version: {json.dumps(execution.tool_version, ensure_ascii=False)}")
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
    try:
        outcome, root = _run_ebook_collection_analysis(args)
    except ValueError as error:
        print(f"E-book collection analysis failed: {error}")
        return 2
    except EbookCollectionInterrupted as error:
        print(f"E-book collection run: {error.run_id}")
        print("Status: INTERRUPTED")
        print("Resume is safe with --resume-run and the same logical ScanRoot.")
        return 130
    except EbookCollectionError as error:
        print(f"E-book collection analysis failed: {error}")
        if error.run_id is not None:
            print(f"E-book collection run: {error.run_id}")
        return 2
    except EbookCollectionStoreError as error:
        print(f"E-book collection analysis failed: {error}")
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

    _print_ebook_collection_outcome(outcome, root)
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED:
        return 0
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED_WITH_FAILURES:
        return 1
    if outcome.run.status is EbookCollectionRunStatus.INTERRUPTED:
        return 3
    return 2


def _run_ebook_collection_maintain(args: argparse.Namespace) -> int:
    try:
        if args.run_inventory_report:
            _validate_collection_report_paths(
                args.root,
                args.database,
                args.inventory_report_root,
            )
        if args.run_collection_report:
            _validate_collection_report_paths(
                args.root,
                args.database,
                args.collection_report_root,
            )
    except ValueError as error:
        print(f"E-book collection maintain failed: {error}")
        return 2

    try:
        outcome, root = _run_ebook_collection_analysis(args)
    except ValueError as error:
        print(f"E-book collection maintain failed: {error}")
        return 2
    except EbookCollectionInterrupted as error:
        print(f"E-book collection run: {error.run_id}")
        print("Status: INTERRUPTED")
        print("Resume is safe with --resume-run and the same logical ScanRoot.")
        _run_ebook_collection_maintain_auxiliary(args, outcome=None)
        return 130
    except EbookCollectionError as error:
        print(f"E-book collection maintain failed: {error}")
        if error.run_id is not None:
            print(f"E-book collection run: {error.run_id}")
        return 2
    except EbookCollectionStoreError as error:
        print(f"E-book collection maintain failed: {error}")
        return 2
    except OSError:
        print("E-book collection maintain failed: runtime storage is unavailable.")
        return 2
    except KeyboardInterrupt:
        print("E-book collection maintain interrupted before a run was acquired.")
        return 130
    except Exception:
        print("E-book collection maintain failed: internal persistence error.")
        return 2

    _print_ebook_collection_outcome(outcome, root)
    _run_ebook_collection_maintain_auxiliary(
        args,
        outcome=outcome,
    )
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED:
        return 0
    if outcome.run.status is EbookCollectionRunStatus.COMPLETED_WITH_FAILURES:
        return 1
    if outcome.run.status is EbookCollectionRunStatus.INTERRUPTED:
        return 3
    return 2


def _run_ebook_collection_maintain_auxiliary(
    args: argparse.Namespace,
    outcome: EbookCollectionOutcome | None,
) -> None:
    if args.run_hash_candidates:
        hash_args = argparse.Namespace(
            root=args.root,
            scan_root=args.scan_root,
            database=args.database,
            workers=args.hash_workers,
            batch_size=args.hash_batch_size,
            max_items=args.hash_max_items,
        )
        hash_result = _run_ebook_hash_candidates(hash_args)
        if hash_result != 0 and hash_result != 1:
            print(
                "E-book collection maintain warning: hash candidate maintenance "
                f"did not complete successfully: {hash_result}"
            )

    if args.run_inventory_report:
        inventory_result = _run_ebook_collection_inventory_report(
            args.root,
            args.scan_root,
            args.database,
            args.inventory_report_root,
            args.report_group_limit,
            args.report_member_limit,
        )
        if inventory_result != 0:
            print(
                "E-book collection maintain warning: inventory report generation "
                f"did not complete successfully: {inventory_result}"
            )

    if args.run_collection_report:
        if outcome is None or outcome.run.status is EbookCollectionRunStatus.INTERRUPTED:
            print(
                "E-book collection maintain warning: collection report is "
                "available only after a non-interrupted collection run."
            )
            return
        report_args = argparse.Namespace(
            run=outcome.run.id,
            source_root=args.root,
            database=args.database,
            report_root=args.collection_report_root,
            review_limit=args.review_limit,
            group_limit=args.report_group_limit,
            group_member_limit=args.report_member_limit,
        )
        report_result = _run_ebook_collection_report(report_args)
        if report_result != 0:
            print(
                "E-book collection maintain warning: collection report generation "
                f"did not complete successfully: {report_result}"
            )


def _run_ebook_collection_inventory_report(
    source_root: Path,
    scan_root: str,
    database: Path,
    report_root: Path,
    group_limit: int,
    group_member_limit: int,
) -> int:
    try:
        _validate_collection_report_paths(source_root, database, report_root)
        limits = EbookInventoryReportLimits(
            candidate_groups=group_limit,
            members_per_group=group_member_limit,
        )
        migrate(database)
        engine = create_sqlite_engine(database)
        roots = tuple(
            root
            for root in repository(engine, ScanRoot).list_all()
            if root.name == scan_root.strip()
        )
        if len(roots) != 1:
            print("E-book inventory report failed: logical ScanRoot does not exist.")
            return 2
        root = roots[0]
        if root.media_type is not MediaType.EBOOK or not root.enabled:
            print(
                "E-book inventory report failed: ScanRoot must be an enabled "
                "EBOOK root."
            )
            return 2
        outcome = EbookInventoryReportService(
            SQLiteEbookInventoryReportStore(engine)
        ).generate(
            root.id,
            report_root,
            limits=limits,
        )
    except (
        EbookInventoryReportError,
        EbookInventoryReportStoreError,
        ValueError,
    ) as error:
        print(f"E-book inventory report failed: {error}")
        return 2
    except OSError:
        print("E-book inventory report failed: runtime storage is unavailable.")
        return 2
    except Exception:
        print("E-book inventory report failed: internal persistence error.")
        return 2

    print(f"ScanRoot: {root.name}")
    print(f"Source ScanRun: {outcome.scan_run_id}")
    print(f"Report profile: {outcome.profile}")
    print(f"Observations: {outcome.observations}")
    print(f"Total bytes: {outcome.total_bytes}")
    for aggregate in outcome.formats:
        observation_label = (
            "observation" if aggregate.observations == 1 else "observations"
        )
        print(
            f"Format {aggregate.format_name}: {aggregate.observations} "
            f"{observation_label}, {aggregate.total_bytes} bytes"
        )
    print(f"Full-hash observations: {outcome.full_hash_observations}")
    print(f"Quick candidate groups: {outcome.quick_candidate_groups}")
    print(f"Quick candidate observations: {outcome.quick_candidate_observations}")
    print(
        "Quick candidates missing full hash: "
        f"{outcome.quick_candidates_missing_full_hash}"
    )
    print(f"Exact duplicate groups: {outcome.exact_duplicate_groups}")
    print(f"Exact duplicate observations: {outcome.exact_duplicate_members}")
    print(f"Potential redundant bytes: {outcome.redundant_bytes}")
    print(f"Report SHA-256: {outcome.report_sha256}")
    print(f"Report files: {len(outcome.files)}")
    print(f"Report directory: {outcome.report_directory}")
    print("Identity verdict: NOT_PRODUCED")
    print("Relation records written: 0")
    return 0


def _run_ebook_collection_analysis(
    args: argparse.Namespace,
) -> tuple[EbookCollectionOutcome, ScanRoot]:
    if not args.root.is_dir():
        raise ValueError("source root is unavailable.")

    _validate_collection_storage_paths(
        args.root,
        args.database,
        args.artifact_root,
        args.work_root,
    )
    if args.plan_limit is not None and args.plan_per_format is not None:
        raise ValueError("--plan-limit and --plan-per-format are mutually exclusive.")
    if (args.resume_run is not None or args.resume_last_interrupted) and (
        args.fresh
        or args.workers is not None
        or args.plan_limit is not None
        or args.plan_per_format is not None
    ):
        raise ValueError(
            "--fresh, --workers, --plan-limit, and --plan-per-format cannot "
            "change a resumed run."
        )

    migrate(args.database)
    engine = create_sqlite_engine(args.database)
    roots = tuple(
        root
        for root in repository(engine, ScanRoot).list_all()
        if root.name == args.scan_root.strip()
    )
    if len(roots) != 1:
        raise ValueError("logical ScanRoot does not exist.")
    root = roots[0]
    if root.media_type is not MediaType.EBOOK or not root.enabled:
        raise ValueError("ScanRoot must be an enabled EBOOK root.")

    store = SQLiteEbookCollectionStore(engine)
    if args.resume_run is not None:
        persisted = store.get_run(args.resume_run)
        if persisted is None or persisted.scan_root_id != root.id:
            raise ValueError("resume run does not belong to the requested ScanRoot.")
    elif args.resume_last_interrupted:
        persisted = store.latest_interrupted_run(root.id)
        if persisted is None:
            raise ValueError("no INTERRUPTED run exists for this ScanRoot.")
        args.resume_run = persisted.id

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
            plan_per_format=args.plan_per_format,
        )
    else:
        outcome = service.resume(
            args.resume_run,
            max_items=args.max_items,
        )
    return outcome, root


def _print_ebook_collection_outcome(
    outcome: EbookCollectionOutcome,
    root: ScanRoot,
) -> None:
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


def _run_ebook_collection_report(args: argparse.Namespace) -> int:
    try:
        _validate_collection_report_paths(
            args.source_root,
            args.database,
            args.report_root,
        )
        limits = EbookCollectionReportLimits(
            review_items=args.review_limit,
            candidate_groups=args.group_limit,
            members_per_group=args.group_member_limit,
        )
        migrate(args.database)
        engine = create_sqlite_engine(args.database)
        outcome = EbookCollectionReportService(SQLiteEbookCollectionReportStore(engine)).generate(
            args.run,
            args.report_root,
            limits=limits,
        )
    except (
        EbookCollectionReportError,
        EbookCollectionReportStoreError,
        ValueError,
    ) as error:
        print(f"E-book collection report failed: {error}")
        return 2
    except OSError:
        print("E-book collection report failed: runtime storage is unavailable.")
        return 2
    except Exception:
        print("E-book collection report failed: internal persistence error.")
        return 2

    print(f"E-book collection run: {outcome.run_id}")
    print(f"Report profile: {outcome.profile}")
    print(f"Report SHA-256: {outcome.report_sha256}")
    print(f"Report files: {len(outcome.files)}")
    print(f"Review items: {outcome.review_item_total}")
    print(f"Review items emitted: {outcome.review_item_emitted}")
    print(f"Exact duplicate groups: {outcome.exact_duplicate_groups}")
    print(f"Content variant groups: {outcome.content_variant_groups}")
    print(f"Report directory: {outcome.report_directory}")
    print("Identity verdict: NOT_PRODUCED")
    print("Relation records written: 0")
    return 0


def _run_ebook_inventory_report(args: argparse.Namespace) -> int:
    try:
        _validate_collection_report_paths(
            args.source_root,
            args.database,
            args.report_root,
        )
        limits = EbookInventoryReportLimits(
            candidate_groups=args.group_limit,
            members_per_group=args.group_member_limit,
        )
        migrate(args.database)
        engine = create_sqlite_engine(args.database)
        roots = tuple(
            root
            for root in repository(engine, ScanRoot).list_all()
            if root.name == args.scan_root.strip()
        )
        if len(roots) != 1:
            print("E-book inventory report failed: logical ScanRoot does not exist.")
            return 2
        root = roots[0]
        if root.media_type is not MediaType.EBOOK or not root.enabled:
            print("E-book inventory report failed: ScanRoot must be an enabled EBOOK root.")
            return 2
        outcome = EbookInventoryReportService(SQLiteEbookInventoryReportStore(engine)).generate(
            root.id,
            args.report_root,
            limits=limits,
        )
    except (
        EbookInventoryReportError,
        EbookInventoryReportStoreError,
        ValueError,
    ) as error:
        print(f"E-book inventory report failed: {error}")
        return 2
    except OSError:
        print("E-book inventory report failed: runtime storage is unavailable.")
        return 2
    except Exception:
        print("E-book inventory report failed: internal persistence error.")
        return 2

    print(f"ScanRoot: {root.name}")
    print(f"Source ScanRun: {outcome.scan_run_id}")
    print(f"Report profile: {outcome.profile}")
    print(f"Observations: {outcome.observations}")
    print(f"Total bytes: {outcome.total_bytes}")
    for aggregate in outcome.formats:
        observation_label = "observation" if aggregate.observations == 1 else "observations"
        print(
            f"Format {aggregate.format_name}: {aggregate.observations} "
            f"{observation_label}, {aggregate.total_bytes} bytes"
        )
    print(f"Full-hash observations: {outcome.full_hash_observations}")
    print(f"Quick candidate groups: {outcome.quick_candidate_groups}")
    print(f"Quick candidate observations: {outcome.quick_candidate_observations}")
    print(f"Quick candidates missing full hash: {outcome.quick_candidates_missing_full_hash}")
    print(f"Exact duplicate groups: {outcome.exact_duplicate_groups}")
    print(f"Exact duplicate observations: {outcome.exact_duplicate_members}")
    print(f"Potential redundant bytes: {outcome.redundant_bytes}")
    print(f"Report SHA-256: {outcome.report_sha256}")
    print(f"Report files: {len(outcome.files)}")
    print(f"Report directory: {outcome.report_directory}")
    print("Identity verdict: NOT_PRODUCED")
    print("Relation records written: 0")
    return 0


def _run_ebook_postscan_verify(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _ebook_postscan_verify_error(args, "DATABASE_UNAVAILABLE")
    try:
        limits = EbookInventoryReportLimits(
            candidate_groups=args.inventory_group_limit,
            members_per_group=args.inventory_member_limit,
        )
        engine = create_sqlite_read_only_engine(database)
        try:
            report = PostscanCompletionVerifier(engine).verify(
                args.scan_root.strip(),
                inventory_report_root=args.inventory_report_root,
                inventory_report_sha256=args.inventory_report_sha256,
                inventory_limits=limits,
                collection_run_id=args.collection_run,
                plan_per_format=args.plan_per_format,
            )
        finally:
            engine.dispose()
    except KeyboardInterrupt:
        return 130
    except (OperationalError, OSError, ValueError):
        return _ebook_postscan_verify_error(args, "INTERNAL_READ_ERROR")

    if args.output == "json":
        print(
            json.dumps(
                report.payload(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        print(f"ScanRoot: {report.scan_root}")
        print(f"Overall: {report.overall.value}")
        for name, check in report.checks.items():
            print(f"{name}: {check.state.value} ({check.code})")
    return report.exit_code


def _ebook_postscan_verify_error(
    args: argparse.Namespace,
    error_code: str,
) -> int:
    if args.output == "json":
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "ebook-postscan-verify",
                    "overall": "INVALID",
                    "error": {"code": error_code},
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        print("E-book postscan verification failed: read-only state is unavailable.")
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


def _validate_hash_candidate_paths(source_root: Path, database: Path) -> None:
    if database.resolve().is_relative_to(source_root.resolve()):
        raise ValueError("database path must be outside source root")


def _validate_collection_report_paths(
    source_root: Path,
    database: Path,
    report_root: Path,
) -> None:
    source = source_root.resolve()
    for destination in (database, report_root):
        if destination.resolve().is_relative_to(source):
            raise ValueError("database and report paths must be outside source root")


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
        print(f"{label} version: {json.dumps(execution.tool_version, ensure_ascii=False)}")
        if execution.error_summary is not None:
            print(f"{label} error: {json.dumps(execution.error_summary, ensure_ascii=False)}")

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
