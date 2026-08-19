"""Bounded, read-only mapping for Calibre reconciliation cases A through D.

The mapper consumes already captured snapshot DTOs and a caller-selected set of
current e-book observations.  It never opens source media, changes Calibre,
or writes persistence.  The persistence store remains responsible for
lineage and referential validation at commit time.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from foliotone.core import (
    EBOOK_COLLECTION_FORMATS,
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
)

from .calibre_reconciliation import (
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySnapshot,
    CalibreReconciliationFinding,
    CalibreReconciliationFindingCode,
    CalibreReconciliationFindingRef,
    CalibreReconciliationFindingRefKind,
    CalibreReconciliationFindingRefRole,
)

FULL_FILE_SHA256_PROFILE = ("FILE_SHA256", "sha256", "1")
MAX_FINDING_REFS = 256


@dataclass(frozen=True, slots=True)
class CalibreReconciliationMapping:
    """Immutable findings and ordered references produced by one mapping."""

    findings: tuple[CalibreReconciliationFinding, ...]
    refs: tuple[CalibreReconciliationFindingRef, ...]

    def refs_for(
        self,
        finding: CalibreReconciliationFinding,
    ) -> tuple[CalibreReconciliationFindingRef, ...]:
        """Return that finding's references in their persisted order."""
        return tuple(ref for ref in self.refs if ref.finding_id == finding.id)


type FullHashInput = Iterable[Fingerprint] | None
type RefSpec = tuple[
    CalibreReconciliationFindingRefKind,
    EntityId,
    CalibreReconciliationFindingRefRole,
    str,
]


