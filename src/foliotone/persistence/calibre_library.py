"""Dedicated insert-only SQLite persistence for ADR-0033 library evidence."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import Engine, Table, desc, insert, select
from sqlalchemy.engine import Connection

from foliotone.core import EntityId, MediaType, ScanRunStatus
from foliotone.persistence import calibre_library_schema as cs
from foliotone.persistence import resolution_review_schema as rr
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

if TYPE_CHECKING:
    from foliotone.workflows.calibre_reconciliation import (
        CalibreLibraryFormatSnapshot,
        CalibreLibraryRecordSnapshot,
        CalibreLibrarySidecarSnapshot,
        CalibreLibrarySnapshot,
        CalibreReconciliationFinding,
        CalibreReconciliationFindingRef,
    )

MAX_CALIBRE_FINDING_REFS = 256

_FINDING_REF_KINDS = {
    "FILESYSTEM_ONLY": frozenset({"FILE_OBSERVATION", "FINGERPRINT", "TOOL_RESULT"}),
    "CALIBRE_RECORD_WITHOUT_FILE": frozenset({"CALIBRE_RECORD"}),
    "CALIBRE_DUPLICATE_RECORD_CANDIDATE": frozenset(
        {"CALIBRE_RECORD", "CALIBRE_FORMAT", "FILE_OBSERVATION", "FINGERPRINT"}
    ),
    "CALIBRE_MULTI_FORMAT_RECORD": frozenset(
        {"CALIBRE_RECORD", "CALIBRE_FORMAT", "FILE_OBSERVATION"}
    ),
    "CALIBRE_METADATA_CONFLICT": frozenset(
        {"CALIBRE_RECORD", "CALIBRE_FORMAT", "FILE_OBSERVATION", "VALUE_ASSERTION", "TOOL_RESULT"}
    ),
    "CALIBRE_AUTHORITY_CONFLICT": frozenset(
        {"CALIBRE_RECORD", "VALUE_ASSERTION", "TOOL_RESULT", "RESOLUTION_CANDIDATE", "REVIEW_ITEM"}
    ),
    "CALIBRE_SIDECAR_DEPENDENCY": frozenset(
        {"CALIBRE_RECORD", "CALIBRE_FORMAT", "CALIBRE_SIDECAR", "FILE_OBSERVATION"}
    ),
}


class CalibreLibraryStoreError(RuntimeError):
    """A path-free Calibre-library persistence failure."""


class SQLiteCalibreLibraryStore:
    """Persist one fully validated immutable Calibre snapshot atomically."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._leases = SQLiteScanRootWriteLeaseStore(engine)

    def create_or_get(
        self,
        snapshot: CalibreLibrarySnapshot,
        records: Iterable[CalibreLibraryRecordSnapshot],
        formats: Iterable[CalibreLibraryFormatSnapshot],
        sidecars: Iterable[CalibreLibrarySidecarSnapshot],
        findings: Iterable[CalibreReconciliationFinding],
        refs: Iterable[CalibreReconciliationFindingRef],
        *,
        lease: OwnedScanRootWriteLease,
        now: datetime,
    ) -> CalibreLibrarySnapshot:
        """Insert exactly one snapshot graph or prove a byte-for-byte retry.

        The caller's EBOOK_ANALYSIS lease, source ScanRun and every referenced
        observation are fenced and checked before any graph row is inserted.
        """

        record_items, format_items = tuple(records), tuple(formats)
        sidecar_items, finding_items, ref_items = tuple(sidecars), tuple(findings), tuple(refs)
        with self._engine.begin() as connection:
            self._validate_lease_and_lineage(connection, snapshot, lease, now)
            self._validate_shape(
                snapshot, record_items, format_items, sidecar_items, finding_items, ref_items
            )
            self._validate_observations(connection, snapshot, format_items, sidecar_items)
            self._validate_finding_refs(
                connection,
                snapshot,
                record_items,
                format_items,
                sidecar_items,
                finding_items,
                ref_items,
            )
            _insert_exact(
                connection, cs.calibre_library_snapshots, _snapshot_row(snapshot), ("id",)
            )
            record_ids: dict[EntityId, str] = {}
            for record in record_items:
                record_ids[record.id] = _insert_exact(
                    connection,
                    cs.calibre_library_records,
                    _record_row(record),
                    ("snapshot_id", "calibre_record_id"),
                    ignore_comparison=("id",),
                )
            format_ids: dict[EntityId, str] = {}
            for format_item in format_items:
                row = _format_row(format_item)
                row["record_snapshot_id"] = record_ids[format_item.record_snapshot_id]
                format_ids[format_item.id] = _insert_exact(
                    connection,
                    cs.calibre_library_formats,
                    row,
                    ("record_snapshot_id", "format_label", "relative_locator"),
                    ignore_comparison=("id",),
                )
            sidecar_ids: dict[EntityId, str] = {}
            for sidecar_item in sidecar_items:
                row = _sidecar_row(sidecar_item)
                row["record_snapshot_id"] = record_ids[sidecar_item.record_snapshot_id]
                sidecar_ids[sidecar_item.id] = _insert_exact(
                    connection,
                    cs.calibre_library_sidecars,
                    row,
                    ("record_snapshot_id", "kind", "relative_locator"),
                    ignore_comparison=("id",),
                )
            finding_ids: dict[EntityId, str] = {}
            for finding in finding_items:
                finding_ids[finding.id] = _insert_exact(
                    connection,
                    cs.calibre_reconciliation_findings,
                    _finding_row(finding),
                    ("snapshot_id", "code", "finding_fingerprint"),
                    ignore_comparison=("id",),
                )
            for ref in ref_items:
                row = _ref_row(ref)
                row["finding_id"] = finding_ids[ref.finding_id]
                row["ref_id"] = _remap_ref_id(ref, record_ids, format_ids, sidecar_ids)
                _insert_exact(
                    connection,
                    cs.calibre_reconciliation_finding_refs,
                    row,
                    ("finding_id", "ordinal"),
                    ignore_comparison=("id",),
                )
        return snapshot

    persist = create_or_get

    def _validate_lease_and_lineage(
        self,
        connection: Connection,
        snapshot: CalibreLibrarySnapshot,
        lease: OwnedScanRootWriteLease,
        now: datetime,
    ) -> None:
        if (
            lease.scan_root_id != snapshot.scan_root_id
            or lease.owner_kind is not ScanRootWriteOwnerKind.EBOOK_ANALYSIS
        ):
            raise CalibreLibraryStoreError(
                "Calibre library persistence requires its EBOOK_ANALYSIS root lease"
            )
        try:
            self._leases.fence(connection, lease, now)
        except ScanRootWriteLeaseError as error:
            raise CalibreLibraryStoreError("Calibre library root lease was lost") from error
        row = connection.execute(
            select(schema.scan_roots.c.media_type).where(
                schema.scan_roots.c.id == str(snapshot.scan_root_id)
            )
        ).one_or_none()
        if row is None or str(row.media_type) != MediaType.EBOOK.value:
            raise CalibreLibraryStoreError("Calibre library snapshot requires an EBOOK ScanRoot")
        scan = connection.execute(
            select(schema.scan_runs.c.scan_root_id, schema.scan_runs.c.status).where(
                schema.scan_runs.c.id == str(snapshot.source_scan_run_id)
            )
        ).one_or_none()
        if (
            scan is None
            or str(scan.scan_root_id) != str(snapshot.scan_root_id)
            or str(scan.status) != ScanRunStatus.COMPLETED.value
        ):
            raise CalibreLibraryStoreError(
                "Calibre library snapshot requires its completed source scan"
            )
        latest_scan_id = connection.execute(
            select(schema.scan_runs.c.id)
            .where(
                schema.scan_runs.c.scan_root_id == str(snapshot.scan_root_id),
                schema.scan_runs.c.status == ScanRunStatus.COMPLETED.value,
            )
            .order_by(desc(schema.scan_runs.c.started_at), desc(schema.scan_runs.c.id))
            .limit(1)
        ).scalar_one_or_none()
        if str(latest_scan_id) != str(snapshot.source_scan_run_id):
            raise CalibreLibraryStoreError(
                "Calibre library snapshot requires the latest completed source scan"
            )

    @staticmethod
    def _validate_shape(
        snapshot: CalibreLibrarySnapshot,
        records: tuple[CalibreLibraryRecordSnapshot, ...],
        formats: tuple[CalibreLibraryFormatSnapshot, ...],
        sidecars: tuple[CalibreLibrarySidecarSnapshot, ...],
        findings: tuple[CalibreReconciliationFinding, ...],
        refs: tuple[CalibreReconciliationFindingRef, ...],
    ) -> None:
        if snapshot.status.value == "RUNNING":
            if records or formats or sidecars or findings or refs:
                raise CalibreLibraryStoreError(
                    "running Calibre snapshot cannot persist reconciliation evidence"
                )
        if any(item.snapshot_id != snapshot.id for item in records):
            raise CalibreLibraryStoreError("Calibre record belongs to another snapshot")
        record_ids = {item.id for item in records}
        if any(item.record_snapshot_id not in record_ids for item in formats) or any(
            item.record_snapshot_id not in record_ids for item in sidecars
        ):
            raise CalibreLibraryStoreError("Calibre ownership row belongs to an unknown record")
        if findings and snapshot.status.value != "COMPLETED":
            raise CalibreLibraryStoreError("only completed Calibre snapshots may persist findings")
        if any(item.snapshot_id != snapshot.id for item in findings):
            raise CalibreLibraryStoreError("Calibre finding belongs to another snapshot")
        finding_ids = {item.id for item in findings}
        if any(item.finding_id not in finding_ids for item in refs):
            raise CalibreLibraryStoreError(
                "Calibre finding reference belongs to an unknown finding"
            )
        for finding in findings:
            linked = tuple(item for item in refs if item.finding_id == finding.id)
            if not 1 <= len(linked) <= MAX_CALIBRE_FINDING_REFS or tuple(
                item.ordinal for item in linked
            ) != tuple(range(len(linked))):
                raise CalibreLibraryStoreError(
                    "Calibre finding references must be contiguous and within bounds"
                )
            allowed_kinds = _FINDING_REF_KINDS[finding.code.value]
            if any(item.ref_kind.value not in allowed_kinds for item in linked):
                raise CalibreLibraryStoreError(
                    "Calibre finding contains an incompatible reference kind"
                )
            if not any(item.role.value == "PRIMARY" for item in linked):
                raise CalibreLibraryStoreError(
                    "Calibre finding requires a primary reference"
                )
            if any(
                item.ref_kind.value == "REVIEW_ITEM" and item.role.value != "REVIEW"
                for item in linked
            ):
                raise CalibreLibraryStoreError(
                    "Calibre review references require the review role"
                )
            if finding.code.value not in {
                "CALIBRE_METADATA_CONFLICT",
                "CALIBRE_AUTHORITY_CONFLICT",
            } and any(item.role.value == "CONTRADICTING" for item in linked):
                raise CalibreLibraryStoreError(
                    "only conflict findings may contain contradicting references"
                )
        _validate_sidecar_ownership(formats, sidecars)

    @staticmethod
    def _validate_observations(
        connection: Connection,
        snapshot: CalibreLibrarySnapshot,
        formats: tuple[CalibreLibraryFormatSnapshot, ...],
        sidecars: tuple[CalibreLibrarySidecarSnapshot, ...],
    ) -> None:
        for format_item in formats:
            _validate_observation(
                connection, snapshot, format_item.observation_id, format_item.relative_locator
            )
        for sidecar_item in sidecars:
            _validate_observation(
                connection, snapshot, sidecar_item.observation_id, sidecar_item.relative_locator
            )

    @staticmethod
    def _validate_finding_refs(
        connection: Connection,
        snapshot: CalibreLibrarySnapshot,
        records: tuple[CalibreLibraryRecordSnapshot, ...],
        formats: tuple[CalibreLibraryFormatSnapshot, ...],
        sidecars: tuple[CalibreLibrarySidecarSnapshot, ...],
        findings: tuple[CalibreReconciliationFinding, ...],
        refs: tuple[CalibreReconciliationFindingRef, ...],
    ) -> None:
        record_ids = {record.id for record in records}
        format_ids = {format_item.id for format_item in formats}
        sidecar_ids = {sidecar.id for sidecar in sidecars}
        allowed = {
            "CALIBRE_RECORD": record_ids,
            "CALIBRE_FORMAT": format_ids,
            "CALIBRE_SIDECAR": sidecar_ids,
        }
        for ref in refs:
            ref_kind = ref.ref_kind.value
            if ref_kind in allowed:
                if ref.ref_id not in allowed[ref_kind]:
                    raise CalibreLibraryStoreError(
                        "Calibre finding reference is outside its snapshot"
                    )
                continue
            if ref_kind == "FILE_OBSERVATION":
                _validate_file_observation_lineage(connection, snapshot, ref.ref_id)
                continue
            table = {
                "VALUE_ASSERTION": schema.value_assertions,
                "FINGERPRINT": schema.fingerprints,
                "TOOL_RESULT": schema.tool_results,
            }.get(ref_kind)
            if table is not None:
                evidence = connection.execute(
                    select(table.c.target_kind, table.c.target_id).where(
                        table.c.id == str(ref.ref_id)
                    )
                ).one_or_none()
                if evidence is None:
                    raise CalibreLibraryStoreError("Calibre finding reference does not exist")
                _validate_target_lineage(
                    connection, snapshot, str(evidence.target_kind), str(evidence.target_id)
                )
                continue
            table = {
                "RESOLUTION_CANDIDATE": rr.resolution_candidates,
                "REVIEW_ITEM": rr.review_items,
            }[ref_kind]
            candidate = connection.execute(
                select(table.c.subject_kind, table.c.subject_id).where(
                    table.c.id == str(ref.ref_id)
                )
            ).one_or_none()
            if candidate is None:
                raise CalibreLibraryStoreError("Calibre finding reference does not exist")
            _validate_target_lineage(
                connection, snapshot, str(candidate.subject_kind), str(candidate.subject_id)
            )


