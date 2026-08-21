"""Synthetic deterministic planning tests for ADR-0053 S-EBAR-08B."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import ArchiveCollectionRun, ArchiveCollectionRunStatus, EntityId
from foliotone.persistence.archive_collection import SQLiteArchiveCollectionStore
from foliotone.workflows.archive_collection_plan import (
    ArchiveCollectionPlanningError,
    ArchiveCollectionPlanSourceInput,
    build_archive_collection_plan,
    persist_archive_collection_plan,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
RUN_ID = EntityId.parse("00000000-0000-0000-0000-000000000401")
ROOT_ID = EntityId.parse("00000000-0000-0000-0000-000000000402")
SCAN_ID = EntityId.parse("00000000-0000-0000-0000-000000000403")


def _run(*, plan_limit: int | None = None) -> ArchiveCollectionRun:
    return ArchiveCollectionRun(
        id=RUN_ID,
        scan_root_id=ROOT_ID,
        source_scan_run_id=SCAN_ID,
        worker_count=1,
        plan_limit=plan_limit,
        started_at=NOW,
        status=ArchiveCollectionRunStatus.PLANNING,
        fence_epoch=1,
        heartbeat_at=NOW,
        lease_token="opaque-owner",
        lease_expires_at=NOW + timedelta(minutes=30),
    )


def _source(
    suffix: int,
    basename: str,
    header: bytes,
    *,
    parent: str = "private-parent-a",
    full_sha256: str | None = None,
) -> ArchiveCollectionPlanSourceInput:
    return ArchiveCollectionPlanSourceInput(
        file_observation_id=EntityId.parse(
            f"00000000-0000-0000-0000-{suffix:012d}"
        ),
        size_bytes=8,
        full_sha256=full_sha256 if full_sha256 is not None else f"{suffix % 16:x}" * 64,
        private_parent_key=parent,
        basename=basename,
        signature_prefix=header,
    )


def test_direct_and_multivolume_plan_is_order_independent_and_name_free() -> None:
    candidates = (
        _source(411, "alpha.part02.rar", b"ignored"),
        _source(412, "solo.cbz", b"PK\x03\x04data", parent="private-parent-b"),
        _source(410, "alpha.part01.rar", b"Rar!\x1a\x07\x00"),
    )
    forward = build_archive_collection_plan(_run(), candidates)
    reversed_plan = build_archive_collection_plan(_run(), reversed(candidates))

    assert forward == reversed_plan
    assert len(forward.entries) == 2
    rar = forward.entries[0]
    assert tuple(source.staging_name for source in rar.sources) == (
        "archive",
        "archive.001",
    )
    assert tuple(source.file_observation_id for source in rar.sources) == (
        candidates[2].file_observation_id,
        candidates[0].file_observation_id,
    )
    rendered = repr(forward)
    assert "alpha" not in rendered
    assert "solo" not in rendered
    assert "private-parent" not in rendered


def test_findings_are_complete_and_plan_limit_is_deterministic() -> None:
    missing_hash = replace(
        _source(420, "missing.zip", b"PK\x03\x04"), full_sha256=None
    )
    candidates = (
        _source(421, "gap.7z.001", b"7z\xbc\xaf'\x1c"),
        _source(422, "gap.7z.003", b"ignored"),
        _source(423, "orphan.r00", b"ignored"),
        _source(424, "Case.zip", b"PK\x03\x04"),
        _source(425, "case.ZIP", b"PK\x03\x04"),
        _source(426, "mixed.part01.rar", b"Rar!\x1a\x07\x00"),
        _source(427, "mixed.rar", b"Rar!\x1a\x07\x00"),
        missing_hash,
        _source(428, "one.zip", b"PK\x03\x04", parent="private-parent-b"),
        _source(429, "two.zip", b"PK\x03\x04", parent="private-parent-b"),
    )
    planned = build_archive_collection_plan(_run(plan_limit=1), candidates)

    assert len(planned.entries) == 1
    assert planned.findings.hash_evidence_missing == 1
    assert planned.findings.missing_volume == 1
    assert planned.findings.ambiguous_volume == 1
    assert planned.findings.name_collision == 1
    assert planned.findings.orphan_volume == 1


def test_candidate_stream_failure_and_duplicate_observation_fail_closed() -> None:
    first = _source(430, "one.zip", b"PK\x03\x04")

    def broken():
        yield first
        raise RuntimeError("private locator")

    with pytest.raises(
        ArchiveCollectionPlanningError,
        match="archive collection candidate stream failed",
    ) as raised:
        build_archive_collection_plan(_run(), broken())
    assert "private locator" not in str(raised.value)

    duplicate = _source(430, "two.zip", b"PK\x03\x04")
    with pytest.raises(ArchiveCollectionPlanningError, match="duplicated"):
        build_archive_collection_plan(_run(), (first, duplicate))


def test_private_source_dto_rejects_paths_and_redacts_material() -> None:
    source = _source(440, "one.zip", b"PK\x03\x04")
    assert "one.zip" not in repr(source)
    assert "private-parent-a" not in repr(source)
    with pytest.raises(ValueError, match="basename contains a path"):
        _source(441, "private/one.zip", b"PK\x03\x04")


def test_persistence_uses_exact_500_row_batches_and_renews_each_batch() -> None:
    class RecordingStore(SQLiteArchiveCollectionStore):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []
            self.heartbeats = 0

        def append_plan_batch(self, run_id, lease_token, entries, *, now):
            self.batch_sizes.append(len(entries))
            return sum(self.batch_sizes)

        def heartbeat(
            self, run_id, lease_token, *, heartbeat_at, lease_expires_at
        ):
            self.heartbeats += 1
            return run

        def seal_plan(
            self,
            run_id,
            lease_token,
            *,
            planned_count,
            findings,
            plan_content_hash,
            sealed_at,
        ):
            assert planned_count == 501
            return replace(
                run,
                status=ArchiveCollectionRunStatus.RUNNING,
                planned_count=planned_count,
                plan_findings=findings,
                plan_content_hash=plan_content_hash,
            )

    run = _run()
    candidates = tuple(
        _source(
            1_000 + ordinal,
            f"item-{ordinal:03d}.zip",
            b"PK\x03\x04",
        )
        for ordinal in range(501)
    )
    store = RecordingStore()
    ticks = iter(NOW + timedelta(seconds=value) for value in range(3))
    sealed = persist_archive_collection_plan(
        store, run, "opaque-owner", candidates, now=lambda: next(ticks)
    )

    assert store.batch_sizes == [500, 1]
    assert store.heartbeats == 2
    assert sealed.status is ArchiveCollectionRunStatus.RUNNING
