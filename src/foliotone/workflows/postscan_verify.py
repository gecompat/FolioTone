"""Read-only, path-free verification of the bounded e-book postscan chain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import OperationalError

from foliotone.core import (
    EbookCandidateHashPhase,
    EbookCandidateHashRun,
    EbookCandidateHashRunStatus,
    EbookCollectionRunStatus,
    EntityId,
    MediaType,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    EbookCollectionStoreError,
    EbookInventoryReportSnapshot,
    EbookInventoryReportStoreError,
    SQLiteEbookCandidateHashRunStore,
    SQLiteEbookCollectionStore,
    SQLiteEbookInventoryReportStore,
    alembic_config,
    repository,
)
from foliotone.workflows.collection import EBOOK_COLLECTION_PROFILE
from foliotone.workflows.collection_report import (
    EbookInventoryReportError,
    EbookInventoryReportLimits,
    EbookInventoryReportMissingError,
    verify_inventory_report_files,
)
from foliotone.workflows.ebook import EBOOK_ANALYSIS_PROFILE


def _packaged_schema_revision() -> str:
    revision = ScriptDirectory.from_config(
        alembic_config(":memory:")
    ).get_current_head()
    if revision is None:
        raise RuntimeError("packaged migration head is unavailable")
    return revision


POSTSCAN_SCHEMA_REVISION = _packaged_schema_revision()
POSTSCAN_CANDIDATE_HASH_PROFILE = "ebook-duplicate-hash/v1"
_FORMAT_ORDER = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")
_CHECK_ORDER = (
    "migration",
    "source_scan",
    "candidate_hash",
    "inventory_report",
    "collection_analysis",
)


class PostscanVerificationState(StrEnum):
    COMPLETE = "COMPLETE"
    PENDING = "PENDING"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class PostscanVerificationCheck:
    state: PostscanVerificationState
    code: str
    details: dict[str, object]

    def payload(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "code": self.code,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class PostscanVerificationReport:
    scan_root: str
    checks: dict[str, PostscanVerificationCheck]

    @property
    def overall(self) -> PostscanVerificationState:
        states = {check.state for check in self.checks.values()}
        for state in (
            PostscanVerificationState.INVALID,
            PostscanVerificationState.PENDING,
            PostscanVerificationState.DEGRADED,
        ):
            if state in states:
                return state
        return PostscanVerificationState.COMPLETE

    @property
    def exit_code(self) -> int:
        return {
            PostscanVerificationState.COMPLETE: 0,
            PostscanVerificationState.DEGRADED: 1,
            PostscanVerificationState.INVALID: 2,
            PostscanVerificationState.PENDING: 3,
        }[self.overall]

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "ebook-postscan-verify",
            "overall": self.overall.value,
            "scan_root": self.scan_root,
            "checks": {
                name: self.checks[name].payload()
                for name in _CHECK_ORDER
            },
        }


class PostscanCompletionVerifier:
    """Verify one explicit postscan lineage without opening the source collection."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def verify(
        self,
        scan_root_name: str,
        *,
        inventory_report_root: Path,
        inventory_report_sha256: str,
        inventory_limits: EbookInventoryReportLimits,
        collection_run_id: EntityId,
        plan_per_format: int,
    ) -> PostscanVerificationReport:
        if plan_per_format <= 0:
            raise ValueError("plan_per_format must be positive")
        checks: dict[str, PostscanVerificationCheck] = {}
        migration = self._migration_check()
        checks["migration"] = migration
        if migration.state is not PostscanVerificationState.COMPLETE:
            blocked = _check(
                PostscanVerificationState.PENDING,
                "BLOCKED_BY_SCHEMA",
            )
            for name in _CHECK_ORDER[1:]:
                checks[name] = blocked
            return PostscanVerificationReport(scan_root_name, checks)

        roots = tuple(
            root
            for root in repository(self._engine, ScanRoot).list_all()
            if root.name == scan_root_name
            and root.enabled
            and root.media_type is MediaType.EBOOK
        )
        if len(roots) != 1:
            checks["source_scan"] = _check(
                PostscanVerificationState.INVALID,
                "SCAN_ROOT_NOT_FOUND",
            )
            blocked = _check(
                PostscanVerificationState.PENDING,
                "BLOCKED_BY_SOURCE_SCAN",
            )
            for name in _CHECK_ORDER[2:]:
                checks[name] = blocked
            return PostscanVerificationReport(scan_root_name, checks)
        root = roots[0]
        scans = sorted(
            (
                scan
                for scan in repository(self._engine, ScanRun).list_all()
                if scan.scan_root_id == root.id
            ),
            key=lambda scan: (scan.started_at, str(scan.id)),
            reverse=True,
        )
        scan = scans[0] if scans else None
        checks["source_scan"] = self._source_scan_check(scan)
        if scan is None or scan.status is not ScanRunStatus.COMPLETED:
            blocked = _check(
                PostscanVerificationState.PENDING,
                "BLOCKED_BY_SOURCE_SCAN",
            )
            for name in _CHECK_ORDER[2:]:
                checks[name] = blocked
            return PostscanVerificationReport(scan_root_name, checks)

        candidate_run = SQLiteEbookCandidateHashRunStore(self._engine).latest(root.id)
        checks["candidate_hash"] = self._candidate_check(scan, candidate_run)

        inventory_snapshot = None
        try:
            inventory_snapshot = SQLiteEbookInventoryReportStore(
                self._engine
            ).snapshot(
                root.id,
                candidate_group_limit=inventory_limits.candidate_groups,
                candidate_member_limit=inventory_limits.members_per_group,
            )
            if inventory_snapshot.scan.id != scan.id:
                checks["inventory_report"] = _check(
                    PostscanVerificationState.INVALID,
                    "INVENTORY_LINEAGE_MISMATCH",
                )
            elif inventory_snapshot.quick_candidates_missing_full_hash:
                checks["inventory_report"] = _check(
                    PostscanVerificationState.PENDING,
                    "FULL_HASH_COVERAGE_INCOMPLETE",
                    quick_candidates_missing_full_hash=(
                        inventory_snapshot.quick_candidates_missing_full_hash
                    ),
                )
            else:
                try:
                    files_verified = verify_inventory_report_files(
                        inventory_report_root,
                        inventory_report_sha256,
                        inventory_snapshot,
                        inventory_limits,
                    )
                except EbookInventoryReportMissingError:
                    checks["inventory_report"] = _check(
                        PostscanVerificationState.PENDING,
                        "INVENTORY_REPORT_MISSING",
                    )
                except (EbookInventoryReportError, OSError):
                    checks["inventory_report"] = _check(
                        PostscanVerificationState.INVALID,
                        "INVENTORY_REPORT_INVALID",
                    )
                else:
                    checks["inventory_report"] = _check(
                        PostscanVerificationState.COMPLETE,
                        "VERIFIED",
                        scan_run_id=str(scan.id),
                        files_verified=files_verified,
                        formats={
                            value.format_name: value.observations
                            for value in inventory_snapshot.formats
                        },
                    )
        except EbookInventoryReportStoreError:
            checks["inventory_report"] = _check(
                PostscanVerificationState.INVALID,
                "INVENTORY_SNAPSHOT_INVALID",
            )

        checks["collection_analysis"] = self._collection_check(
            root.id,
            scan,
            collection_run_id,
            plan_per_format,
            inventory_snapshot,
        )
        return PostscanVerificationReport(scan_root_name, checks)

    def _migration_check(self) -> PostscanVerificationCheck:
        try:
            with self._engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            inspector = inspect(self._engine)
            tables = set(inspector.get_table_names())
            candidate_indexes = {
                value["name"]
                for value in inspector.get_indexes("ebook_candidate_hash_runs")
            } if "ebook_candidate_hash_runs" in tables else set()
            fingerprint_indexes = {
                value["name"] for value in inspector.get_indexes("fingerprints")
            } if "fingerprints" in tables else set()
        except (OperationalError, OSError):
            return _check(
                PostscanVerificationState.INVALID,
                "SCHEMA_UNAVAILABLE",
            )
        expected_candidate_indexes = {
            "uq_ebook_candidate_hash_runs_active_root",
            "ix_ebook_candidate_hash_runs_root_started",
        }
        if (
            revision != POSTSCAN_SCHEMA_REVISION
            or "ebook_candidate_hash_runs" not in tables
            or not expected_candidate_indexes.issubset(candidate_indexes)
            or "ix_fingerprints_target_profile_id_value" not in fingerprint_indexes
        ):
            return _check(
                PostscanVerificationState.INVALID,
                "SCHEMA_MISMATCH",
            )
        return _check(
            PostscanVerificationState.COMPLETE,
            "VERIFIED",
            revision=POSTSCAN_SCHEMA_REVISION,
        )

    @staticmethod
    def _source_scan_check(scan: ScanRun | None) -> PostscanVerificationCheck:
        if scan is None:
            return _check(PostscanVerificationState.PENDING, "SCAN_NOT_FOUND")
        details = {"scan_run_id": str(scan.id), "status": scan.status.value}
        if scan.status is ScanRunStatus.COMPLETED:
            return _check(PostscanVerificationState.COMPLETE, "VERIFIED", **details)
        if scan.status in {ScanRunStatus.RUNNING, ScanRunStatus.INTERRUPTED}:
            return _check(PostscanVerificationState.PENDING, "SCAN_NOT_COMPLETE", **details)
        return _check(PostscanVerificationState.INVALID, "SCAN_FAILED", **details)

    @staticmethod
    def _candidate_check(
        scan: ScanRun,
        run: EbookCandidateHashRun | None,
    ) -> PostscanVerificationCheck:
        if run is None:
            return _check(PostscanVerificationState.PENDING, "CANDIDATE_RUN_MISSING")
        candidate = run
        details = {
            "run_id": str(candidate.id),
            "source_scan_run_id": str(candidate.source_scan_run_id),
            "status": candidate.status.value,
            "phase": candidate.phase.value,
            "candidate_observations": candidate.candidate_observations,
            "already_hashed": candidate.already_hashed,
            "processed": candidate.processed_count,
            "hashed": candidate.hashed_count,
            "failures": candidate.failure_count,
            "remaining": candidate.remaining_count,
        }
        if (
            candidate.source_scan_run_id != scan.id
            or candidate.profile != POSTSCAN_CANDIDATE_HASH_PROFILE
        ):
            return _check(
                PostscanVerificationState.INVALID,
                "CANDIDATE_LINEAGE_MISMATCH",
                **details,
            )
        if candidate.status in {
            EbookCandidateHashRunStatus.RUNNING,
            EbookCandidateHashRunStatus.INTERRUPTED,
        }:
            return _check(
                PostscanVerificationState.PENDING,
                "CANDIDATE_RUN_NOT_COMPLETE",
                **details,
            )
        if candidate.status is EbookCandidateHashRunStatus.FAILED:
            return _check(
                PostscanVerificationState.INVALID,
                "CANDIDATE_RUN_FAILED",
                **details,
            )
        valid = (
            candidate.phase is EbookCandidateHashPhase.FINALIZING
            and candidate.finished_at is not None
            and candidate.lease_token is None
            and candidate.lease_expires_at is None
            and candidate.candidate_observations is not None
            and candidate.already_hashed is not None
            and candidate.remaining_count is not None
            and candidate.processed_count
            == candidate.hashed_count + candidate.failure_count
            and candidate.candidate_observations
            == candidate.already_hashed
            + candidate.hashed_count
            + candidate.remaining_count
        )
        if not valid:
            return _check(
                PostscanVerificationState.INVALID,
                "CANDIDATE_COUNTERS_INVALID",
                **details,
            )
        if candidate.status is EbookCandidateHashRunStatus.COMPLETED_WITH_FAILURES:
            return _check(
                PostscanVerificationState.DEGRADED,
                "CANDIDATE_HASH_FAILURES",
                **details,
            )
        if candidate.failure_count or candidate.remaining_count:
            return _check(
                PostscanVerificationState.INVALID,
                "CANDIDATE_COMPLETION_INVALID",
                **details,
            )
        return _check(PostscanVerificationState.COMPLETE, "VERIFIED", **details)

    def _collection_check(
        self,
        scan_root_id: EntityId,
        scan: ScanRun,
        run_id: EntityId,
        plan_per_format: int,
        inventory_snapshot: EbookInventoryReportSnapshot | None,
    ) -> PostscanVerificationCheck:
        store = SQLiteEbookCollectionStore(self._engine)
        try:
            run = store.get_run(run_id)
            if run is None:
                return _check(
                    PostscanVerificationState.PENDING,
                    "COLLECTION_RUN_MISSING",
                )
            counts = store.counts(run_id)
            format_counts = dict(store.format_counts(run_id))
        except EbookCollectionStoreError:
            return _check(
                PostscanVerificationState.INVALID,
                "COLLECTION_STATE_INVALID",
            )
        details = {
            "run_id": str(run.id),
            "source_scan_run_id": str(run.source_scan_run_id),
            "status": run.status.value,
            "planned": counts.planned,
            "terminal": counts.terminal,
            "pending": counts.pending,
            "running": counts.running,
            "partial_failure": counts.partial_failure,
            "failed": counts.failed,
            "error": counts.error,
            "formats": format_counts,
        }
        if (
            run.scan_root_id != scan_root_id
            or run.source_scan_run_id != scan.id
            or run.profile != EBOOK_COLLECTION_PROFILE
            or run.analysis_profile != EBOOK_ANALYSIS_PROFILE
        ):
            return _check(
                PostscanVerificationState.INVALID,
                "COLLECTION_LINEAGE_MISMATCH",
                **details,
            )
        if inventory_snapshot is None:
            return _check(
                PostscanVerificationState.PENDING,
                "COLLECTION_COVERAGE_NOT_VERIFIABLE",
                **details,
            )
        inventory_formats = {
            value.format_name: value.observations
            for value in inventory_snapshot.formats
        }
        expected_formats = {
            name: min(plan_per_format, inventory_formats.get(name, 0))
            for name in _FORMAT_ORDER
        }
        if format_counts != expected_formats or counts.planned != sum(
            expected_formats.values()
        ):
            return _check(
                PostscanVerificationState.INVALID,
                "COLLECTION_FORMAT_COVERAGE_INVALID",
                **details,
            )
        if run.status in {
            EbookCollectionRunStatus.RUNNING,
            EbookCollectionRunStatus.INTERRUPTED,
        }:
            return _check(
                PostscanVerificationState.PENDING,
                "COLLECTION_RUN_NOT_COMPLETE",
                **details,
            )
        if (
            run.lease_token is not None
            or run.lease_expires_at is not None
            or counts.pending
            or counts.running
            or counts.terminal != counts.planned
        ):
            return _check(
                PostscanVerificationState.INVALID,
                "COLLECTION_COMPLETION_INVALID",
                **details,
            )
        if (
            run.status is EbookCollectionRunStatus.COMPLETED_WITH_FAILURES
            or counts.partial_failure
            or counts.failed
            or counts.error
        ):
            return _check(
                PostscanVerificationState.DEGRADED,
                "COLLECTION_ANALYSIS_FAILURES",
                **details,
            )
        return _check(PostscanVerificationState.COMPLETE, "VERIFIED", **details)


def _check(
    state: PostscanVerificationState,
    code: str,
    **details: object,
) -> PostscanVerificationCheck:
    return PostscanVerificationCheck(state=state, code=code, details=details)
