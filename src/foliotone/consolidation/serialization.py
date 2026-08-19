"""Canonical, content-addressed serialization for consolidation plans."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from foliotone.consolidation.contracts import (
    ConsolidationBlocker,
    ConsolidationCandidateSnapshot,
    ConsolidationDependency,
    ConsolidationEvidenceReference,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationPlan,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationReviewSnapshot,
    KeepPreferenceOutcome,
)
from foliotone.core import EntityId

_JSONValue = dict[str, object] | list[object] | str | int | bool | None


def _enum(value: StrEnum) -> str:
    return value.value


def _entity_id(value: EntityId | None) -> str | None:
    return None if value is None else str(value)


def _timestamp(value: datetime) -> str:
    """Render an aware timestamp using the ADR's fixed UTC representation."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sorted_unique[T](
    values: tuple[T, ...],
    key: Callable[[T], tuple[object, ...]],
    field_name: str,
) -> tuple[T, ...]:
    ordered = tuple(sorted(values, key=key))
    keys = tuple(key(value) for value in ordered)
    if len(keys) != len(set(keys)):
        raise ValueError(f"{field_name} contains duplicate semantic entries")
    return ordered


def _evidence_key(value: ConsolidationEvidenceReference) -> tuple[str, ...]:
    return (
        _enum(value.role),
        _enum(value.kind),
        unicodedata.normalize("NFC", value.ref_id),
        value.material_fingerprint,
    )


def _evidence(value: ConsolidationEvidenceReference) -> dict[str, object]:
    return {
        "kind": _enum(value.kind),
        "ref_id": value.ref_id,
        "role": _enum(value.role),
        "material_fingerprint": value.material_fingerprint,
    }


def _blocker(value: ConsolidationBlocker) -> dict[str, object]:
    evidence = _sorted_unique(value.evidence_refs, _evidence_key, "evidence_refs")
    return {
        "code": _enum(value.code),
        "evidence_refs": [_evidence(item) for item in evidence],
    }


def _dependency(value: ConsolidationDependency) -> dict[str, object]:
    return {
        "file_role": _enum(value.file_role),
        "kind": _enum(value.kind),
        "state": _enum(value.state),
        "material_fingerprint": value.material_fingerprint,
        "snapshot_kind": value.snapshot_kind,
        "snapshot_id": _entity_id(value.snapshot_id),
    }


def _identity(value: ConsolidationIdentitySnapshot) -> dict[str, object]:
    return {
        "relation_candidate_id": str(value.relation_candidate_id),
        "relation_type": _enum(value.relation_type),
        "left_kind": _enum(value.left_kind),
        "right_kind": _enum(value.right_kind),
        "left_file_id": str(value.left_file_id),
        "right_file_id": str(value.right_file_id),
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "status": _enum(value.status),
        "matcher_version": value.matcher_version,
        "decision_compatibility_version": value.decision_compatibility_version,
        "evidence_fingerprint": value.evidence_fingerprint,
        "candidate_set_fingerprint": value.candidate_set_fingerprint,
    }


def _endpoint(value: ConsolidationFileEndpoint) -> dict[str, object]:
    return {
        "role": _enum(value.role),
        "file_id": str(value.file_id),
        "observation_id": str(value.observation_id),
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "expected_presence_state": _enum(value.expected_presence_state),
        "expected_full_sha256": value.expected_full_sha256,
        "expected_size_bytes": value.expected_size_bytes,
        "expected_modified_at": _timestamp(value.expected_modified_at),
        "expected_observed_at": _timestamp(value.expected_observed_at),
        "format_label": value.format_label,
    }


def _quality(value: ConsolidationQualityEvidenceSnapshot) -> dict[str, object]:
    return {
        "id": str(value.id),
        "role": _enum(value.role),
        "collection_run_id": str(value.collection_run_id),
        "collection_item_id": str(value.collection_item_id),
        "observation_id": str(value.observation_id),
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "collection_profile": value.collection_profile,
        "analysis_profile": value.analysis_profile,
        "quality_profile": value.quality_profile,
        "format_label": value.format_label,
        "assessment_fingerprint": value.assessment_fingerprint,
    }


def _intent_key(value: ConsolidationFutureOperationIntent) -> tuple[object, ...]:
    return (value.ordinal, _enum(value.code), _enum(value.file_role))


