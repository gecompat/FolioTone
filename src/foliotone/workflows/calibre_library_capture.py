"""Pure projection for one consistency-checked Calibre library capture."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from foliotone.adapters.calibre.library import (
    CALIBRE_LIBRARY_MAX_PAGE_SIZE,
    CALIBRE_LIBRARY_PROVIDER,
    MAX_CALIBRE_METADATA_STDOUT_BYTES,
    build_calibredb_exact_id_command,
    build_calibredb_inventory_command,
    build_calibredb_list_categories_command,
    build_calibredb_show_metadata_command,
)
from foliotone.adapters.calibre.library_capture import (
    ParsedCalibreCaptureRecord,
    calibre_inventory_digest,
    parse_calibredb_capture_inventory_page,
    parse_calibredb_categories,
    parse_calibredb_exact_ids,
)
from foliotone.core import EntityId, ToolExecutionStatus
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
    scan_root_write_scope,
)
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome, ToolRuntime
from foliotone.workflows.calibre_reconciliation import (
    CALIBRE_LIBRARY_ADAPTER_VERSION,
    CALIBRE_LIBRARY_PARSER_VERSION,
    CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySnapshot,
    CalibreLibrarySnapshotStatus,
)


class CalibreLibraryCaptureError(ValueError):
    """A bounded capture projection is malformed or internally inconsistent."""


CALIBRE_CAPTURE_CONFIG_PROFILE = "calibre-library-capture/v1"
MAX_CALIBRE_CAPTURE_RECORDS = 1_000_000
MAX_CALIBRE_CAPTURE_PAGES = MAX_CALIBRE_CAPTURE_RECORDS // CALIBRE_LIBRARY_MAX_PAGE_SIZE + 1

type Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CalibreCapturedRecord:
    """One bounded inventory record bound to its exact OPF fingerprint."""

    inventory: ParsedCalibreCaptureRecord = field(repr=False)
    metadata_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, ParsedCalibreCaptureRecord):
            raise CalibreLibraryCaptureError("Calibre capture record is invalid")
        object.__setattr__(
            self,
            "metadata_fingerprint",
            _require_sha256(self.metadata_fingerprint, "metadata fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class CalibreLibrarySnapshotGraph:
    """The atomic snapshot subset produced directly by the capture adapter."""

    snapshot: CalibreLibrarySnapshot
    records: tuple[CalibreLibraryRecordSnapshot, ...]
    formats: tuple[CalibreLibraryFormatSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, CalibreLibrarySnapshot):
            raise CalibreLibraryCaptureError("Calibre snapshot is invalid")
        if not isinstance(self.records, tuple) or any(
            not isinstance(item, CalibreLibraryRecordSnapshot) for item in self.records
        ):
            raise CalibreLibraryCaptureError("Calibre snapshot records are invalid")
        if not isinstance(self.formats, tuple) or any(
            not isinstance(item, CalibreLibraryFormatSnapshot) for item in self.formats
        ):
            raise CalibreLibraryCaptureError("Calibre snapshot formats are invalid")
        if any(item.snapshot_id != self.snapshot.id for item in self.records):
            raise CalibreLibraryCaptureError("Calibre record belongs to another snapshot")
        record_ids = {item.id for item in self.records}
        if len(record_ids) != len(self.records):
            raise CalibreLibraryCaptureError("Calibre record IDs must be unique")
        if any(item.record_snapshot_id not in record_ids for item in self.formats):
            raise CalibreLibraryCaptureError("Calibre format belongs to another snapshot")
        record_numbers = tuple(item.calibre_record_id for item in self.records)
        if record_numbers != tuple(sorted(record_numbers)) or len(set(record_numbers)) != len(
            record_numbers
        ):
            raise CalibreLibraryCaptureError("Calibre records must be strictly ordered")
        format_keys = tuple(
            (item.record_snapshot_id, item.format_label, item.relative_locator)
            for item in self.formats
        )
        if len(set(format_keys)) != len(format_keys):
            raise CalibreLibraryCaptureError("Calibre formats must be unique")
        record_ordinals = {item.id: ordinal for ordinal, item in enumerate(self.records)}
        ordered_format_keys = tuple(
            (record_ordinals[item.record_snapshot_id], item.format_label, item.relative_locator)
            for item in self.formats
        )
        if ordered_format_keys != tuple(sorted(ordered_format_keys)):
            raise CalibreLibraryCaptureError("Calibre formats must be canonically ordered")


@dataclass(frozen=True, slots=True)
class CalibreLibraryReadCapture:
    """Path-free result of one complete read-only Calibre command sequence."""

    capture_id: EntityId
    captured_records: tuple[CalibreCapturedRecord, ...] = field(repr=False)
    initial_inventory_digest: str = field(repr=False)
    final_inventory_digest: str = field(repr=False)
    tool_version: str
    execution_ids: tuple[EntityId, ...]
    category_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.capture_id, EntityId):
            raise CalibreLibraryCaptureError("Calibre capture ID is invalid")
        if not isinstance(self.captured_records, tuple) or any(
            not isinstance(item, CalibreCapturedRecord) for item in self.captured_records
        ):
            raise CalibreLibraryCaptureError("Calibre read capture records are invalid")
        numbers = tuple(item.inventory.record.record_id for item in self.captured_records)
        if numbers != tuple(sorted(numbers)) or len(set(numbers)) != len(numbers):
            raise CalibreLibraryCaptureError("Calibre read capture records are not ordered")
        object.__setattr__(
            self,
            "initial_inventory_digest",
            _require_sha256(self.initial_inventory_digest, "initial inventory digest"),
        )
        object.__setattr__(
            self,
            "final_inventory_digest",
            _require_sha256(self.final_inventory_digest, "final inventory digest"),
        )
        if not isinstance(self.tool_version, str) or not self.tool_version.strip():
            raise CalibreLibraryCaptureError("Calibre tool version is invalid")
        if (
            not isinstance(self.execution_ids, tuple)
            or not self.execution_ids
            or any(not isinstance(item, EntityId) for item in self.execution_ids)
        ):
            raise CalibreLibraryCaptureError("Calibre capture executions are invalid")
        if len(set(self.execution_ids)) != len(self.execution_ids):
            raise CalibreLibraryCaptureError("Calibre capture executions must be unique")
        if (
            isinstance(self.category_count, bool)
            or not isinstance(self.category_count, int)
            or self.category_count < 0
        ):
            raise CalibreLibraryCaptureError("Calibre category count is invalid")


class CalibreLibraryCaptureReader:
    """Execute the fixed ADR-0033 read sequence under an existing root lease."""

    def __init__(self, runtime: ToolRuntime, *, clock: Clock) -> None:
        self._runtime = runtime
        self._clock = clock

    def read(
        self,
        library_path: Path,
        *,
        capture_id: EntityId,
        library_identity_digest: str,
        lease: OwnedScanRootWriteLease,
    ) -> CalibreLibraryReadCapture:
        if (
            lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_ANALYSIS
            or lease.owner_run_id != capture_id
        ):
            raise CalibreLibraryCaptureError("Calibre capture lease is incompatible")
        identity_digest = _require_sha256(library_identity_digest, "library identity digest")
        input_identity = f"calibre-library-capture:{capture_id}"
        config_identity = f"{CALIBRE_CAPTURE_CONFIG_PROFILE}:{identity_digest}"
        execution_ids: list[EntityId] = []
        tool_versions: set[str] = set()

        def execute(command: LocalCommand) -> bytes:
            with scan_root_write_scope(lease, self._clock):
                outcome = self._runtime.execute_local(
                    CALIBRE_LIBRARY_PROVIDER,
                    command,
                    input_identity=input_identity,
                    config_identity=config_identity,
                )
            return self._validated_stdout(
                outcome,
                command,
                input_identity=input_identity,
                config_identity=config_identity,
                execution_ids=execution_ids,
                tool_versions=tool_versions,
            )

        initial = self._read_inventory(library_path, execute)
        captured: list[CalibreCapturedRecord] = []
        for inventory in initial:
            record_id = inventory.record.record_id
            exact_ids = parse_calibredb_exact_ids(
                execute(build_calibredb_exact_id_command(library_path, record_id=record_id))
            )
            if exact_ids != (record_id,):
                raise CalibreLibraryCaptureError("Calibre exact-ID verification failed")
            opf = execute(build_calibredb_show_metadata_command(library_path, record_id=record_id))
            captured.append(CalibreCapturedRecord(inventory, calibre_opf_fingerprint(opf)))
        categories = parse_calibredb_categories(
            execute(build_calibredb_list_categories_command(library_path))
        )
        final = self._read_inventory(library_path, execute)
        if len(tool_versions) != 1:
            raise CalibreLibraryCaptureError("Calibre tool version changed during capture")
        return CalibreLibraryReadCapture(
            capture_id=capture_id,
            captured_records=tuple(captured),
            initial_inventory_digest=calibre_inventory_digest(initial),
            final_inventory_digest=calibre_inventory_digest(final),
            tool_version=next(iter(tool_versions)),
            execution_ids=tuple(execution_ids),
            category_count=len(categories),
        )

    def _read_inventory(
        self,
        library_path: Path,
        execute: Callable[[LocalCommand], bytes],
    ) -> tuple[ParsedCalibreCaptureRecord, ...]:
        records: list[ParsedCalibreCaptureRecord] = []
        after_record_id = 0
        for _page in range(MAX_CALIBRE_CAPTURE_PAGES):
            page = parse_calibredb_capture_inventory_page(
                execute(
                    build_calibredb_inventory_command(
                        library_path,
                        after_record_id=after_record_id,
                        limit=CALIBRE_LIBRARY_MAX_PAGE_SIZE,
                    )
                )
            )
            if page and page[0].record.record_id <= after_record_id:
                raise CalibreLibraryCaptureError("Calibre inventory pagination did not advance")
            if records and page and page[0].record.record_id <= records[-1].record.record_id:
                raise CalibreLibraryCaptureError("Calibre inventory pages overlap")
            records.extend(page)
            if len(records) > MAX_CALIBRE_CAPTURE_RECORDS:
                raise CalibreLibraryCaptureError("Calibre inventory exceeds the capture limit")
            if len(page) < CALIBRE_LIBRARY_MAX_PAGE_SIZE:
                return tuple(records)
            after_record_id = page[-1].record.record_id
        raise CalibreLibraryCaptureError("Calibre inventory exceeds the page limit")

    def _validated_stdout(
        self,
        outcome: ToolRunOutcome,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str,
        execution_ids: list[EntityId],
        tool_versions: set[str],
    ) -> bytes:
        execution = outcome.execution
        if (
            execution.provider_id != CALIBRE_LIBRARY_PROVIDER.provider_id
            or execution.adapter_version != CALIBRE_LIBRARY_PROVIDER.adapter_version
            or execution.capability not in CALIBRE_LIBRARY_PROVIDER.capabilities
            or execution.input_identity != input_identity
            or execution.config_identity != config_identity
        ):
            raise CalibreLibraryCaptureError("Calibre command lineage is invalid")
        execution_ids.append(execution.id)
        tool_versions.add(execution.tool_version)
        if execution.status is not ToolExecutionStatus.SUCCEEDED:
            raise CalibreLibraryCaptureError("Calibre command execution failed")
        stdout = tuple(item for item in outcome.artifacts if item.artifact_type == "STDOUT")
        if len(stdout) != 1:
            raise CalibreLibraryCaptureError("Calibre command stdout is unavailable")
        if stdout[0].execution_id != execution.id:
            raise CalibreLibraryCaptureError("Calibre command stdout lineage is invalid")
        try:
            return self._runtime.read_artifact_bytes(stdout[0], max_bytes=command.max_stdout_bytes)
        except Exception as error:
            raise CalibreLibraryCaptureError("Calibre command stdout is invalid") from error


def calibre_opf_fingerprint(data: bytes) -> str:
    """Validate one bounded OPF document and hash its exact captured bytes."""
    if not isinstance(data, bytes) or len(data) > MAX_CALIBRE_METADATA_STDOUT_BYTES:
        raise CalibreLibraryCaptureError("Calibre OPF exceeds the configured limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CalibreLibraryCaptureError("Calibre OPF is not valid UTF-8") from error
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise CalibreLibraryCaptureError("Calibre OPF contains a forbidden declaration")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise CalibreLibraryCaptureError("Calibre OPF is not well-formed XML") from error
    if _local_name(root.tag) != "package" or not any(
        _local_name(element.tag) == "metadata" for element in root.iter()
    ):
        raise CalibreLibraryCaptureError("Calibre OPF has an invalid document shape")
    return hashlib.sha256(data).hexdigest()


def build_calibre_snapshot_graph(
    *,
    snapshot_id: EntityId,
    scan_root_id: EntityId,
    source_scan_run_id: EntityId,
    tool_version: str,
    library_identity_digest: str,
    initial_inventory_digest: str,
    final_inventory_digest: str,
    started_at: datetime,
    completed_at: datetime,
    captured_records: tuple[CalibreCapturedRecord, ...],
) -> CalibreLibrarySnapshotGraph:
    """Project one complete before/after capture into immutable domain rows."""
    if not isinstance(captured_records, tuple) or any(
        not isinstance(item, CalibreCapturedRecord) for item in captured_records
    ):
        raise TypeError("captured_records must be a tuple of CalibreCapturedRecord values")
    numbers = tuple(item.inventory.record.record_id for item in captured_records)
    if numbers != tuple(sorted(numbers)) or len(set(numbers)) != len(numbers):
        raise CalibreLibraryCaptureError("Calibre capture records must be strictly ordered")
    status = (
        CalibreLibrarySnapshotStatus.COMPLETED
        if initial_inventory_digest == final_inventory_digest
        else CalibreLibrarySnapshotStatus.INVALIDATED
    )
    snapshot = CalibreLibrarySnapshot(
        id=snapshot_id,
        scan_root_id=scan_root_id,
        source_scan_run_id=source_scan_run_id,
        profile=CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
        adapter_version=CALIBRE_LIBRARY_ADAPTER_VERSION,
        tool_version=tool_version,
        parser_version=CALIBRE_LIBRARY_PARSER_VERSION,
        library_identity_digest=library_identity_digest,
        initial_inventory_digest=initial_inventory_digest,
        final_inventory_digest=final_inventory_digest,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
    )
    records: list[CalibreLibraryRecordSnapshot] = []
    formats: list[CalibreLibraryFormatSnapshot] = []
    for captured in captured_records:
        inventory = captured.inventory
        source = inventory.record
        record = CalibreLibraryRecordSnapshot(
            id=EntityId.new(),
            snapshot_id=snapshot.id,
            calibre_record_id=source.record_id,
            metadata_fingerprint=captured.metadata_fingerprint,
            calibre_uuid=source.uuid,
            title=source.title,
            authors=source.authors,
            identifiers=source.identifiers,
            last_modified_at=inventory.last_modified_at,
        )
        records.append(record)
        formats.extend(
            CalibreLibraryFormatSnapshot(
                id=EntityId.new(),
                record_snapshot_id=record.id,
                format_label=item.format_label,
                relative_locator=item.relative_locator,
            )
            for item in source.formats
        )
    return CalibreLibrarySnapshotGraph(snapshot, tuple(records), tuple(formats))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise CalibreLibraryCaptureError(f"{field_name} is invalid")
    digest = value.casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise CalibreLibraryCaptureError(f"{field_name} is invalid")
    return digest
