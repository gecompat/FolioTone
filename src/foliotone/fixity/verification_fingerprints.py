"""Canonical, path-free SHA-256 material for fixity review reuse."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime

from foliotone.core.ids import EntityId
from foliotone.fixity.contracts import canonical_json_bytes, require_sha256
from foliotone.fixity.verification_contracts import (
    EbookFixityVerificationResultRecord,
)


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def verification_result_payload(result: EbookFixityVerificationResultRecord) -> dict[str, object]:
    """Return mandatory result material, preserving JSON null for absent bytes."""
    return {
        "profile": "ebook-fixity-result/v1",
        "result_type": result.result.value,
        "file_id": str(result.file_id),
        "expected": {
            "observation_id": None
            if result.expected_observation_id is None
            else str(result.expected_observation_id),
            "size_bytes": result.expected_size_bytes,
            "sha256": result.expected_sha256,
            "relative_locator": result.expected_relative_locator,
        },
        "current": {
            "observation_id": None
            if result.current_observation_id is None
            else str(result.current_observation_id),
            "size_bytes": result.current_size_bytes,
            "sha256": result.current_sha256,
            "relative_locator": result.current_relative_locator,
        },
        "failure_code": result.failure_code,
    }


def verification_result_fingerprint(result: EbookFixityVerificationResultRecord) -> str:
    return _digest(verification_result_payload(result))


def verification_evidence_fingerprint(
    *,
    subject_id: object,
    scan_root_id: object,
    baseline_activation_id: object,
    expectation_revision_no: int,
    expectation_revision_digest: str,
    scan_run_id: object,
    verification_run_id: object,
    verification_run_content_digest: str,
    result_id: object,
    result_content_digest: str,
    review_type: str = "FIXITY_EXPECTATION",
    decision_compatibility_version: str = "ebook-fixity-decision/v1",
) -> str:
    for name, value in {
        "subject_id": subject_id,
        "scan_root_id": scan_root_id,
        "baseline_activation_id": baseline_activation_id,
        "scan_run_id": scan_run_id,
        "verification_run_id": verification_run_id,
        "result_id": result_id,
    }.items():
        if not isinstance(value, EntityId):
            raise ValueError(f"{name} must be an EntityId")
    if (
        isinstance(expectation_revision_no, bool)
        or not isinstance(expectation_revision_no, int)
        or expectation_revision_no < 0
    ):
        raise ValueError("expectation_revision_no must be nonnegative")
    for name, value in {
        "expectation_revision_digest": expectation_revision_digest,
        "verification_run_content_digest": verification_run_content_digest,
        "result_content_digest": result_content_digest,
    }.items():
        require_sha256(value, name)
    if (
        review_type != "FIXITY_EXPECTATION"
        or decision_compatibility_version != "ebook-fixity-decision/v1"
    ):
        raise ValueError("fixity fingerprint profile is invalid")
    payload = {
        "profile": "ebook-fixity-evidence-fingerprint/v1",
        "review_type": review_type,
        "subject_kind": "FILE",
        "subject_id": str(subject_id),
        "scan_root_id": str(scan_root_id),
        "baseline_activation_id": str(baseline_activation_id),
        "expectation_revision_no": expectation_revision_no,
        "expectation_revision_digest": expectation_revision_digest,
        "scan_run_id": str(scan_run_id),
        "verification_run_id": str(verification_run_id),
        "verification_run_content_digest": verification_run_content_digest,
        "result_id": str(result_id),
        "result_content_digest": result_content_digest,
        "decision_compatibility_version": decision_compatibility_version,
    }
    return _digest(payload)


def verification_candidate_set_fingerprint(result: EbookFixityVerificationResultRecord) -> str:
    """Fingerprint the one-result candidate set (never an empty set)."""
    return _digest(
        {
            "profile": "ebook-fixity-candidate-set-fingerprint/v1",
            "candidate_kind": "FIXITY_RESULT",
            "candidates": [
                {"result_id": str(result.result_id), "result_content_digest": result.content_digest}
            ],
            "decision_compatibility_version": "ebook-fixity-decision/v1",
        }
    )


def verification_results_digest(
    results: Iterable[EbookFixityVerificationResultRecord],
) -> tuple[int, str]:
    """Digest an ordered streaming result sequence and return count plus digest."""
    digest = hashlib.sha256(b"foliotone:ebook-fixity-verification-results/v1\x00")
    count = 0
    for result in results:
        value = verification_result_fingerprint(result).encode("ascii")
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
        count += 1
    return count, digest.hexdigest()


def verification_run_content_digest(
    *,
    run_id: EntityId,
    baseline_activation_id: EntityId,
    scan_root_id: EntityId,
    source_scan_run_id: EntityId,
    expectation_revision_no: int,
    expectation_revision_digest: str,
    result_count: int,
    results_digest: str,
    started_at: datetime,
    completed_at: datetime,
) -> str:
    return _digest(
        verification_run_content_payload(
            run_id=run_id,
            baseline_activation_id=baseline_activation_id,
            scan_root_id=scan_root_id,
            source_scan_run_id=source_scan_run_id,
            expectation_revision_no=expectation_revision_no,
            expectation_revision_digest=expectation_revision_digest,
            result_count=result_count,
            results_digest=results_digest,
            started_at=started_at,
            completed_at=completed_at,
        )
    )


def verification_run_content_payload(
    *,
    run_id: EntityId,
    baseline_activation_id: EntityId,
    scan_root_id: EntityId,
    source_scan_run_id: EntityId,
    expectation_revision_no: int,
    expectation_revision_digest: str,
    result_count: int,
    results_digest: str,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, object]:
    """Canonical immutable run material; status is deliberately excluded."""
    for name, value in {
        "run_id": run_id,
        "baseline_activation_id": baseline_activation_id,
        "scan_root_id": scan_root_id,
        "source_scan_run_id": source_scan_run_id,
    }.items():
        if not isinstance(value, EntityId):
            raise ValueError(f"{name} must be an EntityId")
    if (
        isinstance(expectation_revision_no, bool)
        or not isinstance(expectation_revision_no, int)
        or expectation_revision_no < 0
    ):
        raise ValueError("expectation_revision_no must be nonnegative")
    if isinstance(result_count, bool) or not isinstance(result_count, int) or result_count < 0:
        raise ValueError("result_count must be nonnegative")
    require_sha256(expectation_revision_digest, "expectation_revision_digest")
    require_sha256(results_digest, "results_digest")
    from foliotone.core._validation import require_aware_datetime

    require_aware_datetime(started_at, "started_at")
    require_aware_datetime(completed_at, "completed_at")
    if completed_at < started_at:
        raise ValueError("completed_at must not precede started_at")
    started_encoded = started_at.astimezone(UTC).isoformat()
    completed_encoded = completed_at.astimezone(UTC).isoformat()
    return {
        "profile": "ebook-fixity-verification/v1",
        "run_id": str(run_id),
        "baseline_activation_id": str(baseline_activation_id),
        "scan_root_id": str(scan_root_id),
        "source_scan_run_id": str(source_scan_run_id),
        "expectation_revision_no": expectation_revision_no,
        "expectation_revision_digest": expectation_revision_digest,
        "result_count": result_count,
        "results_digest": results_digest,
        "started_at": started_encoded,
        "completed_at": completed_encoded,
    }


__all__ = [
    "verification_candidate_set_fingerprint",
    "verification_evidence_fingerprint",
    "verification_result_fingerprint",
    "verification_result_payload",
    "verification_results_digest",
    "verification_run_content_digest",
    "verification_run_content_payload",
]
