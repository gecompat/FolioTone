"""Bounded builder and insert-only store for book-only CollectionState v1."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Final

from sqlalchemy import Engine, and_, insert, or_, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from foliotone.collection_state import (
    COLLECTION_STATE_COMPONENT_ORDER,
    COLLECTION_STATE_COUNT_PREFIXES,
    COLLECTION_STATE_FORMAT_NAMES,
    COLLECTION_STATE_PROFILE,
    CollectionStateComponentName,
    CollectionStateComponentSummary,
    CollectionStateConflictState,
    CollectionStateCount,
    CollectionStateCoverageState,
    CollectionStateFreshnessState,
    CollectionStateItem,
    CollectionStateItemsHasher,
    CollectionStateItemState,
    CollectionStateSnapshot,
    CollectionStateTruncationState,
    collection_state_snapshot_id,
)
from foliotone.collection_state.contracts import (
    COLLECTION_STATE_SERIALIZER,
    MAX_COLLECTION_STATE_PROFILE_VERSIONS,
    canonical_json_bytes,
    sha256_digest,
)
from foliotone.core import EntityId, MediaType, ScanRunStatus
from foliotone.persistence import (
    archive_collection_schema,
    archive_schema,
    calibre_library_schema,
    classification_schema,
    consolidation_schema,
    quarantine_schema,
    relation_candidate_schema,
    resolution_review_schema,
    schema,
    w2_schema,
    w3_schema,
)
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db
from foliotone.persistence.collection_state_schema import (
    collection_state_components,
    collection_state_counts,
    collection_state_items,
    collection_state_snapshots,
)

COLLECTION_STATE_KEYSET_BATCH_SIZE: Final = 500
class CollectionStateStoreError(RuntimeError):
    """The requested snapshot cannot be built or read consistently."""


@dataclass(frozen=True, slots=True)
class CollectionStateBuildResult:
    snapshot: CollectionStateSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class _SourceScan:
    scan_root_id: EntityId
    scan_run_id: EntityId
    completed_at: str


class _EvidenceDigest:
    def __init__(self, component: str) -> None:
        self._digest = hashlib.sha256(f"foliotone:collection-state:{component}/v1\0".encode())
        self.current_count = 0
        self.stale_count = 0
        self.unscoped_count = 0
        self.conflict = False

    def add(
        self,
        *,
        scope: str,
        source: str,
        material: Mapping[str, object],
        conflict: bool = False,
    ) -> None:
        payload = canonical_json_bytes(
            {"scope": scope, "source": source, "material": dict(material)}
        )
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        if scope == "CURRENT":
            self.current_count += 1
        elif scope == "STALE":
            self.stale_count += 1
        elif scope == "UNSCOPED":
            self.unscoped_count += 1
        else:
            raise ValueError("unknown CollectionState evidence scope")
        self.conflict = self.conflict or conflict

    def state_and_digest(self) -> tuple[CollectionStateItemState, str | None]:
        if self.current_count:
            state = (
                CollectionStateItemState.CURRENT_CONFLICT
                if self.conflict
                else CollectionStateItemState.CURRENT
            )
        elif self.stale_count:
            state = (
                CollectionStateItemState.STALE_CONFLICT
                if self.conflict
                else CollectionStateItemState.STALE
            )
        elif self.unscoped_count:
            state = (
                CollectionStateItemState.UNSCOPED_CONFLICT
                if self.conflict
                else CollectionStateItemState.UNSCOPED
            )
        else:
            return CollectionStateItemState.MISSING, None
        return state, self._digest.hexdigest()

    @property
    def evidence_count(self) -> int:
        return self.current_count + self.stale_count + self.unscoped_count


@dataclass(slots=True)
class _ItemBuild:
    file_id: EntityId
    observation_id: EntityId
    relative_path: str
    size_bytes: int
    technical: _EvidenceDigest = field(default_factory=lambda: _EvidenceDigest("technical"))
    dimensions: dict[CollectionStateComponentName, _EvidenceDigest] = field(
        default_factory=lambda: {
            component: _EvidenceDigest(component.value.casefold())
            for component in COLLECTION_STATE_COMPONENT_ORDER
        }
    )

    @property
    def format_name(self) -> str:
        normalized = self.relative_path.replace("\\", "/")
        suffix = PurePosixPath(normalized).suffix.casefold().removeprefix(".").upper()
        return suffix if suffix in {"EPUB", "MOBI", "AZW", "AZW3", "PDF"} else "OTHER"

    def contract(self, ordinal: int) -> CollectionStateItem:
        states = {
            component: self.dimensions[component].state_and_digest()
            for component in COLLECTION_STATE_COMPONENT_ORDER
        }
        return CollectionStateItem(
            ordinal=ordinal,
            file_id=self.file_id,
            observation_id=self.observation_id,
            format_name=self.format_name,
            size_bytes=self.size_bytes,
            technical_digest=self.technical.state_and_digest()[1] or "",
            analysis_state=states[CollectionStateComponentName.ANALYSIS][0],
            analysis_digest=states[CollectionStateComponentName.ANALYSIS][1],
            resolution_state=states[CollectionStateComponentName.RESOLUTION][0],
            resolution_digest=states[CollectionStateComponentName.RESOLUTION][1],
            classification_state=states[CollectionStateComponentName.CLASSIFICATION][0],
            classification_digest=states[CollectionStateComponentName.CLASSIFICATION][1],
            matching_state=states[CollectionStateComponentName.MATCHING][0],
            matching_digest=states[CollectionStateComponentName.MATCHING][1],
            review_state=states[CollectionStateComponentName.REVIEW][0],
            review_digest=states[CollectionStateComponentName.REVIEW][1],
            calibre_state=states[CollectionStateComponentName.CALIBRE][0],
            calibre_digest=states[CollectionStateComponentName.CALIBRE][1],
            archive_state=states[CollectionStateComponentName.ARCHIVE][0],
            archive_digest=states[CollectionStateComponentName.ARCHIVE][1],
            consolidation_state=states[CollectionStateComponentName.CONSOLIDATION][0],
            consolidation_digest=states[CollectionStateComponentName.CONSOLIDATION][1],
            quarantine_state=states[CollectionStateComponentName.QUARANTINE][0],
            quarantine_digest=states[CollectionStateComponentName.QUARANTINE][1],
            item_digest="",
        )


class _ComponentAccumulator:
    def __init__(self, component: CollectionStateComponentName) -> None:
        self.component = component
        self._digest = hashlib.sha256(
            f"foliotone:collection-state-component:{component.value}/v1\0".encode()
        )
        self._profiles: set[str] = set()
        self._profiles_truncated = False
        self.evidence_count = 0
        self.current_item_count = 0
        self.stale_item_count = 0
        self.unscoped_item_count = 0
        self.missing_item_count = 0
        self.conflict_item_count = 0

    def add_evidence(
        self,
        *,
        file_id: EntityId,
        scope: str,
        source: str,
        material: Mapping[str, object],
        profiles: Sequence[str],
    ) -> None:
        payload = canonical_json_bytes(
            {
                "file_id": str(file_id),
                "scope": scope,
                "source": source,
                "material": dict(material),
            }
        )
        self._digest.update(len(payload).to_bytes(8, "big"))
        self._digest.update(payload)
        self.evidence_count += 1
        for profile in profiles:
            normalized = profile.strip()
            if not normalized:
                continue
            if normalized in self._profiles:
                continue
            if len(self._profiles) < MAX_COLLECTION_STATE_PROFILE_VERSIONS:
                self._profiles.add(normalized)
            else:
                self._profiles_truncated = True

    def observe_item(self, evidence: _EvidenceDigest) -> None:
        state, _digest = evidence.state_and_digest()
        if state in {
            CollectionStateItemState.CURRENT,
            CollectionStateItemState.CURRENT_CONFLICT,
        }:
            self.current_item_count += 1
        elif state in {
            CollectionStateItemState.STALE,
            CollectionStateItemState.STALE_CONFLICT,
        }:
            self.stale_item_count += 1
        elif state in {
            CollectionStateItemState.UNSCOPED,
            CollectionStateItemState.UNSCOPED_CONFLICT,
        }:
            self.unscoped_item_count += 1
        else:
            self.missing_item_count += 1
        if state in {
            CollectionStateItemState.CURRENT_CONFLICT,
            CollectionStateItemState.STALE_CONFLICT,
            CollectionStateItemState.UNSCOPED_CONFLICT,
        }:
            self.conflict_item_count += 1

    def summary(self, item_count: int) -> CollectionStateComponentSummary:
        if item_count == 0 or self.current_item_count == item_count:
            coverage = CollectionStateCoverageState.COMPLETE
        elif self.current_item_count or self.unscoped_item_count:
            coverage = CollectionStateCoverageState.PARTIAL
        else:
            coverage = CollectionStateCoverageState.NONE
        if item_count == 0:
            freshness = CollectionStateFreshnessState.CURRENT
        elif self.stale_item_count and (self.current_item_count or self.unscoped_item_count):
            freshness = CollectionStateFreshnessState.MIXED
        elif self.stale_item_count:
            freshness = CollectionStateFreshnessState.STALE
        elif self.unscoped_item_count:
            freshness = CollectionStateFreshnessState.UNKNOWN
        elif self.current_item_count:
            freshness = CollectionStateFreshnessState.CURRENT
        else:
            freshness = CollectionStateFreshnessState.UNKNOWN
        return CollectionStateComponentSummary(
            component=self.component,
            profile_versions=tuple(sorted(self._profiles)),
            evidence_count=self.evidence_count,
            current_item_count=self.current_item_count,
            stale_item_count=self.stale_item_count,
            unscoped_item_count=self.unscoped_item_count,
            missing_item_count=self.missing_item_count,
            conflict_item_count=self.conflict_item_count,
            coverage_state=coverage,
            freshness_state=freshness,
            conflict_state=(
                CollectionStateConflictState.PRESENT
                if self.conflict_item_count
                else CollectionStateConflictState.NONE
            ),
            truncation_state=(
                CollectionStateTruncationState.PROFILE_VERSIONS
                if self._profiles_truncated
                else CollectionStateTruncationState.NONE
            ),
            evidence_digest=self._digest.hexdigest(),
        )


class SQLiteCollectionStateStore:
    """Build and read immutable CollectionState snapshots on one SQLite engine."""

    def __init__(self, engine: Engine, *, batch_size: int = COLLECTION_STATE_KEYSET_BATCH_SIZE):
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
            raise ValueError("CollectionState batch_size must be between 1 and 1000")
        self._engine = engine
        self._batch_size = batch_size

    def build(
        self, source_scan_run_id: EntityId, created_at: datetime
    ) -> CollectionStateBuildResult:
        encoded_created_at = datetime_to_db(created_at)
        if encoded_created_at is None:
            raise ValueError("created_at is required")
        try:
            with self._engine.begin() as connection:
                source = self._source_scan(connection, source_scan_run_id)
                components = {
                    name: _ComponentAccumulator(name) for name in COLLECTION_STATE_COMPONENT_ORDER
                }
                item_hasher = CollectionStateItemsHasher()
                format_counts: Counter[str] = Counter()
                total_size_bytes = 0
                for item in self._iter_items(connection, source, components):
                    item_hasher.update(item)
                    format_counts[item.format_name] += 1
                    total_size_bytes += item.size_bytes
                item_count = item_hasher.count
                component_summaries = tuple(
                    components[name].summary(item_count)
                    for name in COLLECTION_STATE_COMPONENT_ORDER
                )
                counts = self._counts(
                    item_count, total_size_bytes, format_counts, component_summaries
                )
                material = {
                    "profile": COLLECTION_STATE_PROFILE,
                    "serializer": COLLECTION_STATE_SERIALIZER,
                    "scan_root_id": str(source.scan_root_id),
                    "source_scan_run_id": str(source.scan_run_id),
                    "item_count": item_count,
                    "total_size_bytes": total_size_bytes,
                    "items_digest": item_hasher.hexdigest(),
                    "components": [item.canonical_payload() for item in component_summaries],
                    "counts": [item.canonical_payload() for item in counts],
                }
                content_digest = sha256_digest(material)
                snapshot = CollectionStateSnapshot(
                    id=collection_state_snapshot_id(content_digest),
                    scan_root_id=source.scan_root_id,
                    source_scan_run_id=source.scan_run_id,
                    created_at=created_at,
                    item_count=item_count,
                    total_size_bytes=total_size_bytes,
                    items_digest=item_hasher.hexdigest(),
                    components=component_summaries,
                    counts=counts,
                    content_digest=content_digest,
                )
                existing = self._read(connection, snapshot.id, verify_items=True)
                if existing is not None:
                    if existing.material_payload() != snapshot.material_payload():
                        raise CollectionStateStoreError("CollectionState content collision")
                    self._ensure_query_index(connection, existing)
                    return CollectionStateBuildResult(existing, False)
                self._insert_parent(connection, snapshot)
                self._insert_items(connection, source, snapshot)
                self._ensure_query_index(connection, snapshot)
                return CollectionStateBuildResult(snapshot, True)
        except CollectionStateStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise CollectionStateStoreError("CollectionState persistence failed") from error

    def get(self, snapshot_id: EntityId) -> CollectionStateSnapshot | None:
        try:
            with self._engine.connect() as connection:
                return self._read(connection, snapshot_id, verify_items=True)
        except CollectionStateStoreError:
            raise
        except (IntegrityError, ValueError) as error:
            raise CollectionStateStoreError("CollectionState read failed") from error

    def _ensure_query_index(
        self,
        connection: Connection,
        snapshot: CollectionStateSnapshot,
    ) -> None:
        """Bind the CS-02 metadata index to this exact immutable snapshot."""

        from foliotone.persistence.collection_query import (
            CollectionQueryStoreError,
            SQLiteCollectionQueryStore,
        )

        try:
            SQLiteCollectionQueryStore(
                self._engine,
                batch_size=self._batch_size,
            ).ensure_for_snapshot(connection, snapshot)
        except CollectionQueryStoreError as error:
            raise CollectionStateStoreError("Collection query index build failed") from error

    @staticmethod
    def _source_scan(connection: Connection, scan_run_id: EntityId) -> _SourceScan:
        row = (
            connection.execute(
                select(
                    schema.scan_runs.c.id,
                    schema.scan_runs.c.scan_root_id,
                    schema.scan_runs.c.status,
                    schema.scan_runs.c.completed_at,
                    schema.scan_roots.c.media_type,
                )
                .select_from(
                    schema.scan_runs.join(
                        schema.scan_roots,
                        schema.scan_runs.c.scan_root_id == schema.scan_roots.c.id,
                    )
                )
                .where(schema.scan_runs.c.id == str(scan_run_id))
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CollectionStateStoreError("source ScanRun is unavailable")
        if str(row["status"]) != ScanRunStatus.COMPLETED.value or row["completed_at"] is None:
            raise CollectionStateStoreError("source ScanRun is not completed")
        if str(row["media_type"]) != MediaType.EBOOK.value:
            raise CollectionStateStoreError("source ScanRoot is not book-only")
        return _SourceScan(
            EntityId.parse(str(row["scan_root_id"])),
            EntityId.parse(str(row["id"])),
            str(row["completed_at"]),
        )

    @staticmethod
    def _counts(
        item_count: int,
        total_size_bytes: int,
        format_counts: Counter[str],
        components: tuple[CollectionStateComponentSummary, ...],
    ) -> tuple[CollectionStateCount, ...]:
        values: dict[str, int] = {
            "physical.byte_count": total_size_bytes,
            "physical.item_count": item_count,
        }
        for format_name in COLLECTION_STATE_FORMAT_NAMES:
            values[f"physical.format.{format_name.casefold()}"] = format_counts[format_name]
        for component in components:
            prefix = COLLECTION_STATE_COUNT_PREFIXES[component.component]
            values[f"{prefix}.conflict_items"] = component.conflict_item_count
            values[f"{prefix}.current_items"] = component.current_item_count
            values[f"{prefix}.evidence_links"] = component.evidence_count
            values[f"{prefix}.missing_items"] = component.missing_item_count
            values[f"{prefix}.stale_items"] = component.stale_item_count
            values[f"{prefix}.unscoped_items"] = component.unscoped_item_count
        return tuple(CollectionStateCount(key, values[key]) for key in sorted(values))

    def _insert_parent(self, connection: Connection, snapshot: CollectionStateSnapshot) -> None:
        connection.execute(
            insert(collection_state_snapshots),
            {
                "id": str(snapshot.id),
                "profile": snapshot.profile,
                "serializer": snapshot.serializer,
                "scan_root_id": str(snapshot.scan_root_id),
                "source_scan_run_id": str(snapshot.source_scan_run_id),
                "created_at": datetime_to_db(snapshot.created_at),
                "item_count": snapshot.item_count,
                "total_size_bytes": snapshot.total_size_bytes,
                "items_digest": snapshot.items_digest,
                "content_digest": snapshot.content_digest,
            },
        )
        connection.execute(
            insert(collection_state_components),
            [
                {
                    "snapshot_id": str(snapshot.id),
                    "ordinal": ordinal,
                    "component": component.component.value,
                    "profile_versions_json": json.dumps(
                        component.profile_versions,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "evidence_count": component.evidence_count,
                    "current_item_count": component.current_item_count,
                    "stale_item_count": component.stale_item_count,
                    "unscoped_item_count": component.unscoped_item_count,
                    "missing_item_count": component.missing_item_count,
                    "conflict_item_count": component.conflict_item_count,
                    "coverage_state": component.coverage_state.value,
                    "freshness_state": component.freshness_state.value,
                    "conflict_state": component.conflict_state.value,
                    "truncation_state": component.truncation_state.value,
                    "evidence_digest": component.evidence_digest,
                }
                for ordinal, component in enumerate(snapshot.components)
            ],
        )
        connection.execute(
            insert(collection_state_counts),
            [
                {
                    "snapshot_id": str(snapshot.id),
                    "ordinal": ordinal,
                    "count_key": count.key,
                    "count_value": count.value,
                }
                for ordinal, count in enumerate(snapshot.counts)
            ],
        )

    def _insert_items(
        self,
        connection: Connection,
        source: _SourceScan,
        snapshot: CollectionStateSnapshot,
    ) -> None:
        item_hasher = CollectionStateItemsHasher()
        rows: list[dict[str, object]] = []
        for item in self._iter_items(connection, source, None):
            item_hasher.update(item)
            rows.append(_item_row(snapshot.id, item))
            if len(rows) == self._batch_size:
                connection.execute(insert(collection_state_items), rows)
                rows.clear()
        if rows:
            connection.execute(insert(collection_state_items), rows)
        if (
            item_hasher.count != snapshot.item_count
            or item_hasher.hexdigest() != snapshot.items_digest
        ):
            raise CollectionStateStoreError("CollectionState evidence changed during build")

    def _iter_items(
        self,
        connection: Connection,
        source: _SourceScan,
        components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
    ) -> Iterator[CollectionStateItem]:
        ordinal = 0
        after_file_id: str | None = None
        after_observation_id: str | None = None
        previous_file_id: str | None = None
        while True:
            query = (
                select(
                    schema.file_records.c.id.label("file_id"),
                    schema.file_observations.c.id.label("observation_id"),
                    schema.file_observations.c.relative_path.label("observation_relative_path"),
                    schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                    schema.file_observations.c.modified_at.label("observation_modified_at"),
                    schema.file_observations.c.observed_at,
                )
                .select_from(
                    schema.file_observations.join(
                        schema.file_records,
                        schema.file_observations.c.file_id == schema.file_records.c.id,
                    )
                )
                .where(
                    schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                    schema.file_records.c.scan_root_id == str(source.scan_root_id),
                    schema.file_records.c.media_type == MediaType.EBOOK.value,
                )
                .order_by(schema.file_records.c.id, schema.file_observations.c.id)
                .limit(self._batch_size)
            )
            if after_file_id is not None and after_observation_id is not None:
                query = query.where(
                    or_(
                        schema.file_records.c.id > after_file_id,
                        and_(
                            schema.file_records.c.id == after_file_id,
                            schema.file_observations.c.id > after_observation_id,
                        ),
                    )
                )
            base_rows = connection.execute(query).mappings().all()
            if not base_rows:
                break
            items: dict[str, _ItemBuild] = {}
            observation_to_file: dict[str, str] = {}
            for row in base_rows:
                file_id = str(row["file_id"])
                observation_id = str(row["observation_id"])
                if file_id == previous_file_id or file_id in items:
                    raise CollectionStateStoreError(
                        "source ScanRun contains duplicate observations for one file"
                    )
                previous_file_id = file_id
                item = _ItemBuild(
                    EntityId.parse(file_id),
                    EntityId.parse(observation_id),
                    str(row["observation_relative_path"]),
                    int(row["observation_size_bytes"]),
                )
                item.technical.add(
                    scope="CURRENT",
                    source="file_observation",
                    material={
                        "file_id": file_id,
                        "observation_id": observation_id,
                        "format_name": item.format_name,
                        "size_bytes": int(row["observation_size_bytes"]),
                        "modified_at": _json_value(row["observation_modified_at"]),
                        "observed_at": _json_value(row["observed_at"]),
                    },
                )
                items[file_id] = item
                observation_to_file[observation_id] = file_id
            self._load_batch_evidence(
                connection,
                source,
                items,
                observation_to_file,
                components,
            )
            for item in items.values():
                contract = item.contract(ordinal)
                if components is not None:
                    for component in COLLECTION_STATE_COMPONENT_ORDER:
                        components[component].observe_item(item.dimensions[component])
                yield contract
                ordinal += 1
            last = base_rows[-1]
            after_file_id = str(last["file_id"])
            after_observation_id = str(last["observation_id"])

    def _load_batch_evidence(
        self,
        connection: Connection,
        source: _SourceScan,
        items: dict[str, _ItemBuild],
        observation_to_file: dict[str, str],
        components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
    ) -> None:
        _load_technical(connection, source, items, observation_to_file)
        _load_analysis(connection, source, items, observation_to_file, components)
        _load_resolution(connection, source, items, observation_to_file, components)
        _load_classification(connection, source, items, observation_to_file, components)
        _load_matching(connection, source, items, components)
        _load_review(connection, source, items, observation_to_file, components)
        _load_calibre(connection, source, items, observation_to_file, components)
        _load_archive(connection, source, items, observation_to_file, components)
        _load_consolidation(connection, source, items, observation_to_file, components)
        _load_quarantine(connection, source, items, components)

    def _read(
        self,
        connection: Connection,
        snapshot_id: EntityId,
        *,
        verify_items: bool,
    ) -> CollectionStateSnapshot | None:
        parent = (
            connection.execute(
                select(collection_state_snapshots).where(
                    collection_state_snapshots.c.id == str(snapshot_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            return None
        component_rows = (
            connection.execute(
                select(collection_state_components)
                .where(collection_state_components.c.snapshot_id == str(snapshot_id))
                .order_by(collection_state_components.c.ordinal)
            )
            .mappings()
            .all()
        )
        count_rows = (
            connection.execute(
                select(collection_state_counts)
                .where(collection_state_counts.c.snapshot_id == str(snapshot_id))
                .order_by(collection_state_counts.c.ordinal)
            )
            .mappings()
            .all()
        )
        if [int(row["ordinal"]) for row in component_rows] != list(
            range(len(COLLECTION_STATE_COMPONENT_ORDER))
        ):
            raise CollectionStateStoreError("CollectionState component rows are incomplete")
        if [int(row["ordinal"]) for row in count_rows] != list(range(len(count_rows))):
            raise CollectionStateStoreError("CollectionState count rows are incomplete")
        components = tuple(_component_from_row(row) for row in component_rows)
        counts = tuple(
            CollectionStateCount(str(row["count_key"]), int(row["count_value"]))
            for row in count_rows
        )
        snapshot = CollectionStateSnapshot(
            id=EntityId.parse(str(parent["id"])),
            scan_root_id=EntityId.parse(str(parent["scan_root_id"])),
            source_scan_run_id=EntityId.parse(str(parent["source_scan_run_id"])),
            created_at=required_datetime_from_db(str(parent["created_at"])),
            item_count=int(parent["item_count"]),
            total_size_bytes=int(parent["total_size_bytes"]),
            items_digest=str(parent["items_digest"]),
            components=components,
            counts=counts,
            content_digest=str(parent["content_digest"]),
            profile=str(parent["profile"]),
            serializer=str(parent["serializer"]),
        )
        if verify_items:
            self._verify_persisted_items(connection, snapshot)
        return snapshot

    def _verify_persisted_items(
        self, connection: Connection, snapshot: CollectionStateSnapshot
    ) -> None:
        hasher = CollectionStateItemsHasher()
        after_ordinal = -1
        while True:
            rows = (
                connection.execute(
                    select(collection_state_items)
                    .where(
                        collection_state_items.c.snapshot_id == str(snapshot.id),
                        collection_state_items.c.ordinal > after_ordinal,
                    )
                    .order_by(collection_state_items.c.ordinal)
                    .limit(self._batch_size)
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            for row in rows:
                hasher.update(_item_from_row(row))
            after_ordinal = int(rows[-1]["ordinal"])
        if hasher.count != snapshot.item_count or hasher.hexdigest() != snapshot.items_digest:
            raise CollectionStateStoreError("CollectionState item rows are incomplete")


def _material(row: Mapping[Any, Any], *, exclude: Sequence[str] = ()) -> dict[str, object]:
    excluded = set(exclude)
    return {str(key): _json_value(value) for key, value in row.items() if str(key) not in excluded}


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    return str(value)


def _add(
    *,
    item: _ItemBuild,
    component: CollectionStateComponentName,
    scope: str,
    source: str,
    material: Mapping[str, object],
    profiles: Sequence[str],
    conflict: bool,
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    item.dimensions[component].add(
        scope=scope,
        source=source,
        material=material,
        conflict=conflict,
    )
    if components is not None:
        components[component].add_evidence(
            file_id=item.file_id,
            scope=scope,
            source=source,
            material=material,
            profiles=profiles,
        )


def _scope(source_scan_run_id: object, source: _SourceScan) -> str:
    return "CURRENT" if str(source_scan_run_id) == str(source.scan_run_id) else "STALE"


def _source_scan_filter(
    source_scan_table: Any, source_scan_column: Any, source: _SourceScan
) -> Any:
    return and_(
        source_scan_table.c.scan_root_id == str(source.scan_root_id),
        or_(
            source_scan_column == str(source.scan_run_id),
            and_(
                source_scan_table.c.status == ScanRunStatus.COMPLETED.value,
                source_scan_table.c.completed_at.is_not(None),
                source_scan_table.c.completed_at < source.completed_at,
            ),
        ),
    )


def _profiles(*values: object) -> tuple[str, ...]:
    return tuple(str(value) for value in values if value is not None and str(value).strip())


def _item_row(snapshot_id: EntityId, item: CollectionStateItem) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_id": str(snapshot_id),
        "ordinal": item.ordinal,
        "file_id": str(item.file_id),
        "observation_id": str(item.observation_id),
        "format_name": item.format_name,
        "size_bytes": item.size_bytes,
        "technical_digest": item.technical_digest,
        "item_digest": item.item_digest,
    }
    for component in COLLECTION_STATE_COMPONENT_ORDER:
        key = component.value.casefold()
        row[f"{key}_state"] = getattr(item, f"{key}_state").value
        row[f"{key}_digest"] = getattr(item, f"{key}_digest")
    return row


def _item_from_row(row: Mapping[Any, Any]) -> CollectionStateItem:
    values: dict[str, object] = {
        "ordinal": int(row["ordinal"]),
        "file_id": EntityId.parse(str(row["file_id"])),
        "observation_id": EntityId.parse(str(row["observation_id"])),
        "format_name": str(row["format_name"]),
        "size_bytes": int(row["size_bytes"]),
        "technical_digest": str(row["technical_digest"]),
        "item_digest": str(row["item_digest"]),
    }
    for component in COLLECTION_STATE_COMPONENT_ORDER:
        key = component.value.casefold()
        values[f"{key}_state"] = CollectionStateItemState(str(row[f"{key}_state"]))
        values[f"{key}_digest"] = (
            None if row[f"{key}_digest"] is None else str(row[f"{key}_digest"])
        )
    return CollectionStateItem(**values)  # type: ignore[arg-type]


def _component_from_row(row: Mapping[Any, Any]) -> CollectionStateComponentSummary:
    profiles = json.loads(str(row["profile_versions_json"]))
    if not isinstance(profiles, list) or any(not isinstance(item, str) for item in profiles):
        raise CollectionStateStoreError("CollectionState component profiles are invalid")
    return CollectionStateComponentSummary(
        component=CollectionStateComponentName(str(row["component"])),
        profile_versions=tuple(profiles),
        evidence_count=int(row["evidence_count"]),
        current_item_count=int(row["current_item_count"]),
        stale_item_count=int(row["stale_item_count"]),
        unscoped_item_count=int(row["unscoped_item_count"]),
        missing_item_count=int(row["missing_item_count"]),
        conflict_item_count=int(row["conflict_item_count"]),
        coverage_state=CollectionStateCoverageState(str(row["coverage_state"])),
        freshness_state=CollectionStateFreshnessState(str(row["freshness_state"])),
        conflict_state=CollectionStateConflictState(str(row["conflict_state"])),
        truncation_state=CollectionStateTruncationState(str(row["truncation_state"])),
        evidence_digest=str(row["evidence_digest"]),
    )


# Evidence loaders are kept table-specific so provider schemas terminate at this boundary.


def _load_technical(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
) -> None:
    file_ids = tuple(items)
    observation_ids = tuple(observation_to_file)
    event_rows = connection.execute(
        select(w2_schema.file_scan_events)
        .where(
            w2_schema.file_scan_events.c.scan_run_id == str(source.scan_run_id),
            w2_schema.file_scan_events.c.file_id.in_(file_ids),
        )
        .order_by(w2_schema.file_scan_events.c.file_id, w2_schema.file_scan_events.c.id)
    ).mappings()
    for row in event_rows:
        items[str(row["file_id"])].technical.add(
            scope="CURRENT", source="file_scan_event", material=_material(row)
        )
    fingerprint_rows = connection.execute(
        select(schema.fingerprints)
        .where(
            schema.fingerprints.c.tool_execution_id.is_(None),
            or_(
                and_(
                    schema.fingerprints.c.target_kind == "FILE",
                    schema.fingerprints.c.target_id.in_(file_ids),
                ),
                and_(
                    schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
                    schema.fingerprints.c.target_id.in_(observation_ids),
                ),
            ),
        )
        .order_by(
            schema.fingerprints.c.target_kind,
            schema.fingerprints.c.target_id,
            schema.fingerprints.c.id,
        )
    ).mappings()
    for row in fingerprint_rows:
        target_kind = str(row["target_kind"])
        target_id = str(row["target_id"])
        file_id = target_id if target_kind == "FILE" else observation_to_file[target_id]
        items[file_id].technical.add(
            scope="CURRENT", source="technical_fingerprint", material=_material(row)
        )


def _load_analysis(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.ANALYSIS
    file_ids = tuple(items)
    source_scan = schema.scan_runs.alias("analysis_source_scan")
    collection_join = (
        w3_schema.ebook_collection_items.join(
            w3_schema.ebook_collection_runs,
            w3_schema.ebook_collection_items.c.run_id == w3_schema.ebook_collection_runs.c.id,
        )
        .join(
            schema.file_observations,
            w3_schema.ebook_collection_items.c.observation_id == schema.file_observations.c.id,
        )
        .join(
            source_scan,
            w3_schema.ebook_collection_runs.c.source_scan_run_id == source_scan.c.id,
        )
    )
    collection_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            w3_schema.ebook_collection_runs.c.source_scan_run_id,
            w3_schema.ebook_collection_runs.c.id.label("collection_run_id"),
            w3_schema.ebook_collection_runs.c.profile,
            w3_schema.ebook_collection_runs.c.analysis_profile,
            w3_schema.ebook_collection_runs.c.status.label("run_status"),
            w3_schema.ebook_collection_items.c.id.label("collection_item_id"),
            w3_schema.ebook_collection_items.c.observation_id,
            w3_schema.ebook_collection_items.c.format_name,
            w3_schema.ebook_collection_items.c.status.label("item_status"),
            w3_schema.ebook_collection_items.c.quality_status,
            w3_schema.ebook_collection_items.c.reused_step_count,
            w3_schema.ebook_collection_items.c.executed_step_count,
            w3_schema.ebook_collection_items.c.finding_count,
            w3_schema.ebook_collection_items.c.error_code,
        )
        .select_from(collection_join)
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            _source_scan_filter(
                source_scan,
                w3_schema.ebook_collection_runs.c.source_scan_run_id,
                source,
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            w3_schema.ebook_collection_runs.c.source_scan_run_id,
            w3_schema.ebook_collection_runs.c.id,
            w3_schema.ebook_collection_items.c.id,
        )
    ).mappings()
    for row in collection_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["observation_id"]) != str(items[file_id].observation_id):
            scope = "STALE"
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="ebook_collection_item",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(row["profile"], row["analysis_profile"]),
            conflict=False,
            components=components,
        )
    _load_analysis_details(
        connection,
        source,
        items,
        observation_to_file,
        components,
    )


def _load_resolution(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.RESOLUTION
    file_ids = tuple(items)
    observation_scan = schema.scan_runs.alias("resolution_observation_scan")
    candidate = resolution_review_schema.resolution_candidates
    evidence = resolution_review_schema.resolution_candidate_evidence
    observed_join = (
        candidate.join(
            schema.file_observations,
            and_(
                candidate.c.subject_kind == "FILE_OBSERVATION",
                candidate.c.subject_id == schema.file_observations.c.id,
            ),
        )
        .join(
            observation_scan,
            schema.file_observations.c.scan_run_id == observation_scan.c.id,
        )
        .outerjoin(evidence, candidate.c.id == evidence.c.resolution_candidate_id)
    )
    observed_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            schema.file_observations.c.scan_run_id.label("evidence_scan_run_id"),
            candidate.c.id.label("candidate_id"),
            candidate.c.subject_kind,
            candidate.c.subject_id,
            candidate.c.candidate_kind,
            candidate.c.candidate_entity_id,
            candidate.c.resolver_name,
            candidate.c.resolver_version,
            candidate.c.decision_compatibility_version,
            candidate.c.evidence_fingerprint,
            candidate.c.candidate_set_fingerprint,
            candidate.c.confidence,
            candidate.c.disposition,
            candidate.c.created_at,
            evidence.c.id.label("evidence_link_id"),
            evidence.c.ordinal.label("evidence_ordinal"),
            evidence.c.evidence_kind,
            evidence.c.evidence_id,
            evidence.c.evidence_role,
            evidence.c.asserted_entity_kind,
            evidence.c.material_fingerprint,
        )
        .select_from(observed_join)
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            observation_scan.c.scan_root_id == str(source.scan_root_id),
            or_(
                schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                and_(
                    observation_scan.c.status == ScanRunStatus.COMPLETED.value,
                    observation_scan.c.completed_at.is_not(None),
                    observation_scan.c.completed_at < source.completed_at,
                ),
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            schema.file_observations.c.scan_run_id,
            candidate.c.id,
            evidence.c.ordinal,
        )
    ).mappings()
    observed_targets: dict[tuple[str, str, str], str] = {}
    for row in observed_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["evidence_scan_run_id"], source)
        conflict_key = (file_id, scope, str(row["candidate_kind"]))
        target = str(row["candidate_entity_id"])
        prior = observed_targets.setdefault(conflict_key, target)
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="resolution_candidate",
            material=_material(row, exclude=("item_file_id", "evidence_scan_run_id")),
            profiles=_profiles(
                f"resolver:{row['resolver_name']}@{row['resolver_version']}",
                f"decision:{row['decision_compatibility_version']}",
            ),
            conflict=prior != target or str(row.get("evidence_role", "")) == "CONTRADICTS",
            components=components,
        )

    file_join = candidate.outerjoin(evidence, candidate.c.id == evidence.c.resolution_candidate_id)
    file_rows = connection.execute(
        select(
            candidate.c.subject_id.label("item_file_id"),
            candidate.c.id.label("candidate_id"),
            candidate.c.subject_kind,
            candidate.c.candidate_kind,
            candidate.c.candidate_entity_id,
            candidate.c.resolver_name,
            candidate.c.resolver_version,
            candidate.c.decision_compatibility_version,
            candidate.c.evidence_fingerprint,
            candidate.c.candidate_set_fingerprint,
            candidate.c.confidence,
            candidate.c.disposition,
            candidate.c.created_at,
            evidence.c.id.label("evidence_link_id"),
            evidence.c.ordinal.label("evidence_ordinal"),
            evidence.c.evidence_kind,
            evidence.c.evidence_id,
            evidence.c.evidence_role,
            evidence.c.asserted_entity_kind,
            evidence.c.material_fingerprint,
        )
        .select_from(file_join)
        .where(candidate.c.subject_kind == "FILE", candidate.c.subject_id.in_(file_ids))
        .order_by(candidate.c.subject_id, candidate.c.id, evidence.c.ordinal)
    ).mappings()
    file_targets: dict[tuple[str, str], str] = {}
    for row in file_rows:
        file_id = str(row["item_file_id"])
        file_conflict_key = (file_id, str(row["candidate_kind"]))
        target = str(row["candidate_entity_id"])
        prior = file_targets.setdefault(file_conflict_key, target)
        _add(
            item=items[file_id],
            component=component,
            scope="UNSCOPED",
            source="resolution_candidate",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                f"resolver:{row['resolver_name']}@{row['resolver_version']}",
                f"decision:{row['decision_compatibility_version']}",
            ),
            conflict=prior != target or str(row.get("evidence_role", "")) == "CONTRADICTS",
            components=components,
        )


def _load_classification(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.CLASSIFICATION
    file_ids = tuple(items)
    candidate = resolution_review_schema.resolution_candidates
    projection = classification_schema.book_classification_projections
    values = classification_schema.book_classification_projection_values
    observation_scan = schema.scan_runs.alias("classification_observation_scan")

    observed_join = (
        candidate.join(
            schema.file_observations,
            and_(
                candidate.c.subject_kind == "FILE_OBSERVATION",
                candidate.c.subject_id == schema.file_observations.c.id,
            ),
        )
        .join(
            observation_scan,
            schema.file_observations.c.scan_run_id == observation_scan.c.id,
        )
        .join(
            projection,
            and_(
                candidate.c.candidate_kind == projection.c.target_kind,
                candidate.c.candidate_entity_id == projection.c.target_id,
            ),
        )
        .outerjoin(values, projection.c.id == values.c.projection_id)
    )
    observed_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            schema.file_observations.c.scan_run_id.label("evidence_scan_run_id"),
            candidate.c.id.label("resolution_candidate_id"),
            projection.c.id.label("projection_id"),
            projection.c.target_kind,
            projection.c.target_id,
            projection.c.assertion_profile_version,
            projection.c.projection_profile_version,
            projection.c.input_fingerprint,
            projection.c.status,
            values.c.dimension,
            values.c.ordinal.label("value_ordinal"),
            values.c.taxonomy,
            values.c.normalized_value,
            values.c.facet_status,
            values.c.conflict_code,
        )
        .select_from(observed_join)
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            observation_scan.c.scan_root_id == str(source.scan_root_id),
            or_(
                schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                and_(
                    observation_scan.c.status == ScanRunStatus.COMPLETED.value,
                    observation_scan.c.completed_at.is_not(None),
                    observation_scan.c.completed_at < source.completed_at,
                ),
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            schema.file_observations.c.scan_run_id,
            projection.c.id,
            values.c.dimension,
            values.c.ordinal,
        )
    ).mappings()
    for row in observed_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope=_scope(row["evidence_scan_run_id"], source),
            source="classification_projection",
            material=_material(row, exclude=("item_file_id", "evidence_scan_run_id")),
            profiles=_profiles(row["assertion_profile_version"], row["projection_profile_version"]),
            conflict=(str(row["status"]) == "REVIEW_REQUIRED" or row["conflict_code"] is not None),
            components=components,
        )

    file_join = candidate.join(
        projection,
        and_(
            candidate.c.candidate_kind == projection.c.target_kind,
            candidate.c.candidate_entity_id == projection.c.target_id,
        ),
    ).outerjoin(values, projection.c.id == values.c.projection_id)
    file_rows = connection.execute(
        select(
            candidate.c.subject_id.label("item_file_id"),
            candidate.c.id.label("resolution_candidate_id"),
            projection.c.id.label("projection_id"),
            projection.c.target_kind,
            projection.c.target_id,
            projection.c.assertion_profile_version,
            projection.c.projection_profile_version,
            projection.c.input_fingerprint,
            projection.c.status,
            values.c.dimension,
            values.c.ordinal.label("value_ordinal"),
            values.c.taxonomy,
            values.c.normalized_value,
            values.c.facet_status,
            values.c.conflict_code,
        )
        .select_from(file_join)
        .where(candidate.c.subject_kind == "FILE", candidate.c.subject_id.in_(file_ids))
        .order_by(candidate.c.subject_id, projection.c.id, values.c.dimension, values.c.ordinal)
    ).mappings()
    for row in file_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope="UNSCOPED",
            source="classification_projection",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(row["assertion_profile_version"], row["projection_profile_version"]),
            conflict=(str(row["status"]) == "REVIEW_REQUIRED" or row["conflict_code"] is not None),
            components=components,
        )


def _load_analysis_details(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.ANALYSIS
    file_ids = tuple(items)
    source_scan = schema.scan_runs.alias("analysis_source_scan_details")
    for child_table, child_name in (
        (w3_schema.ebook_collection_findings, "ebook_collection_finding"),
        (w3_schema.ebook_collection_item_executions, "ebook_collection_execution"),
    ):
        child_join = (
            child_table.join(
                w3_schema.ebook_collection_items,
                child_table.c.item_id == w3_schema.ebook_collection_items.c.id,
            )
            .join(
                w3_schema.ebook_collection_runs,
                w3_schema.ebook_collection_items.c.run_id == w3_schema.ebook_collection_runs.c.id,
            )
            .join(
                schema.file_observations,
                w3_schema.ebook_collection_items.c.observation_id == schema.file_observations.c.id,
            )
            .join(
                source_scan,
                w3_schema.ebook_collection_runs.c.source_scan_run_id == source_scan.c.id,
            )
        )
        child_rows = connection.execute(
            select(
                schema.file_observations.c.file_id.label("item_file_id"),
                w3_schema.ebook_collection_runs.c.source_scan_run_id,
                w3_schema.ebook_collection_runs.c.profile,
                w3_schema.ebook_collection_runs.c.analysis_profile,
                w3_schema.ebook_collection_items.c.observation_id,
                *child_table.c,
            )
            .select_from(child_join)
            .where(
                schema.file_observations.c.file_id.in_(file_ids),
                _source_scan_filter(
                    source_scan,
                    w3_schema.ebook_collection_runs.c.source_scan_run_id,
                    source,
                ),
            )
            .order_by(
                schema.file_observations.c.file_id,
                w3_schema.ebook_collection_runs.c.source_scan_run_id,
                w3_schema.ebook_collection_items.c.id,
                child_table.c.ordinal,
            )
        ).mappings()
        for row in child_rows:
            file_id = str(row["item_file_id"])
            scope = _scope(row["source_scan_run_id"], source)
            if scope == "CURRENT" and str(row["observation_id"]) != str(
                items[file_id].observation_id
            ):
                scope = "STALE"
            conflict = child_name == "ebook_collection_finding" and str(
                row.get("severity", "")
            ) in {"REVIEW", "ACTION_REQUIRED"}
            _add(
                item=items[file_id],
                component=component,
                scope=scope,
                source=child_name,
                material=_material(
                    row,
                    exclude=(
                        "item_file_id",
                        "source_scan_run_id",
                        "profile",
                        "analysis_profile",
                        "observation_id",
                    ),
                ),
                profiles=_profiles(row["profile"], row["analysis_profile"]),
                conflict=conflict,
                components=components,
            )

    observation_scan = schema.scan_runs.alias("analysis_observation_scan")
    tool_result_join = (
        schema.tool_results.join(
            schema.tool_executions,
            schema.tool_results.c.execution_id == schema.tool_executions.c.id,
        )
        .join(
            schema.file_observations,
            schema.tool_results.c.target_id == schema.file_observations.c.id,
        )
        .join(
            observation_scan,
            schema.file_observations.c.scan_run_id == observation_scan.c.id,
        )
    )
    tool_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            schema.file_observations.c.scan_run_id.label("evidence_scan_run_id"),
            schema.tool_results.c.id.label("result_id"),
            schema.tool_results.c.execution_id,
            schema.tool_results.c.result_type,
            schema.tool_results.c.key,
            schema.tool_results.c.value,
            schema.tool_results.c.confidence,
            schema.tool_results.c.explanation,
            schema.tool_executions.c.provider_id,
            schema.tool_executions.c.tool_version,
            schema.tool_executions.c.adapter_version,
            schema.tool_executions.c.capability,
            schema.tool_executions.c.config_identity,
            schema.tool_executions.c.status.label("execution_status"),
            schema.tool_executions.c.exit_code,
        )
        .select_from(tool_result_join)
        .where(
            schema.tool_results.c.target_kind == "FILE_OBSERVATION",
            schema.file_observations.c.file_id.in_(file_ids),
            observation_scan.c.scan_root_id == str(source.scan_root_id),
            or_(
                schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                and_(
                    observation_scan.c.status == ScanRunStatus.COMPLETED.value,
                    observation_scan.c.completed_at.is_not(None),
                    observation_scan.c.completed_at < source.completed_at,
                ),
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            schema.file_observations.c.scan_run_id,
            schema.tool_results.c.id,
        )
    ).mappings()
    metadata_values: dict[tuple[str, str], str] = {}
    for row in tool_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["evidence_scan_run_id"], source)
        conflict = False
        if scope == "CURRENT" and str(row["result_type"]) == "ebook_metadata_candidate":
            conflict_key = (file_id, str(row["key"]))
            prior = metadata_values.setdefault(conflict_key, str(row["value"]))
            conflict = prior != str(row["value"])
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="tool_result",
            material=_material(row, exclude=("item_file_id", "evidence_scan_run_id")),
            profiles=_profiles(
                f"tool:{row['provider_id']}@{row['tool_version']}",
                f"adapter:{row['adapter_version']}",
                f"capability:{row['capability']}",
            ),
            conflict=conflict,
            components=components,
        )

    fingerprint_join = (
        schema.fingerprints.join(
            schema.file_observations,
            schema.fingerprints.c.target_id == schema.file_observations.c.id,
        )
        .join(
            observation_scan,
            schema.file_observations.c.scan_run_id == observation_scan.c.id,
        )
        .outerjoin(
            schema.tool_executions,
            schema.fingerprints.c.tool_execution_id == schema.tool_executions.c.id,
        )
    )
    fingerprint_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            schema.file_observations.c.scan_run_id.label("evidence_scan_run_id"),
            schema.fingerprints.c.id,
            schema.fingerprints.c.kind,
            schema.fingerprints.c.algorithm,
            schema.fingerprints.c.algorithm_version,
            schema.fingerprints.c.value,
            schema.fingerprints.c.created_at,
            schema.fingerprints.c.tool_execution_id,
            schema.tool_executions.c.provider_id,
            schema.tool_executions.c.tool_version,
            schema.tool_executions.c.adapter_version,
            schema.tool_executions.c.capability,
        )
        .select_from(fingerprint_join)
        .where(
            schema.fingerprints.c.target_kind == "FILE_OBSERVATION",
            schema.fingerprints.c.tool_execution_id.is_not(None),
            schema.file_observations.c.file_id.in_(file_ids),
            observation_scan.c.scan_root_id == str(source.scan_root_id),
            or_(
                schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                and_(
                    observation_scan.c.status == ScanRunStatus.COMPLETED.value,
                    observation_scan.c.completed_at.is_not(None),
                    observation_scan.c.completed_at < source.completed_at,
                ),
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            schema.file_observations.c.scan_run_id,
            schema.fingerprints.c.id,
        )
    ).mappings()
    for row in fingerprint_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope=_scope(row["evidence_scan_run_id"], source),
            source="analysis_fingerprint",
            material=_material(row, exclude=("item_file_id", "evidence_scan_run_id")),
            profiles=_profiles(
                f"tool:{row['provider_id']}@{row['tool_version']}",
                f"adapter:{row['adapter_version']}",
                f"fingerprint:{row['algorithm']}@{row['algorithm_version']}",
            ),
            conflict=False,
            components=components,
        )

    file_tool_rows = connection.execute(
        select(
            schema.tool_results.c.target_id.label("item_file_id"),
            schema.tool_results.c.id.label("result_id"),
            schema.tool_results.c.execution_id,
            schema.tool_results.c.result_type,
            schema.tool_results.c.key,
            schema.tool_results.c.value,
            schema.tool_results.c.confidence,
            schema.tool_executions.c.provider_id,
            schema.tool_executions.c.tool_version,
            schema.tool_executions.c.adapter_version,
            schema.tool_executions.c.capability,
        )
        .select_from(
            schema.tool_results.join(
                schema.tool_executions,
                schema.tool_results.c.execution_id == schema.tool_executions.c.id,
            )
        )
        .where(
            schema.tool_results.c.target_kind == "FILE",
            schema.tool_results.c.target_id.in_(file_ids),
        )
        .order_by(schema.tool_results.c.target_id, schema.tool_results.c.id)
    ).mappings()
    for row in file_tool_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope="UNSCOPED",
            source="file_tool_result",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                f"tool:{row['provider_id']}@{row['tool_version']}",
                f"adapter:{row['adapter_version']}",
            ),
            conflict=False,
            components=components,
        )


def _load_matching(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.MATCHING
    file_ids = tuple(items)
    candidate = relation_candidate_schema.relation_candidates
    evidence = relation_candidate_schema.relation_candidate_evidence
    source_scan = schema.scan_runs.alias("matching_source_scan")
    rows = connection.execute(
        select(
            candidate.c.id.label("candidate_id"),
            candidate.c.source_scan_run_id,
            candidate.c.left_kind,
            candidate.c.left_id,
            candidate.c.right_kind,
            candidate.c.right_id,
            candidate.c.relation_type,
            candidate.c.matcher_name,
            candidate.c.matcher_version,
            candidate.c.decision_compatibility_version,
            candidate.c.evidence_fingerprint,
            candidate.c.candidate_set_fingerprint,
            candidate.c.confidence,
            candidate.c.status,
            evidence.c.id.label("evidence_link_id"),
            evidence.c.ordinal.label("evidence_ordinal"),
            evidence.c.feature_code,
            evidence.c.feature_state,
            evidence.c.material_fingerprint,
            evidence.c.evidence_kind,
            evidence.c.evidence_id,
        )
        .select_from(
            candidate.join(
                source_scan, candidate.c.source_scan_run_id == source_scan.c.id
            ).outerjoin(evidence, candidate.c.id == evidence.c.relation_candidate_id)
        )
        .where(
            candidate.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, candidate.c.source_scan_run_id, source),
            or_(
                and_(candidate.c.left_kind == "FILE", candidate.c.left_id.in_(file_ids)),
                and_(candidate.c.right_kind == "FILE", candidate.c.right_id.in_(file_ids)),
            ),
        )
        .order_by(candidate.c.source_scan_run_id, candidate.c.id, evidence.c.ordinal)
    ).mappings()
    for row in rows:
        endpoints = {
            endpoint
            for kind, endpoint in (
                (str(row["left_kind"]), str(row["left_id"])),
                (str(row["right_kind"]), str(row["right_id"])),
            )
            if kind == "FILE" and endpoint in items
        }
        conflict = (
            row["feature_code"] is not None
            and str(row["feature_code"]).endswith("CONTRADICTORY")
            and str(row["feature_state"]) == "PRESENT"
        )
        material = _material(row)
        for file_id in sorted(endpoints):
            _add(
                item=items[file_id],
                component=component,
                scope=_scope(row["source_scan_run_id"], source),
                source="relation_candidate",
                material=material,
                profiles=_profiles(
                    f"matcher:{row['matcher_name']}@{row['matcher_version']}",
                    f"decision:{row['decision_compatibility_version']}",
                ),
                conflict=conflict,
                components=components,
            )


def _load_review(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.REVIEW
    file_ids = tuple(items)
    review = resolution_review_schema.review_items
    decision = resolution_review_schema.review_decisions
    observation_scan = schema.scan_runs.alias("review_observation_scan")
    observation_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            schema.file_observations.c.scan_run_id.label("evidence_scan_run_id"),
            review.c.id.label("review_item_id"),
            review.c.review_type,
            review.c.candidate_kind,
            review.c.candidate_id,
            review.c.producer_name,
            review.c.producer_version,
            review.c.decision_compatibility_version,
            review.c.evidence_fingerprint,
            review.c.candidate_set_fingerprint,
            review.c.state,
            decision.c.id.label("decision_id"),
            decision.c.sequence_no,
            decision.c.decision,
            decision.c.decision_reason,
            decision.c.actor_kind,
            decision.c.decided_at,
        )
        .select_from(
            review.join(
                schema.file_observations,
                and_(
                    review.c.subject_kind == "FILE_OBSERVATION",
                    review.c.subject_id == schema.file_observations.c.id,
                ),
            )
            .join(
                observation_scan,
                schema.file_observations.c.scan_run_id == observation_scan.c.id,
            )
            .outerjoin(decision, review.c.id == decision.c.review_item_id)
        )
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            observation_scan.c.scan_root_id == str(source.scan_root_id),
            or_(
                schema.file_observations.c.scan_run_id == str(source.scan_run_id),
                and_(
                    observation_scan.c.status == ScanRunStatus.COMPLETED.value,
                    observation_scan.c.completed_at.is_not(None),
                    observation_scan.c.completed_at < source.completed_at,
                ),
            ),
        )
        .order_by(
            schema.file_observations.c.file_id,
            schema.file_observations.c.scan_run_id,
            review.c.id,
            decision.c.sequence_no,
        )
    ).mappings()
    for row in observation_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope=_scope(row["evidence_scan_run_id"], source),
            source="review_item",
            material=_material(row, exclude=("item_file_id", "evidence_scan_run_id")),
            profiles=_profiles(
                f"review:{row['producer_name']}@{row['producer_version']}",
                f"decision:{row['decision_compatibility_version']}",
            ),
            conflict=False,
            components=components,
        )

    file_rows = connection.execute(
        select(
            review.c.subject_id.label("item_file_id"),
            review.c.id.label("review_item_id"),
            review.c.review_type,
            review.c.candidate_kind,
            review.c.candidate_id,
            review.c.producer_name,
            review.c.producer_version,
            review.c.decision_compatibility_version,
            review.c.evidence_fingerprint,
            review.c.candidate_set_fingerprint,
            review.c.state,
            decision.c.id.label("decision_id"),
            decision.c.sequence_no,
            decision.c.decision,
            decision.c.decision_reason,
            decision.c.actor_kind,
            decision.c.decided_at,
        )
        .select_from(review.outerjoin(decision, review.c.id == decision.c.review_item_id))
        .where(review.c.subject_kind == "FILE", review.c.subject_id.in_(file_ids))
        .order_by(review.c.subject_id, review.c.id, decision.c.sequence_no)
    ).mappings()
    for row in file_rows:
        file_id = str(row["item_file_id"])
        _add(
            item=items[file_id],
            component=component,
            scope="UNSCOPED",
            source="review_item",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                f"review:{row['producer_name']}@{row['producer_version']}",
                f"decision:{row['decision_compatibility_version']}",
            ),
            conflict=False,
            components=components,
        )


def _load_calibre(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.CALIBRE
    file_ids = tuple(items)
    source_scan = schema.scan_runs.alias("calibre_source_scan")
    snapshot = calibre_library_schema.calibre_library_snapshots
    record = calibre_library_schema.calibre_library_records
    for child, child_name in (
        (calibre_library_schema.calibre_library_formats, "calibre_format"),
        (calibre_library_schema.calibre_library_sidecars, "calibre_sidecar"),
    ):
        child_rows = connection.execute(
            select(
                schema.file_observations.c.file_id.label("item_file_id"),
                snapshot.c.source_scan_run_id,
                snapshot.c.id.label("snapshot_id"),
                snapshot.c.profile,
                snapshot.c.adapter_version,
                snapshot.c.tool_version,
                snapshot.c.parser_version,
                snapshot.c.status.label("snapshot_status"),
                record.c.id.label("record_snapshot_id"),
                *child.c,
            )
            .select_from(
                child.join(record, child.c.record_snapshot_id == record.c.id)
                .join(snapshot, record.c.snapshot_id == snapshot.c.id)
                .join(source_scan, snapshot.c.source_scan_run_id == source_scan.c.id)
                .join(
                    schema.file_observations,
                    child.c.observation_id == schema.file_observations.c.id,
                )
            )
            .where(
                child.c.observation_id.is_not(None),
                schema.file_observations.c.file_id.in_(file_ids),
                snapshot.c.scan_root_id == str(source.scan_root_id),
                _source_scan_filter(source_scan, snapshot.c.source_scan_run_id, source),
            )
            .order_by(
                schema.file_observations.c.file_id,
                snapshot.c.source_scan_run_id,
                snapshot.c.id,
                child.c.id,
            )
        ).mappings()
        for row in child_rows:
            file_id = str(row["item_file_id"])
            scope = _scope(row["source_scan_run_id"], source)
            if scope == "CURRENT" and str(row["observation_id"]) != str(
                items[file_id].observation_id
            ):
                scope = "STALE"
            _add(
                item=items[file_id],
                component=component,
                scope=scope,
                source=child_name,
                material=_material(row, exclude=("item_file_id",)),
                profiles=_profiles(
                    row["profile"],
                    f"adapter:{row['adapter_version']}",
                    f"tool:calibre@{row['tool_version']}",
                    f"parser:{row['parser_version']}",
                ),
                conflict=False,
                components=components,
            )

    finding = calibre_library_schema.calibre_reconciliation_findings
    finding_ref = calibre_library_schema.calibre_reconciliation_finding_refs
    finding_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            snapshot.c.source_scan_run_id,
            snapshot.c.profile,
            snapshot.c.adapter_version,
            snapshot.c.tool_version,
            snapshot.c.parser_version,
            finding.c.id.label("finding_id"),
            finding.c.code,
            finding.c.finding_fingerprint,
            finding.c.review_required,
            finding_ref.c.ordinal,
            finding_ref.c.role,
            finding_ref.c.material_fingerprint,
            finding_ref.c.ref_id.label("observation_id"),
        )
        .select_from(
            finding_ref.join(finding, finding_ref.c.finding_id == finding.c.id)
            .join(snapshot, finding.c.snapshot_id == snapshot.c.id)
            .join(source_scan, snapshot.c.source_scan_run_id == source_scan.c.id)
            .join(schema.file_observations, finding_ref.c.ref_id == schema.file_observations.c.id)
        )
        .where(
            finding_ref.c.ref_kind == "FILE_OBSERVATION",
            schema.file_observations.c.file_id.in_(file_ids),
            snapshot.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, snapshot.c.source_scan_run_id, source),
        )
        .order_by(
            schema.file_observations.c.file_id,
            snapshot.c.source_scan_run_id,
            finding.c.id,
            finding_ref.c.ordinal,
        )
    ).mappings()
    for row in finding_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["observation_id"]) != str(items[file_id].observation_id):
            scope = "STALE"
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="calibre_finding",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                row["profile"],
                f"adapter:{row['adapter_version']}",
                f"tool:calibre@{row['tool_version']}",
                f"parser:{row['parser_version']}",
            ),
            conflict="CONFLICT" in str(row["code"]),
            components=components,
        )


def _load_archive(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.ARCHIVE
    file_ids = tuple(items)
    source_scan = schema.scan_runs.alias("archive_source_scan_for_collection_state")
    archive = archive_schema.archive_observations
    archive_source = archive_schema.archive_observation_sources
    source_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            archive.c.source_scan_run_id,
            archive.c.id.label("archive_observation_id"),
            archive.c.profile,
            archive.c.signature_profile,
            archive.c.compatibility_profile,
            archive.c.provider_profile,
            archive.c.runner_profile,
            archive.c.parser_profile,
            archive.c.format_lock_profile,
            archive.c.listing_profile,
            archive.c.integrity_profile,
            archive.c.extraction_profile,
            archive.c.safety_profile,
            archive.c.recognition_status,
            archive.c.listing_status,
            archive.c.encryption_status,
            archive.c.integrity_status,
            archive.c.extraction_status,
            archive.c.password_attempt_status,
            archive.c.extraction_policy_status,
            archive_source.c.source_ordinal,
            archive_source.c.file_observation_id,
            archive_source.c.source_full_sha256,
            archive_source.c.source_size_bytes,
        )
        .select_from(
            archive_source.join(archive, archive_source.c.archive_observation_id == archive.c.id)
            .join(source_scan, archive.c.source_scan_run_id == source_scan.c.id)
            .join(
                schema.file_observations,
                archive_source.c.file_observation_id == schema.file_observations.c.id,
            )
        )
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            archive.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, archive.c.source_scan_run_id, source),
        )
        .order_by(
            schema.file_observations.c.file_id,
            archive.c.source_scan_run_id,
            archive.c.id,
            archive_source.c.source_ordinal,
        )
    ).mappings()
    for row in source_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["file_observation_id"]) != str(
            items[file_id].observation_id
        ):
            scope = "STALE"
        conflict = str(row["integrity_status"]) in {"FAILED", "CORRUPT"} or str(
            row["recognition_status"]
        ) in {"UNSUPPORTED", "AMBIGUOUS"}
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="archive_observation",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                row["profile"],
                row["signature_profile"],
                row["compatibility_profile"],
                row["provider_profile"],
                row["runner_profile"],
                row["parser_profile"],
                row["format_lock_profile"],
                row["listing_profile"],
                row["integrity_profile"],
                row["extraction_profile"],
                row["safety_profile"],
            ),
            conflict=conflict,
            components=components,
        )

    sidecar_inventory = archive_schema.archive_sidecar_inventories
    sidecar_item = archive_schema.archive_sidecar_inventory_items
    sidecar_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            sidecar_inventory.c.source_scan_run_id,
            sidecar_inventory.c.id.label("inventory_id"),
            sidecar_inventory.c.profile,
            sidecar_inventory.c.content_hash,
            sidecar_inventory.c.archive_observation_id,
            sidecar_item.c.sidecar_ordinal,
            sidecar_item.c.sidecar_file_observation_id.label("file_observation_id"),
            sidecar_item.c.sidecar_kind,
        )
        .select_from(
            sidecar_item.join(
                sidecar_inventory,
                sidecar_item.c.inventory_id == sidecar_inventory.c.id,
            )
            .join(
                source_scan,
                sidecar_inventory.c.source_scan_run_id == source_scan.c.id,
            )
            .join(
                schema.file_observations,
                sidecar_item.c.sidecar_file_observation_id == schema.file_observations.c.id,
            )
        )
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            sidecar_inventory.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, sidecar_inventory.c.source_scan_run_id, source),
        )
        .order_by(
            schema.file_observations.c.file_id,
            sidecar_inventory.c.source_scan_run_id,
            sidecar_inventory.c.id,
            sidecar_item.c.sidecar_ordinal,
        )
    ).mappings()
    for row in sidecar_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["file_observation_id"]) != str(
            items[file_id].observation_id
        ):
            scope = "STALE"
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="archive_sidecar_inventory",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(row["profile"]),
            conflict=False,
            components=components,
        )

    collection_run = archive_collection_schema.archive_collection_runs
    collection_source = archive_collection_schema.archive_collection_item_sources
    collection_rows = connection.execute(
        select(
            schema.file_observations.c.file_id.label("item_file_id"),
            collection_run.c.source_scan_run_id,
            collection_run.c.id.label("archive_collection_run_id"),
            collection_run.c.profile,
            collection_run.c.plan_profile,
            collection_run.c.status.label("run_status"),
            collection_run.c.missing_volume_count,
            collection_run.c.unsupported_volume_count,
            collection_run.c.ambiguous_volume_count,
            collection_run.c.name_collision_count,
            collection_run.c.orphan_volume_count,
            collection_source.c.item_id,
            collection_source.c.source_ordinal,
            collection_source.c.file_observation_id,
        )
        .select_from(
            collection_source.join(
                collection_run, collection_source.c.run_id == collection_run.c.id
            )
            .join(source_scan, collection_run.c.source_scan_run_id == source_scan.c.id)
            .join(
                schema.file_observations,
                collection_source.c.file_observation_id == schema.file_observations.c.id,
            )
        )
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            collection_run.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, collection_run.c.source_scan_run_id, source),
        )
        .order_by(
            schema.file_observations.c.file_id,
            collection_run.c.source_scan_run_id,
            collection_run.c.id,
            collection_source.c.item_id,
            collection_source.c.source_ordinal,
        )
    ).mappings()
    for row in collection_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["file_observation_id"]) != str(
            items[file_id].observation_id
        ):
            scope = "STALE"
        conflict = any(
            int(row[key]) > 0
            for key in (
                "missing_volume_count",
                "unsupported_volume_count",
                "ambiguous_volume_count",
                "name_collision_count",
                "orphan_volume_count",
            )
        )
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="archive_collection_item",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(row["profile"], row["plan_profile"]),
            conflict=conflict,
            components=components,
        )


def _load_consolidation(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    observation_to_file: dict[str, str],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.CONSOLIDATION
    file_ids = tuple(items)
    observation_ids = tuple(observation_to_file)
    plan = consolidation_schema.consolidation_plans
    blocker = consolidation_schema.consolidation_plan_blockers
    source_scan = schema.scan_runs.alias("consolidation_source_scan_for_collection_state")
    plan_rows = connection.execute(
        select(
            plan.c.id.label("plan_id"),
            plan.c.profile,
            plan.c.plan_version,
            plan.c.serializer_version,
            plan.c.source_scan_run_id,
            plan.c.keeper_file_id,
            plan.c.keeper_observation_id,
            plan.c.candidate_file_id,
            plan.c.candidate_observation_id,
            plan.c.status,
            plan.c.execution_state,
            plan.c.content_hash,
            blocker.c.ordinal.label("blocker_ordinal"),
            blocker.c.code.label("blocker_code"),
        )
        .select_from(
            plan.join(source_scan, plan.c.source_scan_run_id == source_scan.c.id).outerjoin(
                blocker, plan.c.id == blocker.c.plan_id
            )
        )
        .where(
            plan.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, plan.c.source_scan_run_id, source),
            or_(
                plan.c.keeper_file_id.in_(file_ids),
                plan.c.candidate_file_id.in_(file_ids),
                plan.c.keeper_observation_id.in_(observation_ids),
                plan.c.candidate_observation_id.in_(observation_ids),
            ),
        )
        .order_by(plan.c.source_scan_run_id, plan.c.id, blocker.c.ordinal)
    ).mappings()
    for row in plan_rows:
        endpoints = {
            value
            for value in (str(row["keeper_file_id"]), str(row["candidate_file_id"]))
            if value in items
        }
        material = _material(row)
        for file_id in sorted(endpoints):
            _add(
                item=items[file_id],
                component=component,
                scope=_scope(row["source_scan_run_id"], source),
                source="consolidation_plan",
                material=material,
                profiles=_profiles(
                    row["profile"],
                    f"plan:{row['plan_version']}",
                    f"serializer:{row['serializer_version']}",
                ),
                conflict=row["blocker_code"] is not None,
                components=components,
            )

    quality = consolidation_schema.consolidation_quality_evidence
    quality_rows = connection.execute(
        select(quality, schema.file_observations.c.file_id.label("item_file_id"))
        .select_from(
            quality.join(
                schema.file_observations,
                quality.c.observation_id == schema.file_observations.c.id,
            ).join(source_scan, quality.c.source_scan_run_id == source_scan.c.id)
        )
        .where(
            schema.file_observations.c.file_id.in_(file_ids),
            quality.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, quality.c.source_scan_run_id, source),
        )
        .order_by(
            schema.file_observations.c.file_id,
            quality.c.source_scan_run_id,
            quality.c.id,
        )
    ).mappings()
    for row in quality_rows:
        file_id = str(row["item_file_id"])
        scope = _scope(row["source_scan_run_id"], source)
        if scope == "CURRENT" and str(row["observation_id"]) != str(items[file_id].observation_id):
            scope = "STALE"
        _add(
            item=items[file_id],
            component=component,
            scope=scope,
            source="consolidation_quality_evidence",
            material=_material(row, exclude=("item_file_id",)),
            profiles=_profiles(
                row["profile"],
                row["collection_profile"],
                row["analysis_profile"],
                row["quality_profile"],
            ),
            conflict=str(row["aggregate_quality_status"]) in {"REVIEW", "ACTION_REQUIRED"},
            components=components,
        )


def _load_quarantine(
    connection: Connection,
    source: _SourceScan,
    items: dict[str, _ItemBuild],
    components: dict[CollectionStateComponentName, _ComponentAccumulator] | None,
) -> None:
    component = CollectionStateComponentName.QUARANTINE
    file_ids = tuple(items)
    authorization = quarantine_schema.quarantine_authorizations
    run = quarantine_schema.quarantine_execution_runs
    event = quarantine_schema.quarantine_execution_events
    plan = consolidation_schema.consolidation_plans
    source_scan = schema.scan_runs.alias("quarantine_source_scan_for_collection_state")
    rows = connection.execute(
        select(
            plan.c.source_scan_run_id,
            plan.c.keeper_file_id,
            plan.c.candidate_file_id,
            authorization.c.id.label("authorization_id"),
            authorization.c.profile.label("authorization_profile"),
            authorization.c.content_hash.label("authorization_content_hash"),
            authorization.c.authorized_at,
            authorization.c.expires_at,
            run.c.id.label("run_id"),
            run.c.profile.label("run_profile"),
            run.c.created_at,
            event.c.sequence_no,
            event.c.status.label("event_status"),
            event.c.occurred_at,
            event.c.finding_code,
        )
        .select_from(
            authorization.join(plan, authorization.c.plan_id == plan.c.id)
            .join(source_scan, plan.c.source_scan_run_id == source_scan.c.id)
            .outerjoin(run, authorization.c.id == run.c.authorization_id)
            .outerjoin(event, run.c.id == event.c.run_id)
        )
        .where(
            plan.c.scan_root_id == str(source.scan_root_id),
            _source_scan_filter(source_scan, plan.c.source_scan_run_id, source),
            or_(plan.c.keeper_file_id.in_(file_ids), plan.c.candidate_file_id.in_(file_ids)),
        )
        .order_by(
            plan.c.source_scan_run_id,
            authorization.c.id,
            run.c.id,
            event.c.sequence_no,
        )
    ).mappings()
    safe_statuses = {None, "PREPARED", "MOVED", "VERIFIED", "COMPLETED"}
    for row in rows:
        endpoints = {
            value
            for value in (str(row["keeper_file_id"]), str(row["candidate_file_id"]))
            if value in items
        }
        material = _material(row)
        for file_id in sorted(endpoints):
            _add(
                item=items[file_id],
                component=component,
                scope=_scope(row["source_scan_run_id"], source),
                source="quarantine_execution",
                material=material,
                profiles=_profiles(row["authorization_profile"], row["run_profile"]),
                conflict=(None if row["event_status"] is None else str(row["event_status"]))
                not in safe_statuses,
                components=components,
            )
