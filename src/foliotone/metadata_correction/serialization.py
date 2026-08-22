"""Canonical serialization and content identities for metadata correction planning."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid5

from foliotone.core import EntityId
from foliotone.metadata_correction.contracts import (
    METADATA_CORRECTION_CANDIDATE_NAMESPACE,
    METADATA_CORRECTION_PLAN_NAMESPACE,
    METADATA_CORRECTION_WRITE_INTENT_PROFILE,
    MetadataCorrectionBlocker,
    MetadataCorrectionCandidate,
    MetadataCorrectionOperation,
    MetadataCorrectionPlan,
    MetadataCorrectionPrecondition,
    MetadataCorrectionPreconditionCode,
    MetadataCorrectionReviewSnapshot,
    MetadataCorrectionVerification,
    MetadataDependencySnapshot,
    MetadataEvidenceReference,
    MetadataFieldCorrection,
    MetadataTargetCarrier,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    MetadataWriterRequirement,
    validate_metadata_field_path,
)

_JSONValue = dict[str, object] | list[object] | str | int | bool | None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalize(value: object) -> _JSONValue:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are forbidden in canonical metadata correction payloads")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {
            unicodedata.normalize("NFC", key): _normalize(item)
            for key, item in value.items()
        }
    raise TypeError(
        f"unsupported value in canonical metadata correction payload: {type(value).__name__}"
    )


def _canonical_bytes(value: object) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _enum(value: StrEnum) -> str:
    return value.value


def _evidence_key(value: MetadataEvidenceReference) -> tuple[str, str, str]:
    return (value.kind, str(value.ref_id), value.material_fingerprint)


def _evidence(value: MetadataEvidenceReference) -> dict[str, object]:
    return {
        "kind": value.kind,
        "ref_id": str(value.ref_id),
        "material_fingerprint": value.material_fingerprint,
    }


def _value(value: MetadataValueSnapshot) -> dict[str, object]:
    return {
        "ordinal": value.ordinal,
        "state": _enum(value.state),
        "source_ref": _evidence(value.source_ref),
        "value": value.value,
    }


def _field_selection_material(
    *,
    field_path: str,
    operation: MetadataCorrectionOperation,
    observed_values: tuple[MetadataValueSnapshot, ...],
    selected_values: tuple[MetadataValueSnapshot, ...],
) -> dict[str, object]:
    return {
        "domain": "foliotone:metadata-field-selection/v1",
        "field_path": validate_metadata_field_path(field_path),
        "operation": _enum(operation),
        "observed_values": [_value(item) for item in observed_values],
        "selected_values": [_value(item) for item in selected_values],
    }


def metadata_field_selection_fingerprint(
    *,
    field_path: str,
    operation: MetadataCorrectionOperation,
    observed_values: tuple[MetadataValueSnapshot, ...],
    selected_values: tuple[MetadataValueSnapshot, ...],
) -> str:
    """Hash the complete ordered observed/selected value decision for one field."""
    if not isinstance(operation, MetadataCorrectionOperation):
        raise ValueError("operation must be a MetadataCorrectionOperation")
    return _digest(
        _field_selection_material(
            field_path=field_path,
            operation=operation,
            observed_values=observed_values,
            selected_values=selected_values,
        )
    )


def _field(value: MetadataFieldCorrection) -> dict[str, object]:
    evidence = tuple(sorted(value.evidence_refs, key=_evidence_key))
    return {
        "field_path": value.field_path,
        "operation": _enum(value.operation),
        "observed_values": [_value(item) for item in value.observed_values],
        "selected_values": [_value(item) for item in value.selected_values],
        "selection_fingerprint": value.selection_fingerprint,
        "evidence_refs": [_evidence(item) for item in evidence],
    }


def _target(value: MetadataTargetSnapshot) -> dict[str, object]:
    return {
        "carrier": _enum(value.carrier),
        "reference_kind": _enum(value.reference_kind),
        "reference_id": str(value.reference_id),
        "carrier_state_fingerprint": value.carrier_state_fingerprint,
    }


def _dependency(value: MetadataDependencySnapshot) -> dict[str, object]:
    return {
        "kind": _enum(value.kind),
        "state": _enum(value.state),
        "snapshot_kind": value.snapshot_kind,
        "snapshot_id": str(value.snapshot_id),
        "material_fingerprint": value.material_fingerprint,
    }


def _writer_material(
    *,
    format_label: str,
    target_carrier: MetadataTargetCarrier,
) -> dict[str, object]:
    return {
        "domain": "foliotone:ebook-metadata-write-intent/v1",
        "profile": METADATA_CORRECTION_WRITE_INTENT_PROFILE,
        "format_label": format_label,
        "target_carrier": _enum(target_carrier),
    }


def metadata_writer_requirement_fingerprint(
    *,
    format_label: str,
    target_carrier: MetadataTargetCarrier,
) -> str:
    """Hash a semantic writer requirement without naming a writer or command."""
    return _digest(
        _writer_material(
            format_label=format_label,
            target_carrier=target_carrier,
        )
    )


def _writer(value: MetadataWriterRequirement) -> dict[str, object]:
    return {
        "profile": value.profile,
        "format_label": value.format_label,
        "target_carrier": _enum(value.target_carrier),
        "material_fingerprint": value.material_fingerprint,
    }


def _candidate_evidence_payload(candidate: MetadataCorrectionCandidate) -> dict[str, object]:
    fields = tuple(sorted(candidate.field_corrections, key=lambda item: item.field_path))
    dependencies = tuple(sorted(candidate.dependencies, key=lambda item: item.kind.value))
    evidence = tuple(sorted(candidate.evidence_refs, key=_evidence_key))
    return {
        "domain": "foliotone:metadata-correction-evidence/v1",
        "scan_root_id": str(candidate.scan_root_id),
        "source_scan_run_id": str(candidate.source_scan_run_id),
        "source_scan_run_status": _enum(candidate.source_scan_run_status),
        "file_id": str(candidate.file_id),
        "observation_id": str(candidate.observation_id),
        "format_label": candidate.format_label,
        "expected_presence_state": _enum(candidate.expected_presence_state),
        "expected_full_sha256": candidate.expected_full_sha256,
        "expected_size_bytes": candidate.expected_size_bytes,
        "expected_modified_at": _timestamp(candidate.expected_modified_at),
        "expected_observed_at": _timestamp(candidate.expected_observed_at),
        "metadata_evidence_fingerprint": candidate.metadata_evidence_fingerprint,
        "target": _target(candidate.target),
        "field_corrections": [_field(item) for item in fields],
        "dependencies": [_dependency(item) for item in dependencies],
        "writer_requirement": _writer(candidate.writer_requirement),
        "evidence_refs": [_evidence(item) for item in evidence],
    }


def metadata_correction_candidate_evidence_fingerprint(
    candidate: MetadataCorrectionCandidate,
) -> str:
    """Hash all material source, selection, target and dependency evidence."""
    if not isinstance(candidate, MetadataCorrectionCandidate):
        raise TypeError("candidate must be a MetadataCorrectionCandidate")
    return _digest(_candidate_evidence_payload(candidate))


def canonical_metadata_correction_candidate_payload(
    candidate: MetadataCorrectionCandidate,
) -> dict[str, object]:
    """Return the candidate hash payload without ID, content hash or audit time."""
    if not isinstance(candidate, MetadataCorrectionCandidate):
        raise TypeError("candidate must be a MetadataCorrectionCandidate")
    evidence_payload = {
        key: value
        for key, value in _candidate_evidence_payload(candidate).items()
        if key != "domain"
    }
    return {
        "profile": candidate.profile,
        "serializer_version": candidate.serializer_version,
        **evidence_payload,
        "domain": "foliotone:metadata-correction-candidate/v1",
        "evidence_fingerprint": candidate.evidence_fingerprint,
    }


def serialize_metadata_correction_candidate(candidate: MetadataCorrectionCandidate) -> bytes:
    """Serialize one candidate using ``canonical-json/v1``."""
    return _canonical_bytes(canonical_metadata_correction_candidate_payload(candidate))


def metadata_correction_candidate_content_hash(
    candidate: MetadataCorrectionCandidate,
) -> str:
    return hashlib.sha256(serialize_metadata_correction_candidate(candidate)).hexdigest()


def metadata_correction_candidate_id(content_hash: str) -> EntityId:
    if len(content_hash) != 64 or any(value not in "0123456789abcdef" for value in content_hash):
        raise ValueError("content_hash must be a lowercase SHA-256 digest")
    return EntityId(uuid5(METADATA_CORRECTION_CANDIDATE_NAMESPACE, content_hash))


def metadata_correction_selected_fields_fingerprint(
    candidate: MetadataCorrectionCandidate,
) -> str:
    fields = tuple(sorted(candidate.field_corrections, key=lambda item: item.field_path))
    return _digest(
        {
            "domain": "foliotone:metadata-correction-selected-fields/v1",
            "fields": [
                {
                    "field_path": item.field_path,
                    "operation": _enum(item.operation),
                    "selected_values": [_value(value) for value in item.selected_values],
                    "selection_fingerprint": item.selection_fingerprint,
                }
                for item in fields
            ],
        }
    )


def metadata_correction_precondition_fingerprint(
    code: MetadataCorrectionPreconditionCode,
    expected_material: object,
) -> str:
    """Hash the expected state for one future immediate revalidation check."""
    if not isinstance(code, MetadataCorrectionPreconditionCode):
        raise ValueError("code must be a MetadataCorrectionPreconditionCode")
    return _digest(
        {
            "domain": "foliotone:metadata-correction-precondition/v1",
            "code": _enum(code),
            "expected": expected_material,
        }
    )


def _review(value: MetadataCorrectionReviewSnapshot | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "candidate_id": str(value.candidate_id),
        "review_type": value.review_type,
        "candidate_kind": value.candidate_kind,
        "state": _enum(value.state),
        "producer_name": value.producer_name,
        "producer_version": value.producer_version,
        "decision_compatibility_version": value.decision_compatibility_version,
        "evidence_fingerprint": value.evidence_fingerprint,
        "candidate_set_fingerprint": value.candidate_set_fingerprint,
        "review_item_id": (
            None if value.review_item_id is None else str(value.review_item_id)
        ),
        "decision_id": None if value.decision_id is None else str(value.decision_id),
        "decision_sequence_no": value.decision_sequence_no,
    }


def _precondition(value: MetadataCorrectionPrecondition) -> dict[str, object]:
    return {
        "code": _enum(value.code),
        "expected_fingerprint": value.expected_fingerprint,
    }


def _verification(value: MetadataCorrectionVerification) -> dict[str, object]:
    return {
        "profile": value.profile,
        "analysis_profile": value.analysis_profile,
        "format_label": value.format_label,
        "target_carrier": _enum(value.target_carrier),
        "expected_selected_fields_fingerprint": (
            value.expected_selected_fields_fingerprint
        ),
        "preserved_fields_fingerprint": value.preserved_fields_fingerprint,
        "changed_field_paths": list(value.changed_field_paths),
        "format_validation_required": value.format_validation_required,
        "readability_validation_required": value.readability_validation_required,
        "dependency_reconciliation": [
            _enum(item) for item in value.dependency_reconciliation
        ],
    }


def _blocker(value: MetadataCorrectionBlocker) -> dict[str, object]:
    evidence = tuple(sorted(value.evidence_refs, key=_evidence_key))
    return {
        "code": _enum(value.code),
        "evidence_refs": [_evidence(item) for item in evidence],
    }


def canonical_metadata_correction_plan_payload(
    plan: MetadataCorrectionPlan,
) -> dict[str, object]:
    """Return the plan hash payload without ID, content hash or audit time."""
    if not isinstance(plan, MetadataCorrectionPlan):
        raise TypeError("plan must be a MetadataCorrectionPlan")
    preconditions = tuple(sorted(plan.preconditions, key=lambda item: item.code.value))
    blockers = tuple(sorted(plan.blockers, key=lambda item: item.code.value))
    return {
        "domain": "foliotone:metadata-correction-plan/v1",
        "profile": plan.profile,
        "serializer_version": plan.serializer_version,
        "candidate": {
            "id": str(plan.candidate.id),
            "profile": plan.candidate.profile,
            "content_hash": plan.candidate.content_hash,
            "evidence_fingerprint": plan.candidate.evidence_fingerprint,
        },
        "review": _review(plan.review),
        "preconditions": [_precondition(item) for item in preconditions],
        "verification": _verification(plan.verification),
        "blockers": [_blocker(item) for item in blockers],
        "status": _enum(plan.status),
        "execution_state": _enum(plan.execution_state),
    }


def serialize_metadata_correction_plan(plan: MetadataCorrectionPlan) -> bytes:
    """Serialize one plan using ``canonical-json/v1``."""
    return _canonical_bytes(canonical_metadata_correction_plan_payload(plan))


def metadata_correction_plan_content_hash(plan: MetadataCorrectionPlan) -> str:
    return hashlib.sha256(serialize_metadata_correction_plan(plan)).hexdigest()


def metadata_correction_plan_id(content_hash: str) -> EntityId:
    if len(content_hash) != 64 or any(value not in "0123456789abcdef" for value in content_hash):
        raise ValueError("content_hash must be a lowercase SHA-256 digest")
    return EntityId(uuid5(METADATA_CORRECTION_PLAN_NAMESPACE, content_hash))


__all__ = [
    "canonical_metadata_correction_candidate_payload",
    "canonical_metadata_correction_plan_payload",
    "metadata_correction_candidate_content_hash",
    "metadata_correction_candidate_evidence_fingerprint",
    "metadata_correction_candidate_id",
    "metadata_correction_plan_content_hash",
    "metadata_correction_plan_id",
    "metadata_correction_precondition_fingerprint",
    "metadata_correction_selected_fields_fingerprint",
    "metadata_field_selection_fingerprint",
    "metadata_writer_requirement_fingerprint",
    "serialize_metadata_correction_candidate",
    "serialize_metadata_correction_plan",
]
