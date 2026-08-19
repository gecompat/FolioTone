"""Bounded, read-only mapping for Calibre reconciliation cases A through G.

The mapper consumes already captured snapshot DTOs and a caller-selected set of
current e-book observations.  It never opens source media, changes Calibre,
or writes persistence.  The persistence store remains responsible for
lineage and referential validation at commit time.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath

from foliotone.core import (
    EBOOK_COLLECTION_FORMATS,
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ResolutionCandidate,
    ReviewCandidateKind,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ValueAssertion,
)
from foliotone.tooling import ToolResult

from .calibre_reconciliation import (
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySidecarSnapshot,
    CalibreLibrarySnapshot,
    CalibreReconciliationFinding,
    CalibreReconciliationFindingCode,
    CalibreReconciliationFindingRef,
    CalibreReconciliationFindingRefKind,
    CalibreReconciliationFindingRefRole,
)

FULL_FILE_SHA256_PROFILE = ("FILE_SHA256", "sha256", "1")
MAX_FINDING_REFS = 256
_METADATA_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


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
type CalibreMetadataEvidence = ValueAssertion | ToolResult
type RefSpec = tuple[
    CalibreReconciliationFindingRefKind,
    EntityId,
    CalibreReconciliationFindingRefRole,
    str,
]


@dataclass(frozen=True, slots=True)
class CalibreMetadataConflict:
    """Explicit field-level contradiction between calibre and embedded evidence."""

    record_id: EntityId
    field_name: str
    calibre_evidence: CalibreMetadataEvidence = field(repr=False)
    embedded_evidence: CalibreMetadataEvidence = field(repr=False)


@dataclass(frozen=True, slots=True)
class CalibreAuthorityConflict:
    """Calibre contributor evidence versus a persisted Agent assignment candidate."""

    record_id: EntityId
    calibre_contributor_name: str = field(repr=False)
    calibre_evidence: CalibreMetadataEvidence = field(repr=False)
    resolved_candidate: ResolutionCandidate
    review_item: ReviewItem


@dataclass(frozen=True, slots=True)
class CalibreSidecarDependency:
    """Record-bound sidecar dependency that is not yet safely executable."""

    record_id: EntityId
    sidecar: CalibreLibrarySidecarSnapshot
    sidecar_observation_id: EntityId | None = None
    format_ids: tuple[EntityId, ...] = ()
    extra_observation_ids: tuple[EntityId, ...] = ()
    ambiguous: bool = False


class CalibreReconciliationMapper:
    """Map fixed non-corrective Calibre cases A through G."""

    def map(
        self,
        snapshot: CalibreLibrarySnapshot,
        records: Iterable[CalibreLibraryRecordSnapshot],
        formats: Iterable[CalibreLibraryFormatSnapshot],
        current_observations: Iterable[FileObservation],
        full_hashes: FullHashInput = None,
        *,
        created_at: datetime | None = None,
        metadata_conflicts: Iterable[CalibreMetadataConflict] = (),
        authority_conflicts: Iterable[CalibreAuthorityConflict] = (),
        sidecar_dependencies: Iterable[CalibreSidecarDependency] = (),
    ) -> CalibreReconciliationMapping:
        if snapshot.status.value != "COMPLETED":
            raise ValueError("Calibre reconciliation requires a completed snapshot")

        record_items = tuple(records)
        format_items = tuple(formats)
        record_by_id = self._records(snapshot, record_items)
        formats_by_id = self._formats(record_by_id, format_items)
        format_by_id = {format_item.id: format_item for format_item in formats_by_id}
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
            if (
                _is_supported_ebook_observation(observation)
                and observation.id not in mapped_observation_ids
            ):
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

        # E: calibre metadata value contradicts embedded persisted evidence.
        for metadata_conflict in tuple(metadata_conflicts):
            self._validate_metadata_conflict(record_by_id, observations, metadata_conflict)
            refs = [
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                    metadata_conflict.record_id,
                    CalibreReconciliationFindingRefRole.PRIMARY,
                    _metadata_record_material(
                        record_by_id[metadata_conflict.record_id],
                        metadata_conflict.field_name,
                    ),
                ),
                (
                    _metadata_evidence_kind(metadata_conflict.calibre_evidence),
                    metadata_conflict.calibre_evidence.id,
                    CalibreReconciliationFindingRefRole.SUPPORTING,
                    _metadata_evidence_material(
                        metadata_conflict.field_name,
                        metadata_conflict.calibre_evidence,
                    ),
                ),
                (
                    _metadata_evidence_kind(metadata_conflict.embedded_evidence),
                    metadata_conflict.embedded_evidence.id,
                    CalibreReconciliationFindingRefRole.CONTRADICTING,
                    _metadata_evidence_material(
                        metadata_conflict.field_name,
                        metadata_conflict.embedded_evidence,
                    ),
                ),
            ]
            _ensure_ref_limit(refs)
            specs.append((CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT, refs))

        # F: calibre contributor evidence contradicts a resolved Agent assignment.
        for authority_conflict in tuple(authority_conflicts):
            self._validate_authority_conflict(authority_conflict, observations)
            if authority_conflict.record_id not in record_by_id:
                raise ValueError("authority conflict references unknown calibre record")
            refs = [
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                    authority_conflict.record_id,
                    CalibreReconciliationFindingRefRole.PRIMARY,
                    _authority_record_material(
                        record_by_id[authority_conflict.record_id],
                        authority_conflict.calibre_contributor_name,
                    ),
                ),
                (
                    _metadata_evidence_kind(authority_conflict.calibre_evidence),
                    authority_conflict.calibre_evidence.id,
                    CalibreReconciliationFindingRefRole.CONTRADICTING,
                    _authority_evidence_material(
                        authority_conflict.calibre_contributor_name,
                    ),
                ),
                (
                    CalibreReconciliationFindingRefKind.RESOLUTION_CANDIDATE,
                    authority_conflict.resolved_candidate.id,
                    CalibreReconciliationFindingRefRole.RELATED,
                    _resolution_candidate_material(authority_conflict.resolved_candidate),
                ),
            ]
            refs.append(
                (
                    CalibreReconciliationFindingRefKind.REVIEW_ITEM,
                    authority_conflict.review_item.id,
                    CalibreReconciliationFindingRefRole.REVIEW,
                    _review_item_material(authority_conflict.review_item),
                )
            )
            _ensure_ref_limit(refs)
            specs.append((CalibreReconciliationFindingCode.CALIBRE_AUTHORITY_CONFLICT, refs))

        # G: sidecar/extra-data dependencies are review-only and must remain
        # bounded by explicit evidence references.
        for dependency in sorted(
            tuple(sidecar_dependencies),
            key=lambda item: (
                record_by_id[item.record_id].calibre_record_id
                if item.record_id in record_by_id
                else -1,
                item.sidecar.kind.value,
                item.sidecar.relative_locator,
            ),
        ):
            dependency_formats, sidecar_observation, extra_observations = (
                self._validate_sidecar_dependency(
                    record_by_id,
                    format_by_id,
                    observations,
                    dependency,
                )
            )
            refs = [
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_RECORD,
                    dependency.record_id,
                    CalibreReconciliationFindingRefRole.PRIMARY,
                    _sidecar_dependency_record_material(record_by_id[dependency.record_id]),
                ),
                (
                    CalibreReconciliationFindingRefKind.CALIBRE_SIDECAR,
                    dependency.sidecar.id,
                    CalibreReconciliationFindingRefRole.RELATED,
                    _sidecar_material(dependency.sidecar, dependency.ambiguous),
                ),
            ]
            for dependency_format in dependency_formats:
                refs.append(
                    (
                        CalibreReconciliationFindingRefKind.CALIBRE_FORMAT,
                        dependency_format.id,
                        CalibreReconciliationFindingRefRole.RELATED,
                        _format_material(
                            record_by_id[dependency.record_id],
                            dependency_format,
                            None,
                        ),
                    )
                )
            if sidecar_observation is not None:
                refs.append(
                    (
                        CalibreReconciliationFindingRefKind.FILE_OBSERVATION,
                        sidecar_observation.id,
                        CalibreReconciliationFindingRefRole.SUPPORTING,
                        _observation_material(sidecar_observation),
                    )
                )
            for extra_observation in extra_observations:
                refs.append(
                    (
                        CalibreReconciliationFindingRefKind.FILE_OBSERVATION,
                        extra_observation.id,
                        CalibreReconciliationFindingRefRole.SUPPORTING,
                        _observation_material(extra_observation),
                    )
                )
            _ensure_ref_limit(refs)
            specs.append((CalibreReconciliationFindingCode.CALIBRE_SIDECAR_DEPENDENCY, refs))

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

    @staticmethod
    def _validate_metadata_conflict(
        records: Mapping[EntityId, CalibreLibraryRecordSnapshot],
        observations: Mapping[EntityId, FileObservation],
        conflict: CalibreMetadataConflict,
    ) -> None:
        if conflict.record_id not in records:
            raise ValueError("metadata conflict references unknown calibre record")
        if not isinstance(conflict.field_name, str) or _METADATA_FIELD.fullmatch(
            conflict.field_name
        ) is None:
            raise ValueError("metadata conflict field is invalid")
        calibre_field = _metadata_evidence_field(conflict.calibre_evidence)
        embedded_field = _metadata_evidence_field(conflict.embedded_evidence)
        if calibre_field != conflict.field_name or embedded_field != conflict.field_name:
            raise ValueError("metadata conflict evidence must use the same exact field")
        calibre_target = _metadata_evidence_target(conflict.calibre_evidence)
        embedded_target = _metadata_evidence_target(conflict.embedded_evidence)
        if calibre_target != embedded_target:
            raise ValueError("metadata conflict evidence must use the same exact target")
        _validate_current_evidence_target(observations, *calibre_target)
        calibre_value = _metadata_evidence_value(conflict.calibre_evidence)
        embedded_value = _metadata_evidence_value(conflict.embedded_evidence)
        _require_conflict_text(calibre_value, "calibre metadata value")
        _require_conflict_text(embedded_value, "embedded metadata value")
        if calibre_value == embedded_value:
            raise ValueError("metadata conflict requires different observed values")
        if (
            _metadata_evidence_kind(conflict.calibre_evidence)
            is _metadata_evidence_kind(conflict.embedded_evidence)
            and conflict.calibre_evidence.id == conflict.embedded_evidence.id
        ):
            raise ValueError("metadata conflict requires distinct evidence records")

    @staticmethod
    def _validate_authority_conflict(
        conflict: CalibreAuthorityConflict,
        observations: Mapping[EntityId, FileObservation],
    ) -> None:
        _require_conflict_text(conflict.calibre_contributor_name, "calibre contributor")
        if _metadata_evidence_value(conflict.calibre_evidence) != conflict.calibre_contributor_name:
            raise ValueError("authority conflict evidence must match the calibre contributor")
        if conflict.resolved_candidate.candidate_kind is not EntityKind.AGENT:
            raise ValueError("authority conflict requires an Agent resolution candidate")
        if (
            conflict.resolved_candidate.subject_kind is not EntityKind.FILE_OBSERVATION
            or conflict.resolved_candidate.subject_id not in observations
        ):
            raise ValueError(
                "authority conflict candidate must belong to a current file observation"
            )
        evidence_target = _metadata_evidence_target(conflict.calibre_evidence)
        if evidence_target != (
            conflict.resolved_candidate.subject_kind,
            conflict.resolved_candidate.subject_id,
        ):
            raise ValueError("authority conflict evidence must target its resolution subject")
        if conflict.resolved_candidate.disposition.value != "REVIEW_REQUIRED":
            raise ValueError("authority conflict candidate must remain review required")
        item = conflict.review_item
        if item.review_type is not ReviewType.AUTHORITY_RESOLUTION:
            raise ValueError("authority conflict requires an authority review item")
        if item.candidate_kind is not ReviewCandidateKind.RESOLUTION_CANDIDATE:
            raise ValueError("authority conflict review must reference a resolution candidate")
        if item.candidate_id != conflict.resolved_candidate.id:
            raise ValueError("authority conflict review must reference its resolution candidate")
        if (
            item.subject_kind != conflict.resolved_candidate.subject_kind
            or item.subject_id != conflict.resolved_candidate.subject_id
        ):
            raise ValueError(
                "authority conflict review subject must match its resolution candidate"
            )
        if (
            item.decision_compatibility_version
            != conflict.resolved_candidate.decision_compatibility_version
            or item.evidence_fingerprint != conflict.resolved_candidate.evidence_fingerprint
            or item.candidate_set_fingerprint
            != conflict.resolved_candidate.candidate_set_fingerprint
        ):
            raise ValueError(
                "authority conflict review must match its resolution evidence contract"
            )
        if item.state not in {ReviewItemState.PENDING, ReviewItemState.DEFERRED}:
            raise ValueError("authority conflict must not use a decided review item")

    @staticmethod
    def _validate_sidecar_dependency(
        records: Mapping[EntityId, CalibreLibraryRecordSnapshot],
        formats: Mapping[EntityId, CalibreLibraryFormatSnapshot],
        observations: Mapping[EntityId, FileObservation],
        dependency: CalibreSidecarDependency,
    ) -> tuple[
        tuple[CalibreLibraryFormatSnapshot, ...],
        FileObservation | None,
        tuple[FileObservation, ...],
    ]:
        if dependency.record_id not in records:
            raise ValueError("sidecar dependency references unknown calibre record")
        if dependency.sidecar.record_snapshot_id != dependency.record_id:
            raise ValueError("sidecar dependency must belong to its calibre record")
        if not isinstance(dependency.ambiguous, bool):
            raise ValueError("sidecar dependency ambiguity must be boolean")
        if not dependency.format_ids or len(set(dependency.format_ids)) != len(
            dependency.format_ids
        ):
            raise ValueError("sidecar dependency requires unique record formats")
        dependency_formats: list[CalibreLibraryFormatSnapshot] = []
        directories: set[PurePosixPath] = set()
        candidate_formats: list[CalibreLibraryFormatSnapshot] = []
        for format_id in dependency.format_ids:
            dependency_format = formats.get(format_id)
            if dependency_format is None:
                raise ValueError("sidecar dependency references unknown calibre format")
            if dependency_format.record_snapshot_id != dependency.record_id:
                raise ValueError("sidecar dependency format must belong to its calibre record")
            if (
                dependency_format.observation_id is None
                or dependency_format.observation_id not in observations
                or observations[dependency_format.observation_id].relative_path
                != dependency_format.relative_locator
            ):
                raise ValueError(
                    "sidecar dependency format requires its exact current observation"
                )
            candidate_formats.append(dependency_format)
            directories.add(PurePosixPath(dependency_format.relative_locator).parent)
        dependency_formats.extend(
            sorted(
                candidate_formats,
                key=lambda item: (item.format_label, item.relative_locator),
            )
        )
        if len(directories) != 1:
            raise ValueError("sidecar dependency requires one unambiguous record directory")
        directory = next(iter(directories))
        sidecar_path = PurePosixPath(dependency.sidecar.relative_locator)
        if dependency.sidecar.kind.value == "METADATA_OPF":
            valid_sidecar_path = sidecar_path == directory / "metadata.opf"
        elif dependency.sidecar.kind.value == "COVER":
            valid_sidecar_path = sidecar_path == directory / "cover.jpg"
        elif dependency.sidecar.kind.value == "EXTRA_DATA":
            valid_sidecar_path = (directory / "data") in sidecar_path.parents
        else:
            valid_sidecar_path = directory in sidecar_path.parents
        if not valid_sidecar_path or any(
            sidecar_path == PurePosixPath(item.relative_locator)
            for item in dependency_formats
        ):
            raise ValueError("sidecar dependency is outside its record directory")

        sidecar_observation_id = dependency.sidecar_observation_id
        if dependency.sidecar.observation_id is not None:
            if sidecar_observation_id not in {None, dependency.sidecar.observation_id}:
                raise ValueError("sidecar dependency has conflicting observation identities")
            sidecar_observation_id = dependency.sidecar.observation_id
        sidecar_observation = (
            None if sidecar_observation_id is None else observations.get(sidecar_observation_id)
        )
        if sidecar_observation_id is not None and (
            sidecar_observation is None
            or sidecar_observation.relative_path != dependency.sidecar.relative_locator
        ):
            raise ValueError("sidecar dependency observation does not match its locator")

        if len(set(dependency.extra_observation_ids)) != len(dependency.extra_observation_ids):
            raise ValueError("sidecar dependency extra observations must be unique")
        extra_observations: list[FileObservation] = []
        data_directory = directory / "data"
        candidate_extra_observations: list[FileObservation] = []
        for observation_id in dependency.extra_observation_ids:
            extra_observation = observations.get(observation_id)
            if (
                extra_observation is None
                or data_directory not in PurePosixPath(extra_observation.relative_path).parents
            ):
                raise ValueError("extra-data observation is outside the record data directory")
            candidate_extra_observations.append(extra_observation)
        extra_observations.extend(
            sorted(candidate_extra_observations, key=_observation_sort_key)
        )
        return tuple(dependency_formats), sidecar_observation, tuple(extra_observations)


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
    metadata_conflicts: Iterable[CalibreMetadataConflict] = (),
    authority_conflicts: Iterable[CalibreAuthorityConflict] = (),
    sidecar_dependencies: Iterable[CalibreSidecarDependency] = (),
) -> CalibreReconciliationMapping:
    """Functional entry point for the non-corrective A-G mapper."""
    return CalibreReconciliationMapper().map(
        snapshot,
        records,
        formats,
        current_observations,
        full_hashes,
        created_at=created_at,
        metadata_conflicts=metadata_conflicts,
        authority_conflicts=authority_conflicts,
        sidecar_dependencies=sidecar_dependencies,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value)


def _is_supported_ebook_observation(observation: FileObservation) -> bool:
    suffix = (
        observation.relative_path.rsplit(".", 1)[-1].upper()
        if "." in observation.relative_path
        else ""
    )
    return suffix in EBOOK_COLLECTION_FORMATS


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


def _metadata_record_material(record: CalibreLibraryRecordSnapshot, field_name: str) -> str:
    return _canonical(
        "CALIBRE_METADATA_RECORD",
        record.calibre_record_id,
        record.metadata_fingerprint,
        field_name,
    )


def _metadata_evidence_material(
    field_name: str,
    evidence: CalibreMetadataEvidence,
) -> str:
    target_kind, target_id = _metadata_evidence_target(evidence)
    return _canonical(
        "METADATA_EVIDENCE",
        field_name,
        target_kind.value,
        str(target_id),
        _metadata_evidence_value(evidence),
    )


def _authority_record_material(
    record: CalibreLibraryRecordSnapshot,
    contributor_name: str,
) -> str:
    return _canonical(
        "CALIBRE_CONTRIBUTOR",
        record.calibre_record_id,
        record.metadata_fingerprint,
        contributor_name,
    )


def _authority_evidence_material(contributor_name: str) -> str:
    return _canonical("CALIBRE_CONTRIBUTOR_EVIDENCE", contributor_name)


def _resolution_candidate_material(candidate: ResolutionCandidate) -> str:
    return _canonical(
        "RESOLUTION_CANDIDATE",
        candidate.subject_kind.value,
        str(candidate.subject_id),
        candidate.candidate_kind.value,
        str(candidate.candidate_entity_id),
        candidate.resolver_name,
        candidate.decision_compatibility_version,
        candidate.evidence_fingerprint,
        candidate.candidate_set_fingerprint,
        candidate.disposition.value,
    )


def _review_item_material(item: ReviewItem) -> str:
    return _canonical(
        "REVIEW_ITEM",
        item.review_type.value,
        item.candidate_kind.value,
        item.producer_name,
        item.decision_compatibility_version,
        item.evidence_fingerprint,
        item.candidate_set_fingerprint,
        item.state.value,
    )


def _sidecar_dependency_record_material(record: CalibreLibraryRecordSnapshot) -> str:
    return _canonical(
        "CALIBRE_SIDECAR_RECORD",
        record.calibre_record_id,
        record.metadata_fingerprint,
    )


def _sidecar_material(sidecar: CalibreLibrarySidecarSnapshot, ambiguous: bool) -> str:
    return _canonical(
        "CALIBRE_SIDECAR",
        sidecar.kind.value,
        sidecar.relative_locator,
        ambiguous,
    )


def _ensure_ref_limit(refs: Iterable[RefSpec]) -> None:
    if len(tuple(refs)) > MAX_FINDING_REFS:
        raise ValueError("Calibre finding exceeds the reference limit")


def _metadata_evidence_kind(
    evidence: CalibreMetadataEvidence,
) -> CalibreReconciliationFindingRefKind:
    if isinstance(evidence, ValueAssertion):
        return CalibreReconciliationFindingRefKind.VALUE_ASSERTION
    if isinstance(evidence, ToolResult):
        return CalibreReconciliationFindingRefKind.TOOL_RESULT
    raise ValueError("metadata conflict must reference persisted evidence")


def _metadata_evidence_field(evidence: CalibreMetadataEvidence) -> str:
    _metadata_evidence_kind(evidence)
    return evidence.field_name if isinstance(evidence, ValueAssertion) else evidence.key


def _metadata_evidence_value(evidence: CalibreMetadataEvidence) -> str:
    _metadata_evidence_kind(evidence)
    return evidence.value


def _metadata_evidence_target(
    evidence: CalibreMetadataEvidence,
) -> tuple[EntityKind, EntityId]:
    _metadata_evidence_kind(evidence)
    return evidence.target_kind, evidence.target_id


def _validate_current_evidence_target(
    observations: Mapping[EntityId, FileObservation],
    target_kind: EntityKind,
    target_id: EntityId,
) -> None:
    if target_kind is EntityKind.FILE_OBSERVATION and target_id in observations:
        return
    if target_kind is EntityKind.FILE and any(
        observation.file_id == target_id for observation in observations.values()
    ):
        return
    raise ValueError("metadata conflict evidence is outside the current source scan")


def _require_conflict_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} is invalid")


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
        CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT: 4,
        CalibreReconciliationFindingCode.CALIBRE_AUTHORITY_CONFLICT: 5,
        CalibreReconciliationFindingCode.CALIBRE_SIDECAR_DEPENDENCY: 6,
    }.get(code, 99)


# Backward-friendly name for callers that prefer an outcome noun.
CalibreReconciliationOutcome = CalibreReconciliationMapping
