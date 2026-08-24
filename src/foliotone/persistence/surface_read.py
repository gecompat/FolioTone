"""Path-free SQLite read adapter for the local E-Book product surface."""

from __future__ import annotations

from sqlalchemy import Engine, select

from foliotone.core import EntityId
from foliotone.persistence import consolidation_schema, schema, w3_schema
from foliotone.persistence.consolidation_report import SQLiteConsolidationPlanReportReader
from foliotone.persistence.ebook_collection_report import (
    EbookCollectionCandidateSet,
    EbookCollectionReportSnapshot,
    SQLiteEbookCollectionReportStore,
)
from foliotone.persistence.ebook_inventory_report import SQLiteEbookInventoryReportStore


class SQLiteEbookSurfaceReadModel:
    """Read existing projections without exposing source locators or raw values."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._inventory = SQLiteEbookInventoryReportStore(engine)
        self._collection = SQLiteEbookCollectionReportStore(engine)

    def scan_status(self, scan_root_id: EntityId) -> dict[str, object] | None:
        with self._engine.connect() as connection:
            scan = (
                connection.execute(
                    select(
                        schema.scan_runs.c.id,
                        schema.scan_runs.c.status,
                        schema.scan_runs.c.started_at,
                        schema.scan_runs.c.completed_at,
                    )
                    .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
                    .order_by(schema.scan_runs.c.started_at.desc(), schema.scan_runs.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            candidate = (
                connection.execute(
                    select(
                        w3_schema.ebook_candidate_hash_runs.c.id,
                        w3_schema.ebook_candidate_hash_runs.c.status,
                        w3_schema.ebook_candidate_hash_runs.c.phase,
                        w3_schema.ebook_candidate_hash_runs.c.processed_count,
                        w3_schema.ebook_candidate_hash_runs.c.hashed_count,
                        w3_schema.ebook_candidate_hash_runs.c.failure_count,
                        w3_schema.ebook_candidate_hash_runs.c.remaining_count,
                    )
                    .where(w3_schema.ebook_candidate_hash_runs.c.scan_root_id == str(scan_root_id))
                    .order_by(
                        w3_schema.ebook_candidate_hash_runs.c.started_at.desc(),
                        w3_schema.ebook_candidate_hash_runs.c.id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if scan is None:
            return None
        return {
            "scan_root_id": str(scan_root_id),
            "scan_run_id": str(scan["id"]),
            "status": str(scan["status"]),
            "started_at": str(scan["started_at"]),
            "completed_at": None if scan["completed_at"] is None else str(scan["completed_at"]),
            "candidate_hash": None
            if candidate is None
            else {
                "run_id": str(candidate["id"]),
                "status": str(candidate["status"]),
                "phase": str(candidate["phase"]),
                "processed": int(candidate["processed_count"]),
                "hashed": int(candidate["hashed_count"]),
                "failures": int(candidate["failure_count"]),
                "remaining": candidate["remaining_count"],
            },
        }

    def inventory(self, scan_root_id: EntityId) -> dict[str, object] | None:
        try:
            snapshot = self._inventory.snapshot(
                scan_root_id, candidate_group_limit=100, candidate_member_limit=100
            )
        except RuntimeError:
            return None
        return {
            "scan_run_id": str(snapshot.scan.id),
            "observations": snapshot.observations,
            "total_bytes": snapshot.total_bytes,
            "formats": [
                {"format": item.format_name, "observations": item.observations}
                for item in snapshot.formats
            ],
            "candidate_hash_coverage": {
                "full_hash_observations": snapshot.full_hash_observations,
                "quick_candidate_groups": snapshot.quick_candidate_groups,
                "quick_candidate_observations": snapshot.quick_candidate_observations,
                "missing_full_hash": snapshot.quick_candidates_missing_full_hash,
            },
            "exact_duplicate_evidence": {
                "groups": snapshot.exact_duplicates.total_groups,
                "members": snapshot.exact_duplicates.total_members,
                "redundant_bytes": snapshot.exact_duplicates.total_redundant_bytes,
            },
        }

    def collection_analysis(self, run_id: EntityId) -> dict[str, object] | None:
        snapshot = self._snapshot(run_id)
        if snapshot is None:
            return None
        return {
            "collection_run_id": str(snapshot.run.id),
            "scan_root_id": str(snapshot.run.scan_root_id),
            "source_scan_run_id": str(snapshot.run.source_scan_run_id),
            "status": snapshot.run.status.value,
            "counts": {
                "planned": snapshot.counts.planned,
                "pending": snapshot.counts.pending,
                "running": snapshot.counts.running,
                "succeeded": snapshot.counts.succeeded,
                "partial_failure": snapshot.counts.partial_failure,
                "failed": snapshot.counts.failed,
                "error": snapshot.counts.error,
                "findings": snapshot.counts.findings,
            },
            "format_coverage": dict(snapshot.format_counts),
            "analysis_coverage": dict(snapshot.analysis_status_counts),
            "quality_coverage": dict(snapshot.quality_status_counts),
            "finding_counts": [
                {
                    "code": finding.code,
                    "dimension": finding.dimension,
                    "severity": finding.severity,
                    "count": finding.count,
                }
                for finding in snapshot.finding_counts
            ],
            "review_item_count": snapshot.review_item_total,
        }

    def review_queue(
        self, run_id: EntityId, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        snapshot = self._snapshot(run_id, review_limit=100)
        if snapshot is None:
            return (), None
        rows = [
            item
            for item in snapshot.review_items
            if after_id is None or str(item.observation_id) > after_id
        ]
        page = rows[:limit]
        return (
            tuple(
                {
                    "observation_id": str(item.observation_id),
                    "priority": item.priority,
                    "format": item.format_name,
                    "analysis_status": item.analysis_status,
                    "quality_status": item.quality_status,
                    "error_code": item.error_code,
                    "findings": [
                        {
                            "code": finding.code,
                            "dimension": finding.dimension,
                            "severity": finding.severity,
                        }
                        for finding in item.findings
                    ],
                }
                for item in page
            ),
            None if len(rows) <= limit else str(page[-1].observation_id),
        )

    def candidate_evidence(self, run_id: EntityId) -> dict[str, object] | None:
        snapshot = self._snapshot(run_id)
        if snapshot is None:
            return None
        return {
            "collection_run_id": str(snapshot.run.id),
            "exact_duplicates": _candidate_set(snapshot.exact_duplicates),
            "content_variants": _candidate_set(snapshot.content_variants),
        }

    def list_plans(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        statement = (
            select(
                consolidation_schema.consolidation_plans.c.id,
                consolidation_schema.consolidation_plans.c.profile,
                consolidation_schema.consolidation_plans.c.status,
                consolidation_schema.consolidation_plans.c.execution_state,
                consolidation_schema.consolidation_plans.c.created_at,
            )
            .order_by(consolidation_schema.consolidation_plans.c.id)
            .limit(limit + 1)
        )
        if after_id is not None:
            statement = statement.where(consolidation_schema.consolidation_plans.c.id > after_id)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        visible = rows[:limit]
        return (
            tuple(
                {
                    "plan_id": str(row["id"]),
                    "profile": str(row["profile"]),
                    "status": str(row["status"]),
                    "execution_state": str(row["execution_state"]),
                    "created_at": str(row["created_at"]),
                }
                for row in visible
            ),
            None if len(rows) <= limit else str(visible[-1]["id"]),
        )

    def plan_report(self, plan_id: EntityId) -> dict[str, object] | None:
        try:
            report = SQLiteConsolidationPlanReportReader(self._engine).read(plan_id)
        except RuntimeError:
            return None
        payload = report.payload()
        payload.pop("content_hash", None)
        payload.pop("keeper_file_id", None)
        payload.pop("candidate_file_id", None)
        return payload

    def _snapshot(
        self, run_id: EntityId, *, review_limit: int = 100
    ) -> EbookCollectionReportSnapshot | None:
        try:
            return self._collection.snapshot(
                run_id,
                review_item_limit=review_limit,
                candidate_group_limit=100,
                candidate_member_limit=100,
            )
        except RuntimeError:
            return None


def _candidate_set(value: EbookCollectionCandidateSet) -> dict[str, object]:
    groups = value.groups
    return {
        "groups": value.total_groups,
        "members": value.total_members,
        "items": [
            {
                "group_id": group.group_id,
                "basis": group.basis,
                "member_count": group.member_count,
                "members": [
                    {
                        "observation_id": str(member.observation_id),
                        "format": member.format_name,
                    }
                    for member in group.members
                ],
            }
            for group in groups
        ],
    }