class CalibreReconciliationMapper:
    """Map only the fixed non-corrective Calibre cases A, B, C and D."""

    def map(
        self,
        snapshot: CalibreLibrarySnapshot,
        records: Iterable[CalibreLibraryRecordSnapshot],
        formats: Iterable[CalibreLibraryFormatSnapshot],
        current_observations: Iterable[FileObservation],
        full_hashes: FullHashInput = None,
        *,
        created_at: datetime | None = None,
    ) -> CalibreReconciliationMapping:
        if snapshot.status.value != "COMPLETED":
            raise ValueError("Calibre reconciliation requires a completed snapshot")

        record_items = tuple(records)
        format_items = tuple(formats)
        record_by_id = self._records(snapshot, record_items)
        formats_by_id = self._formats(record_by_id, format_items)
        observations = self._current_observations(snapshot, current_observations)
        hashes = self._full_hashes(full_hashes)

        mapped_by_record: dict[EntityId, list[CalibreLibraryFormatSnapshot]] = defaultdict(list)
        mapped_observation_ids: set[EntityId] = set()
        for format_item in formats_by_id:
            observation_id = format_item.observation_id
            if observation_id is None or observation_id not in observations:
                continue
            if format_item.relative_locator != observations[observation_id].relative_path:
                raise ValueError("Calibre format locator does not match its current observation")
            mapped_by_record[format_item.record_snapshot_id].append(format_item)
            mapped_observation_ids.add(observation_id)

        specs: list[tuple[CalibreReconciliationFindingCode, list[RefSpec]]] = []

        # A: only current supported e-book observations are considered.  The
        # caller supplies the current scan projection; unsupported suffixes are
        # excluded defensively at this boundary as well.
        for observation in sorted(observations.values(), key=_observation_sort_key):
            if observation.id not in mapped_observation_ids:
                specs.append(
                    (
                        CalibreReconciliationFindingCode.FILESYSTEM_ONLY,
                        [
                            (
                                CalibreReconciliationFindingRefKind.FILE_OBSERVATION,
                                observation.id,
                                CalibreReconciliationFindingRefRole.PRIMARY,
                                _observation_material(observation),
                            )
                        ],
                    )
                )

        # B: records with no current mapped format remain review findings, not
        # deletion judgements.
        for record in sorted(record_by_id.values(), key=_record_sort_key):
            if not mapped_by_record.get(record.id):
                specs.append(
                    (
                        CalibreReconciliationFindingCode.CALIBRE_RECORD_WITHOUT_FILE,
                        [
                            (
                                CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                                record.id,
                                CalibreReconciliationFindingRefRole.PRIMARY,
                                _record_material(record),
                            )
                        ],
                    )
                )

        # C: group by a consistent full hash first.  This avoids collection-
        # wide all-vs-all comparison and deliberately requires distinct
        # Calibre records in the same hash group.
        hash_members: dict[
            str,
            list[tuple[CalibreLibraryRecordSnapshot, CalibreLibraryFormatSnapshot, Fingerprint]],
        ] = defaultdict(list)
        for format_item in formats_by_id:
            observation_id = format_item.observation_id
            if observation_id is None or observation_id not in mapped_observation_ids:
                continue
            value = hashes.get(observation_id)
            if value is None:
                continue
            fingerprint = hashes.fingerprints.get(observation_id)
            if fingerprint is None:
                continue
            record = record_by_id[format_item.record_snapshot_id]
            hash_members[value].append((record, format_item, fingerprint))

        for value in sorted(hash_members):
            members = sorted(
                hash_members[value],
                key=lambda item: (
                    _record_sort_key(item[0]),
                    item[1].format_label,
                    item[1].relative_locator,
                ),
            )
            distinct_records = {item[0].id for item in members}
            if len(distinct_records) < 2:
                continue
            refs: list[RefSpec] = []
            seen_records: set[EntityId] = set()
            seen_fingerprints: set[EntityId] = set()
            for record, format_item, fingerprint in members:
                if record.id not in seen_records:
                    refs.append(
                        (
                            CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                            record.id,
                            (
                                CalibreReconciliationFindingRefRole.PRIMARY
                                if not seen_records
                                else CalibreReconciliationFindingRefRole.RELATED
                            ),
                            _record_material(record),
                        )
                    )
                    seen_records.add(record.id)
                refs.append(
                    (
                        CalibreReconciliationFindingRefKind.CALIBRE_FORMAT,
                        format_item.id,
                        CalibreReconciliationFindingRefRole.SUPPORTING,
                        _format_material(record, format_item, value),
                    )
                )
                if fingerprint.id not in seen_fingerprints:
                    refs.append(
                        (
                            CalibreReconciliationFindingRefKind.FINGERPRINT,
                            fingerprint.id,
                            CalibreReconciliationFindingRefRole.SUPPORTING,
                            _fingerprint_material(record, format_item, fingerprint),
                        )
                    )
                    seen_fingerprints.add(fingerprint.id)
            if len(refs) > MAX_FINDING_REFS:
                raise ValueError("Calibre duplicate finding exceeds the reference limit")
            specs.append(
                (
                    CalibreReconciliationFindingCode.CALIBRE_DUPLICATE_RECORD_CANDIDATE,
                    refs,
                )
            )

        # D: format multiplicity is an ownership finding.  It is independent
        # of C; a single record with several formats never enters C above.
        for record in sorted(record_by_id.values(), key=_record_sort_key):
            mapped = sorted(
                mapped_by_record.get(record.id, ()),
                key=lambda item: (item.format_label, item.relative_locator),
            )
            if len(mapped) < 2:
                continue
            refs = [
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                    record.id,
                    CalibreReconciliationFindingRefRole.PRIMARY,
                    _record_material(record),
                )
            ]
            refs.extend(
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_FORMAT,
                    format_item.id,
                    CalibreReconciliationFindingRefRole.RELATED,
                    _format_material(record, format_item, None),
                )
                for format_item in mapped
            )
            if len(refs) > MAX_FINDING_REFS:
                raise ValueError("Calibre multi-format finding exceeds the reference limit")
            # Format snapshots already carry ownership observation IDs.  Add
            # explicit observation refs for normal-sized findings, while
            # retaining the S-06 256-reference bound for pathological input.
            observation_refs = [
                (
                    CalibreReconciliationFindingRefKind.FILE_OBSERVATION,
                    format_item.observation_id,
                    CalibreReconciliationFindingRefRole.SUPPORTING,
                    _observation_material(observations[format_item.observation_id]),
                )
                for format_item in mapped
                if format_item.observation_id is not None
            ]
            if len(refs) + len(observation_refs) <= MAX_FINDING_REFS:
                refs.extend(observation_refs)
            specs.append((CalibreReconciliationFindingCode.CALIBRE_MULTI_FORMAT_RECORD, refs))

        # Stable output order is part of the mapper contract.  Finding IDs are
        # intentionally fresh; semantic fingerprints do not use them.
        specs.sort(key=lambda item: (_code_order(item[0]), _spec_fingerprint(item[0], item[1])))
        timestamp = created_at or datetime.now(UTC)
        findings: list[CalibreReconciliationFinding] = []
        refs_out: list[CalibreReconciliationFindingRef] = []
        for code, ref_specs in specs:
            finding_id = EntityId.new()
            finding = CalibreReconciliationFinding(
                id=finding_id,
                snapshot_id=snapshot.id,
                code=code,
                finding_fingerprint=_spec_fingerprint(code, ref_specs),
                review_required=True,
                created_at=timestamp,
            )
            findings.append(finding)
            for ordinal, (kind, ref_id, role, material) in enumerate(ref_specs):
                refs_out.append(
                    CalibreReconciliationFindingRef(
                        id=EntityId.new(),
                        finding_id=finding_id,
                        ordinal=ordinal,
                        ref_kind=kind,
                        ref_id=ref_id,
                        role=role,
                        material_fingerprint=_digest(material),
                    )
                )
        return CalibreReconciliationMapping(tuple(findings), tuple(refs_out))

    @staticmethod
    def _records(
        snapshot: CalibreLibrarySnapshot,
        records: tuple[CalibreLibraryRecordSnapshot, ...],
    ) -> dict[EntityId, CalibreLibraryRecordSnapshot]:
        result: dict[EntityId, CalibreLibraryRecordSnapshot] = {}
        for record in records:
            if record.snapshot_id != snapshot.id:
                raise ValueError("Calibre record belongs to another snapshot")
            if record.id in result or any(
                existing.calibre_record_id == record.calibre_record_id
                for existing in result.values()
            ):
                raise ValueError("Calibre records must be unique within a snapshot")
            result[record.id] = record
        return result

    @staticmethod
    def _formats(
        records: Mapping[EntityId, CalibreLibraryRecordSnapshot],
        formats: tuple[CalibreLibraryFormatSnapshot, ...],
    ) -> tuple[CalibreLibraryFormatSnapshot, ...]:
        result: list[CalibreLibraryFormatSnapshot] = []
        seen: set[tuple[EntityId, str, str]] = set()
        seen_ids: set[EntityId] = set()
        for format_item in formats:
            record = records.get(format_item.record_snapshot_id)
            if record is None:
                raise ValueError("Calibre format belongs to an unknown record")
            key = (record.id, format_item.format_label, format_item.relative_locator)
            if format_item.id in seen_ids or key in seen:
                raise ValueError("Calibre formats must be unique within a record")
            seen_ids.add(format_item.id)
            seen.add(key)
            result.append(format_item)
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    str(item.record_snapshot_id),
                    item.format_label,
                    item.relative_locator,
                ),
            )
        )

    @staticmethod
    def _current_observations(
        snapshot: CalibreLibrarySnapshot,
        observations: Iterable[FileObservation],
    ) -> dict[EntityId, FileObservation]:
        result: dict[EntityId, FileObservation] = {}
        for observation in observations:
            if observation.scan_run_id != snapshot.source_scan_run_id:
                raise ValueError("current observation belongs to another source scan")
            suffix = (
                observation.relative_path.rsplit(".", 1)[-1].upper()
                if "." in observation.relative_path
                else ""
            )
            if suffix not in EBOOK_COLLECTION_FORMATS:
                continue
            existing = result.get(observation.id)
            if existing is not None and existing != observation:
                raise ValueError("current observations contain a conflicting duplicate ID")
            result[observation.id] = observation
        return result

    @staticmethod
    def _full_hashes(full_hashes: FullHashInput) -> _FullHashes:
        if full_hashes is None:
            return _FullHashes({}, {})
        by_observation: dict[EntityId, set[str]] = defaultdict(set)
        by_id: dict[EntityId, list[Fingerprint]] = defaultdict(list)
        for fingerprint in full_hashes:
            if (
                fingerprint.target_kind is EntityKind.FILE_OBSERVATION
                and (
                    fingerprint.kind,
                    fingerprint.algorithm,
                    fingerprint.algorithm_version,
                )
                == FULL_FILE_SHA256_PROFILE
                and _is_sha256(fingerprint.value)
            ):
                by_observation[fingerprint.target_id].add(fingerprint.value.casefold())
                by_id[fingerprint.target_id].append(fingerprint)
        values = {
            key: next(iter(items))
            for key, items in by_observation.items()
            if len(items) == 1
        }
        fingerprints = {
            key: sorted(items, key=lambda item: (item.created_at, str(item.id)))[0]
            for key, items in by_id.items()
            if key in values and len({item.value.casefold() for item in items}) == 1
        }
        return _FullHashes(values, fingerprints)