def _intent(value: ConsolidationFutureOperationIntent) -> dict[str, object]:
    return {
        "ordinal": value.ordinal,
        "code": _enum(value.code),
        "file_role": _enum(value.file_role),
    }


def _candidate(value: ConsolidationCandidateSnapshot) -> dict[str, object]:
    intents = _sorted_unique(value.intents, _intent_key, "intents")
    return {
        "candidate_id": str(value.candidate_id),
        "profile": value.profile,
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "relation_candidate_id": str(value.relation_candidate_id),
        "relation_fingerprint": value.relation_fingerprint,
        "keep_preference_id": str(value.keep_preference_id),
        "keep_preference_fingerprint": value.keep_preference_fingerprint,
        "keeper_file_id": str(value.keeper_file_id),
        "candidate_file_id": str(value.candidate_file_id),
        "dependency_fingerprint": value.dependency_fingerprint,
        "precondition_fingerprint": value.precondition_fingerprint,
        "evidence_fingerprint": value.evidence_fingerprint,
        "candidate_set_fingerprint": value.candidate_set_fingerprint,
        "intents": [_intent(item) for item in intents],
    }


def _precondition_key(value: ConsolidationFilePreconditionSnapshot) -> tuple[str, ...]:
    return (_enum(value.file_role), _enum(value.code))


def _precondition(value: ConsolidationFilePreconditionSnapshot) -> dict[str, object]:
    return {
        "file_role": _enum(value.file_role),
        "code": _enum(value.code),
        "expected_file_id": str(value.expected_file_id),
        "expected_observation_id": str(value.expected_observation_id),
        "expected_scan_root_id": str(value.expected_scan_root_id),
        "expected_scan_run_id": str(value.expected_scan_run_id),
        "expected_presence_state": _enum(value.expected_presence_state),
        "expected_full_sha256": value.expected_full_sha256,
        "expected_size_bytes": value.expected_size_bytes,
        "expected_modified_at": _timestamp(value.expected_modified_at),
        "expected_observed_at": _timestamp(value.expected_observed_at),
        "dependency_kind": None if value.dependency_kind is None else _enum(value.dependency_kind),
        "dependency_state": (
            None if value.dependency_state is None else _enum(value.dependency_state)
        ),
        "dependency_fingerprint": value.dependency_fingerprint,
        "dependency_snapshot_kind": value.dependency_snapshot_kind,
        "dependency_snapshot_id": _entity_id(value.dependency_snapshot_id),
        "review_item_id": _entity_id(value.review_item_id),
        "review_decision_id": _entity_id(value.review_decision_id),
        "review_decision_sequence_no": value.review_decision_sequence_no,
        "review_decision_compatibility_version": (
            value.review_decision_compatibility_version
        ),
        "review_evidence_fingerprint": value.review_evidence_fingerprint,
        "review_candidate_set_fingerprint": value.review_candidate_set_fingerprint,
    }


def _review_key(value: ConsolidationReviewSnapshot) -> tuple[str, ...]:
    return (_enum(value.review_type), _entity_id(value.review_item_id) or "")


def _review(value: ConsolidationReviewSnapshot) -> dict[str, object]:
    return {
        "review_type": _enum(value.review_type),
        "state": _enum(value.state),
        "evidence_fingerprint": value.evidence_fingerprint,
        "candidate_set_fingerprint": value.candidate_set_fingerprint,
        "candidate_kind": _enum(value.candidate_kind),
        "producer_name": value.producer_name,
        "decision_compatibility_version": value.decision_compatibility_version,
        "review_item_id": _entity_id(value.review_item_id),
        "decision_id": _entity_id(value.decision_id),
        "decision_sequence_no": value.decision_sequence_no,
    }