def _insert_exact(
    connection: Connection,
    table: Table,
    row: dict[str, object],
    keys: tuple[str, ...],
    *,
    ignore_comparison: tuple[str, ...] = (),
) -> str:
    result = connection.execute(insert(table).values(**row).prefix_with("OR IGNORE"))
    if result.rowcount == 1:
        return str(row["id"])
    existing = (
        connection.execute(select(table).where(*(table.c[key] == row[key] for key in keys)))
        .mappings()
        .one_or_none()
    )
    if existing is None or any(
        existing[key] != value
        for key, value in row.items()
        if key not in ignore_comparison
    ):
        raise CalibreLibraryStoreError("Calibre library retry payload is nondeterministic")
    return str(existing["id"])


def _validate_observation(
    connection: Connection,
    snapshot: CalibreLibrarySnapshot,
    observation_id: EntityId | None,
    relative_locator: str,
) -> None:
    if observation_id is None:
        return
    observation = connection.execute(
        select(
            schema.file_observations.c.scan_run_id,
            schema.file_observations.c.relative_path,
            schema.file_records.c.scan_root_id,
            schema.file_records.c.media_type,
        )
        .select_from(
            schema.file_observations.join(
                schema.file_records,
                schema.file_observations.c.file_id == schema.file_records.c.id,
            )
        )
        .where(schema.file_observations.c.id == str(observation_id))
    ).one_or_none()
    if (
        observation is None
        or str(observation.scan_run_id) != str(snapshot.source_scan_run_id)
        or str(observation.scan_root_id) != str(snapshot.scan_root_id)
        or str(observation.media_type) != MediaType.EBOOK.value
        or str(observation.relative_path) != relative_locator
    ):
        raise CalibreLibraryStoreError("Calibre ownership observation is outside the source scan")


