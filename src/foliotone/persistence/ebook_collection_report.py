"""Bounded snapshot queries for deterministic private collection reports."""

from __future__ import annotations

import hashlib
import heapq
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, Select, and_, case, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import ColumnElement

from foliotone.core import (
    EbookCollectionItemStatus,
    EbookCollectionRun,
    EbookCollectionRunStatus,
    EntityId,
    EntityKind,
)
from foliotone.persistence import schema, w3_schema
from foliotone.persistence.codecs import codec_for
from foliotone.persistence.ebook_collection import EbookCollectionCounts

EBOOK_COLLECTION_REPORT_FETCH_SIZE = 500
FILE_SHA256_KIND = "FILE_SHA256"
FILE_SHA256_ALGORITHM = "sha256"
FILE_SHA256_VERSION = "1"
NORMALIZED_TEXT_KIND = "EBOOK_NORMALIZED_TEXT"

_FORMAT_ORDER = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")
_ANALYSIS_STATUS_ORDER = tuple(status.value for status in EbookCollectionItemStatus)
_QUALITY_STATUS_ORDER = (
    "OK",
    "REVIEW",
    "ACTION_REQUIRED",
    "INCOMPLETE",
    "UNAVAILABLE",
)
_REVIEW_PRIORITY_LABELS = {
    0: "ANALYSIS_ERROR",
    1: "ANALYSIS_FAILED",
    2: "NOT_ANALYZED",
    3: "ACTION_REQUIRED",
    4: "INCOMPLETE",
    5: "PARTIAL_FAILURE",
    6: "REVIEW",
}


class EbookCollectionReportStoreError(RuntimeError):
    """A persisted collection run cannot produce a consistent report snapshot."""


@dataclass(frozen=True, slots=True)
class EbookCollectionFindingAggregate:
    code: str
    dimension: str
    severity: str
    count: int


@dataclass(frozen=True, slots=True)
class EbookCollectionReviewFinding:
    code: str
    dimension: str
    severity: str
    source_execution_ids: tuple[EntityId, ...]


@dataclass(frozen=True, slots=True)
class EbookCollectionReviewItem:
    priority: str
    ordinal: int
    observation_id: EntityId
    relative_path: str
    format_name: str
    analysis_status: str
    quality_status: str | None
    error_code: str | None
    findings: tuple[EbookCollectionReviewFinding, ...]


@dataclass(frozen=True, slots=True)
class EbookCollectionCandidateMember:
    ordinal: int
    observation_id: EntityId
    relative_path: str
    format_name: str


@dataclass(frozen=True, slots=True)
class EbookCollectionCandidateGroup:
    group_id: str
    basis: str
    member_count: int
    members: tuple[EbookCollectionCandidateMember, ...]

    @property
    def members_truncated(self) -> bool:
        return len(self.members) < self.member_count


@dataclass(frozen=True, slots=True)
class EbookCollectionCandidateSet:
    total_groups: int
    total_members: int
    groups: tuple[EbookCollectionCandidateGroup, ...]

    @property
    def emitted_members(self) -> int:
        return sum(len(group.members) for group in self.groups)

    @property
    def groups_truncated(self) -> bool:
        return len(self.groups) < self.total_groups

    @property
    def members_truncated(self) -> bool:
        return self.emitted_members < self.total_members


@dataclass(frozen=True, slots=True)
class EbookCollectionReportSnapshot:
    run: EbookCollectionRun
    counts: EbookCollectionCounts
    format_counts: tuple[tuple[str, int], ...]
    analysis_status_counts: tuple[tuple[str, int], ...]
    quality_status_counts: tuple[tuple[str, int], ...]
    finding_counts: tuple[EbookCollectionFindingAggregate, ...]
    review_item_total: int
    review_items: tuple[EbookCollectionReviewItem, ...]
    exact_duplicates: EbookCollectionCandidateSet
    content_variants: EbookCollectionCandidateSet


