"""Read-only aggregate queries for persisted Calibre reconciliation snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, Engine, func, select

from foliotone.core import EntityId
from foliotone.persistence import calibre_library_schema as schema

CALIBRE_RECONCILIATION_REPORT_PROFILE = "calibre-reconciliation-report/v1"
CALIBRE_RECONCILIATION_FINDING_CODES = (
    "FILESYSTEM_ONLY",
    "CALIBRE_RECORD_WITHOUT_FILE",
    "CALIBRE_DUPLICATE_RECORD_CANDIDATE",
    "CALIBRE_MULTI_FORMAT_RECORD",
    "CALIBRE_METADATA_CONFLICT",
    "CALIBRE_AUTHORITY_CONFLICT",
    "CALIBRE_SIDECAR_DEPENDENCY",
)


class CalibreLibraryReportReaderError(RuntimeError):
    """A persisted Calibre report projection cannot be read."""


@dataclass(frozen=True, slots=True)
class CalibreReconciliationReportCounts:
    """Path-free row counts for one persisted reconciliation snapshot."""

    records: int
    formats: int
    sidecars: int
    findings: int
    review_required: int
    refs: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                self.records,
                self.formats,
                self.sidecars,
                self.findings,
                self.review_required,
                self.refs,
            )
        ):
            raise ValueError("Calibre report counts must be nonnegative integers")


@dataclass(frozen=True, slots=True)
class CalibreReconciliationReport:
    """Immutable, path-free report projection of persisted reconciliation data."""

    snapshot_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    snapshot_status: str
    counts: CalibreReconciliationReportCounts
    finding_counts: tuple[tuple[str, int], ...]
    profile: str = CALIBRE_RECONCILIATION_REPORT_PROFILE

    def __post_init__(self) -> None:
        if self.profile != CALIBRE_RECONCILIATION_REPORT_PROFILE:
            raise ValueError("Calibre report profile is invalid")
        if self.snapshot_status not in {"RUNNING", "COMPLETED", "INVALIDATED", "FAILED"}:
            raise ValueError("Calibre snapshot status is invalid")
        if tuple(code for code, _count in self.finding_counts) != (
            CALIBRE_RECONCILIATION_FINDING_CODES
        ) or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for _code, count in self.finding_counts
        ):
            raise ValueError("Calibre finding counts are invalid")

    def payload(self) -> dict[str, object]:
        """Return the stable machine-readable report contract."""

        return {
            "schema_version": 1,
            "command": "calibre-reconciliation-report",
            "ok": True,
            "profile": self.profile,
            "snapshot_id": str(self.snapshot_id),
            "scan_root_id": str(self.scan_root_id),
            "source_scan_run_id": str(self.source_scan_run_id),
            "snapshot_status": self.snapshot_status,
            "counts": {
                "records": self.counts.records,
                "formats": self.counts.formats,
                "sidecars": self.counts.sidecars,
                "findings": self.counts.findings,
                "review_required": self.counts.review_required,
                "refs": self.counts.refs,
            },
            "finding_counts": {code: count for code, count in self.finding_counts},
        }

    @property
    def records(self) -> int:
        return self.counts.records

    @property
    def formats(self) -> int:
        return self.counts.formats

    @property
    def sidecars(self) -> int:
        return self.counts.sidecars

    @property
    def findings(self) -> int:
        return self.counts.findings

    @property
    def review_required(self) -> int:
        return self.counts.review_required

    @property
    def refs(self) -> int:
        return self.counts.refs


class SQLiteCalibreLibraryReportReader:
    """Read one persisted Calibre report snapshot using SELECT statements only."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(self, snapshot_id: EntityId) -> CalibreReconciliationReport:
        """Read one persisted report projection in a single read transaction."""

        with self._engine.connect() as connection, connection.begin():
            scan_root_id, source_scan_run_id, status = self._snapshot_lineage(
                connection, snapshot_id
            )
            counts = self._counts(connection, snapshot_id)
            finding_counts = self._finding_counts(connection, snapshot_id)
            return CalibreReconciliationReport(
                snapshot_id=snapshot_id,
                scan_root_id=scan_root_id,
                source_scan_run_id=source_scan_run_id,
                snapshot_status=status,
                counts=counts,
                finding_counts=finding_counts,
            )

    # ``snapshot`` mirrors the naming of the other persisted report readers and
    # keeps the public reader convenient for callers that use that convention.
    snapshot = read
    report = read

    @staticmethod
    def _snapshot_lineage(
        connection: Connection, snapshot_id: EntityId
    ) -> tuple[EntityId, EntityId, str]:
        row = connection.execute(
            select(
                schema.calibre_library_snapshots.c.scan_root_id,
                schema.calibre_library_snapshots.c.source_scan_run_id,
                schema.calibre_library_snapshots.c.status,
            ).where(
                schema.calibre_library_snapshots.c.id == str(snapshot_id)
            )
        ).one_or_none()
        if row is None:
            raise CalibreLibraryReportReaderError("Calibre snapshot does not exist")
        status = str(row.status)
        if status not in {"RUNNING", "COMPLETED", "INVALIDATED", "FAILED"}:
            raise CalibreLibraryReportReaderError("Calibre snapshot status is invalid")
        return EntityId.parse(str(row.scan_root_id)), EntityId.parse(
            str(row.source_scan_run_id)
        ), status

    @staticmethod
    def _counts(
        connection: Connection,
        snapshot_id: EntityId,
    ) -> CalibreReconciliationReportCounts:
        snapshot = str(snapshot_id)
        records = schema.calibre_library_records
        formats = schema.calibre_library_formats
        sidecars = schema.calibre_library_sidecars
        findings = schema.calibre_reconciliation_findings
        refs = schema.calibre_reconciliation_finding_refs
        record_count = connection.execute(
            select(func.count()).select_from(records).where(records.c.snapshot_id == snapshot)
        ).scalar_one()
        format_count = connection.execute(
            select(func.count())
            .select_from(formats.join(records, formats.c.record_snapshot_id == records.c.id))
            .where(records.c.snapshot_id == snapshot)
        ).scalar_one()
        sidecar_count = connection.execute(
            select(func.count())
            .select_from(sidecars.join(records, sidecars.c.record_snapshot_id == records.c.id))
            .where(records.c.snapshot_id == snapshot)
        ).scalar_one()
        finding_count = connection.execute(
            select(func.count()).select_from(findings).where(findings.c.snapshot_id == snapshot)
        ).scalar_one()
        review_count = connection.execute(
            select(func.count())
            .select_from(findings)
            .where(findings.c.snapshot_id == snapshot, findings.c.review_required.is_(True))
        ).scalar_one()
        ref_count = connection.execute(
            select(func.count())
            .select_from(refs.join(findings, refs.c.finding_id == findings.c.id))
            .where(findings.c.snapshot_id == snapshot)
        ).scalar_one()
        return CalibreReconciliationReportCounts(
            records=int(record_count),
            formats=int(format_count),
            sidecars=int(sidecar_count),
            findings=int(finding_count),
            review_required=int(review_count),
            refs=int(ref_count),
        )

    @staticmethod
    def _finding_counts(
        connection: Connection,
        snapshot_id: EntityId,
    ) -> tuple[tuple[str, int], ...]:
        findings = schema.calibre_reconciliation_findings
        rows = connection.execute(
            select(findings.c.code, func.count().label("count"))
            .where(findings.c.snapshot_id == str(snapshot_id))
            .group_by(findings.c.code)
        ).all()
        counts = {str(row[0]): int(row[1]) for row in rows}
        return tuple((code, counts.get(code, 0)) for code in CALIBRE_RECONCILIATION_FINDING_CODES)


# Naming aliases keep the snapshot terminology used by the other persisted
# report readers available without introducing a second mutable representation.
CalibreReconciliationReportSnapshot = CalibreReconciliationReport
