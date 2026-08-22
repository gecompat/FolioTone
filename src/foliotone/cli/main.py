"""Command-line interface for safe FolioTone analysis workflows."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
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
from foliotone.collection_state import (
    DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT,
    MAX_COLLECTION_STATE_DIFF_LIMIT,
    MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING,
    CollectionQuerySpec,
    CollectionStateDiffRequest,
    parse_collection_query_spec,
)
from foliotone.core import (
    MAX_EBOOK_COLLECTION_WORKERS,
    EbookCollectionRunStatus,
    EntityId,
    EntityKind,
    FileChangeState,
    FileObservation,
    FileRecord,
    MediaType,
    RelocationCandidateKind,
    ReviewActorKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItemState,
    ReviewType,
    ScanRoot,
    ScanRun,
    ToolExecutionStatus,
)
from foliotone.index import (
    MAX_DUPLICATE_HASH_BATCH_SIZE,
    MAX_DUPLICATE_HASH_WORKERS,
    MAX_SCAN_HASH_WORKERS,
    DeletionConfirmationPolicy,
    DiscoveryProgress,
    DuplicateHashCandidateError,
    DuplicateHashCandidateService,
    FingerprintWriter,
    HashMode,
    HashProgress,
    IncrementalScanner,
    ReconciliationProgress,
    RelocationCandidateDetector,
    ScanLeaseError,
    ScanProgress,
    ScanProgressPhase,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import (
    CalibreLibraryReportReaderError,
    EbookCollectionReportStoreError,
    EbookCollectionStoreError,
    EbookInventoryReportStoreError,
    ResolutionReviewStoreError,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteCalibreLibraryReportReader,
    SQLiteEbookCandidateHashRunStore,
    SQLiteEbookCollectionReportStore,
    SQLiteEbookCollectionStore,
    SQLiteEbookInventoryReportStore,
    SQLiteRelationCandidateStore,
    SQLiteResolutionReviewStore,
    SQLiteScanRootWriteLeaseStore,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    repository,
    scan_root_write_scope,
)
from foliotone.persistence.archive_collection import SQLiteArchiveCollectionStore
from foliotone.persistence.consolidation_report import (
    ConsolidationPlanReportReaderError,
    SQLiteConsolidationPlanReportReader,
)
from foliotone.persistence.metadata_correction_report import (
    MetadataCorrectionPlanReport,
    MetadataCorrectionPlanReportReaderError,
    SQLiteMetadataCorrectionPlanReportReader,
)
from foliotone.persistence.metadata_write import SQLiteMetadataWriteStore
from foliotone.persistence.quarantine import SQLiteQuarantineStore
from foliotone.tooling.ebook_readiness import inspect_ebook_toolchain
from foliotone.tooling.runtime import ToolRuntime
from foliotone.workflows import (
    DEFAULT_COLLECTION_REPORT_GROUP_LIMIT,
    DEFAULT_COLLECTION_REPORT_MEMBER_LIMIT,
    DEFAULT_COLLECTION_REPORT_REVIEW_LIMIT,
    CollectionQueryReport,
    CollectionQueryService,
    CollectionQueryWorkflowError,
    CollectionStateBuildService,
    CollectionStateDiffReport,
    CollectionStateDiffService,
    CollectionStateDiffWorkflowError,
    CollectionStateReport,
    CollectionStateWorkflowError,
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
    EbookMatchingError,
    EbookMatchingService,
    LibraryHealthReport,
    LibraryHealthWorkflowError,
    PostscanCompletionVerifier,
    SQLiteCollectionStateReportReader,
    SQLiteLibraryHealthReportReader,
    candidate_hash_status_payload,
    ebook_analysis_format,
)
from foliotone.workflows.archive_collection_report import (
    ArchiveCollectionReportError,
    ArchiveCollectionStatusReport,
    SQLiteArchiveCollectionReportReader,
)
from foliotone.workflows.classification import (
    ClassificationReportError,
    read_book_classification_report,
)
from foliotone.workflows.metadata_write_operation import (
    METADATA_WRITE_STAGE_ROOT_ENV,
    MetadataWriteAuthorizationResult,
    MetadataWriteOperationResult,
    MetadataWriteOperatorError,
    MetadataWriteOperatorService,
    create_metadata_write_operator_service,
)
from foliotone.workflows.metadata_write_report import (
    MetadataWriteStatusReport,
    MetadataWriteStatusReportError,
    SQLiteMetadataWriteStatusReportReader,
)
from foliotone.workflows.quarantine_report import (
    QuarantineStatusReport,
    QuarantineStatusReportError,
    SQLiteQuarantineStatusReportReader,
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


def _scan_hash_worker_value(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized == "auto":
        return None
    try:
        workers = int(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected auto or an integer from 1 to 8") from error
    if not 1 <= workers <= MAX_SCAN_HASH_WORKERS:
        raise argparse.ArgumentTypeError(
            f"hash workers must be between 1 and {MAX_SCAN_HASH_WORKERS}"
        )
    return workers


def _resolved_scan_hash_workers(requested: int | None, hash_mode: HashMode) -> int:
    if hash_mode is HashMode.NONE:
        return 1
    if requested is not None:
        return requested
    available = os.cpu_count() or 1
    return min(MAX_SCAN_HASH_WORKERS, max(1, available // 2))


class _ScanConsoleProgress:
    """Render path-free progress without changing stdout contracts."""

    _DASHBOARD_PHASES = ("discovering", "reconciling", "hashing", "scanning")

    def __init__(
        self,
        enabled: bool,
        *,
        overwrite: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._enabled = enabled
        self._stream = sys.stderr
        self._dashboard = overwrite
        self._overwrite = not self._dashboard and self._stream.isatty()
        self._clock = clock
        self._started_at = clock()
        self._active_line = False
        self._active_phase: str | None = None
        self._line_width = 0
        self._dashboard_active = False
        self._dashboard_rows = {
            phase: f"Scan progress: {phase}; waiting" for phase in self._DASHBOARD_PHASES
        }

    def announce(self, message: str) -> None:
        if not self._enabled:
            return
        self.close_line()
        self._stream.write(f"Scan progress: {message}\n")
        self._stream.flush()

    def start_scan(self) -> None:
        self._started_at = self._clock()

    def report(
        self,
        progress: (ScanProgress | HashProgress | DiscoveryProgress | ReconciliationProgress),
    ) -> None:
        if not self._enabled:
            return
        if isinstance(progress, HashProgress):
            text = (
                "Scan progress: hashing; "
                f"batch={progress.completed_files}/{progress.batch_files}; "
                f"read={progress.bytes_read / (1024 * 1024):.1f} MiB; "
                "current-throughput="
                f"{progress.current_bytes_per_second / (1024 * 1024):.1f} MiB/s; "
                f"average-throughput={progress.average_bytes_per_second / (1024 * 1024):.1f} MiB/s"
            )
            self._write_progress_line(text, phase="hashing", completed=False)
            return
        if isinstance(progress, DiscoveryProgress):
            text = (
                "Scan progress: discovering; "
                f"files={progress.discovered_files}; "
                f"data={progress.discovered_bytes / (1024 * 1024):.1f} MiB; "
                "current-throughput="
                f"{progress.current_bytes_per_second / (1024 * 1024):.1f} MiB/s; "
                f"average-throughput={progress.average_bytes_per_second / (1024 * 1024):.1f} MiB/s"
            )
            self._write_progress_line(text, phase="discovering", completed=False)
            return
        if isinstance(progress, ReconciliationProgress):
            text = (
                "Scan progress: reconciling; "
                f"completed-files={progress.processed_files}; "
                f"completed-data={progress.processed_bytes / (1024 * 1024):.1f} MiB; "
                f"batch={progress.reconciled_files}/{progress.batch_files}; "
                f"batch-data={progress.reconciled_bytes / (1024 * 1024):.1f}/"
                f"{progress.batch_bytes / (1024 * 1024):.1f} MiB"
            )
            self._write_progress_line(text, phase="reconciling", completed=False)
            return
        elapsed = max(self._clock() - self._started_at, 0.001)
        mib_per_second = progress.processed_bytes / (1024 * 1024) / elapsed
        phase = {
            ScanProgressPhase.DISCOVERING: "scanning",
            ScanProgressPhase.FINALIZING: "finalizing",
            ScanProgressPhase.COMPLETED: "completed",
        }[progress.phase]
        text = (
            f"Scan progress: {phase}; files={progress.processed_files}; "
            f"data={progress.processed_bytes / (1024 * 1024):.1f} MiB; "
            f"throughput={mib_per_second:.1f} MiB/s"
        )
        if progress.hash_failures:
            text += f"; hash-failures={progress.hash_failures}"
        self._write_progress_line(
            text,
            phase="scanning",
            completed=progress.phase is ScanProgressPhase.COMPLETED,
        )

    def _write_progress_line(self, text: str, *, phase: str, completed: bool) -> None:
        if self._dashboard:
            self._dashboard_rows[phase] = text
            self._render_dashboard()
            if completed:
                self.close_line()
            return
        if self._overwrite:
            if self._active_line and self._active_phase != phase:
                self.close_line()
            padded = text.ljust(self._line_width)
            self._stream.write(f"\r{padded}")
            self._line_width = max(self._line_width, len(text))
            self._active_line = True
            self._active_phase = phase
            if completed:
                self.close_line()
        else:
            self._stream.write(f"{text}\n")
        self._stream.flush()

    def _render_dashboard(self) -> None:
        if self._dashboard_active:
            self._stream.write(f"\x1b[{len(self._DASHBOARD_PHASES)}A")
        for phase in self._DASHBOARD_PHASES:
            self._stream.write(f"\r\x1b[2K{self._dashboard_rows[phase]}\n")
        self._dashboard_active = True
        self._stream.flush()

    def close_line(self) -> None:
        if self._dashboard:
            self._dashboard_active = False
            return
        if self._enabled and self._active_line:
            self._stream.write("\n")
            self._stream.flush()
            self._active_line = False
            self._active_phase = None


def _scan_progress_enabled(requested: bool | None) -> bool:
    return requested is True


def _optional_entity_id(value: str) -> EntityId | None:
    if value.strip().upper() == "NONE":
        return None
    try:
        return EntityId.parse(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected NONE or a valid entity ID") from error


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def _collection_state_diff_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a bounded positive integer") from error
    if not 1 <= limit <= MAX_COLLECTION_STATE_DIFF_LIMIT:
        raise argparse.ArgumentTypeError(
            f"diff limit must be between 1 and {MAX_COLLECTION_STATE_DIFF_LIMIT}"
        )
    return limit


def _collection_query_spec(value: str) -> CollectionQuerySpec:
    try:
        return parse_collection_query_spec(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("query must match collection-query/v1") from error


def _library_health_sample_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a bounded nonnegative integer") from error
    if not 0 <= limit <= MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING:
        raise argparse.ArgumentTypeError(
            f"sample limit must be between 0 and {MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING}"
        )
    return limit


def _metadata_write_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("expected one lowercase SHA-256 digest")
    return value


def _add_metadata_write_binders(
    parser: argparse.ArgumentParser,
    *,
    include_authorization: bool,
) -> None:
    parser.add_argument(
        "--plan-id",
        required=True,
        type=EntityId.parse,
        help="Opaque approved metadata correction plan identifier.",
    )
    parser.add_argument(
        "--plan-content-hash",
        required=True,
        type=_metadata_write_sha256,
        help="Exact lowercase content hash of the approved plan.",
    )
    parser.add_argument(
        "--capability-id",
        required=True,
        type=EntityId.parse,
        help="Opaque locally configured metadata-write capability identifier.",
    )
    if include_authorization:
        parser.add_argument(
            "--authorization-id",
            required=True,
            type=EntityId.parse,
            help="Opaque short-lived metadata-write authorization identifier.",
        )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Path- and metadata-value-free output format; defaults to text.",
    )


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

    ebook_tools_doctor = subparsers.add_parser(
        "ebook-tools-doctor",
        help=(
            "Check calibre, Poppler, Java, EPUBCheck, and readiness for every "
            "supported e-book format without installing tools or opening media."
        ),
    )
    ebook_tools_doctor.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable path-free ebook-toolchain-doctor/v1 JSON report.",
    )
    ebook_tools_doctor.add_argument(
        "--ebook-meta-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
        help="ebook-meta executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--ebook-convert-executable",
        default=os.environ.get("FOLIOTONE_EBOOK_CONVERT", "ebook-convert"),
        help="ebook-convert executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--calibre-debug-executable",
        default=os.environ.get("FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"),
        help="calibre-debug executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--pdfinfo-executable",
        default=os.environ.get("FOLIOTONE_PDFINFO", "pdfinfo"),
        help="pdfinfo executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--pdftotext-executable",
        default=os.environ.get("FOLIOTONE_PDFTOTEXT", "pdftotext"),
        help="pdftotext executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--java-executable",
        default=os.environ.get("FOLIOTONE_JAVA", "java"),
        help="Java executable or absolute executable path.",
    )
    ebook_tools_doctor.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")),
        help="EPUBCheck JAR path; defaults to epubcheck.jar.",
    )

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
        type=_scan_hash_worker_value,
        default=None,
        metavar=f"auto|1..{MAX_SCAN_HASH_WORKERS}",
        help=(
            "Bounded file-hash worker count. Defaults to auto (half the visible CPU count, "
            "bounded to 1..8). Fingerprints are persisted atomically per discovery batch."
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
    scan.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Show a path-free file counter and throughput on stderr. Disabled by default; "
            "use --progress to enable it."
        ),
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
            "Bounded analyzer worker count for a new run; defaults to 1 and is preserved on resume."
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
        default=Path(os.environ.get("FOLIOTONE_TOOL_ARTIFACT_ROOT", "/data/tool-artifacts")),
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

    ebook_classification_report = subparsers.add_parser(
        "ebook-classification-report",
        help="Show one bounded, read-only classification projection summary.",
    )
    ebook_classification_report.add_argument(
        "--target-kind",
        required=True,
        choices=("WORK", "EDITION"),
        help="Classification target kind.",
    )
    ebook_classification_report.add_argument(
        "--target-id",
        required=True,
        type=EntityId.parse,
        help="Opaque internal target ID.",
    )
    ebook_classification_report.add_argument(
        "--projection-id",
        type=EntityId.parse,
        default=None,
        help="Optional opaque projection ID; otherwise the latest bounded snapshot is read.",
    )
    ebook_classification_report.add_argument(
        "--profile",
        dest="projection_profile",
        default="book-classification-projection/v1",
        help="Projection profile literal.",
    )
    ebook_classification_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; opened read-only.",
    )
    ebook_classification_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
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

    ebook_match = subparsers.add_parser(
        "ebook-match",
        help="Persist bounded offline E-book relation candidates for one completed scan.",
    )
    ebook_match.add_argument("--scan-root", required=True, help="Existing logical EBOOK root.")
    ebook_match.add_argument(
        "--scan-run",
        required=True,
        type=EntityId.parse,
        help="Explicit latest completed ScanRun ID.",
    )
    ebook_match.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    ebook_match.add_argument("--block-limit", type=int, default=100)
    ebook_match.add_argument("--candidate-limit", type=int, default=200)
    ebook_match.add_argument("--pairwise-limit", type=int, default=32)
    ebook_match.add_argument("--output", choices=("text", "json"), default="text")

    match_review_list = subparsers.add_parser(
        "ebook-match-review-list",
        help="List bounded pending/deferred matching review items without source access.",
    )
    match_review_list.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
    )
    match_review_list.add_argument("--limit", type=int, default=100)
    match_review_list.add_argument("--after-created-at", type=_aware_datetime)
    match_review_list.add_argument("--after-id", type=EntityId.parse)
    match_review_list.add_argument("--output", choices=("text", "json"), default="text")

    match_review_decide = subparsers.add_parser(
        "ebook-match-review-decide",
        help="Append an optimistically fenced matching review decision.",
    )
    match_review_decide.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
    )
    match_review_decide.add_argument("--review-item", required=True, type=EntityId.parse)
    match_review_decide.add_argument(
        "--decision", required=True, choices=("accept", "reject", "defer")
    )
    match_review_decide.add_argument("--reason-code", required=True)
    match_review_decide.add_argument(
        "--expected-latest-decision",
        required=True,
        type=_optional_entity_id,
        metavar="NONE|UUID",
    )
    match_review_decide.add_argument("--output", choices=("text", "json"), default="text")
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

    calibre_reconciliation_report = subparsers.add_parser(
        "calibre-reconciliation-report",
        help="Read a persisted Calibre reconciliation snapshot without opening Calibre.",
    )
    calibre_reconciliation_report.add_argument(
        "--snapshot",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted Calibre snapshot identifier.",
    )
    calibre_reconciliation_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; defaults to /data/foliotone.db.",
    )
    calibre_reconciliation_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    collection_state_build = subparsers.add_parser(
        "collection-state-build",
        help="Build an immutable book-only state from one completed ScanRun.",
    )
    collection_state_build.add_argument(
        "--scan-run-id",
        required=True,
        type=EntityId.parse,
        help="Opaque completed e-book ScanRun identifier.",
    )
    collection_state_build.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="SQLite database path; defaults to /data/foliotone.db.",
    )
    collection_state_build.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    collection_state_report = subparsers.add_parser(
        "collection-state-report",
        help="Read one persisted CollectionState through SQLite read-only access.",
    )
    collection_state_report.add_argument(
        "--snapshot",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted CollectionState snapshot identifier.",
    )
    collection_state_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    collection_state_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    collection_state_diff = subparsers.add_parser(
        "collection-state-diff",
        help="Compare two compatible immutable CollectionState snapshots read-only.",
    )
    collection_state_diff.add_argument(
        "--before",
        required=True,
        type=EntityId.parse,
        help="Opaque earlier CollectionState snapshot identifier.",
    )
    collection_state_diff.add_argument(
        "--after",
        required=True,
        type=EntityId.parse,
        help="Opaque later CollectionState snapshot identifier.",
    )
    collection_state_diff.add_argument(
        "--limit",
        type=_collection_state_diff_limit,
        default=100,
        help="Bounded changed-item page size; defaults to 100.",
    )
    collection_state_diff.add_argument(
        "--after-file-id",
        type=EntityId.parse,
        help="Opaque keyset cursor returned by an earlier diff page.",
    )
    collection_state_diff.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    collection_state_diff.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    collection_search = subparsers.add_parser(
        "collection-search",
        help="Run a bounded validated query against one local metadata index.",
    )
    collection_search.add_argument(
        "--snapshot",
        required=True,
        type=EntityId.parse,
        help="Opaque CollectionState snapshot identifier.",
    )
    collection_search.add_argument(
        "--query",
        required=True,
        type=_collection_query_spec,
        help="Bounded collection-query/v1 JSON AST; never persisted as query history.",
    )
    collection_search.add_argument(
        "--private-details",
        action="store_true",
        help="Show selected local metadata candidates in interactive text output only.",
    )
    collection_search.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    collection_search.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; JSON remains private-detail-free.",
    )

    library_health_report = subparsers.add_parser(
        "library-health-report",
        help="Read the multidimensional book-only Health projection strictly read-only.",
    )
    library_health_report.add_argument(
        "--snapshot",
        required=True,
        type=EntityId.parse,
        help="Opaque CollectionState snapshot identifier.",
    )
    library_health_report.add_argument(
        "--baseline",
        type=EntityId.parse,
        help="Optional earlier CollectionState snapshot of the same ScanRoot.",
    )
    library_health_report.add_argument(
        "--sample-limit",
        type=_library_health_sample_limit,
        default=DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT,
        help=(
            "Opaque samples per finding; defaults to "
            f"{DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT}, maximum "
            f"{MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING}."
        ),
    )
    library_health_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    library_health_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; both variants remain path- and metadata-value-free.",
    )

    consolidation_plan_report = subparsers.add_parser(
        "ebook-consolidation-report",
        help="Read one persisted non-executable consolidation plan without source access.",
    )
    consolidation_plan_report.add_argument(
        "--plan",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted ConsolidationPlan identifier.",
    )
    consolidation_plan_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; defaults to /data/foliotone.db.",
    )
    consolidation_plan_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    metadata_correction_report = subparsers.add_parser(
        "ebook-metadata-correction-report",
        help="Read one persisted non-executable metadata correction plan read-only.",
    )
    metadata_correction_report.add_argument(
        "--plan",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted MetadataCorrectionPlan identifier.",
    )
    metadata_correction_report.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    metadata_correction_report.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; both variants remain path- and metadata-value-free.",
    )

    metadata_write_authorize = subparsers.add_parser(
        "metadata-write-authorize",
        help="Prepare and authorize one exact reviewed EPUB title replacement.",
    )
    _add_metadata_write_binders(
        metadata_write_authorize,
        include_authorization=False,
    )

    metadata_write_execute = subparsers.add_parser(
        "metadata-write-execute",
        help="Execute one authorized EPUB title replacement after an exact stdin confirmation.",
    )
    _add_metadata_write_binders(
        metadata_write_execute,
        include_authorization=True,
    )

    metadata_write_recover = subparsers.add_parser(
        "metadata-write-recover",
        help="Recover one exact pre-VERIFIED EPUB title write state.",
    )
    _add_metadata_write_binders(
        metadata_write_recover,
        include_authorization=True,
    )

    metadata_write_status = subparsers.add_parser(
        "metadata-write-status",
        help="Read one persisted metadata-write run without source access.",
    )
    metadata_write_status.add_argument(
        "--run-id",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted metadata-write run identifier.",
    )
    metadata_write_status.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Path- and metadata-value-free output format; defaults to text.",
    )

    archive_collection_status = subparsers.add_parser(
        "archive-collection-status",
        help="Read one persisted archive collection run without source access.",
    )
    archive_collection_status.add_argument(
        "--run-id",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted archive collection run identifier.",
    )
    archive_collection_status.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; defaults to /data/foliotone.db.",
    )
    archive_collection_status.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text.",
    )

    quarantine_status = subparsers.add_parser(
        "quarantine-status",
        help="Read one persisted W10 quarantine run without source access.",
    )
    quarantine_status.add_argument(
        "--run-id",
        required=True,
        type=EntityId.parse,
        help="Opaque persisted quarantine run identifier.",
    )
    quarantine_status.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db")),
        help="Existing SQLite database path; opened strictly read-only.",
    )
    quarantine_status.add_argument(
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
            "The bounded postscan lineage can be verified read-only through ebook-postscan-verify."
        )
        print(
            "Persisted Calibre reconciliation snapshots can be inspected read-only through "
            "calibre-reconciliation-report."
        )
        print(
            "Immutable book-only collection snapshots can be built and inspected through "
            "collection-state-build and collection-state-report."
        )
        print(
            "Compatible snapshots can be compared and their bounded local metadata index "
            "searched through collection-state-diff and collection-search."
        )
        print(
            "Persisted non-executable metadata correction plans can be inspected read-only "
            "through ebook-metadata-correction-report."
        )
        print(
            "Bounded offline relation candidates and append-only matching review are "
            "available through ebook-match and ebook-match-review-* commands."
        )
        print("Read-only PDF metadata and text analysis is available through pdf-analyze.")
        print("Read-only EPUB conformance evidence is available through epub-validate.")
        print("Explicit e-book specialist readiness is available through ebook-tools-doctor.")
        print(
            "The bounded reviewed EPUB title writer is available through "
            "metadata-write-authorize, metadata-write-execute, metadata-write-recover, "
            "and metadata-write-status."
        )
        print("Other source-media and external-tool mutation commands remain unavailable.")
        return 0

    if args.command == "ebook-tools-doctor":
        return _run_ebook_tools_doctor(args)

    if args.command == "scan":
        deletion_policy = _deletion_policy(parser, args)
        try:
            return _run_scan(args, deletion_policy)
        except KeyboardInterrupt:
            print("Scan interrupted before a terminal ScanRun status could be reported.")
            return 130

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

    if args.command == "ebook-classification-report":
        return _run_ebook_classification_report(args)

    if args.command == "ebook-postscan-verify":
        return _run_ebook_postscan_verify(args)

    if args.command == "calibre-reconciliation-report":
        return _run_calibre_reconciliation_report(args)

    if args.command == "collection-state-build":
        return _run_collection_state_build(args)

    if args.command == "collection-state-report":
        return _run_collection_state_report(args)

    if args.command == "collection-state-diff":
        return _run_collection_state_diff(args)

    if args.command == "collection-search":
        return _run_collection_search(args)

    if args.command == "library-health-report":
        return _run_library_health_report(args)

    if args.command == "ebook-consolidation-report":
        return _run_ebook_consolidation_report(args)

    if args.command == "ebook-metadata-correction-report":
        return _run_ebook_metadata_correction_report(args)

    if args.command == "metadata-write-authorize":
        return _run_metadata_write_authorize(args)

    if args.command == "metadata-write-execute":
        return _run_metadata_write_execute(args)

    if args.command == "metadata-write-recover":
        return _run_metadata_write_recover(args)

    if args.command == "metadata-write-status":
        return _run_metadata_write_status(args)

    if args.command == "archive-collection-status":
        return _run_archive_collection_status(args)

    if args.command == "quarantine-status":
        return _run_quarantine_status(args)

    if args.command == "ebook-match":
        return _run_ebook_match(args)

    if args.command == "ebook-match-review-list":
        return _run_ebook_match_review_list(args)

    if args.command == "ebook-match-review-decide":
        return _run_ebook_match_review_decide(args)

    if args.command == "ebook-compare":
        return _run_ebook_compare(args)

    if args.command == "pdf-analyze":
        return _run_pdf_analyze(args)

    if args.command == "epub-validate":
        return _run_epub_validate(args)

    parser.print_help()
    return 0


def _run_ebook_tools_doctor(args: argparse.Namespace) -> int:
    report = inspect_ebook_toolchain(
        ebook_meta_executable=args.ebook_meta_executable,
        ebook_convert_executable=args.ebook_convert_executable,
        calibre_debug_executable=args.calibre_debug_executable,
        pdfinfo_executable=args.pdfinfo_executable,
        pdftotext_executable=args.pdftotext_executable,
        java_executable=args.java_executable,
        epubcheck_jar=args.epubcheck_jar,
    )
    if args.json:
        print(json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":")))
        return 0 if report.ready else 2

    print(f"E-book toolchain: {'READY' if report.ready else 'NOT_READY'}")
    print(f"Doctor profile: {report.profile}")
    print(f"Provisioned profile: {report.provisioned_profile}")
    print("Tools:")
    for tool in report.tools:
        detail = tool.version or tool.reason or "no details"
        print(f"  {tool.tool:<16} {tool.status:<12} {detail}")
    print("Formats:")
    for item in report.formats:
        detail = (
            "all required tools ready"
            if item.ready
            else "unavailable: " + ", ".join(item.unavailable_tools)
        )
        print(f"  {item.format:<16} {item.status:<12} {detail}")
    print("Provisioning is explicit; analysis commands never install or update tools.")
    return 0 if report.ready else 2


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
    progress = _ScanConsoleProgress(
        _scan_progress_enabled(args.progress),
        overwrite=args.progress is True,
    )
    progress.announce("preparing database schema")
    try:
        migrate(database)
    except KeyboardInterrupt:
        progress.close_line()
        print("Scan interrupted before a ScanRun was started.")
        return 130
    except (OperationalError, RuntimeError):
        progress.close_line()
        print("Scan failed: database migration could not be completed.")
        return 2
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
    hash_workers = _resolved_scan_hash_workers(args.hash_workers, hash_mode)
    fingerprint_writer = None if hash_mode is HashMode.NONE else FingerprintWriter(engine)
    relocation_detector = (
        None if hash_mode is HashMode.NONE else RelocationCandidateDetector(engine)
    )
    scanner = IncrementalScanner(
        store,
        batch_size=args.batch_size,
        hash_mode=hash_mode,
        hash_workers=hash_workers,
        fingerprint_writer=fingerprint_writer,
        deletion_policy=deletion_policy,
        relocation_detector=relocation_detector,
        progress=progress.report,
    )
    suffixes = None if args.suffix is None else frozenset(args.suffix)
    progress.announce(f"starting scan with {hash_workers} hash worker(s)")
    progress.start_scan()
    try:
        summary = scanner.scan(
            root,
            ScanRootBinding(args.path, include_suffixes=suffixes),
            resume_from=resume_from,
        )
    except KeyboardInterrupt:
        progress.close_line()
        print("Status: INTERRUPTED")
        print("Scan interrupted; rerun with --resume-last-interrupted to continue.")
        return 130
    finally:
        progress.close_line()

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
            print("E-book inventory report failed: ScanRoot must be an enabled EBOOK root.")
            return 2
        outcome = EbookInventoryReportService(SQLiteEbookInventoryReportStore(engine)).generate(
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
            "--fresh, --workers, --plan-limit, and --plan-per-format cannot change a resumed run."
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


def _run_ebook_classification_report(args: argparse.Namespace) -> int:
    """Render one classification projection without opening source media."""

    database: Path = args.database
    if not database.is_file():
        return _ebook_classification_report_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = read_book_classification_report(
                engine,
                EntityKind(args.target_kind),
                args.target_id,
                projection_id=args.projection_id,
                projection_profile_version=args.projection_profile,
            )
        finally:
            engine.dispose()
    except ClassificationReportError:
        return _ebook_classification_report_error(args, "CLASSIFICATION_UNAVAILABLE")
    except OperationalError:
        return _ebook_classification_report_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _ebook_classification_report_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _ebook_classification_report_error(args, "INTERNAL_READ_ERROR")

    if args.output == "json":
        _emit_json(report.payload())
    else:
        print(f"Target kind: {report.target_kind}")
        print(f"Target ID: {report.target_id}")
        print(f"Projection ID: {report.projection_id}")
        print(f"Assertion profile: {report.assertion_profile_version}")
        print(f"Projection profile: {report.projection_profile_version}")
        print(f"Status: {report.status}")
        print(f"Truncated: {'yes' if report.truncated else 'no'}")
        for facet in report.facets:
            conflict = facet.conflict or "NONE"
            print(
                f"Facet {facet.dimension}: {facet.status} "
                f"values={facet.value_count} conflict={conflict}"
            )
        print(f"Count facets: {report.counts.facets}")
        print(f"Count projected_values: {report.counts.projected_values}")
        print(f"Count assertion_links: {report.counts.assertion_links}")
        print(f"Count selected_links: {report.counts.selected_links}")
        print(f"Count considered_links: {report.counts.considered_links}")
        print(f"Count conflicting_links: {report.counts.conflicting_links}")
    return 0


def _ebook_classification_report_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "ebook-classification-report",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Classification report failed: read-only state is unavailable.")
    return 2


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


def _run_calibre_reconciliation_report(args: argparse.Namespace) -> int:
    """Render a persisted Calibre reconciliation report without mutable access."""

    try:
        engine = create_sqlite_read_only_engine(args.database)
        try:
            report = SQLiteCalibreLibraryReportReader(engine).read(args.snapshot)
        finally:
            engine.dispose()
    except CalibreLibraryReportReaderError:
        return _calibre_reconciliation_report_error(args, "SNAPSHOT_UNAVAILABLE")
    except OperationalError:
        return _calibre_reconciliation_report_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _calibre_reconciliation_report_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _calibre_reconciliation_report_error(args, "INTERNAL_READ_ERROR")

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
        print(f"Snapshot: {report.snapshot_id}")
        print(f"Scan root: {report.scan_root_id}")
        print(f"Source scan run: {report.source_scan_run_id}")
        print(f"Snapshot status: {report.snapshot_status}")
        print(f"Report profile: {report.profile}")
        print(f"Records: {report.counts.records}")
        print(f"Formats: {report.counts.formats}")
        print(f"Sidecars: {report.counts.sidecars}")
        print(f"Findings: {report.counts.findings}")
        print(f"Review required: {report.counts.review_required}")
        print(f"Finding refs: {report.counts.refs}")
        for code, count in report.finding_counts:
            print(f"Finding {code}: {count}")
    return 0


def _calibre_reconciliation_report_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "calibre-reconciliation-report",
                    "ok": False,
                    "error": {"code": code},
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        print("Calibre reconciliation report failed: read-only state is unavailable.")
    return 2


def _run_collection_state_build(args: argparse.Namespace) -> int:
    """Build one immutable state projection without Source Media access."""

    database: Path = args.database
    try:
        migrate(database)
        engine = create_sqlite_engine(database)
        try:
            report = CollectionStateBuildService(engine).build(args.scan_run_id, datetime.now(UTC))
        finally:
            engine.dispose()
    except CollectionStateWorkflowError:
        return _collection_state_error(args, "SOURCE_STATE_UNAVAILABLE")
    except OperationalError:
        return _collection_state_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _collection_state_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _collection_state_error(args, "INTERNAL_BUILD_ERROR")
    _emit_collection_state(report, args, command="collection-state-build")
    return 0


def _run_collection_state_report(args: argparse.Namespace) -> int:
    """Read and verify one state projection through SQLite read-only access."""

    database: Path = args.database
    if not database.is_file():
        return _collection_state_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteCollectionStateReportReader(engine).read(args.snapshot)
        finally:
            engine.dispose()
    except CollectionStateWorkflowError:
        return _collection_state_error(args, "SNAPSHOT_UNAVAILABLE")
    except OperationalError:
        return _collection_state_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _collection_state_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _collection_state_error(args, "INTERNAL_READ_ERROR")
    _emit_collection_state(report, args, command="collection-state-report")
    return 0


def _emit_collection_state(
    report: CollectionStateReport,
    args: argparse.Namespace,
    *,
    command: str,
) -> None:
    if args.output == "json":
        _emit_json(report.payload(command=command))
        return
    snapshot = report.snapshot
    print(f"Snapshot: {snapshot.id}")
    print(f"Profile: {snapshot.profile}")
    print(f"ScanRoot: {snapshot.scan_root_id}")
    print(f"Source scan: {snapshot.source_scan_run_id}")
    print(f"Created at: {snapshot.created_at.isoformat()}")
    print(f"Content digest: {snapshot.content_digest}")
    if command == "collection-state-build":
        print(f"Created: {str(report.created).casefold()}")
    for count in snapshot.counts:
        print(f"Count: {count.key}={count.value}")
    for component in snapshot.components:
        print(
            f"Component: {component.component.value} "
            f"coverage={component.coverage_state.value} "
            f"freshness={component.freshness_state.value} "
            f"conflict={component.conflict_state.value} "
            f"truncation={component.truncation_state.value}"
        )
        for profile in component.profile_versions:
            print(f"Component profile: {component.component.value}={profile}")


def _collection_state_error(args: argparse.Namespace, code: str) -> int:
    command = str(args.command)
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": command,
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("CollectionState operation failed: persisted state is unavailable.")
    return 2


def _run_collection_state_diff(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _collection_projection_error(args, "DATABASE_UNAVAILABLE")
    try:
        request = CollectionStateDiffRequest(
            args.before,
            args.after,
            args.limit,
            args.after_file_id,
        )
        engine = create_sqlite_read_only_engine(database)
        try:
            report = CollectionStateDiffService(engine).diff(request)
        finally:
            engine.dispose()
    except CollectionStateDiffWorkflowError:
        return _collection_projection_error(args, "SNAPSHOTS_INCOMPATIBLE_OR_UNAVAILABLE")
    except OperationalError:
        return _collection_projection_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _collection_projection_error(args, "REQUEST_OR_DATABASE_INVALID")
    except Exception:
        return _collection_projection_error(args, "INTERNAL_DIFF_ERROR")
    _emit_collection_state_diff(report, args)
    return 0


def _run_collection_search(args: argparse.Namespace) -> int:
    database: Path = args.database
    if args.private_details and args.output != "text":
        return _collection_projection_error(args, "PRIVATE_DETAILS_REQUIRE_TEXT")
    if not database.is_file():
        return _collection_projection_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = CollectionQueryService(engine).search(
                args.snapshot,
                args.query,
                private_details=args.private_details,
            )
        finally:
            engine.dispose()
    except CollectionQueryWorkflowError:
        return _collection_projection_error(args, "INDEX_OR_QUERY_UNAVAILABLE")
    except OperationalError:
        return _collection_projection_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _collection_projection_error(args, "REQUEST_OR_DATABASE_INVALID")
    except Exception:
        return _collection_projection_error(args, "INTERNAL_QUERY_ERROR")
    _emit_collection_query(report, args)
    return 0


def _emit_collection_state_diff(
    report: CollectionStateDiffReport,
    args: argparse.Namespace,
) -> None:
    payload = report.payload()
    if args.output == "json":
        _emit_json(payload)
        return
    print(f"Before snapshot: {payload['before_snapshot_id']}")
    print(f"After snapshot: {payload['after_snapshot_id']}")
    print(f"Changed items: {payload['total_changed_items']}")
    counts = payload["counts"]
    assert isinstance(counts, dict)
    for category, count in counts.items():
        print(f"Change count: {category}={count}")
    entries = payload["entries"]
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, dict)
        categories = ",".join(str(value) for value in entry["categories"])
        print(f"Change: {entry['file_id']} categories={categories}")
    print(f"Truncated: {str(payload['truncated']).casefold()}")
    if payload["next_after_file_id"] is not None:
        print(f"Next after file: {payload['next_after_file_id']}")


def _emit_collection_query(report: CollectionQueryReport, args: argparse.Namespace) -> None:
    payload = report.payload()
    if args.output == "json":
        _emit_json(payload)
        return
    print(f"Snapshot: {payload['snapshot_id']}")
    print(f"Coverage: {payload['coverage']}")
    print(f"Index truncation: {payload['index_truncation']}")
    print(f"Results: {payload['result_count']}")
    hits = payload["hits"]
    assert isinstance(hits, list)
    for hit, private_hit in zip(hits, report.page.hits, strict=True):
        assert isinstance(hit, dict)
        print(
            f"Result: {hit['file_id']} observation={hit['observation_id']} format={hit['format']}"
        )
        private_values = report.private_values(private_hit) if args.private_details else ()
        for value in private_values:
            print(
                f"Metadata candidate: {value.field.value}={value.value} "
                f"evidence={value.evidence_kind.value}"
            )
    print(f"Truncated: {str(payload['truncated']).casefold()}")
    if payload["next_after_file_id"] is not None:
        print(f"Next after file: {payload['next_after_file_id']}")


def _run_library_health_report(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _collection_projection_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteLibraryHealthReportReader(engine).read(
                args.snapshot,
                baseline_snapshot_id=args.baseline,
                sample_limit=args.sample_limit,
            )
        finally:
            engine.dispose()
    except LibraryHealthWorkflowError:
        return _collection_projection_error(args, "HEALTH_PROJECTION_UNAVAILABLE")
    except OperationalError:
        return _collection_projection_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _collection_projection_error(args, "REQUEST_OR_DATABASE_INVALID")
    except Exception:
        return _collection_projection_error(args, "INTERNAL_HEALTH_ERROR")
    _emit_library_health(report, args)
    return 0


def _emit_library_health(report: LibraryHealthReport, args: argparse.Namespace) -> None:
    payload = report.payload()
    if args.output == "json":
        _emit_json(payload)
        return
    print(f"Health snapshot: {payload['health_snapshot_id']}")
    print(f"CollectionState snapshot: {payload['collection_state_snapshot_id']}")
    print(f"Items: {payload['item_count']}")
    for dimension in report.snapshot.dimensions:
        print(
            f"Dimension: {dimension.dimension.value} "
            f"status={dimension.status.value} "
            f"coverage={dimension.coverage_state.value} "
            f"affected={dimension.affected_item_count}"
        )
        for finding in dimension.findings:
            print(
                f"Finding: {finding.code.value} severity={finding.severity.value} "
                f"items={finding.item_count}"
            )
            for sample in finding.samples[: report.sample_limit]:
                print(f"Sample: file={sample.file_id} observation={sample.observation_id}")
    if report.comparison is not None:
        print(f"Baseline Health snapshot: {report.comparison.before_health_snapshot_id}")
        for value in report.comparison.dimension_deltas:
            print(
                f"Dimension delta: {value.dimension.value} "
                f"affected={value.affected_item_delta} "
                f"status={value.before_status.value}->{value.after_status.value}"
            )
    print(f"Truncated: {str(payload['truncated']).casefold()}")


def _collection_projection_error(args: argparse.Namespace, code: str) -> int:
    command = str(args.command)
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": command,
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Collection projection operation failed: request or persisted state is unavailable.")
    return 2


def _run_ebook_consolidation_report(args: argparse.Namespace) -> int:
    """Render one persisted consolidation plan without mutable access."""

    database: Path = args.database
    if not database.is_file():
        return _ebook_consolidation_report_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteConsolidationPlanReportReader(engine).read(args.plan)
        finally:
            engine.dispose()
    except ConsolidationPlanReportReaderError:
        return _ebook_consolidation_report_error(args, "PLAN_UNAVAILABLE")
    except OperationalError:
        return _ebook_consolidation_report_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _ebook_consolidation_report_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _ebook_consolidation_report_error(args, "INTERNAL_READ_ERROR")

    if args.output == "json":
        _emit_json(report.payload())
    else:
        print(f"Plan: {report.plan_id}")
        print(f"Profile: {report.profile}")
        print(f"Status: {report.status}")
        print(f"Execution state: {report.execution_state}")
        print(f"Content hash: {report.content_hash}")
        print(f"Dependencies: {report.counts.dependencies}")
        print(f"Quality evidence: {report.counts.quality_evidence}")
        print(f"Required reviews: {report.counts.required_reviews}")
        print(f"Preconditions: {report.counts.preconditions}")
        print(f"Future operation intents: {report.counts.future_operation_intents}")
        print(f"Blockers: {report.counts.blockers}")
        print(f"Blocker evidence refs: {report.counts.blocker_evidence_refs}")
        print(f"Review items: {report.counts.review_items}")
        print(f"Decisions: {report.counts.decisions}")
        if report.keeper_file_id is not None:
            print(f"Keeper file: {report.keeper_file_id}")
        if report.candidate_file_id is not None:
            print(f"Candidate file: {report.candidate_file_id}")
        for code in report.blocker_codes:
            print(f"Blocker code: {code}")
    return 0


def _ebook_consolidation_report_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "ebook-consolidation-report",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Consolidation report failed: read-only state is unavailable.")
    return 2


def _run_ebook_metadata_correction_report(args: argparse.Namespace) -> int:
    """Render one persisted metadata correction plan without mutable access."""

    database: Path = args.database
    if not database.is_file():
        return _ebook_metadata_correction_report_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteMetadataCorrectionPlanReportReader(engine).read(args.plan)
        finally:
            engine.dispose()
    except MetadataCorrectionPlanReportReaderError:
        return _ebook_metadata_correction_report_error(args, "PLAN_UNAVAILABLE")
    except OperationalError:
        return _ebook_metadata_correction_report_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _ebook_metadata_correction_report_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _ebook_metadata_correction_report_error(args, "INTERNAL_READ_ERROR")

    if args.output == "json":
        _emit_json(report.payload())
    else:
        _print_ebook_metadata_correction_report(report)
    return 0


def _print_ebook_metadata_correction_report(
    report: MetadataCorrectionPlanReport,
) -> None:
    print(f"Plan: {report.plan_id}")
    print(f"Candidate: {report.candidate_id}")
    print(f"Plan profile: {report.plan_profile}")
    print(f"Candidate profile: {report.candidate_profile}")
    print(f"Status: {report.status}")
    print(f"Execution state: {report.execution_state}")
    print(f"Content hash: {report.content_hash}")
    print(f"Target carrier: {report.target_carrier}")
    print(f"Format: {report.format_label}")
    print(f"Review status: {report.review_status}")
    for label, value in (
        ("Fields", report.counts.fields),
        ("Observed values", report.counts.observed_values),
        ("Selected values", report.counts.selected_values),
        ("Field evidence refs", report.counts.field_evidence_refs),
        ("Candidate evidence refs", report.counts.candidate_evidence_refs),
        ("Dependencies", report.counts.dependencies),
        ("Preconditions", report.counts.preconditions),
        ("Verification fields", report.counts.verification_fields),
        ("Verification dependencies", report.counts.verification_dependencies),
        ("Blockers", report.counts.blockers),
        ("Blocker evidence refs", report.counts.blocker_evidence_refs),
        ("Review items", report.counts.review_items),
        ("Decisions", report.counts.decisions),
    ):
        print(f"{label}: {value}")
    for field in report.fields:
        print(
            f"Field: {field.field_path} operation={field.operation} "
            f"observed_values={field.observed_value_count} "
            f"selected_values={field.selected_value_count} "
            f"evidence_refs={field.evidence_ref_count}"
        )
    for code in report.blocker_codes:
        print(f"Blocker code: {code}")


def _ebook_metadata_correction_report_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "ebook-metadata-correction-report",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Metadata correction report failed: read-only state is unavailable.")
    return 2


def _metadata_write_database() -> Path:
    return Path(os.environ.get("FOLIOTONE_DATABASE", "/data/foliotone.db"))


def _metadata_write_stage_root() -> Path:
    return Path(
        os.environ.get(
            METADATA_WRITE_STAGE_ROOT_ENV,
            "/data/foliotone-metadata-write-stage",
        )
    )


def _open_metadata_write_operator() -> tuple[Engine, MetadataWriteOperatorService]:
    database = _metadata_write_database()
    migrate(database)
    engine = create_sqlite_engine(database)
    try:
        service = create_metadata_write_operator_service(
            engine,
            _metadata_write_stage_root(),
            metadata_executable=os.environ.get("FOLIOTONE_EBOOK_META", "ebook-meta"),
            text_executable=os.environ.get(
                "FOLIOTONE_EBOOK_CONVERT", "ebook-convert"
            ),
            cover_executable=os.environ.get(
                "FOLIOTONE_CALIBRE_DEBUG", "calibre-debug"
            ),
            java_executable=os.environ.get("FOLIOTONE_JAVA", "java"),
            epubcheck_jar=Path(
                os.environ.get("FOLIOTONE_EPUBCHECK_JAR", "epubcheck.jar")
            ),
        )
    except Exception:
        engine.dispose()
        raise
    return engine, service


def _run_metadata_write_authorize(args: argparse.Namespace) -> int:
    engine: Engine | None = None
    try:
        engine, service = _open_metadata_write_operator()
        result = service.authorize(
            plan_id=args.plan_id,
            plan_content_hash=args.plan_content_hash,
            capability_id=args.capability_id,
        )
    except MetadataWriteOperatorError as error:
        return _metadata_write_error(args, "metadata-write-authorize", error.code.value)
    except (OperationalError, OSError, ValueError):
        return _metadata_write_error(args, "metadata-write-authorize", "RUNTIME_UNAVAILABLE")
    except Exception:
        return _metadata_write_error(args, "metadata-write-authorize", "INTERNAL_ERROR")
    finally:
        if engine is not None:
            engine.dispose()
    _emit_metadata_write_authorization(args, result)
    return 0


def _run_metadata_write_execute(args: argparse.Namespace) -> int:
    engine: Engine | None = None
    try:
        engine, service = _open_metadata_write_operator()
        prompt = service.confirmation_prompt(
            plan_id=args.plan_id,
            plan_content_hash=args.plan_content_hash,
            capability_id=args.capability_id,
            authorization_id=args.authorization_id,
        )
        confirmation = _read_metadata_write_confirmation(prompt)
        if confirmation is None:
            return _metadata_write_error(
                args,
                "metadata-write-execute",
                "CONFIRMATION_INVALID",
            )
        result = service.execute(
            plan_id=args.plan_id,
            plan_content_hash=args.plan_content_hash,
            capability_id=args.capability_id,
            authorization_id=args.authorization_id,
            confirmation_text=confirmation,
        )
    except MetadataWriteOperatorError as error:
        return _metadata_write_error(args, "metadata-write-execute", error.code.value)
    except KeyboardInterrupt:
        return _metadata_write_error(args, "metadata-write-execute", "CONFIRMATION_INVALID")
    except (OperationalError, OSError, ValueError):
        return _metadata_write_error(args, "metadata-write-execute", "RUNTIME_UNAVAILABLE")
    except Exception:
        return _metadata_write_error(args, "metadata-write-execute", "INTERNAL_ERROR")
    finally:
        if engine is not None:
            engine.dispose()
    _emit_metadata_write_operation(args, "metadata-write-execute", result)
    return 0


def _run_metadata_write_recover(args: argparse.Namespace) -> int:
    engine: Engine | None = None
    try:
        engine, service = _open_metadata_write_operator()
        result = service.recover(
            plan_id=args.plan_id,
            plan_content_hash=args.plan_content_hash,
            capability_id=args.capability_id,
            authorization_id=args.authorization_id,
        )
    except MetadataWriteOperatorError as error:
        return _metadata_write_error(args, "metadata-write-recover", error.code.value)
    except (OperationalError, OSError, ValueError):
        return _metadata_write_error(args, "metadata-write-recover", "RUNTIME_UNAVAILABLE")
    except Exception:
        return _metadata_write_error(args, "metadata-write-recover", "INTERNAL_ERROR")
    finally:
        if engine is not None:
            engine.dispose()
    _emit_metadata_write_operation(args, "metadata-write-recover", result)
    return 0


def _run_metadata_write_status(args: argparse.Namespace) -> int:
    database = _metadata_write_database()
    if not database.is_file():
        return _metadata_write_error(args, "metadata-write-status", "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteMetadataWriteStatusReportReader(SQLiteMetadataWriteStore(engine)).read(
                args.run_id
            )
        finally:
            engine.dispose()
    except MetadataWriteStatusReportError:
        return _metadata_write_error(args, "metadata-write-status", "RUN_UNAVAILABLE")
    except OperationalError:
        return _metadata_write_error(args, "metadata-write-status", "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _metadata_write_error(args, "metadata-write-status", "DATABASE_UNAVAILABLE")
    except Exception:
        return _metadata_write_error(args, "metadata-write-status", "INTERNAL_READ_ERROR")
    if args.output == "json":
        _emit_json(report.payload())
    else:
        _print_metadata_write_status(report)
    return 0


def _read_metadata_write_confirmation(prompt: str) -> str | None:
    prefix = "CONFIRM METADATA WRITE "
    if not isinstance(prompt, str) or not prompt.startswith(prefix):
        return None
    try:
        authorization_id = EntityId.parse(prompt.removeprefix(prefix))
    except (TypeError, ValueError):
        return None
    if prompt != f"{prefix}{authorization_id}":
        return None
    sys.stderr.write(f"{prompt}\n")
    sys.stderr.flush()
    supplied = sys.stdin.readline(257)
    if not supplied.endswith("\n") or len(supplied) > 256:
        return None
    supplied = supplied[:-1]
    if supplied.endswith("\r"):
        supplied = supplied[:-1]
    if "\r" in supplied or "\n" in supplied:
        return None
    return supplied if hmac.compare_digest(supplied, prompt) else None


def _emit_metadata_write_authorization(
    args: argparse.Namespace,
    result: MetadataWriteAuthorizationResult,
) -> None:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "metadata-write-authorize",
                "ok": True,
                "profile": result.profile,
                "authorization_id": str(result.authorization_id),
                "plan_id": str(result.plan_id),
                "scan_root_id": str(result.scan_root_id),
                "authorized_at": result.authorized_at.isoformat(),
                "expires_at": result.expires_at.isoformat(),
                "status": result.status,
            }
        )
        return
    print(f"Authorization: {result.authorization_id}")
    print(f"Plan: {result.plan_id}")
    print(f"ScanRoot: {result.scan_root_id}")
    print(f"Profile: {result.profile}")
    print(f"Status: {result.status}")
    print(f"Authorized: {result.authorized_at.isoformat()}")
    print(f"Expires: {result.expires_at.isoformat()}")


def _emit_metadata_write_operation(
    args: argparse.Namespace,
    command: str,
    result: MetadataWriteOperationResult,
) -> None:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": command,
                "ok": True,
                "profile": result.profile,
                "authorization_id": str(result.authorization_id),
                "run_id": str(result.run_id),
                "plan_id": str(result.plan_id),
                "scan_root_id": str(result.scan_root_id),
                "status": result.status.value,
                "scan_run_id": (None if result.scan_run_id is None else str(result.scan_run_id)),
                "observation_id": (
                    None if result.observation_id is None else str(result.observation_id)
                ),
                "collection_state_snapshot_id": (
                    None
                    if result.collection_state_snapshot_id is None
                    else str(result.collection_state_snapshot_id)
                ),
            }
        )
        return
    print(f"Run: {result.run_id}")
    print(f"Authorization: {result.authorization_id}")
    print(f"Plan: {result.plan_id}")
    print(f"ScanRoot: {result.scan_root_id}")
    print(f"Profile: {result.profile}")
    print(f"Status: {result.status.value}")
    if result.scan_run_id is not None:
        print(f"Reconciliation scan: {result.scan_run_id}")
    if result.observation_id is not None:
        print(f"Reconciliation observation: {result.observation_id}")
    if result.collection_state_snapshot_id is not None:
        print(f"CollectionState: {result.collection_state_snapshot_id}")


def _print_metadata_write_status(report: MetadataWriteStatusReport) -> None:
    print(f"Run: {report.run_id}")
    print(f"Authorization: {report.authorization_id}")
    print(f"Plan: {report.plan_id}")
    print(f"ScanRoot: {report.scan_root_id}")
    print(f"Profile: {report.profile}")
    print(f"Status: {report.status.value}")
    print(f"Created: {report.created_at.isoformat()}")
    print(f"Authorized: {report.authorized_at.isoformat()}")
    print(f"Expires: {report.expires_at.isoformat()}")
    for event in report.events:
        print(f"Event: {event.sequence_no} {event.status.value} {event.occurred_at.isoformat()}")
    if report.reconciliation is not None:
        print(f"Reconciliation outcome: {report.reconciliation.outcome.value}")
        print(f"Reconciliation scan: {report.reconciliation.scan_run_id}")
        print(f"Reconciliation observation: {report.reconciliation.observation_id}")
        print(f"CollectionState: {report.reconciliation.collection_state_snapshot_id}")
        print(f"Reconciled: {report.reconciliation.reconciled_at.isoformat()}")


def _metadata_write_error(args: argparse.Namespace, command: str, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": command,
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print(f"Metadata write failed: {code}.")
    return 2


def _run_archive_collection_status(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _archive_collection_status_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteArchiveCollectionReportReader(SQLiteArchiveCollectionStore(engine)).read(
                args.run_id
            )
        finally:
            engine.dispose()
    except ArchiveCollectionReportError:
        return _archive_collection_status_error(args, "RUN_UNAVAILABLE")
    except OperationalError:
        return _archive_collection_status_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _archive_collection_status_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _archive_collection_status_error(args, "INTERNAL_READ_ERROR")
    if args.output == "json":
        _emit_json(report.payload())
    else:
        _print_archive_collection_status(report)
    return 0


def _print_archive_collection_status(report: ArchiveCollectionStatusReport) -> None:
    print(f"Run: {report.run_id}")
    print(f"Profile: {report.profile}")
    print(f"Status: {report.status.value}")
    print(f"Source scan: {report.source_scan_run_id}")
    for label, value in (
        ("Planned", report.counts.planned),
        ("Pending", report.counts.pending),
        ("Running", report.counts.running),
        ("Succeeded", report.counts.succeeded),
        ("Failed", report.counts.failed),
        ("Error", report.counts.error),
        ("Executed", report.counts.executed),
        ("Reused", report.counts.reused),
    ):
        print(f"{label}: {value}")
    for label, values in (
        ("Listing status", report.listing_statuses),
        ("Integrity status", report.integrity_statuses),
        ("Encryption status", report.encryption_statuses),
        ("Recognition status", report.recognition_statuses),
        ("Storage family", report.storage_families),
        ("Error code", report.error_codes),
    ):
        for aggregate in values:
            print(f"{label}: {aggregate.literal}={aggregate.count}")
    print("Truncated: false")


def _archive_collection_status_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "archive-collection-status",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Archive collection status failed: read-only state is unavailable.")
    return 2


def _run_quarantine_status(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _quarantine_status_error(args, "DATABASE_UNAVAILABLE")
    try:
        engine = create_sqlite_read_only_engine(database)
        try:
            report = SQLiteQuarantineStatusReportReader(SQLiteQuarantineStore(engine)).read(
                args.run_id
            )
        finally:
            engine.dispose()
    except QuarantineStatusReportError:
        return _quarantine_status_error(args, "RUN_UNAVAILABLE")
    except OperationalError:
        return _quarantine_status_error(args, "SCHEMA_UNAVAILABLE")
    except (OSError, ValueError):
        return _quarantine_status_error(args, "DATABASE_UNAVAILABLE")
    except Exception:
        return _quarantine_status_error(args, "INTERNAL_READ_ERROR")
    if args.output == "json":
        _emit_json(report.payload())
    else:
        _print_quarantine_status(report)
    return 0


def _print_quarantine_status(report: QuarantineStatusReport) -> None:
    print(f"Run: {report.run_id}")
    print(f"Authorization: {report.authorization_id}")
    print(f"Plan: {report.plan_id}")
    print(f"ScanRoot: {report.scan_root_id}")
    print(f"Profile: {report.profile}")
    print(f"Status: {report.status.value}")
    print(f"Created: {report.created_at.isoformat()}")
    print(f"Authorized: {report.authorized_at.isoformat()}")
    print(f"Expires: {report.expires_at.isoformat()}")
    for event in report.events:
        print(f"Event: {event.sequence_no} {event.status.value} {event.occurred_at.isoformat()}")


def _quarantine_status_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "quarantine-status",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("Quarantine status failed: read-only state is unavailable.")
    return 2


def _run_ebook_match(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _ebook_match_error(args, "DATABASE_UNAVAILABLE")
    try:
        migrate(database)
        engine = create_sqlite_engine(database)
        try:
            roots = tuple(
                root
                for root in repository(engine, ScanRoot).list_all()
                if root.name == args.scan_root.strip()
                and root.enabled
                and root.media_type is MediaType.EBOOK
            )
            if len(roots) != 1:
                return _ebook_match_error(args, "SCAN_ROOT_NOT_FOUND")
            outcome = EbookMatchingService(engine).run(
                roots[0].id,
                args.scan_run,
                block_limit=args.block_limit,
                candidate_limit=args.candidate_limit,
                pairwise_limit=args.pairwise_limit,
            )
        finally:
            engine.dispose()
    except KeyboardInterrupt:
        return 130
    except (EbookMatchingError, OperationalError, OSError, ValueError):
        return _ebook_match_error(args, "MATCHING_FAILED")

    payload = {
        "schema_version": 1,
        "command": "ebook-match",
        "ok": True,
        "scan_root": args.scan_root.strip(),
        "scan_run_id": str(outcome.scan_run_id),
        "profile": outcome.profile,
        "blocks_seen": outcome.blocks_seen,
        "candidates_available": outcome.candidates_available,
        "candidates_processed": outcome.candidates_processed,
        "confirmed": outcome.confirmed,
        "rejected": outcome.rejected,
        "review_queued": outcome.review_queued,
        "decisions_reused": outcome.decisions_reused,
        "truncated": outcome.truncated,
    }
    if args.output == "json":
        _emit_json(payload)
    else:
        print(f"ScanRoot: {payload['scan_root']}")
        print(f"Source ScanRun: {payload['scan_run_id']}")
        print(f"Matching profile: {outcome.profile}")
        print(f"Candidate blocks: {outcome.blocks_seen}")
        print(f"Candidates available: {outcome.candidates_available}")
        print(f"Candidates processed: {outcome.candidates_processed}")
        print(f"Exact duplicates confirmed: {outcome.confirmed}")
        print(f"Candidates rejected: {outcome.rejected}")
        print(f"Review items queued: {outcome.review_queued}")
        print(f"Prior decisions reused: {outcome.decisions_reused}")
        print(f"Status: {'BOUNDED' if outcome.truncated else 'COMPLETED'}")
    return 3 if outcome.truncated else 0


def _ebook_match_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": "ebook-match",
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("E-book matching failed: persisted state is unavailable or inconsistent.")
    return 2


def _run_ebook_match_review_list(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _ebook_match_review_error(args, "DATABASE_UNAVAILABLE")
    try:
        if (args.after_created_at is None) != (args.after_id is None):
            raise ValueError("both review cursor fields are required")
        after = None if args.after_created_at is None else (args.after_created_at, args.after_id)
        engine = create_sqlite_read_only_engine(database)
        try:
            review_store = SQLiteResolutionReviewStore(engine)
            candidate_store = SQLiteRelationCandidateStore(engine)
            page = review_store.list_queue(
                limit=args.limit,
                after=after,
                review_type=ReviewType.MATCH_RELATION,
            )
            items = []
            for item in page.items:
                candidate = candidate_store.get(item.candidate_id)
                if candidate is None:
                    raise ResolutionReviewStoreError("matching candidate is unavailable")
                items.append(
                    (
                        item,
                        review_store.get_effective_decision(item.id),
                        candidate,
                        candidate_store.evidence(candidate.id),
                    )
                )
        finally:
            engine.dispose()
    except (OperationalError, OSError, ResolutionReviewStoreError, ValueError):
        return _ebook_match_review_error(args, "REVIEW_READ_FAILED")
    payload = {
        "schema_version": 1,
        "command": "ebook-match-review-list",
        "ok": True,
        "items": [
            {
                "id": str(item.id),
                "candidate_id": str(candidate.id),
                "state": item.state.value,
                "relation_type": candidate.relation_type.value,
                "status": candidate.status.value,
                "confidence": candidate.confidence,
                "left": {"kind": candidate.left_kind.value, "id": str(candidate.left_id)},
                "right": {"kind": candidate.right_kind.value, "id": str(candidate.right_id)},
                "producer": item.producer_name,
                "producer_version": item.producer_version,
                "created_at": item.created_at.isoformat(),
                "explanation": [
                    {"code": code, "state": state, "evidence_count": count}
                    for (code, state), count in sorted(
                        Counter(
                            (link.feature_code.value, link.feature_state.value) for link in evidence
                        ).items()
                    )
                ],
                "latest_decision": (
                    None
                    if decision is None
                    else {
                        "id": str(decision.id),
                        "sequence_no": decision.sequence_no,
                        "decision": decision.decision.value,
                    }
                ),
            }
            for item, decision, candidate, evidence in items
        ],
        "has_more": page.next_cursor is not None,
        "next_cursor": (
            None
            if page.next_cursor is None
            else {
                "created_at": page.next_cursor[0].isoformat(),
                "id": str(page.next_cursor[1]),
            }
        ),
    }
    if args.output == "json":
        _emit_json(payload)
    else:
        print(f"Matching review items: {len(items)}")
        for item, decision, candidate, evidence in items:
            latest = "NONE" if decision is None else str(decision.id)
            print(
                f"{item.id} {item.state.value} {candidate.relation_type.value} "
                f"{candidate.left_kind.value}:{candidate.left_id} "
                f"{candidate.right_kind.value}:{candidate.right_id} "
                f"candidate={candidate.id} latest={latest}"
            )
            counts = Counter(link.feature_code.value for link in evidence)
            for code, count in sorted(counts.items()):
                print(f"  {code}: {count} Evidence link(s)")
        print(f"More items: {'yes' if page.next_cursor is not None else 'no'}")
        if page.next_cursor is not None:
            print(f"Next created-at: {page.next_cursor[0].isoformat()}")
            print(f"Next ID: {page.next_cursor[1]}")
    return 0


def _run_ebook_match_review_decide(args: argparse.Namespace) -> int:
    database: Path = args.database
    if not database.is_file():
        return _ebook_match_review_error(args, "DATABASE_UNAVAILABLE")
    try:
        migrate(database)
        engine = create_sqlite_engine(database)
        try:
            store = SQLiteResolutionReviewStore(engine)
            item = store.get_review_item(args.review_item)
            if item is None or item.review_type is not ReviewType.MATCH_RELATION:
                return _ebook_match_review_error(args, "REVIEW_ITEM_NOT_FOUND")
            if item.state not in {ReviewItemState.PENDING, ReviewItemState.DEFERRED}:
                return _ebook_match_review_error(args, "REVIEW_ITEM_NOT_ACTIVE")
            latest = store.get_effective_decision(item.id)
            latest_id = None if latest is None else latest.id
            if latest_id != args.expected_latest_decision:
                return _ebook_match_review_error(args, "REVIEW_HISTORY_CHANGED")
            decision_value = {
                "accept": ReviewDecisionValue.ACCEPT,
                "reject": ReviewDecisionValue.REJECT,
                "defer": ReviewDecisionValue.DEFER,
            }[args.decision]
            decision = ReviewDecision(
                EntityId.new(),
                item.id,
                1 if latest is None else latest.sequence_no + 1,
                decision_value,
                args.reason_code,
                item.evidence_fingerprint,
                item.candidate_set_fingerprint,
                item.decision_compatibility_version,
                ReviewActorKind.USER,
                datetime.now(UTC),
            )
            stored = store.append_decision(
                decision,
                expected_latest_decision_id=args.expected_latest_decision,
            )
        finally:
            engine.dispose()
    except (OperationalError, OSError, ResolutionReviewStoreError, ValueError):
        return _ebook_match_review_error(args, "REVIEW_WRITE_FAILED")
    payload = {
        "schema_version": 1,
        "command": "ebook-match-review-decide",
        "ok": True,
        "review_item_id": str(stored.review_item_id),
        "decision_id": str(stored.id),
        "sequence_no": stored.sequence_no,
        "decision": stored.decision.value,
    }
    if args.output == "json":
        _emit_json(payload)
    else:
        print(f"Review item: {stored.review_item_id}")
        print(f"Decision: {stored.decision.value}")
        print(f"Sequence: {stored.sequence_no}")
        print(f"Decision ID: {stored.id}")
    return 0


def _ebook_match_review_error(args: argparse.Namespace, code: str) -> int:
    if args.output == "json":
        _emit_json(
            {
                "schema_version": 1,
                "command": args.command,
                "ok": False,
                "error": {"code": code},
            }
        )
    else:
        print("E-book matching review failed: persisted state is unavailable or stale.")
    return 2


def _emit_json(payload: object) -> None:
    print(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


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