class SQLiteEbookCollectionReportStore:
    """Read one consistent collection report snapshot with bounded outputs."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._run_codec = codec_for(EbookCollectionRun)

    def snapshot(
        self,
        run_id: EntityId,
        *,
        review_item_limit: int,
        candidate_group_limit: int,
        candidate_member_limit: int,
    ) -> EbookCollectionReportSnapshot:
        for value, name in (
            (review_item_limit, "review_item_limit"),
            (candidate_group_limit, "candidate_group_limit"),
            (candidate_member_limit, "candidate_member_limit"),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        with self._engine.connect() as connection, connection.begin():
            run = self._get_run(connection, run_id)
            if run is None:
                raise EbookCollectionReportStoreError("collection run does not exist")
            if run.status is EbookCollectionRunStatus.RUNNING:
                raise EbookCollectionReportStoreError(
                    "running collection run cannot produce a stable report"
                )
            counts = self._counts(connection, run_id)
            self._validate_execution_projection(connection, run_id)
            self._validate_finding_projection(connection, run_id, counts)
            format_counts = self._simple_counts(
                connection,
                run_id,
                w3_schema.ebook_collection_items.c.format_name,
                _FORMAT_ORDER,
            )
            analysis_status_counts = self._simple_counts(
                connection,
                run_id,
                w3_schema.ebook_collection_items.c.status,
                _ANALYSIS_STATUS_ORDER,
            )
            quality_status_counts = self._quality_counts(connection, run_id)
            finding_counts = self._finding_counts(connection, run_id)
            review_total, review_items = self._review_items(
                connection,
                run_id,
                limit=review_item_limit,
            )
            exact_duplicates = self._candidate_groups(
                connection,
                self._exact_duplicate_statement(run_id),
                basis="EXACT_FILE_SHA256",
                group_limit=candidate_group_limit,
                member_limit=candidate_member_limit,
                require_distinct_file_values=False,
            )
            content_variants = self._candidate_groups(
                connection,
                self._content_variant_statement(run_id),
                basis="SAME_NORMALIZED_TEXT_DIFFERENT_FILE_SHA256",
                group_limit=candidate_group_limit,
                member_limit=candidate_member_limit,
                require_distinct_file_values=True,
            )
            return EbookCollectionReportSnapshot(
                run=run,
                counts=counts,
                format_counts=format_counts,
                analysis_status_counts=analysis_status_counts,
                quality_status_counts=quality_status_counts,
                finding_counts=finding_counts,
                review_item_total=review_total,
                review_items=review_items,
                exact_duplicates=exact_duplicates,
                content_variants=content_variants,
            )

    def _get_run(
        self,
        connection: Connection,
        run_id: EntityId,
    ) -> EbookCollectionRun | None:
        row = connection.execute(
            select(w3_schema.ebook_collection_runs).where(
                w3_schema.ebook_collection_runs.c.id == str(run_id)
            )
        ).mappings().one_or_none()
        return None if row is None else self._run_codec.decode(row)

    @staticmethod
    def _counts(connection: Connection, run_id: EntityId) -> EbookCollectionCounts:
        rows = connection.execute(
            select(
                w3_schema.ebook_collection_items.c.status,
                func.count().label("count"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.reused_step_count), 0
                ).label("reused_steps"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.executed_step_count), 0
                ).label("executed_steps"),
                func.coalesce(
                    func.sum(w3_schema.ebook_collection_items.c.finding_count), 0
                ).label("findings"),
            )
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
            .group_by(w3_schema.ebook_collection_items.c.status)
        ).mappings().all()
        values = {str(row["status"]): int(row["count"]) for row in rows}
        return EbookCollectionCounts(
            planned=sum(values.values()),
            pending=values.get(EbookCollectionItemStatus.PENDING.value, 0),
            running=values.get(EbookCollectionItemStatus.RUNNING.value, 0),
            succeeded=values.get(EbookCollectionItemStatus.SUCCEEDED.value, 0),
            partial_failure=values.get(
                EbookCollectionItemStatus.PARTIAL_FAILURE.value, 0
            ),
            failed=values.get(EbookCollectionItemStatus.FAILED.value, 0),
            error=values.get(EbookCollectionItemStatus.ERROR.value, 0),
            reused_steps=sum(int(row["reused_steps"]) for row in rows),
            executed_steps=sum(int(row["executed_steps"]) for row in rows),
            findings=sum(int(row["findings"]) for row in rows),
        )

    @staticmethod
    def _validate_execution_projection(
        connection: Connection,
        run_id: EntityId,
    ) -> None:
        item = w3_schema.ebook_collection_items
        execution = w3_schema.ebook_collection_item_executions
        projected = (
            select(
                execution.c.item_id,
                func.count(func.distinct(execution.c.step_name)).label("all_steps"),
                func.count(
                    func.distinct(
                        case(
                            (
                                execution.c.disposition == "REUSED",
                                execution.c.step_name,
                            )
                        )
                    )
                ).label("reused_steps"),
                func.count(
                    func.distinct(
                        case(
                            (
                                execution.c.disposition == "EXECUTED",
                                execution.c.step_name,
                            )
                        )
                    )
                ).label("executed_steps"),
            )
            .group_by(execution.c.item_id)
            .subquery("collection_execution_projection")
        )
        mismatch_count = connection.execute(
            select(func.count())
            .select_from(
                item.outerjoin(projected, projected.c.item_id == item.c.id)
            )
            .where(
                item.c.run_id == str(run_id),
                or_(
                    func.coalesce(projected.c.all_steps, 0)
                    != item.c.reused_step_count + item.c.executed_step_count,
                    func.coalesce(projected.c.reused_steps, 0)
                    != item.c.reused_step_count,
                    func.coalesce(projected.c.executed_steps, 0)
                    != item.c.executed_step_count,
                ),
            )
        ).scalar_one()
        if int(mismatch_count):
            raise EbookCollectionReportStoreError(
                "collection execution projection is incomplete for this run"
            )

    @staticmethod
    def _validate_finding_projection(
        connection: Connection,
        run_id: EntityId,
        counts: EbookCollectionCounts,
    ) -> None:
        persisted = connection.execute(
            select(func.count())
            .select_from(
                w3_schema.ebook_collection_findings.join(
                    w3_schema.ebook_collection_items,
                    w3_schema.ebook_collection_items.c.id
                    == w3_schema.ebook_collection_findings.c.item_id,
                )
            )
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
        ).scalar_one()
        if int(persisted) != counts.findings:
            raise EbookCollectionReportStoreError(
                "collection finding projection is incomplete for this run"
            )

    @staticmethod
    def _simple_counts(
        connection: Connection,
        run_id: EntityId,
        column: ColumnElement[str],
        expected_order: tuple[str, ...],
    ) -> tuple[tuple[str, int], ...]:
        rows = connection.execute(
            select(column, func.count().label("count"))
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
            .group_by(column)
        ).all()
        values = {str(row[0]): int(row[1]) for row in rows}
        unknown = set(values).difference(expected_order)
        if unknown:
            raise EbookCollectionReportStoreError("collection count contains unknown state")
        return tuple((key, values.get(key, 0)) for key in expected_order)

    @staticmethod
    def _quality_counts(
        connection: Connection,
        run_id: EntityId,
    ) -> tuple[tuple[str, int], ...]:
        key = func.coalesce(
            w3_schema.ebook_collection_items.c.quality_status,
            "UNAVAILABLE",
        )
        rows = connection.execute(
            select(key.label("quality_status"), func.count().label("count"))
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
            .group_by(key)
        ).mappings().all()
        values = {str(row["quality_status"]): int(row["count"]) for row in rows}
        if set(values).difference(_QUALITY_STATUS_ORDER):
            raise EbookCollectionReportStoreError("collection quality state is unknown")
        return tuple((key, values.get(key, 0)) for key in _QUALITY_STATUS_ORDER)

    @staticmethod
    def _finding_counts(
        connection: Connection,
        run_id: EntityId,
    ) -> tuple[EbookCollectionFindingAggregate, ...]:
        count = func.count().label("count")
        rows = connection.execute(
            select(
                w3_schema.ebook_collection_findings.c.code,
                w3_schema.ebook_collection_findings.c.dimension,
                w3_schema.ebook_collection_findings.c.severity,
                count,
            )
            .select_from(
                w3_schema.ebook_collection_findings.join(
                    w3_schema.ebook_collection_items,
                    w3_schema.ebook_collection_items.c.id
                    == w3_schema.ebook_collection_findings.c.item_id,
                )
            )
            .where(w3_schema.ebook_collection_items.c.run_id == str(run_id))
            .group_by(
                w3_schema.ebook_collection_findings.c.code,
                w3_schema.ebook_collection_findings.c.dimension,
                w3_schema.ebook_collection_findings.c.severity,
            )
            .order_by(count.desc(), w3_schema.ebook_collection_findings.c.code)
        ).mappings().all()
        return tuple(
            EbookCollectionFindingAggregate(
                code=str(row["code"]),
                dimension=str(row["dimension"]),
                severity=str(row["severity"]),
                count=int(row["count"]),
            )
            for row in rows
        )

    @staticmethod
    def _review_priority() -> ColumnElement[int]:
        item = w3_schema.ebook_collection_items
        return case(
            (item.c.status == EbookCollectionItemStatus.ERROR.value, 0),
            (item.c.status == EbookCollectionItemStatus.FAILED.value, 1),
            (item.c.status == EbookCollectionItemStatus.PENDING.value, 2),
            (item.c.quality_status == "ACTION_REQUIRED", 3),
            (item.c.quality_status == "INCOMPLETE", 4),
            (item.c.status == EbookCollectionItemStatus.PARTIAL_FAILURE.value, 5),
            (item.c.quality_status == "REVIEW", 6),
            else_=99,
        )

    def _review_items(
        self,
        connection: Connection,
        run_id: EntityId,
        *,
        limit: int,
    ) -> tuple[int, tuple[EbookCollectionReviewItem, ...]]:
        item = w3_schema.ebook_collection_items
        observation = schema.file_observations
        finding = w3_schema.ebook_collection_findings
        finding_execution = w3_schema.ebook_collection_finding_executions
        priority = self._review_priority()
        total = int(
            connection.execute(
                select(func.count())
                .select_from(item)
                .where(item.c.run_id == str(run_id), priority < 99)
            ).scalar_one()
        )
        selected = (
            select(
                item.c.id.label("selected_item_id"),
                priority.label("priority"),
            )
            .select_from(
                item.join(observation, observation.c.id == item.c.observation_id)
            )
            .where(item.c.run_id == str(run_id), priority < 99)
            .order_by(priority, observation.c.relative_path, item.c.id)
            .limit(limit)
            .cte("selected_review_items")
        )
        statement = (
            select(
                selected.c.priority,
                item.c.id.label("item_id"),
                item.c.ordinal,
                item.c.observation_id,
                observation.c.relative_path,
                item.c.format_name,
                item.c.status,
                item.c.quality_status,
                item.c.error_code,
                finding.c.ordinal.label("finding_ordinal"),
                finding.c.id.label("finding_id"),
                finding.c.code,
                finding.c.dimension,
                finding.c.severity,
                finding_execution.c.ordinal.label("source_ordinal"),
                finding_execution.c.execution_id.label("source_execution_id"),
            )
            .select_from(
                selected.join(item, item.c.id == selected.c.selected_item_id)
                .join(observation, observation.c.id == item.c.observation_id)
                .outerjoin(finding, finding.c.item_id == item.c.id)
                .outerjoin(
                    finding_execution,
                    finding_execution.c.finding_id == finding.c.id,
                )
            )
            .order_by(
                selected.c.priority,
                observation.c.relative_path,
                item.c.id,
                finding.c.ordinal,
                finding_execution.c.ordinal,
            )
        )
        rows = connection.execution_options(stream_results=True).execute(statement)
        output: list[EbookCollectionReviewItem] = []
        current_id: str | None = None
        current_row: RowMapping | None = None
        current_findings: list[EbookCollectionReviewFinding] = []
        current_finding_id: str | None = None
        current_finding_row: RowMapping | None = None
        current_sources: list[EntityId] = []

        def finish_finding() -> None:
            nonlocal current_finding_id, current_finding_row, current_sources
            if current_finding_row is not None:
                current_findings.append(
                    EbookCollectionReviewFinding(
                        code=str(current_finding_row["code"]),
                        dimension=str(current_finding_row["dimension"]),
                        severity=str(current_finding_row["severity"]),
                        source_execution_ids=tuple(current_sources),
                    )
                )
            current_finding_id = None
            current_finding_row = None
            current_sources = []

        def finish_item() -> None:
            nonlocal current_row, current_findings
            if current_row is not None:
                output.append(self._review_item_from_row(current_row, current_findings))
            current_row = None
            current_findings = []

        mappings = rows.mappings()
        while batch := mappings.fetchmany(EBOOK_COLLECTION_REPORT_FETCH_SIZE):
            for row in batch:
                item_id = str(row["item_id"])
                if current_id is not None and item_id != current_id:
                    finish_finding()
                    finish_item()
                current_id = item_id
                current_row = row
                if row["finding_id"] is not None:
                    finding_id = str(row["finding_id"])
                    if (
                        current_finding_id is not None
                        and finding_id != current_finding_id
                    ):
                        finish_finding()
                    current_finding_id = finding_id
                    current_finding_row = row
                    if row["source_execution_id"] is not None:
                        current_sources.append(
                            EntityId.parse(str(row["source_execution_id"]))
                        )
        finish_finding()
        finish_item()
        return total, tuple(output)

    @staticmethod
    def _review_item_from_row(
        row: RowMapping,
        findings: list[EbookCollectionReviewFinding],
    ) -> EbookCollectionReviewItem:
        priority = int(row["priority"])
        label = _REVIEW_PRIORITY_LABELS.get(priority)
        if label is None:
            raise EbookCollectionReportStoreError("review priority is unknown")
        return EbookCollectionReviewItem(
            priority=label,
            ordinal=int(row["ordinal"]),
            observation_id=EntityId.parse(str(row["observation_id"])),
            relative_path=str(row["relative_path"]),
            format_name=str(row["format_name"]),
            analysis_status=str(row["status"]),
            quality_status=(
                None if row["quality_status"] is None else str(row["quality_status"])
            ),
            error_code=None if row["error_code"] is None else str(row["error_code"]),
            findings=tuple(findings),
        )

    @staticmethod
    def _exact_duplicate_statement(run_id: EntityId) -> Select[tuple[object, ...]]:
        item = w3_schema.ebook_collection_items
        observation = schema.file_observations
        fingerprint = schema.fingerprints
        return (
            select(
                fingerprint.c.algorithm.label("group_algorithm"),
                fingerprint.c.algorithm_version.label("group_version"),
                fingerprint.c.value.label("group_value"),
                fingerprint.c.value.label("file_value"),
                item.c.ordinal,
                item.c.observation_id,
                observation.c.relative_path,
                item.c.format_name,
            )
            .select_from(
                item.join(observation, observation.c.id == item.c.observation_id).join(
                    fingerprint,
                    and_(
                        fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        fingerprint.c.target_id == item.c.observation_id,
                        fingerprint.c.kind == FILE_SHA256_KIND,
                        fingerprint.c.algorithm == FILE_SHA256_ALGORITHM,
                        fingerprint.c.algorithm_version == FILE_SHA256_VERSION,
                    ),
                )
            )
            .where(item.c.run_id == str(run_id))
            .distinct()
            .order_by(
                fingerprint.c.algorithm,
                fingerprint.c.algorithm_version,
                fingerprint.c.value,
                observation.c.relative_path,
                item.c.observation_id,
            )
        )

    @staticmethod
    def _content_variant_statement(run_id: EntityId) -> Select[tuple[object, ...]]:
        item = w3_schema.ebook_collection_items
        observation = schema.file_observations
        execution_ref = w3_schema.ebook_collection_item_executions
        text_fingerprint = schema.fingerprints.alias("text_fingerprint")
        file_fingerprint = schema.fingerprints.alias("file_fingerprint")
        return (
            select(
                text_fingerprint.c.algorithm.label("group_algorithm"),
                text_fingerprint.c.algorithm_version.label("group_version"),
                text_fingerprint.c.value.label("group_value"),
                file_fingerprint.c.value.label("file_value"),
                item.c.ordinal,
                item.c.observation_id,
                observation.c.relative_path,
                item.c.format_name,
            )
            .select_from(
                item.join(observation, observation.c.id == item.c.observation_id)
                .join(execution_ref, execution_ref.c.item_id == item.c.id)
                .join(
                    text_fingerprint,
                    and_(
                        text_fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        text_fingerprint.c.target_id == item.c.observation_id,
                        text_fingerprint.c.kind == NORMALIZED_TEXT_KIND,
                        text_fingerprint.c.tool_execution_id
                        == execution_ref.c.execution_id,
                    ),
                )
                .join(
                    file_fingerprint,
                    and_(
                        file_fingerprint.c.target_kind
                        == EntityKind.FILE_OBSERVATION.value,
                        file_fingerprint.c.target_id == item.c.observation_id,
                        file_fingerprint.c.kind == FILE_SHA256_KIND,
                        file_fingerprint.c.algorithm == FILE_SHA256_ALGORITHM,
                        file_fingerprint.c.algorithm_version == FILE_SHA256_VERSION,
                    ),
                )
            )
            .where(item.c.run_id == str(run_id))
            .distinct()
            .order_by(
                text_fingerprint.c.algorithm,
                text_fingerprint.c.algorithm_version,
                text_fingerprint.c.value,
                observation.c.relative_path,
                item.c.observation_id,
                file_fingerprint.c.value,
            )
        )

    def _candidate_groups(
        self,
        connection: Connection,
        statement: Select[tuple[object, ...]],
        *,
        basis: str,
        group_limit: int,
        member_limit: int,
        require_distinct_file_values: bool,
    ) -> EbookCollectionCandidateSet:
        rows = connection.execution_options(stream_results=True).execute(statement)
        mappings = rows.mappings()
        heap: list[tuple[int, int, str, EbookCollectionCandidateGroup]] = []
        total_groups = 0
        total_members = 0
        current_key: tuple[str, str, str] | None = None
        members: list[EbookCollectionCandidateMember] = []
        member_count = 0
        first_file_value: str | None = None
        distinct_file_value = False

        def finish_group() -> None:
            nonlocal total_groups, total_members
            if current_key is None or member_count < 2:
                return
            if require_distinct_file_values and not distinct_file_value:
                return
            group_id = _candidate_group_id(basis, current_key)
            group = EbookCollectionCandidateGroup(
                group_id=group_id,
                basis=basis,
                member_count=member_count,
                members=tuple(members),
            )
            total_groups += 1
            total_members += member_count
            entry = (member_count, -int(group_id, 16), group_id, group)
            if len(heap) < group_limit:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)

        while batch := mappings.fetchmany(EBOOK_COLLECTION_REPORT_FETCH_SIZE):
            for row in batch:
                key = (
                    str(row["group_algorithm"]),
                    str(row["group_version"]),
                    str(row["group_value"]),
                )
                if current_key is not None and key != current_key:
                    finish_group()
                    members = []
                    member_count = 0
                    first_file_value = None
                    distinct_file_value = False
                current_key = key
                file_value = str(row["file_value"])
                if first_file_value is None:
                    first_file_value = file_value
                elif file_value != first_file_value:
                    distinct_file_value = True
                member_count += 1
                if len(members) < member_limit:
                    members.append(
                        EbookCollectionCandidateMember(
                            ordinal=int(row["ordinal"]),
                            observation_id=EntityId.parse(str(row["observation_id"])),
                            relative_path=str(row["relative_path"]),
                            format_name=str(row["format_name"]),
                        )
                    )
        finish_group()
        selected = tuple(
            entry[3]
            for entry in sorted(
                heap,
                key=lambda entry: (-entry[0], entry[2]),
            )
        )
        return EbookCollectionCandidateSet(
            total_groups=total_groups,
            total_members=total_members,
            groups=selected,
        )


def _candidate_group_id(basis: str, key: tuple[str, str, str]) -> str:
    digest = hashlib.sha256()
    digest.update(basis.encode("utf-8"))
    for value in key:
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()