@dataclass(frozen=True, slots=True)
class _FullHashes:
    values: dict[EntityId, str]
    fingerprints: dict[EntityId, Fingerprint]

    def get(self, key: EntityId | None) -> str | None:
        return None if key is None else self.values.get(key)


def map_calibre_reconciliation(
    snapshot: CalibreLibrarySnapshot,
    records: Iterable[CalibreLibraryRecordSnapshot],
    formats: Iterable[CalibreLibraryFormatSnapshot],
    current_observations: Iterable[FileObservation],
    full_hashes: FullHashInput = None,
    *,
    created_at: datetime | None = None,
) -> CalibreReconciliationMapping:
    """Functional entry point for the A-D mapper."""
    return CalibreReconciliationMapper().map(
        snapshot,
        records,
        formats,
        current_observations,
        full_hashes,
        created_at=created_at,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value)


def _record_sort_key(record: CalibreLibraryRecordSnapshot) -> tuple[int, str]:
    return record.calibre_record_id, str(record.id)


def _observation_sort_key(observation: FileObservation) -> tuple[str, str]:
    return observation.relative_path, str(observation.id)


def _record_material(record: CalibreLibraryRecordSnapshot) -> str:
    return _canonical(
        "CALIBRE_RECORD",
        record.calibre_record_id,
        record.metadata_fingerprint,
    )