def _validate_file_observation_lineage(
    connection: Connection,
    snapshot: CalibreLibrarySnapshot,
    observation_id: EntityId | str,
) -> None:
    lineage = connection.execute(
        select(schema.file_observations.c.scan_run_id, schema.file_records.c.scan_root_id)
        .select_from(
            schema.file_observations.join(
                schema.file_records,
                schema.file_observations.c.file_id == schema.file_records.c.id,
            )
        )
        .where(schema.file_observations.c.id == str(observation_id))
    ).one_or_none()
    if (
        lineage is None
        or str(lineage.scan_run_id) != str(snapshot.source_scan_run_id)
        or str(lineage.scan_root_id) != str(snapshot.scan_root_id)
    ):
        raise CalibreLibraryStoreError(
            "Calibre finding observation is outside the source scan"
        )


def _validate_target_lineage(
    connection: Connection,
    snapshot: CalibreLibrarySnapshot,
    target_kind: str,
    target_id: str,
) -> None:
    if target_kind == "FILE_OBSERVATION":
        _validate_file_observation_lineage(connection, snapshot, target_id)
    elif target_kind == "FILE":
        root_id = connection.execute(
            select(schema.file_records.c.scan_root_id).where(
                schema.file_records.c.id == target_id
            )
        ).scalar_one_or_none()
        if root_id is None or str(root_id) != str(snapshot.scan_root_id):
            raise CalibreLibraryStoreError(
                "Calibre finding evidence is outside the snapshot root"
            )


