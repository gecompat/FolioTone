from __future__ import annotations

from datetime import UTC, datetime

import pytest

from foliotone.collection_state import (
    COLLECTION_STATE_COMPONENT_ORDER,
    COLLECTION_STATE_COUNT_PREFIXES,
    COLLECTION_STATE_FORMAT_NAMES,
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
from foliotone.collection_state.contracts import sha256_digest
from foliotone.core import EntityId

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _item(ordinal: int = 0) -> CollectionStateItem:
    missing = CollectionStateItemState.MISSING
    return CollectionStateItem(
        ordinal=ordinal,
        file_id=EntityId.parse(f"10000000-0000-0000-0000-{ordinal + 1:012d}"),
        observation_id=EntityId.parse(f"20000000-0000-0000-0000-{ordinal + 1:012d}"),
        format_name="EPUB",
        size_bytes=100 + ordinal,
        technical_digest=sha256_digest({"ordinal": ordinal}),
        analysis_state=missing,
        analysis_digest=None,
        resolution_state=missing,
        resolution_digest=None,
        classification_state=missing,
        classification_digest=None,
        matching_state=missing,
        matching_digest=None,
        review_state=missing,
        review_digest=None,
        calibre_state=missing,
        calibre_digest=None,
        archive_state=missing,
        archive_digest=None,
        consolidation_state=missing,
        consolidation_digest=None,
        quarantine_state=missing,
        quarantine_digest=None,
        item_digest="",
    )


def _components(item_count: int) -> tuple[CollectionStateComponentSummary, ...]:
    return tuple(
        CollectionStateComponentSummary(
            component=component,
            profile_versions=(),
            evidence_count=0,
            current_item_count=0,
            stale_item_count=0,
            unscoped_item_count=0,
            missing_item_count=item_count,
            conflict_item_count=0,
            coverage_state=CollectionStateCoverageState.NONE,
            freshness_state=(
                CollectionStateFreshnessState.CURRENT
                if item_count == 0
                else CollectionStateFreshnessState.UNKNOWN
            ),
            conflict_state=CollectionStateConflictState.NONE,
            truncation_state=CollectionStateTruncationState.NONE,
            evidence_digest=sha256_digest({"component": component.value}),
        )
        for component in COLLECTION_STATE_COMPONENT_ORDER
    )


def _counts(item_count: int, total_size_bytes: int) -> tuple[CollectionStateCount, ...]:
    values = {
        "physical.byte_count": total_size_bytes,
        "physical.item_count": item_count,
    }
    for format_name in COLLECTION_STATE_FORMAT_NAMES:
        values[f"physical.format.{format_name.casefold()}"] = (
            item_count if format_name == "EPUB" else 0
        )
    for prefix in COLLECTION_STATE_COUNT_PREFIXES.values():
        values.update(
            {
                f"{prefix}.conflict_items": 0,
                f"{prefix}.current_items": 0,
                f"{prefix}.evidence_links": 0,
                f"{prefix}.missing_items": item_count,
                f"{prefix}.stale_items": 0,
                f"{prefix}.unscoped_items": 0,
            }
        )
    return tuple(CollectionStateCount(key, values[key]) for key in sorted(values))


def test_item_and_stream_digest_are_deterministic_and_ordered() -> None:
    first = _item(0)
    second = _item(1)
    repeat = _item(0)

    assert first.item_digest == repeat.item_digest
    assert first.canonical_payload() == repeat.canonical_payload()
    hasher = CollectionStateItemsHasher()
    hasher.update(first)
    hasher.update(second)
    assert hasher.count == 2
    assert len(hasher.hexdigest()) == 64

    with pytest.raises(ValueError, match="contiguous"):
        CollectionStateItemsHasher().update(second)


def test_missing_dimension_rejects_a_digest() -> None:
    item = _item()
    with pytest.raises(ValueError, match="missing component"):
        CollectionStateItem(
            ordinal=item.ordinal,
            file_id=item.file_id,
            observation_id=item.observation_id,
            format_name=item.format_name,
            size_bytes=item.size_bytes,
            technical_digest=item.technical_digest,
            analysis_state=CollectionStateItemState.MISSING,
            analysis_digest="a" * 64,
            resolution_state=item.resolution_state,
            resolution_digest=item.resolution_digest,
            classification_state=item.classification_state,
            classification_digest=item.classification_digest,
            matching_state=item.matching_state,
            matching_digest=item.matching_digest,
            review_state=item.review_state,
            review_digest=item.review_digest,
            calibre_state=item.calibre_state,
            calibre_digest=item.calibre_digest,
            archive_state=item.archive_state,
            archive_digest=item.archive_digest,
            consolidation_state=item.consolidation_state,
            consolidation_digest=item.consolidation_digest,
            quarantine_state=item.quarantine_state,
            quarantine_digest=item.quarantine_digest,
            item_digest="",
        )


def test_snapshot_identity_excludes_build_time_but_binds_all_material() -> None:
    item = _item()
    hasher = CollectionStateItemsHasher()
    hasher.update(item)
    components = _components(1)
    counts = _counts(1, 100)
    material = {
        "profile": "collection-state/v1",
        "serializer": "canonical-json/v1",
        "scan_root_id": "30000000-0000-0000-0000-000000000001",
        "source_scan_run_id": "30000000-0000-0000-0000-000000000002",
        "item_count": 1,
        "total_size_bytes": 100,
        "items_digest": hasher.hexdigest(),
        "components": [component.canonical_payload() for component in components],
        "counts": [count.canonical_payload() for count in counts],
    }
    content_digest = sha256_digest(material)
    snapshot = CollectionStateSnapshot(
        id=collection_state_snapshot_id(content_digest),
        scan_root_id=EntityId.parse(str(material["scan_root_id"])),
        source_scan_run_id=EntityId.parse(str(material["source_scan_run_id"])),
        created_at=NOW,
        item_count=1,
        total_size_bytes=100,
        items_digest=hasher.hexdigest(),
        components=components,
        counts=counts,
        content_digest=content_digest,
    )

    assert snapshot.content_digest == content_digest
    assert "created_at" not in snapshot.material_payload()
