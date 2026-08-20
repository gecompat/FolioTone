from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from foliotone.adapters.calibre.library_capture import (
    parse_calibredb_capture_inventory_page,
)
from foliotone.core import EntityId, ToolCapability, ToolExecutionStatus
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
)
from foliotone.tooling.artifacts import ToolArtifact
from foliotone.tooling.contracts import ToolExecution
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome, ToolRuntime
from foliotone.workflows.calibre_library_capture import (
    CalibreCapturedRecord,
    CalibreLibraryCaptureError,
    CalibreLibraryCaptureReader,
    CalibreLibrarySnapshotGraph,
    build_calibre_snapshot_graph,
    calibre_opf_fingerprint,
)
from foliotone.workflows.calibre_reconciliation import CalibreLibrarySnapshotStatus

FIXTURES = Path(__file__).parents[1] / "fixtures" / "calibre_library" / "v1"
NOW = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)
DIGEST = "a" * 64


class _FakeRuntime:
    def __init__(self, *, final_changed: bool = False, bad_exact_id: int | None = None) -> None:
        fixture = (FIXTURES / "cases_a_g" / "list_page_1.json").read_bytes()
        if final_changed:
            decoded = json.loads(fixture)
            decoded[0]["last_modified"] = "2026-01-01T10:00:01Z"
            final = json.dumps(decoded).encode()
        else:
            final = fixture
        self._inventories = [fixture, final]
        self._payloads: dict[EntityId, bytes] = {}
        self._bad_exact_id = bad_exact_id
        self.commands: list[LocalCommand] = []

    def execute_local(
        self,
        _descriptor: object,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.commands.append(command)
        if command.args[0] == "list":
            payload = self._inventories.pop(0)
        elif command.args[0] == "search":
            record_id = int(command.args[-1].removeprefix("id:="))
            payload = f"{self._bad_exact_id or record_id}\n".encode()
        elif command.args[0] == "show_metadata":
            payload = b"<package><metadata><title>synthetic</title></metadata></package>"
        else:
            payload = (FIXTURES / "cases_a_g" / "list_categories.csv").read_bytes()
        execution_id = EntityId.new()
        execution = ToolExecution(
            execution_id,
            "calibre-library",
            "9.13.0",
            "calibredb-library/1",
            ToolCapability.LIBRARY_READ,
            input_identity,
            NOW,
            ToolExecutionStatus.SUCCEEDED,
            finished_at=NOW,
            exit_code=0,
            config_identity=config_identity,
        )
        artifact = ToolArtifact(
            EntityId.new(), execution_id, "STDOUT", f"{execution_id}/stdout.bin", len(payload), "a"
        )
        self._payloads[artifact.id] = payload
        return ToolRunOutcome(execution, (artifact,), "", "")

    def read_artifact_bytes(self, artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        payload = self._payloads[artifact.id]
        if len(payload) > max_bytes:
            raise ValueError("oversized")
        return payload


def _lease(capture_id: EntityId) -> OwnedScanRootWriteLease:
    return OwnedScanRootWriteLease(
        EntityId.new(),
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
        capture_id,
        "synthetic-lease",
        1,
        NOW,
        NOW,
        NOW + timedelta(minutes=5),
    )


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


def test_reader_executes_the_complete_fixed_sequence_under_one_capture_identity() -> None:
    capture_id = EntityId.new()
    runtime = _FakeRuntime()
    reader = CalibreLibraryCaptureReader(cast(ToolRuntime, cast(Any, runtime)), clock=lambda: NOW)

    result = reader.read(
        Path.cwd() / "synthetic-calibre-library",
        capture_id=capture_id,
        library_identity_digest="b" * 64,
        lease=_lease(capture_id),
    )

    assert result.capture_id == capture_id
    assert len(result.captured_records) == 8
    assert len(result.execution_ids) == 19
    assert result.category_count == 6
    assert result.initial_inventory_digest == result.final_inventory_digest
    assert tuple(command.args[0] for command in runtime.commands) == (
        "list",
        *(value for _record in range(8) for value in ("search", "show_metadata")),
        "list_categories",
        "list",
    )


def test_reader_preserves_changed_inventory_and_rejects_exact_id_drift() -> None:
    capture_id = EntityId.new()
    changed_runtime = _FakeRuntime(final_changed=True)
    changed = CalibreLibraryCaptureReader(
        cast(ToolRuntime, cast(Any, changed_runtime)), clock=lambda: NOW
    ).read(
        Path.cwd() / "synthetic-calibre-library",
        capture_id=capture_id,
        library_identity_digest="b" * 64,
        lease=_lease(capture_id),
    )
    assert changed.initial_inventory_digest != changed.final_inventory_digest

    failed_id = EntityId.new()
    failed_runtime = _FakeRuntime(bad_exact_id=999)
    with pytest.raises(CalibreLibraryCaptureError, match="exact-ID"):
        CalibreLibraryCaptureReader(
            cast(ToolRuntime, cast(Any, failed_runtime)), clock=lambda: NOW
        ).read(
            Path.cwd() / "synthetic-calibre-library",
            capture_id=failed_id,
            library_identity_digest="b" * 64,
            lease=_lease(failed_id),
        )
    assert len(failed_runtime.commands) == 2


def test_reader_rejects_a_foreign_lease_before_running_a_tool() -> None:
    capture_id = EntityId.new()
    runtime = _FakeRuntime()
    with pytest.raises(CalibreLibraryCaptureError, match="lease"):
        CalibreLibraryCaptureReader(cast(ToolRuntime, cast(Any, runtime)), clock=lambda: NOW).read(
            Path.cwd() / "synthetic-calibre-library",
            capture_id=capture_id,
            library_identity_digest="b" * 64,
            lease=_lease(EntityId.new()),
        )
    assert runtime.commands == []