def _validate_sidecar_ownership(
    formats: tuple[CalibreLibraryFormatSnapshot, ...],
    sidecars: tuple[CalibreLibrarySidecarSnapshot, ...],
) -> None:
    record_directories: dict[EntityId, set[PurePosixPath]] = {}
    for format_item in formats:
        record_directories.setdefault(format_item.record_snapshot_id, set()).add(
            PurePosixPath(format_item.relative_locator).parent
        )
    for sidecar_item in sidecars:
        directories = record_directories.get(sidecar_item.record_snapshot_id, set())
        if len(directories) != 1:
            raise CalibreLibraryStoreError(
                "Calibre sidecar requires one unambiguous record directory"
            )
        directory = next(iter(directories))
        path = PurePosixPath(sidecar_item.relative_locator)
        if sidecar_item.kind.value == "METADATA_OPF":
            valid = path == directory / "metadata.opf"
        elif sidecar_item.kind.value == "COVER":
            valid = path == directory / "cover.jpg"
        elif sidecar_item.kind.value == "EXTRA_DATA":
            valid = (directory / "data") in path.parents
        else:
            valid = directory in path.parents
        if not valid:
            raise CalibreLibraryStoreError(
                "Calibre sidecar is outside its unambiguous record directory"
            )


def _remap_ref_id(
    item: CalibreReconciliationFindingRef,
    record_ids: dict[EntityId, str],
    format_ids: dict[EntityId, str],
    sidecar_ids: dict[EntityId, str],
) -> str:
    mapping = {
        "CALIBRE_RECORD": record_ids,
        "CALIBRE_FORMAT": format_ids,
        "CALIBRE_SIDECAR": sidecar_ids,
    }.get(item.ref_kind.value)
    if mapping is None:
        return str(item.ref_id)
    return mapping[item.ref_id]


