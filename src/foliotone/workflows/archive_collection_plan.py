"""Pure deterministic planning for one restartable archive collection run."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import batched
from uuid import UUID, uuid5

from foliotone.archive.signatures import (
    MAX_ARCHIVE_HEADER_BYTES,
    ArchiveSuffixKind,
    ArchiveVolumePartitionFinding,
    observe_archive_signature_v2,
    partition_archive_volume_names,
)
from foliotone.core import (
    ArchiveCollectionItem,
    ArchiveCollectionItemSource,
    ArchiveCollectionPlanFindingCounts,
    ArchiveCollectionRun,
    EntityId,
)
from foliotone.persistence.archive_collection import (
    ARCHIVE_COLLECTION_PLAN_BATCH_SIZE,
    ArchiveCollectionPlanEntry,
    SQLiteArchiveCollectionStore,
    archive_collection_plan_content_hash,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ITEM_NAMESPACE = UUID("f1db54a8-01e1-53ef-9921-b217c03cc01f")


class ArchiveCollectionPlanningError(RuntimeError):
    """The private candidate stream cannot form one deterministic plan."""


@dataclass(frozen=True, slots=True)
class ArchiveCollectionPlanSourceInput:
    file_observation_id: EntityId
    size_bytes: int
    full_sha256: str | None
    private_parent_key: str = field(repr=False)
    basename: str = field(repr=False)
    signature_prefix: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.file_observation_id, EntityId):
            raise ValueError("archive collection source observation ID is invalid")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("archive collection source size is invalid")
        if self.full_sha256 is not None and (
            not isinstance(self.full_sha256, str)
            or _SHA256.fullmatch(self.full_sha256) is None
        ):
            raise ValueError("archive collection source hash is invalid")
        for value in (self.private_parent_key, self.basename):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 4_096
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError("archive collection private name material is invalid")
        if any(character in self.basename for character in ("/", "\\", ":")):
            raise ValueError("archive collection basename contains a path")
        if (
            not isinstance(self.signature_prefix, bytes)
            or len(self.signature_prefix) > MAX_ARCHIVE_HEADER_BYTES
        ):
            raise ValueError("archive collection signature prefix is invalid")


@dataclass(frozen=True, slots=True)
class ArchiveCollectionPlanSnapshot:
    run_id: EntityId
    entries: tuple[ArchiveCollectionPlanEntry, ...]
    findings: ArchiveCollectionPlanFindingCounts
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, EntityId):
            raise ValueError("archive collection plan run ID is invalid")
        if (
            not isinstance(self.entries, tuple)
            or any(not isinstance(entry, ArchiveCollectionPlanEntry) for entry in self.entries)
            or tuple(entry.item.plan_ordinal for entry in self.entries)
            != tuple(range(len(self.entries)))
            or any(entry.item.run_id != self.run_id for entry in self.entries)
        ):
            raise ValueError("archive collection plan entries are invalid")
        if not isinstance(self.findings, ArchiveCollectionPlanFindingCounts):
            raise ValueError("archive collection plan findings are invalid")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("archive collection plan content hash is invalid")


def build_archive_collection_plan(
    run: ArchiveCollectionRun,
    candidates: Iterable[ArchiveCollectionPlanSourceInput],
) -> ArchiveCollectionPlanSnapshot:
    """Consume every supplied candidate exactly once and return no private names."""

    if not isinstance(run, ArchiveCollectionRun):
        raise ValueError("archive collection planning run is invalid")
    materialized: list[ArchiveCollectionPlanSourceInput] = []
    seen_observations: set[EntityId] = set()
    try:
        for candidate in candidates:
            if not isinstance(candidate, ArchiveCollectionPlanSourceInput):
                raise ArchiveCollectionPlanningError(
                    "archive collection candidate stream is invalid"
                )
            if candidate.file_observation_id in seen_observations:
                raise ArchiveCollectionPlanningError(
                    "archive collection candidate observation is duplicated"
                )
            seen_observations.add(candidate.file_observation_id)
            materialized.append(candidate)
    except ArchiveCollectionPlanningError:
        raise
    except Exception:
        raise ArchiveCollectionPlanningError(
            "archive collection candidate stream failed"
        ) from None
    ordered = sorted(
        materialized,
        key=lambda item: (
            item.private_parent_key,
            item.basename.casefold(),
            item.basename,
            str(item.file_observation_id),
        ),
    )
    grouped: dict[str, list[ArchiveCollectionPlanSourceInput]] = {}
    for candidate in ordered:
        grouped.setdefault(candidate.private_parent_key, []).append(candidate)

    entries: list[ArchiveCollectionPlanEntry] = []
    counters = {finding: 0 for finding in ArchiveVolumePartitionFinding}
    hash_evidence_missing = 0
    for parent in sorted(grouped):
        parent_candidates = grouped[parent]
        by_name = {candidate.basename: candidate for candidate in parent_candidates}
        partition = partition_archive_volume_names(
            candidate.basename for candidate in parent_candidates
        )
        for finding in partition.findings:
            counters[finding] += 1
        for group in partition.groups:
            sources = tuple(by_name[name] for name in group.members)
            if any(source.full_sha256 is None for source in sources):
                hash_evidence_missing += 1
                continue
            if run.plan_limit is not None and len(entries) >= run.plan_limit:
                continue
            if group.entry_name is None:
                raise ArchiveCollectionPlanningError(
                    "archive collection volume entry is unavailable"
                )
            primary = by_name[group.entry_name]
            signature = observe_archive_signature_v2(
                primary.basename, primary.signature_prefix
            )
            if signature.suffix_kind is ArchiveSuffixKind.OTHER:
                raise ArchiveCollectionPlanningError(
                    "archive collection candidate suffix is unsupported"
                )
            ordinal = len(entries)
            item_id = EntityId(
                uuid5(
                    _ITEM_NAMESPACE,
                    f"{run.id}\x00{ordinal}\x00{primary.file_observation_id}",
                )
            )
            ordered_sources = (primary, *(source for source in sources if source is not primary))
            item = ArchiveCollectionItem(
                id=item_id,
                run_id=run.id,
                primary_file_observation_id=primary.file_observation_id,
                plan_ordinal=ordinal,
                signature=signature,
            )
            persisted_sources = tuple(
                ArchiveCollectionItemSource(
                    run_id=run.id,
                    item_id=item_id,
                    source_ordinal=source_ordinal,
                    file_observation_id=source.file_observation_id,
                    full_sha256=source.full_sha256 or "",
                    size_bytes=source.size_bytes,
                    staging_name=(
                        "archive" if source_ordinal == 0 else f"archive.{source_ordinal:03d}"
                    ),
                )
                for source_ordinal, source in enumerate(ordered_sources)
            )
            entries.append(ArchiveCollectionPlanEntry(item, persisted_sources))

    findings = ArchiveCollectionPlanFindingCounts(
        hash_evidence_missing=hash_evidence_missing,
        missing_volume=counters[ArchiveVolumePartitionFinding.MISSING_VOLUME],
        unsupported_volume=counters[ArchiveVolumePartitionFinding.UNSUPPORTED_VOLUME],
        ambiguous_volume=counters[ArchiveVolumePartitionFinding.AMBIGUOUS_VOLUME],
        name_collision=counters[ArchiveVolumePartitionFinding.NAME_COLLISION],
        orphan_volume=counters[ArchiveVolumePartitionFinding.ORPHAN_VOLUME],
    )
    entry_tuple = tuple(entries)
    return ArchiveCollectionPlanSnapshot(
        run.id,
        entry_tuple,
        findings,
        archive_collection_plan_content_hash(run, entry_tuple, findings),
    )


def persist_archive_collection_plan(
    store: SQLiteArchiveCollectionStore,
    run: ArchiveCollectionRun,
    lease_token: str,
    candidates: Iterable[ArchiveCollectionPlanSourceInput],
    *,
    now: Callable[[], datetime],
    lease_duration: timedelta = timedelta(minutes=30),
) -> ArchiveCollectionRun:
    """Write bounded idempotent batches, renewing the fence after every batch."""

    if not isinstance(store, SQLiteArchiveCollectionStore):
        raise ValueError("archive collection store is invalid")
    if lease_duration <= timedelta(0):
        raise ValueError("archive collection lease duration is invalid")
    snapshot = build_archive_collection_plan(run, candidates)
    current = run
    for batch in batched(snapshot.entries, ARCHIVE_COLLECTION_PLAN_BATCH_SIZE):
        heartbeat_at = now()
        store.append_plan_batch(
            run.id, lease_token, tuple(batch), now=heartbeat_at
        )
        current = store.heartbeat(
            run.id,
            lease_token,
            heartbeat_at=heartbeat_at,
            lease_expires_at=heartbeat_at + lease_duration,
        )
    sealed_at = now()
    return store.seal_plan(
        current.id,
        lease_token,
        planned_count=len(snapshot.entries),
        findings=snapshot.findings,
        plan_content_hash=snapshot.content_hash,
        sealed_at=sealed_at,
    )
