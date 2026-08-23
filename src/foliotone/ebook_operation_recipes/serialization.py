"""Canonical serialization and content identities for e-book operation recipes."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid5

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes.contracts import (
    EBOOK_OPERATION_RECIPE_CANDIDATE_NAMESPACE,
    EBOOK_OPERATION_RECIPE_PLAN_NAMESPACE,
    EbookOperationBlocker,
    EbookOperationCollisionPolicy,
    EbookOperationDependencySnapshot,
    EbookOperationEvidenceReference,
    EbookOperationExpectedOutput,
    EbookOperationKind,
    EbookOperationPrecondition,
    EbookOperationPreconditionCode,
    EbookOperationProcessorRequirement,
    EbookOperationRecipeCandidate,
    EbookOperationRecipePlan,
    EbookOperationRecoveryMode,
    EbookOperationReviewSnapshot,
    EbookOperationSourceSnapshot,
    EbookOperationTargetSnapshot,
    EbookOperationVerificationCode,
    EbookOperationWorkspaceMode,
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
        raise TypeError("floats are forbidden in canonical operation recipe payloads")
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
        f"unsupported value in canonical operation recipe payload: {type(value).__name__}"
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _normalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _enum(value: StrEnum) -> str:
    return value.value


def _require_sha256(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("content_hash must be a lowercase SHA-256 digest")
    return value


def _evidence_key(value: EbookOperationEvidenceReference) -> tuple[str, str, str]:
    return value.kind, str(value.ref_id), value.material_fingerprint


def _evidence(value: EbookOperationEvidenceReference) -> dict[str, object]:
    return {
        "kind": value.kind,
        "ref_id": str(value.ref_id),
        "material_fingerprint": value.material_fingerprint,
    }


def _source_material(value: EbookOperationSourceSnapshot) -> dict[str, object]:
    return {
        "ordinal": value.ordinal,
        "role": _enum(value.role),
        "scan_root_id": str(value.scan_root_id),
        "source_scan_run_id": str(value.source_scan_run_id),
        "source_scan_run_status": _enum(value.source_scan_run_status),
        "file_id": str(value.file_id),
        "observation_id": str(value.observation_id),
        "relative_locator": value.relative_locator,
        "format_label": value.format_label,
        "expected_presence_state": _enum(value.expected_presence_state),
        "expected_full_sha256": value.expected_full_sha256,
        "expected_size_bytes": value.expected_size_bytes,
        "expected_modified_at": _timestamp(value.expected_modified_at),
        "expected_observed_at": _timestamp(value.expected_observed_at),
    }


def ebook_operation_source_evidence_fingerprint(
    value: EbookOperationSourceSnapshot,
) -> str:
    """Hash all material fields of one completed-scan source snapshot."""
    if not isinstance(value, EbookOperationSourceSnapshot):
        raise TypeError("value must be an EbookOperationSourceSnapshot")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-source-evidence/v1",
            **_source_material(value),
        }
    )


def _source(value: EbookOperationSourceSnapshot) -> dict[str, object]:
    return {
        **_source_material(value),
        "source_evidence_fingerprint": value.source_evidence_fingerprint,
    }


def _target(value: EbookOperationTargetSnapshot) -> dict[str, object]:
    return {
        "kind": _enum(value.kind),
        "scope_id": str(value.scope_id),
        "relative_locator": value.relative_locator,
        "target_state_fingerprint": value.target_state_fingerprint,
    }


def _expected_output_material(
    value: EbookOperationExpectedOutput,
) -> dict[str, object]:
    return {
        "identity_kind": _enum(value.identity_kind),
        "format_label": value.format_label,
        "expected_full_sha256": value.expected_full_sha256,
        "expected_size_bytes": value.expected_size_bytes,
    }


def ebook_operation_expected_output_fingerprint(
    value: EbookOperationExpectedOutput,
) -> str:
    """Hash the complete expected output identity and shape."""
    if not isinstance(value, EbookOperationExpectedOutput):
        raise TypeError("value must be an EbookOperationExpectedOutput")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-expected-output/v1",
            **_expected_output_material(value),
        }
    )


def _expected_output(value: EbookOperationExpectedOutput) -> dict[str, object]:
    return {
        **_expected_output_material(value),
        "output_specification_fingerprint": value.output_specification_fingerprint,
    }


def _processor_material(value: EbookOperationProcessorRequirement) -> dict[str, object]:
    return {
        "kind": _enum(value.kind),
        "processor_profile": value.processor_profile,
        "configuration_fingerprint": value.configuration_fingerprint,
        "provider_id": value.provider_id,
        "tool_version": value.tool_version,
        "adapter_version": value.adapter_version,
    }


def ebook_operation_processor_requirement_fingerprint(
    value: EbookOperationProcessorRequirement,
) -> str:
    """Hash a bounded processor requirement without commands or executable paths."""
    if not isinstance(value, EbookOperationProcessorRequirement):
        raise TypeError("value must be an EbookOperationProcessorRequirement")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-processor-requirement/v1",
            **_processor_material(value),
        }
    )


def _processor(value: EbookOperationProcessorRequirement) -> dict[str, object]:
    return {
        **_processor_material(value),
        "material_fingerprint": value.material_fingerprint,
    }


def _dependency(value: EbookOperationDependencySnapshot) -> dict[str, object]:
    return {
        "kind": _enum(value.kind),
        "state": _enum(value.state),
        "snapshot_kind": value.snapshot_kind,
        "snapshot_id": str(value.snapshot_id),
        "material_fingerprint": value.material_fingerprint,
    }


def ebook_operation_workspace_requirement_fingerprint(
    operation_kind: EbookOperationKind,
    workspace_mode: EbookOperationWorkspaceMode,
) -> str:
    """Hash the operation-specific workspace requirement."""
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    if not isinstance(workspace_mode, EbookOperationWorkspaceMode):
        raise ValueError("workspace_mode must be an EbookOperationWorkspaceMode")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-workspace-requirement/v1",
            "operation_kind": _enum(operation_kind),
            "workspace_mode": _enum(workspace_mode),
        }
    )


def ebook_operation_recovery_requirement_fingerprint(
    operation_kind: EbookOperationKind,
    recovery_mode: EbookOperationRecoveryMode,
    collision_policy: EbookOperationCollisionPolicy,
) -> str:
    """Hash the bounded recovery and collision contract."""
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    if not isinstance(recovery_mode, EbookOperationRecoveryMode):
        raise ValueError("recovery_mode must be an EbookOperationRecoveryMode")
    if not isinstance(collision_policy, EbookOperationCollisionPolicy):
        raise ValueError("collision_policy must be an EbookOperationCollisionPolicy")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-recovery-requirement/v1",
            "operation_kind": _enum(operation_kind),
            "recovery_mode": _enum(recovery_mode),
            "collision_policy": _enum(collision_policy),
        }
    )


def ebook_operation_verification_fingerprint(
    operation_kind: EbookOperationKind,
    verification_codes: tuple[EbookOperationVerificationCode, ...],
) -> str:
    """Hash the complete ordered post-operation verification contract."""
    if not isinstance(operation_kind, EbookOperationKind):
        raise ValueError("operation_kind must be an EbookOperationKind")
    if any(
        not isinstance(code, EbookOperationVerificationCode)
        for code in verification_codes
    ):
        raise ValueError("verification_codes must contain verification codes")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-verification-requirement/v1",
            "operation_kind": _enum(operation_kind),
            "verification_codes": [_enum(code) for code in verification_codes],
        }
    )


def _candidate_evidence_payload(
    candidate: EbookOperationRecipeCandidate,
) -> dict[str, object]:
    evidence = tuple(sorted(candidate.evidence_refs, key=_evidence_key))
    return {
        "domain": "foliotone:ebook-operation-recipe-evidence/v1",
        "operation_kind": _enum(candidate.operation_kind),
        "sources": [_source(value) for value in candidate.sources],
        "target": _target(candidate.target),
        "expected_output": _expected_output(candidate.expected_output),
        "collision_policy": _enum(candidate.collision_policy),
        "workspace_mode": _enum(candidate.workspace_mode),
        "recovery_mode": _enum(candidate.recovery_mode),
        "processor_requirement": _processor(candidate.processor_requirement),
        "dependencies": [_dependency(value) for value in candidate.dependencies],
        "verification_codes": [_enum(value) for value in candidate.verification_codes],
        "workspace_requirement_fingerprint": (
            candidate.workspace_requirement_fingerprint
        ),
        "recovery_requirement_fingerprint": (
            candidate.recovery_requirement_fingerprint
        ),
        "verification_fingerprint": candidate.verification_fingerprint,
        "evidence_refs": [_evidence(value) for value in evidence],
    }


def ebook_operation_recipe_candidate_evidence_fingerprint(
    candidate: EbookOperationRecipeCandidate,
) -> str:
    """Hash every material input, expected state and supporting evidence binding."""
    if not isinstance(candidate, EbookOperationRecipeCandidate):
        raise TypeError("candidate must be an EbookOperationRecipeCandidate")
    return _digest(_candidate_evidence_payload(candidate))


def canonical_ebook_operation_recipe_candidate_payload(
    candidate: EbookOperationRecipeCandidate,
) -> dict[str, object]:
    """Return candidate hash material without ID, content hash or audit time."""
    if not isinstance(candidate, EbookOperationRecipeCandidate):
        raise TypeError("candidate must be an EbookOperationRecipeCandidate")
    evidence_payload = {
        key: value
        for key, value in _candidate_evidence_payload(candidate).items()
        if key != "domain"
    }
    return {
        "domain": "foliotone:ebook-operation-recipe-candidate/v1",
        "profile": candidate.profile,
        "serializer_version": candidate.serializer_version,
        **evidence_payload,
        "evidence_fingerprint": candidate.evidence_fingerprint,
    }


def serialize_ebook_operation_recipe_candidate(
    candidate: EbookOperationRecipeCandidate,
) -> bytes:
    """Serialize one candidate using canonical UTF-8 JSON."""
    return _canonical_bytes(canonical_ebook_operation_recipe_candidate_payload(candidate))


def ebook_operation_recipe_candidate_content_hash(
    candidate: EbookOperationRecipeCandidate,
) -> str:
    return hashlib.sha256(
        serialize_ebook_operation_recipe_candidate(candidate)
    ).hexdigest()


def ebook_operation_recipe_candidate_id(content_hash: str) -> EntityId:
    return EntityId(
        uuid5(EBOOK_OPERATION_RECIPE_CANDIDATE_NAMESPACE, _require_sha256(content_hash))
    )


def ebook_operation_precondition_fingerprint(
    code: EbookOperationPreconditionCode,
    expected_material: object,
) -> str:
    """Hash the expected state for one future immediate revalidation check."""
    if not isinstance(code, EbookOperationPreconditionCode):
        raise ValueError("code must be an EbookOperationPreconditionCode")
    return _digest(
        {
            "domain": "foliotone:ebook-operation-precondition/v1",
            "code": _enum(code),
            "expected": expected_material,
        }
    )


def _review(value: EbookOperationReviewSnapshot) -> dict[str, object]:
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


def _precondition(value: EbookOperationPrecondition) -> dict[str, object]:
    return {
        "code": _enum(value.code),
        "expected_fingerprint": value.expected_fingerprint,
    }


def _blocker(value: EbookOperationBlocker) -> dict[str, object]:
    evidence = tuple(sorted(value.evidence_refs, key=_evidence_key))
    return {
        "code": _enum(value.code),
        "evidence_refs": [_evidence(item) for item in evidence],
    }


def canonical_ebook_operation_recipe_plan_payload(
    plan: EbookOperationRecipePlan,
) -> dict[str, object]:
    """Return plan hash material without ID, content hash or audit time."""
    if not isinstance(plan, EbookOperationRecipePlan):
        raise TypeError("plan must be an EbookOperationRecipePlan")
    preconditions = tuple(
        sorted(plan.preconditions, key=lambda value: value.code.value)
    )
    blockers = tuple(sorted(plan.blockers, key=lambda value: value.code.value))
    return {
        "domain": "foliotone:ebook-operation-recipe-plan/v1",
        "profile": plan.profile,
        "serializer_version": plan.serializer_version,
        "candidate": {
            "id": str(plan.candidate.id),
            "profile": plan.candidate.profile,
            "content_hash": plan.candidate.content_hash,
            "evidence_fingerprint": plan.candidate.evidence_fingerprint,
        },
        "review": _review(plan.review),
        "preconditions": [_precondition(value) for value in preconditions],
        "blockers": [_blocker(value) for value in blockers],
        "status": _enum(plan.status),
        "execution_state": _enum(plan.execution_state),
    }


def serialize_ebook_operation_recipe_plan(plan: EbookOperationRecipePlan) -> bytes:
    """Serialize one plan using canonical UTF-8 JSON."""
    return _canonical_bytes(canonical_ebook_operation_recipe_plan_payload(plan))


def ebook_operation_recipe_plan_content_hash(plan: EbookOperationRecipePlan) -> str:
    return hashlib.sha256(serialize_ebook_operation_recipe_plan(plan)).hexdigest()


def ebook_operation_recipe_plan_id(content_hash: str) -> EntityId:
    return EntityId(
        uuid5(EBOOK_OPERATION_RECIPE_PLAN_NAMESPACE, _require_sha256(content_hash))
    )


__all__ = [
    "canonical_ebook_operation_recipe_candidate_payload",
    "canonical_ebook_operation_recipe_plan_payload",
    "ebook_operation_expected_output_fingerprint",
    "ebook_operation_precondition_fingerprint",
    "ebook_operation_processor_requirement_fingerprint",
    "ebook_operation_recipe_candidate_content_hash",
    "ebook_operation_recipe_candidate_evidence_fingerprint",
    "ebook_operation_recipe_candidate_id",
    "ebook_operation_recipe_plan_content_hash",
    "ebook_operation_recipe_plan_id",
    "ebook_operation_recovery_requirement_fingerprint",
    "ebook_operation_source_evidence_fingerprint",
    "ebook_operation_verification_fingerprint",
    "ebook_operation_workspace_requirement_fingerprint",
    "serialize_ebook_operation_recipe_candidate",
    "serialize_ebook_operation_recipe_plan",
]
