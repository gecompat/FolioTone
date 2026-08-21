"""Stable path-free report for one persisted archive collection run."""

from __future__ import annotations

import re
from dataclasses import dataclass

from foliotone.archive.signatures import (
    ArchiveListingStatus,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
)
from foliotone.archive.workflow import ArchiveEncryptionStatus, ArchiveIntegrityStatus
from foliotone.core import (
    ArchiveCollectionDisposition,
    ArchiveCollectionItemStatus,
    ArchiveCollectionPlanFindingCounts,
    ArchiveCollectionRunStatus,
    EntityId,
)
from foliotone.persistence.archive_collection import (
    ArchiveCollectionStoreError,
    SQLiteArchiveCollectionStore,
    _ArchiveCollectionLiteralCount,
    _ArchiveCollectionReportSnapshot,
)


class ArchiveCollectionReportError(RuntimeError):
    """The persisted aggregate cannot be exposed safely."""


_ERROR_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionStatusCounts:
    planned: int
    pending: int
    running: int
    succeeded: int
    failed: int
    error: int
    executed: int
    reused: int

    def __post_init__(self) -> None:
        values = (
            self.planned,
            self.pending,
            self.running,
            self.succeeded,
            self.failed,
            self.error,
            self.executed,
            self.reused,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ValueError("archive collection report counts are invalid")
        if self.pending + self.running + self.succeeded + self.failed + self.error != self.planned:
            raise ValueError("archive collection report item counts are inconsistent")
        if self.executed + self.reused != self.succeeded + self.failed:
            raise ValueError("archive collection report disposition counts are inconsistent")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionStatusReport:
    run_id: EntityId
    profile: str
    status: ArchiveCollectionRunStatus
    source_scan_run_id: EntityId
    counts: ArchiveCollectionStatusCounts
    plan_findings: ArchiveCollectionPlanFindingCounts
    listing_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    integrity_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    encryption_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    recognition_statuses: tuple[_ArchiveCollectionLiteralCount, ...]
    storage_families: tuple[_ArchiveCollectionLiteralCount, ...]
    error_codes: tuple[_ArchiveCollectionLiteralCount, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, EntityId) or not isinstance(
            self.source_scan_run_id, EntityId
        ):
            raise ValueError("archive collection report IDs are invalid")
        if self.profile != "archive-collection-orchestration/v1":
            raise ValueError("archive collection report profile is invalid")
        if not isinstance(self.status, ArchiveCollectionRunStatus):
            raise ValueError("archive collection report status is invalid")
        if not isinstance(self.counts, ArchiveCollectionStatusCounts) or not isinstance(
            self.plan_findings, ArchiveCollectionPlanFindingCounts
        ):
            raise ValueError("archive collection report material is invalid")
        allowed = (
            {value.value for value in ArchiveListingStatus},
            {value.value for value in ArchiveIntegrityStatus},
            {value.value for value in ArchiveEncryptionStatus},
            {value.value for value in ArchiveRecognitionStatus},
            {value.value for value in ArchiveStorageFamily},
        )
        for values, literals in zip(
            (
                self.listing_statuses,
                self.integrity_statuses,
                self.encryption_statuses,
                self.recognition_statuses,
                self.storage_families,
            ),
            allowed,
            strict=True,
        ):
            if (
                not isinstance(values, tuple)
                or any(not isinstance(value, _ArchiveCollectionLiteralCount) for value in values)
                or any(value.literal not in literals for value in values)
                or tuple(value.literal for value in values)
                != tuple(sorted(value.literal for value in values))
                or len({value.literal for value in values}) != len(values)
            ):
                raise ValueError("archive collection report literal is unsupported")
        if (
            not isinstance(self.error_codes, tuple)
            or any(
                not isinstance(value, _ArchiveCollectionLiteralCount)
                or _ERROR_CODE_PATTERN.fullmatch(value.literal) is None
                for value in self.error_codes
            )
            or tuple(value.literal for value in self.error_codes)
            != tuple(sorted(value.literal for value in self.error_codes))
            or len({value.literal for value in self.error_codes})
            != len(self.error_codes)
        ):
            raise ValueError("archive collection report error code is invalid")
        archive_count = self.counts.succeeded + self.counts.failed
        if any(
            sum(value.count for value in values) != archive_count
            for values in (
                self.listing_statuses,
                self.integrity_statuses,
                self.encryption_statuses,
                self.recognition_statuses,
                self.storage_families,
            )
        ) or sum(value.count for value in self.error_codes) != (
            self.counts.failed + self.counts.error
        ):
            raise ValueError("archive collection report aggregates are inconsistent")
        if self.truncated is not False:
            raise ValueError("archive collection aggregate report cannot be truncated")

    @classmethod
    def from_snapshot(
        cls, snapshot: _ArchiveCollectionReportSnapshot
    ) -> ArchiveCollectionStatusReport:
        if not isinstance(snapshot, _ArchiveCollectionReportSnapshot):
            raise TypeError("snapshot must be an archive collection report snapshot")
        statuses = {value.literal: value.count for value in snapshot.item_statuses}
        dispositions = {value.literal: value.count for value in snapshot.dispositions}
        run = snapshot.run
        return cls(
            run.id,
            run.profile,
            run.status,
            run.source_scan_run_id,
            ArchiveCollectionStatusCounts(
                run.planned_count,
                statuses.get(ArchiveCollectionItemStatus.PENDING.value, 0),
                statuses.get(ArchiveCollectionItemStatus.RUNNING.value, 0),
                statuses.get(ArchiveCollectionItemStatus.SUCCEEDED.value, 0),
                statuses.get(ArchiveCollectionItemStatus.FAILED.value, 0),
                statuses.get(ArchiveCollectionItemStatus.ERROR.value, 0),
                dispositions.get(ArchiveCollectionDisposition.EXECUTED.value, 0),
                dispositions.get(ArchiveCollectionDisposition.REUSED.value, 0),
            ),
            run.plan_findings,
            snapshot.listing_statuses,
            snapshot.integrity_statuses,
            snapshot.encryption_statuses,
            snapshot.recognition_statuses,
            snapshot.storage_families,
            snapshot.error_codes,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "archive-collection-status",
            "ok": True,
            "run_id": str(self.run_id),
            "profile": self.profile,
            "status": self.status.value,
            "source_scan_run_id": str(self.source_scan_run_id),
            "counts": {
                "planned": self.counts.planned,
                "pending": self.counts.pending,
                "running": self.counts.running,
                "succeeded": self.counts.succeeded,
                "failed": self.counts.failed,
                "error": self.counts.error,
                "executed": self.counts.executed,
                "reused": self.counts.reused,
            },
            "plan_findings": {
                "hash_evidence_missing": self.plan_findings.hash_evidence_missing,
                "missing_volume": self.plan_findings.missing_volume,
                "unsupported_volume": self.plan_findings.unsupported_volume,
                "ambiguous_volume": self.plan_findings.ambiguous_volume,
                "name_collision": self.plan_findings.name_collision,
                "orphan_volume": self.plan_findings.orphan_volume,
            },
            "listing_statuses": _payload_counts(self.listing_statuses),
            "integrity_statuses": _payload_counts(self.integrity_statuses),
            "encryption_statuses": _payload_counts(self.encryption_statuses),
            "recognition_statuses": _payload_counts(self.recognition_statuses),
            "storage_families": _payload_counts(self.storage_families),
            "error_codes": _payload_counts(self.error_codes),
            "truncated": False,
        }


class SQLiteArchiveCollectionReportReader:
    def __init__(self, store: SQLiteArchiveCollectionStore) -> None:
        if type(store) is not SQLiteArchiveCollectionStore:
            raise ValueError("archive collection report requires the exact store")
        self._store = store

    def read(self, run_id: EntityId) -> ArchiveCollectionStatusReport:
        try:
            snapshot = self._store._read_report_snapshot(run_id)
        except (ArchiveCollectionStoreError, ValueError):
            raise ArchiveCollectionReportError(
                "archive collection status is unavailable"
            ) from None
        if snapshot is None:
            raise ArchiveCollectionReportError(
                "archive collection status is unavailable"
            )
        try:
            return ArchiveCollectionStatusReport.from_snapshot(snapshot)
        except (TypeError, ValueError):
            raise ArchiveCollectionReportError(
                "archive collection status is unavailable"
            ) from None


def _payload_counts(
    values: tuple[_ArchiveCollectionLiteralCount, ...],
) -> list[dict[str, object]]:
    return [
        {"literal": value.literal, "count": value.count}
        for value in values
    ]
