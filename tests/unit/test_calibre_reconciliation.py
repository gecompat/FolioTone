from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId
from foliotone.workflows.calibre_reconciliation import (
    CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySidecarKind,
    CalibreLibrarySidecarSnapshot,
    CalibreLibrarySnapshot,
    CalibreLibrarySnapshotStatus,
)

STARTED = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
COMPLETED = STARTED + timedelta(minutes=2)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _snapshot(
    *,
    status: CalibreLibrarySnapshotStatus = CalibreLibrarySnapshotStatus.COMPLETED,
    initial_digest: str | None = DIGEST_A,
    final_digest: str | None = DIGEST_A,
    completed_at: datetime | None = COMPLETED,
) -> CalibreLibrarySnapshot:
    return CalibreLibrarySnapshot(
        id=EntityId.new(),
        scan_root_id=EntityId.new(),
        source_scan_run_id=EntityId.new(),
        profile=CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
        adapter_version="calibredb-library/1",
        tool_version="9.13.0",
        parser_version="calibre-library-parser/1",
        library_identity_digest=DIGEST_B,
        initial_inventory_digest=initial_digest,
        final_inventory_digest=final_digest,
        status=status,
        started_at=STARTED,
        completed_at=completed_at,
    )


def _record() -> CalibreLibraryRecordSnapshot:
    return CalibreLibraryRecordSnapshot(
        id=EntityId.new(),
        snapshot_id=EntityId.new(),
        calibre_record_id=42,
        metadata_fingerprint=DIGEST_A,
        calibre_uuid="00000000-0000-4000-8000-000000000042",
        title="Synthetic title",
        authors=("Synthetic Author",),
        identifiers=(("isbn", "9780000000042"),),
        last_modified_at=STARTED,
    )


def test_completed_snapshot_record_multiformat_and_sidecar_are_immutable() -> None:
    snapshot = _snapshot()
    record = _record()
    formats = tuple(
        CalibreLibraryFormatSnapshot(
            id=EntityId.new(),
            record_snapshot_id=record.id,
            format_label=label,
            relative_locator=f"Synthetic/Book.{label.lower()}",
            declared_size_bytes=index,
            observation_id=EntityId.new(),
        )
        for index, label in enumerate(("EPUB", "MOBI", "PDF"), start=1)
    )
    sidecar = CalibreLibrarySidecarSnapshot(
        id=EntityId.new(),
        record_snapshot_id=record.id,
        kind=CalibreLibrarySidecarKind.METADATA_OPF,
        relative_locator="Synthetic/metadata.opf",
        observation_id=None,
    )

    assert snapshot.status is CalibreLibrarySnapshotStatus.COMPLETED
    assert tuple(item.format_label for item in formats) == ("EPUB", "MOBI", "PDF")
    assert all(item.record_snapshot_id == record.id for item in formats)
    assert sidecar.record_snapshot_id == record.id
    assert not hasattr(record, "duplicate")
    assert not hasattr(formats[0], "finding")
    with pytest.raises(FrozenInstanceError):
        formats[0].format_label = "AZW3"  # type: ignore[misc]


def test_private_metadata_locators_and_digests_are_hidden_from_repr() -> None:
    snapshot = _snapshot()
    record = _record()
    format_snapshot = CalibreLibraryFormatSnapshot(
        id=EntityId.new(),
        record_snapshot_id=record.id,
        format_label="EPUB",
        relative_locator="Private/Book.epub",
    )
    sidecar = CalibreLibrarySidecarSnapshot(
        id=EntityId.new(),
        record_snapshot_id=record.id,
        kind=CalibreLibrarySidecarKind.UNKNOWN_SIDECAR,
        relative_locator="Private/notes.txt",
    )

    joined = " ".join(map(repr, (snapshot, record, format_snapshot, sidecar)))
    for private_value in (
        DIGEST_A,
        DIGEST_B,
        "Synthetic title",
        "Synthetic Author",
        "9780000000042",
        "Private/Book.epub",
        "Private/notes.txt",
    ):
        assert private_value not in joined


@pytest.mark.parametrize(
    ("status", "initial_digest", "final_digest", "completed_at"),
    (
        (CalibreLibrarySnapshotStatus.RUNNING, None, None, COMPLETED),
        (CalibreLibrarySnapshotStatus.RUNNING, DIGEST_A, DIGEST_A, None),
        (CalibreLibrarySnapshotStatus.COMPLETED, DIGEST_A, DIGEST_B, COMPLETED),
        (CalibreLibrarySnapshotStatus.COMPLETED, None, None, COMPLETED),
        (CalibreLibrarySnapshotStatus.INVALIDATED, DIGEST_A, DIGEST_A, COMPLETED),
        (CalibreLibrarySnapshotStatus.INVALIDATED, DIGEST_A, DIGEST_B, None),
        (CalibreLibrarySnapshotStatus.FAILED, None, None, None),
    ),
)
def test_snapshot_lifecycle_rejects_inconsistent_states(
    status: CalibreLibrarySnapshotStatus,
    initial_digest: str | None,
    final_digest: str | None,
    completed_at: datetime | None,
) -> None:
    with pytest.raises(ValueError):
        _snapshot(
            status=status,
            initial_digest=initial_digest,
            final_digest=final_digest,
            completed_at=completed_at,
        )


