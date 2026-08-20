from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foliotone.adapters.calibre.library_capture import (
    parse_calibredb_capture_inventory_page,
)
from foliotone.core import EntityId
from foliotone.workflows.calibre_library_capture import (
    CalibreCapturedRecord,
    CalibreLibraryCaptureError,
    CalibreLibrarySnapshotGraph,
    build_calibre_snapshot_graph,
    calibre_opf_fingerprint,
)
from foliotone.workflows.calibre_reconciliation import CalibreLibrarySnapshotStatus

FIXTURES = Path(__file__).parents[1] / "fixtures" / "calibre_library" / "v1"
NOW = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _captured() -> tuple[CalibreCapturedRecord, ...]:
    inventory = parse_calibredb_capture_inventory_page(
        (FIXTURES / "cases_a_g" / "list_page_1.json").read_bytes()
    )
    return tuple(
        CalibreCapturedRecord(item, f"{index:064x}") for index, item in enumerate(inventory, 1)
    )


def _graph(*, final_digest: str = DIGEST) -> CalibreLibrarySnapshotGraph:
    return build_calibre_snapshot_graph(
        snapshot_id=EntityId.new(),
        scan_root_id=EntityId.new(),
        source_scan_run_id=EntityId.new(),
        tool_version="9.13.0",
        library_identity_digest="b" * 64,
        initial_inventory_digest=DIGEST,
        final_inventory_digest=final_digest,
        started_at=NOW,
        completed_at=NOW,
        captured_records=_captured(),
    )


def test_opf_fingerprint_validates_the_bounded_document_shape() -> None:
    data = (FIXTURES / "cases_a_g" / "show_metadata_106.opf").read_bytes()
    assert calibre_opf_fingerprint(data) == hashlib.sha256(data).hexdigest()

    for invalid in (
        b"\xff",
        b"<package/>",
        b"<!DOCTYPE package><package><metadata/></package>",
        b"<package><metadata>",
    ):
        with pytest.raises(CalibreLibraryCaptureError):
            calibre_opf_fingerprint(invalid)


def test_projection_builds_one_lineage_bound_record_and_format_graph() -> None:
    graph = _graph()

    assert graph.snapshot.status is CalibreLibrarySnapshotStatus.COMPLETED
    assert len(graph.records) == 8
    assert len(graph.formats) == 10
    assert tuple(item.calibre_record_id for item in graph.records) == tuple(range(101, 109))
    assert {item.snapshot_id for item in graph.records} == {graph.snapshot.id}
    assert {item.record_snapshot_id for item in graph.formats} == {
        item.id for item in graph.records
    }
    assert graph.records[0].last_modified_at == datetime(2026, 1, 1, 10, tzinfo=UTC)


def test_projection_marks_a_changed_final_inventory_invalidated() -> None:
    graph = _graph(final_digest="c" * 64)
    assert graph.snapshot.status is CalibreLibrarySnapshotStatus.INVALIDATED


def test_capture_graph_and_record_dtos_reject_foreign_or_mutated_material() -> None:
    graph = _graph()
    with pytest.raises(CalibreLibraryCaptureError):
        CalibreLibrarySnapshotGraph(
            graph.snapshot,
            (replace(graph.records[0], snapshot_id=EntityId.new()), *graph.records[1:]),
            graph.formats,
        )
    with pytest.raises(CalibreLibraryCaptureError):
        CalibreLibrarySnapshotGraph(graph.snapshot, graph.records, (graph.formats[0],) * 2)
    with pytest.raises(CalibreLibraryCaptureError):
        CalibreLibrarySnapshotGraph(graph.snapshot, graph.records, tuple(reversed(graph.formats)))
    with pytest.raises(CalibreLibraryCaptureError):
        CalibreCapturedRecord(_captured()[0].inventory, "not-a-digest")
    assert "Fixture" not in repr(_captured()[0])
    with pytest.raises(CalibreLibraryCaptureError):
        build_calibre_snapshot_graph(
            snapshot_id=EntityId.new(),
            scan_root_id=EntityId.new(),
            source_scan_run_id=EntityId.new(),
            tool_version="9.13.0",
            library_identity_digest="b" * 64,
            initial_inventory_digest=DIGEST,
            final_inventory_digest=DIGEST,
            started_at=NOW,
            completed_at=NOW,
            captured_records=tuple(reversed(_captured())),
        )
