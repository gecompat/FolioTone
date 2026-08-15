"""Bounded scan-snapshot queries for private e-book inventory reports."""

from __future__ import annotations

import hashlib
import heapq
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, case, exists, func, or_, select

from foliotone.core import (
    EBOOK_COLLECTION_FORMATS,
    EntityId,
    EntityKind,
    MediaType,
    PresenceState,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import schema
from foliotone.persistence.codecs import codec_for

EBOOK_INVENTORY_REPORT_FETCH_SIZE = 500
QUICK_FILE_PROFILE = ("QUICK_FILE", "sha256-head-tail", "1")
FULL_FILE_PROFILE = ("FILE_SHA256", "sha256", "1")
_FORMAT_ORDER = ("EPUB", "MOBI", "AZW", "AZW3", "PDF")


class EbookInventoryReportStoreError(RuntimeError):
    """A scan snapshot cannot produce a safe inventory report."""


@dataclass(frozen=True, slots=True)
class EbookInventoryFormatAggregate:
    format_name: str
    observations: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class EbookInventoryDuplicateMember:
    observation_id: EntityId
    relative_path: str
    format_name: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class EbookInventoryDuplicateGroup:
    group_id: str
    member_count: int
    total_bytes: int
    redundant_bytes: int
    members: tuple[EbookInventoryDuplicateMember, ...]
    basis: str = "EXACT_FILE_SHA256"

    @property
    def members_truncated(self) -> bool:
        return len(self.members) < self.member_count


@dataclass(frozen=True, slots=True)
class EbookInventoryDuplicateSet:
    total_groups: int
    total_members: int
    total_redundant_bytes: int
    groups: tuple[EbookInventoryDuplicateGroup, ...]

    @property
    def emitted_members(self) -> int:
        return sum(len(group.members) for group in self.groups)

    @property
    def groups_truncated(self) -> bool:
        return len(self.groups) < self.total_groups

    @property
    def members_truncated(self) -> bool:
        return any(group.members_truncated for group in self.groups)


@dataclass(frozen=True, slots=True)
class EbookInventoryReportSnapshot:
    scan: ScanRun
    observations: int
    total_bytes: int
    formats: tuple[EbookInventoryFormatAggregate, ...]
    full_hash_observations: int
    quick_candidate_groups: int
    quick_candidate_observations: int
    quick_candidates_missing_full_hash: int
    exact_duplicates: EbookInventoryDuplicateSet


class SQLiteEbookInventoryReportStore:
    """Read one completed scan snapshot with bounded duplicate details."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._scan_codec = codec_for(ScanRun)

    def snapshot(
        self,
        scan_root_id: EntityId,
        *,
        candidate_group_limit: int,
        candidate_member_limit: int,
    ) -> EbookInventoryReportSnapshot:
        if candidate_group_limit <= 0:
            raise ValueError("candidate_group_limit must be positive")
        if candidate_member_limit <= 0:
            raise ValueError("candidate_member_limit must be positive")
        with self._engine.connect() as connection, connection.begin():
            scan = self._latest_scan(connection, scan_root_id)
            current = self._current_observations(scan_root_id, scan.id)
            observations, total_bytes = connection.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(current.c.size_bytes), 0),
                ).select_from(current)
            ).one()
            formats = self._format_aggregates(connection, current)
            quick, quick_groups = self._quick_candidates(current)
            quick_totals = connection.execute(
                select(
                    func.count(quick_groups.c.quick_value),
                    func.coalesce(func.sum(quick_groups.c.member_count), 0),
                )
            ).one()
            quick_members = quick.join(
                quick_groups,
                quick_groups.c.quick_value == quick.c.quick_value,
            )
            missing_full = connection.execute(
                select(func.count())
                .select_from(quick_members)
                .where(~self._full_hash_exists(quick.c.observation_id))
            ).scalar_one()
            full = self._consistent_fingerprint_values(FULL_FILE_PROFILE)
            full_count = connection.execute(
                select(func.count())
                .select_from(current.join(full, full.c.observation_id == current.c.id))
            ).scalar_one()
            exact_duplicates = self._exact_duplicates(
                connection,
                current,
                full,
                group_limit=candidate_group_limit,
                member_limit=candidate_member_limit,
            )
            return EbookInventoryReportSnapshot(
                scan=scan,
                observations=int(observations),
                total_bytes=int(total_bytes),
                formats=formats,
                full_hash_observations=int(full_count),
                quick_candidate_groups=int(quick_totals[0]),
                quick_candidate_observations=int(quick_totals[1]),
                quick_candidates_missing_full_hash=int(missing_full),
                exact_duplicates=exact_duplicates,
            )

    def _latest_scan(
        self,
        connection: Connection,
        scan_root_id: EntityId,
    ) -> ScanRun:
        row = connection.execute(
            select(schema.scan_runs)
            .where(schema.scan_runs.c.scan_root_id == str(scan_root_id))
            .order_by(
                schema.scan_runs.c.started_at.desc(),
                schema.scan_runs.c.id.desc(),
            )
            .limit(1)
        ).mappings().one_or_none()
        if row is None:
            raise EbookInventoryReportStoreError("ScanRoot has no persisted ScanRun")
        scan = self._scan_codec.decode(row)
        if scan.status is not ScanRunStatus.COMPLETED:
            raise EbookInventoryReportStoreError(
                "latest ScanRun must be COMPLETED before inventory reporting"
            )
        return scan

    @staticmethod
    def _current_observations(scan_root_id: EntityId, scan_run_id: EntityId) -> Any:
        observation = schema.file_observations
        record = schema.file_records
        format_expression = case(
            *(
                (
                    func.lower(record.c.relative_path).like(
                        f"%.{format_name.lower()}"
                    ),
                    format_name,
                )
                for format_name in _FORMAT_ORDER
            ),
            else_="UNKNOWN",
        )
        return (
            select(
                observation.c.id,
                observation.c.relative_path,
                observation.c.size_bytes,
                format_expression.label("format_name"),
            )
            .select_from(observation.join(record, record.c.id == observation.c.file_id))
            .where(
                observation.c.scan_run_id == str(scan_run_id),
                record.c.scan_root_id == str(scan_root_id),
                record.c.media_type == MediaType.EBOOK.value,
                record.c.presence_state == PresenceState.PRESENT.value,
                record.c.relative_path == observation.c.relative_path,
                record.c.size_bytes == observation.c.size_bytes,
                record.c.modified_at == observation.c.modified_at,
                or_(
                    *(
                        func.lower(record.c.relative_path).like(
                            f"%.{format_name.lower()}"
                        )
                        for format_name in sorted(EBOOK_COLLECTION_FORMATS)
                    )
                ),
            )
            .subquery("current_ebook_inventory")
        )

    @staticmethod
    def _format_aggregates(
        connection: Connection,
        current: Any,
    ) -> tuple[EbookInventoryFormatAggregate, ...]:
        rows = connection.execute(
            select(
                current.c.format_name,
                func.count().label("observations"),
                func.sum(current.c.size_bytes).label("total_bytes"),
            )
            .group_by(current.c.format_name)
            .order_by(
                case(
                    *(
                        (current.c.format_name == name, ordinal)
                        for ordinal, name in enumerate(_FORMAT_ORDER)
                    ),
                    else_=len(_FORMAT_ORDER),
                )
            )
        ).mappings().all()
        values = {
            str(row["format_name"]): EbookInventoryFormatAggregate(
                format_name=str(row["format_name"]),
                observations=int(row["observations"]),
                total_bytes=int(row["total_bytes"]),
            )
            for row in rows
        }
        return tuple(
            values.get(name, EbookInventoryFormatAggregate(name, 0, 0))
            for name in _FORMAT_ORDER
        )

    def _quick_candidates(self, current: Any) -> tuple[Any, Any]:
        quick_values = self._consistent_fingerprint_values(QUICK_FILE_PROFILE)
        quick = (
            select(
                current.c.id.label("observation_id"),
                quick_values.c.fingerprint_value.label("quick_value"),
            )
            .select_from(
                current.join(
                    quick_values,
                    quick_values.c.observation_id == current.c.id,
                )
            )
            .subquery("inventory_quick_values")
        )
        groups = (
            select(
                quick.c.quick_value,
                func.count().label("member_count"),
            )
            .group_by(quick.c.quick_value)
            .having(func.count() > 1)
            .subquery("inventory_quick_groups")
        )
        return quick, groups

    @staticmethod
    def _consistent_fingerprint_values(profile: tuple[str, str, str]) -> Any:
        fingerprint = schema.fingerprints
        return (
            select(
                fingerprint.c.target_id.label("observation_id"),
                func.min(fingerprint.c.value).label("fingerprint_value"),
            )
            .where(
                fingerprint.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                fingerprint.c.kind == profile[0],
                fingerprint.c.algorithm == profile[1],
                fingerprint.c.algorithm_version == profile[2],
            )
            .group_by(fingerprint.c.target_id)
            .having(func.count(func.distinct(fingerprint.c.value)) == 1)
            .subquery()
        )

    @staticmethod
    def _full_hash_exists(observation_id: object) -> Any:
        fingerprint = schema.fingerprints
        return exists(
            select(fingerprint.c.id).where(
                fingerprint.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                fingerprint.c.target_id == observation_id,
                fingerprint.c.kind == FULL_FILE_PROFILE[0],
                fingerprint.c.algorithm == FULL_FILE_PROFILE[1],
                fingerprint.c.algorithm_version == FULL_FILE_PROFILE[2],
            )
        )

    @staticmethod
    def _exact_duplicates(
        connection: Connection,
        current: Any,
        full: Any,
        *,
        group_limit: int,
        member_limit: int,
    ) -> EbookInventoryDuplicateSet:
        full_current = (
            select(
                current.c.id.label("observation_id"),
                current.c.relative_path,
                current.c.size_bytes,
                current.c.format_name,
                full.c.fingerprint_value.label("group_value"),
            )
            .select_from(current.join(full, full.c.observation_id == current.c.id))
            .subquery("inventory_full_values")
        )
        groups = (
            select(
                full_current.c.group_value,
                func.count().label("member_count"),
                func.sum(full_current.c.size_bytes).label("group_total_bytes"),
                func.max(full_current.c.size_bytes).label("largest_member_bytes"),
            )
            .group_by(full_current.c.group_value)
            .having(func.count() > 1)
            .subquery("inventory_exact_groups")
        )
        statement = (
            select(
                full_current,
                groups.c.member_count,
                groups.c.group_total_bytes,
                groups.c.largest_member_bytes,
            )
            .join(groups, groups.c.group_value == full_current.c.group_value)
            .order_by(
                full_current.c.group_value,
                full_current.c.relative_path,
                full_current.c.observation_id,
            )
        )
        mappings = connection.execution_options(stream_results=True).execute(
            statement
        ).mappings()
        heap: list[
            tuple[int, int, str, EbookInventoryDuplicateGroup]
        ] = []
        total_groups = 0
        total_members = 0
        total_redundant_bytes = 0
        current_value: str | None = None
        members: list[EbookInventoryDuplicateMember] = []
        member_count = 0
        group_total_bytes = 0
        largest_member_bytes = 0

        def finish_group() -> None:
            nonlocal total_groups, total_members, total_redundant_bytes
            if current_value is None or member_count < 2:
                return
            redundant_bytes = max(0, group_total_bytes - largest_member_bytes)
            group_id = _inventory_group_id(current_value)
            group = EbookInventoryDuplicateGroup(
                group_id=group_id,
                member_count=member_count,
                total_bytes=group_total_bytes,
                redundant_bytes=redundant_bytes,
                members=tuple(members),
            )
            total_groups += 1
            total_members += member_count
            total_redundant_bytes += redundant_bytes
            entry = (redundant_bytes, member_count, group_id, group)
            if len(heap) < group_limit:
                heapq.heappush(heap, entry)
            elif entry[:3] > heap[0][:3]:
                heapq.heapreplace(heap, entry)

        while batch := mappings.fetchmany(EBOOK_INVENTORY_REPORT_FETCH_SIZE):
            for row in batch:
                value = str(row["group_value"])
                if current_value is not None and value != current_value:
                    finish_group()
                    members = []
                    member_count = 0
                current_value = value
                member_count += 1
                group_total_bytes = int(row["group_total_bytes"])
                largest_member_bytes = int(row["largest_member_bytes"])
                if len(members) < member_limit:
                    members.append(
                        EbookInventoryDuplicateMember(
                            observation_id=EntityId.parse(
                                str(row["observation_id"])
                            ),
                            relative_path=str(row["relative_path"]),
                            format_name=str(row["format_name"]),
                            size_bytes=int(row["size_bytes"]),
                        )
                    )
        finish_group()
        selected = tuple(
            entry[3]
            for entry in sorted(
                heap,
                key=lambda entry: (-entry[0], -entry[1], entry[2]),
            )
        )
        return EbookInventoryDuplicateSet(
            total_groups=total_groups,
            total_members=total_members,
            total_redundant_bytes=total_redundant_bytes,
            groups=selected,
        )


def _inventory_group_id(full_hash: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"EXACT_FILE_SHA256")
    digest.update(b"\0sha256\0")
    digest.update(b"1")
    digest.update(b"\0")
    digest.update(full_hash.encode("utf-8"))
    return digest.hexdigest()