def _format_material(
    record: CalibreLibraryRecordSnapshot,
    format_item: CalibreLibraryFormatSnapshot,
    full_hash: str | None,
) -> str:
    return _canonical(
        "CALIBRE_FORMAT",
        record.calibre_record_id,
        format_item.format_label,
        format_item.relative_locator,
        format_item.declared_size_bytes,
        full_hash,
    )


def _observation_material(observation: FileObservation) -> str:
    return _canonical(
        "FILE_OBSERVATION",
        observation.relative_path,
        observation.size_bytes,
        observation.modified_at.isoformat(),
    )


def _fingerprint_material(
    record: CalibreLibraryRecordSnapshot,
    format_item: CalibreLibraryFormatSnapshot,
    fingerprint: Fingerprint,
) -> str:
    return _canonical(
        "FINGERPRINT",
        record.calibre_record_id,
        format_item.format_label,
        fingerprint.kind,
        fingerprint.algorithm,
        fingerprint.algorithm_version,
        fingerprint.value.casefold(),
    )


def _spec_fingerprint(
    code: CalibreReconciliationFindingCode,
    refs: Iterable[RefSpec],
) -> str:
    descriptors = sorted(
        (kind.value, role.value, _digest(material)) for kind, _ref_id, role, material in refs
    )
    return _digest(_canonical("CALIBRE_RECONCILIATION", code.value, descriptors))


def _canonical(kind: str, *values: object) -> str:
    return json.dumps((kind, *values), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _code_order(code: CalibreReconciliationFindingCode) -> int:
    return {
        CalibreReconciliationFindingCode.FILESYSTEM_ONLY: 0,
        CalibreReconciliationFindingCode.CALIBRE_RECORD_WITHOUT_FILE: 1,
        CalibreReconciliationFindingCode.CALIBRE_DUPLICATE_RECORD_CANDIDATE: 2,
        CalibreReconciliationFindingCode.CALIBRE_MULTI_FORMAT_RECORD: 3,
    }.get(code, 99)


# Backward-friendly name for callers that prefer an outcome noun.
CalibreReconciliationOutcome = CalibreReconciliationMapping