def _preference(value: KeepPreferenceOutcome) -> dict[str, object]:
    quality = _sorted_unique(
        value.quality_evidence,
        lambda item: (_enum(item.role), str(item.id)),
        "quality_evidence",
    )
    return {
        "preference_id": str(value.preference_id),
        "profile": value.profile,
        "profile_version": value.profile_version,
        "left_file_id": str(value.left_file_id),
        "left_observation_id": str(value.left_observation_id),
        "right_file_id": str(value.right_file_id),
        "right_observation_id": str(value.right_observation_id),
        "status": _enum(value.status),
        "keeper_file_id": _entity_id(value.keeper_file_id),
        "candidate_file_id": _entity_id(value.candidate_file_id),
        "reason_codes": [_enum(item) for item in value.reason_codes],
        "configuration_fingerprint": value.configuration_fingerprint,
        "evidence_fingerprint": value.evidence_fingerprint,
        "quality_evidence": [_quality(item) for item in quality],
        "candidate_set_fingerprint": value.candidate_set_fingerprint,
    }


def _blocker_key(value: ConsolidationBlocker) -> tuple[object, ...]:
    evidence = tuple(sorted(value.evidence_refs, key=_evidence_key))
    return (_enum(value.code), tuple(_evidence_key(ref) for ref in evidence))


def _payload(plan: ConsolidationPlan) -> dict[str, object]:
    dependencies = _sorted_unique(
        plan.dependencies,
        lambda item: (_enum(item.file_role), _enum(item.kind)),
        "dependencies",
    )
    quality = _sorted_unique(
        plan.quality_evidence,
        lambda item: (_enum(item.role), str(item.id)),
        "quality_evidence",
    )
    reviews = _sorted_unique(plan.required_reviews, _review_key, "required_reviews")
    preconditions = _sorted_unique(plan.preconditions, _precondition_key, "preconditions")
    intents = _sorted_unique(plan.future_operation_intents, _intent_key, "future_operation_intents")
    blockers = _sorted_unique(plan.blockers, _blocker_key, "blockers")
    return {
        "domain": "foliotone:consolidation-plan/v1",
        "profile": plan.profile,
        "plan_version": plan.plan_version,
        "serializer_version": plan.serializer_version,
        "scan_root_id": str(plan.scan_root_id),
        "source_scan_run_id": str(plan.source_scan_run_id),
        "identity": None if plan.identity is None else _identity(plan.identity),
        "keeper": None if plan.keeper is None else _endpoint(plan.keeper),
        "candidate": None if plan.candidate is None else _endpoint(plan.candidate),
        "keep_preference": (
            None if plan.keep_preference is None else _preference(plan.keep_preference)
        ),
        "consolidation_candidate": (
            None
            if plan.consolidation_candidate is None
            else _candidate(plan.consolidation_candidate)
        ),
        "dependencies": [_dependency(item) for item in dependencies],
        "quality_evidence": [_quality(item) for item in quality],
        "required_reviews": [_review(item) for item in reviews],
        "preconditions": [_precondition(item) for item in preconditions],
        "future_operation_intents": [_intent(item) for item in intents],
        "blockers": [_blocker(item) for item in blockers],
        "status": _enum(plan.status),
        "execution_state": _enum(plan.execution_state),
    }


def _normalize(value: object) -> _JSONValue:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are forbidden in canonical consolidation payloads")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {unicodedata.normalize("NFC", key): _normalize(item) for key, item in value.items()}
    raise TypeError(f"unsupported value in canonical consolidation payload: {type(value).__name__}")


def canonical_consolidation_plan_payload(plan: ConsolidationPlan) -> dict[str, object]:
    """Return a fresh material payload mapping, excluding persistence fields."""
    if not isinstance(plan, ConsolidationPlan):
        raise TypeError("plan must be a ConsolidationPlan")
    return _payload(plan)


def serialize_consolidation_plan(plan: ConsolidationPlan) -> bytes:
    """Serialize a plan as canonical ``canonical-json/v1`` UTF-8 bytes."""
    normalized = _normalize(canonical_consolidation_plan_payload(plan))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def consolidation_plan_content_hash(plan: ConsolidationPlan) -> str:
    """Return the lowercase SHA-256 digest of the canonical plan payload."""
    return hashlib.sha256(serialize_consolidation_plan(plan)).hexdigest()


# Explicit aliases keep the API discoverable without adding any mutable builder.
canonical_plan_bytes = serialize_consolidation_plan
compute_consolidation_plan_content_hash = consolidation_plan_content_hash


__all__ = [
    "canonical_consolidation_plan_payload",
    "serialize_consolidation_plan",
    "consolidation_plan_content_hash",
    "canonical_plan_bytes",
    "compute_consolidation_plan_content_hash",
]
