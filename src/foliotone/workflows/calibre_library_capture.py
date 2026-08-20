"""Pure projection for one consistency-checked Calibre library capture."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import datetime

from foliotone.adapters.calibre.library import MAX_CALIBRE_METADATA_STDOUT_BYTES
from foliotone.adapters.calibre.library_capture import ParsedCalibreCaptureRecord
from foliotone.core import EntityId
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