def _snapshot_row(item: CalibreLibrarySnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "scan_root_id": str(item.scan_root_id),
        "source_scan_run_id": str(item.source_scan_run_id),
        "profile": item.profile,
        "adapter_version": item.adapter_version,
        "tool_version": item.tool_version,
        "parser_version": item.parser_version,
        "library_identity_digest": item.library_identity_digest,
        "initial_inventory_digest": item.initial_inventory_digest,
        "final_inventory_digest": item.final_inventory_digest,
        "status": item.status.value,
        "started_at": datetime_to_db(item.started_at),
        "completed_at": datetime_to_db(item.completed_at),
    }


def _record_row(item: CalibreLibraryRecordSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "snapshot_id": str(item.snapshot_id),
        "calibre_record_id": item.calibre_record_id,
        "metadata_fingerprint": item.metadata_fingerprint,
        "calibre_uuid": item.calibre_uuid,
        "title": item.title,
        "authors_json": json.dumps(item.authors, separators=(",", ":")),
        "identifiers_json": json.dumps(item.identifiers, separators=(",", ":")),
        "last_modified_at": datetime_to_db(item.last_modified_at),
    }


def _format_row(item: CalibreLibraryFormatSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "record_snapshot_id": str(item.record_snapshot_id),
        "format_label": item.format_label,
        "relative_locator": item.relative_locator,
        "declared_size_bytes": item.declared_size_bytes,
        "observation_id": None if item.observation_id is None else str(item.observation_id),
    }


def _sidecar_row(item: CalibreLibrarySidecarSnapshot) -> dict[str, object]:
    return {
        "id": str(item.id),
        "record_snapshot_id": str(item.record_snapshot_id),
        "kind": item.kind.value,
        "relative_locator": item.relative_locator,
        "observation_id": None if item.observation_id is None else str(item.observation_id),
    }


def _finding_row(item: CalibreReconciliationFinding) -> dict[str, object]:
    return {
        "id": str(item.id),
        "snapshot_id": str(item.snapshot_id),
        "code": item.code.value,
        "finding_fingerprint": item.finding_fingerprint,
        "review_required": item.review_required,
        "created_at": datetime_to_db(item.created_at),
    }


def _ref_row(item: CalibreReconciliationFindingRef) -> dict[str, object]:
    return {
        "id": str(item.id),
        "finding_id": str(item.finding_id),
        "ordinal": item.ordinal,
        "ref_kind": item.ref_kind.value,
        "ref_id": str(item.ref_id),
        "role": item.role.value,
        "material_fingerprint": item.material_fingerprint,
    }
