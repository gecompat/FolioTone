"""Read-only application service for the book-only Library Health projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy.engine import Engine

from foliotone.collection_state.health import (
    DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT,
    MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING,
    LibraryHealthComparison,
    LibraryHealthDimensionSummary,
    LibraryHealthFinding,
    LibraryHealthSnapshot,
    compare_library_health,
)
from foliotone.core.ids import EntityId
from foliotone.persistence.library_health import (
    LibraryHealthStoreError,
    SQLiteLibraryHealthStore,
)

LIBRARY_HEALTH_REPORT_PROFILE: Final = "library-health-report/v1"


class LibraryHealthWorkflowError(RuntimeError):
    """A Library Health projection cannot be reported safely."""


@dataclass(frozen=True, slots=True)
class LibraryHealthReport:
    snapshot: LibraryHealthSnapshot
    comparison: LibraryHealthComparison | None = None
    sample_limit: int = DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT
    profile: str = LIBRARY_HEALTH_REPORT_PROFILE

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, LibraryHealthSnapshot):
            raise ValueError("Library Health report snapshot is invalid")
        if self.comparison is not None and not isinstance(self.comparison, LibraryHealthComparison):
            raise ValueError("Library Health report comparison is invalid")
        if isinstance(self.sample_limit, bool) or not (
            0 <= self.sample_limit <= MAX_LIBRARY_HEALTH_SAMPLES_PER_FINDING
        ):
            raise ValueError("Library Health sample limit is invalid")
        if self.profile != LIBRARY_HEALTH_REPORT_PROFILE:
            raise ValueError("Library Health report profile is invalid")

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "command": "library-health-report",
            "ok": True,
            "profile": self.profile,
            "health_profile": self.snapshot.profile,
            "health_snapshot_id": str(self.snapshot.id),
            "collection_state_snapshot_id": str(self.snapshot.collection_state_snapshot_id),
            "scan_root_id": str(self.snapshot.scan_root_id),
            "source_scan_run_id": str(self.snapshot.source_scan_run_id),
            "created_at": self.snapshot.created_at.isoformat(),
            "item_count": self.snapshot.item_count,
            "dimension_count": len(self.snapshot.dimensions),
            "finding_count": self.snapshot.finding_count,
            "sample_count": self.snapshot.sample_count,
            "dimensions": [
                _dimension_payload(dimension, self.sample_limit)
                for dimension in self.snapshot.dimensions
            ],
            "truncated": any(
                finding.samples_truncated or len(finding.samples) > self.sample_limit
                for dimension in self.snapshot.dimensions
                for finding in dimension.findings
            ),
        }
        if self.comparison is not None:
            payload["comparison"] = _comparison_payload(self.comparison)
        return payload


class SQLiteLibraryHealthReportReader:
    """Read and fully verify immutable Health rows through the supplied engine."""

    def __init__(self, engine: Engine, *, batch_size: int = 250) -> None:
        self._store = SQLiteLibraryHealthStore(engine, batch_size=batch_size)

    def read(
        self,
        snapshot_id: EntityId,
        *,
        baseline_snapshot_id: EntityId | None = None,
        sample_limit: int = DEFAULT_LIBRARY_HEALTH_DETAIL_LIMIT,
    ) -> LibraryHealthReport:
        try:
            snapshot = self._store.get_for_collection_state(snapshot_id)
            if snapshot is None:
                raise LibraryHealthWorkflowError("Library Health projection is unavailable")
            comparison = None
            if baseline_snapshot_id is not None:
                baseline = self._store.get_for_collection_state(baseline_snapshot_id)
                if baseline is None:
                    raise LibraryHealthWorkflowError(
                        "Library Health baseline projection is unavailable"
                    )
                comparison = compare_library_health(baseline, snapshot)
            return LibraryHealthReport(snapshot, comparison, sample_limit)
        except LibraryHealthWorkflowError:
            raise
        except (LibraryHealthStoreError, ValueError) as error:
            raise LibraryHealthWorkflowError(str(error)) from error


def _dimension_payload(
    dimension: LibraryHealthDimensionSummary, sample_limit: int
) -> dict[str, object]:
    return {
        "dimension": dimension.dimension.value,
        "status": dimension.status.value,
        "coverage": dimension.coverage_state.value,
        "assessed_item_count": dimension.assessed_item_count,
        "covered_item_count": dimension.covered_item_count,
        "affected_item_count": dimension.affected_item_count,
        "evidence_categories": [value.value for value in dimension.evidence_categories],
        "findings": [_finding_payload(finding, sample_limit) for finding in dimension.findings],
    }


def _finding_payload(finding: LibraryHealthFinding, sample_limit: int) -> dict[str, object]:
    samples = finding.samples[:sample_limit]
    return {
        "code": finding.code.value,
        "severity": finding.severity.value,
        "item_count": finding.item_count,
        "evidence_categories": [value.value for value in finding.evidence_categories],
        "samples": [
            {
                "file_id": str(sample.file_id),
                "observation_id": str(sample.observation_id),
            }
            for sample in samples
        ],
        "samples_truncated": finding.samples_truncated or len(finding.samples) > len(samples),
    }


def _comparison_payload(comparison: LibraryHealthComparison) -> dict[str, object]:
    return {
        "profile": comparison.profile,
        "before_health_snapshot_id": str(comparison.before_health_snapshot_id),
        "after_health_snapshot_id": str(comparison.after_health_snapshot_id),
        "scan_root_id": str(comparison.scan_root_id),
        "dimensions": [
            {
                "dimension": value.dimension.value,
                "before_status": value.before_status.value,
                "after_status": value.after_status.value,
                "before_coverage": value.before_coverage.value,
                "after_coverage": value.after_coverage.value,
                "before_affected_item_count": value.before_affected_item_count,
                "after_affected_item_count": value.after_affected_item_count,
                "affected_item_delta": value.affected_item_delta,
            }
            for value in comparison.dimension_deltas
        ],
        "findings": [
            {
                "dimension": value.dimension.value,
                "code": value.code.value,
                "before_item_count": value.before_item_count,
                "after_item_count": value.after_item_count,
                "item_delta": value.item_delta,
            }
            for value in comparison.finding_deltas
        ],
    }