def test_running_and_failed_snapshots_allow_partial_capture_evidence() -> None:
    running = _snapshot(
        status=CalibreLibrarySnapshotStatus.RUNNING,
        initial_digest=DIGEST_A,
        final_digest=None,
        completed_at=None,
    )
    failed = _snapshot(
        status=CalibreLibrarySnapshotStatus.FAILED,
        initial_digest=None,
        final_digest=None,
        completed_at=COMPLETED,
    )
    assert running.completed_at is None
    assert failed.completed_at == COMPLETED


@pytest.mark.parametrize("digest", ("", "g" * 64, "a" * 63))
def test_snapshot_rejects_invalid_identity_digest(digest: str) -> None:
    with pytest.raises(ValueError):
        replace(_snapshot(), library_identity_digest=digest)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("profile", "calibre-library-snapshot/v2"),
        ("adapter_version", "calibredb-library/2"),
        ("parser_version", "calibre-library-parser/2"),
    ),
)
def test_snapshot_rejects_unknown_contract_versions(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        replace(_snapshot(), **{field_name: value})


@pytest.mark.parametrize("record_id", (-1, True, 1.5))
def test_record_requires_nonnegative_integer_id(record_id: object) -> None:
    with pytest.raises(ValueError):
        CalibreLibraryRecordSnapshot(
            id=EntityId.new(),
            snapshot_id=EntityId.new(),
            calibre_record_id=record_id,  # type: ignore[arg-type]
            metadata_fingerprint=DIGEST_A,
        )


def test_record_canonicalizes_identifier_order_and_bounds_metadata() -> None:
    record = CalibreLibraryRecordSnapshot(
        id=EntityId.new(),
        snapshot_id=EntityId.new(),
        calibre_record_id=1,
        metadata_fingerprint=DIGEST_A.upper(),
        authors=("First", "Second"),
        identifiers=(("zeta", "2"), ("alpha", "1")),
    )
    assert record.metadata_fingerprint == DIGEST_A
    assert record.identifiers == (("alpha", "1"), ("zeta", "2"))
    with pytest.raises(ValueError, match="count limit"):
        CalibreLibraryRecordSnapshot(
            id=EntityId.new(),
            snapshot_id=EntityId.new(),
            calibre_record_id=1,
            metadata_fingerprint=DIGEST_A,
            authors=tuple("author" for _ in range(257)),
        )


@pytest.mark.parametrize(
    "locator",
    (
        "C:/private/book.epub",
        "/private/book.epub",
        "//server/share/book.epub",
        "../book.epub",
        "folder/./book.epub",
        "folder//book.epub",
        "folder/book.epub:stream",
        "\\\\?\\C:\\book.epub",
        "folder\x00/book.epub",
    ),
)
def test_format_rejects_absolute_traversal_device_and_ads_locators(locator: str) -> None:
    with pytest.raises(ValueError):
        CalibreLibraryFormatSnapshot(
            id=EntityId.new(),
            record_snapshot_id=EntityId.new(),
            format_label="EPUB",
            relative_locator=locator,
        )


def test_format_normalizes_relative_locator_and_validates_label_and_size() -> None:
    item = CalibreLibraryFormatSnapshot(
        id=EntityId.new(),
        record_snapshot_id=EntityId.new(),
        format_label="epub",
        relative_locator="Synthetic\\Book.epub",
        declared_size_bytes=0,
        observation_id=None,
    )
    assert item.format_label == "EPUB"
    assert item.relative_locator == "Synthetic/Book.epub"

    with pytest.raises(ValueError, match="suffix"):
        CalibreLibraryFormatSnapshot(
            id=EntityId.new(),
            record_snapshot_id=EntityId.new(),
            format_label="PDF",
            relative_locator="Synthetic/Book.epub",
        )
    with pytest.raises(ValueError, match="declared_size_bytes"):
        CalibreLibraryFormatSnapshot(
            id=EntityId.new(),
            record_snapshot_id=EntityId.new(),
            format_label="EPUB",
            relative_locator="Synthetic/Book.epub",
            declared_size_bytes=-1,
        )


def test_sidecar_requires_fixed_kind_but_allows_unmapped_observation() -> None:
    sidecar = CalibreLibrarySidecarSnapshot(
        id=EntityId.new(),
        record_snapshot_id=EntityId.new(),
        kind=CalibreLibrarySidecarKind.EXTRA_DATA,
        relative_locator="Synthetic/data/notes.txt",
        observation_id=None,
    )
    assert sidecar.observation_id is None
    with pytest.raises(ValueError, match="SidecarKind"):
        CalibreLibrarySidecarSnapshot(
            id=EntityId.new(),
            record_snapshot_id=EntityId.new(),
            kind="COVER",  # type: ignore[arg-type]
            relative_locator="Synthetic/cover.jpg",
        )

    for kind, locator in (
        (CalibreLibrarySidecarKind.METADATA_OPF, "Synthetic/other.opf"),
        (CalibreLibrarySidecarKind.COVER, "Synthetic/other.jpg"),
        (CalibreLibrarySidecarKind.EXTRA_DATA, "Synthetic/notes.txt"),
    ):
        with pytest.raises(ValueError):
            CalibreLibrarySidecarSnapshot(
                id=EntityId.new(),
                record_snapshot_id=EntityId.new(),
                kind=kind,
                relative_locator=locator,
            )
