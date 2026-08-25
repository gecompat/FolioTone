from datetime import UTC, datetime

import pytest

from foliotone.core import (
    EntityId,
    EntityKind,
    ReviewCandidateKind,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.fixity.verification_contracts import (
    EBOOK_FIXITY_DECISION_PROFILE,
    EbookFixityExpectationAction,
    EbookFixityExpectationDecisionInput,
    EbookFixityExpectationRevision,
    EbookFixityVerificationResult,
    EbookFixityVerificationResultRecord,
    EbookFixityVerificationRun,
    EbookFixityVerificationRunStatus,
)
from foliotone.fixity.verification_fingerprints import (
    verification_candidate_set_fingerprint,
    verification_evidence_fingerprint,
    verification_result_fingerprint,
    verification_result_payload,
    verification_results_digest,
    verification_run_content_digest,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
_RESULT = EbookFixityVerificationResult
_ACTION = EbookFixityExpectationAction


def _result(
    kind: EbookFixityVerificationResult = EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
):
    return EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=EntityId.new(),
        file_id=EntityId.new(),
        result=kind,
        expected_observation_id=EntityId.new(),
        expected_size_bytes=10,
        expected_sha256=DIGEST_A,
        current_observation_id=None
        if kind is EbookFixityVerificationResult.MISSING
        else EntityId.new(),
        current_size_bytes=None if kind is EbookFixityVerificationResult.MISSING else 11,
        current_sha256=None if kind is EbookFixityVerificationResult.MISSING else DIGEST_B,
        expected_relative_locator="book.epub",
        current_relative_locator=(
            None if kind is EbookFixityVerificationResult.MISSING else "book.epub"
        ),
    )


def test_result_fingerprint_is_canonical_and_nulls_are_preserved() -> None:
    result = _result()
    assert verification_result_fingerprint(result) == result.content_digest
    assert verification_result_payload(result)["expected"]["observation_id"] is not None
    missing = _result(EbookFixityVerificationResult.MISSING)
    assert verification_result_payload(missing)["current"]["sha256"] is None
    assert verification_candidate_set_fingerprint(result) == verification_candidate_set_fingerprint(
        result
    )
    common = dict(
        subject_id=result.file_id,
        scan_root_id=EntityId.new(),
        expectation_revision_no=0,
        expectation_revision_digest=DIGEST_A,
        scan_run_id=EntityId.new(),
        verification_run_id=result.run_id,
        verification_run_content_digest=DIGEST_A,
        result_id=result.result_id,
        result_content_digest=result.content_digest,
    )
    assert verification_evidence_fingerprint(
        baseline_activation_id=EntityId.new(), **common
    ) != verification_evidence_fingerprint(baseline_activation_id=EntityId.new(), **common)
    with pytest.raises(ValueError, match="nonnegative"):
        verification_evidence_fingerprint(
            baseline_activation_id=EntityId.new(),
            **(common | {"expectation_revision_no": -1}),
        )


def test_result_legality_and_run_completion_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="VERIFIED"):
        _result(EbookFixityVerificationResult.VERIFIED)
    with pytest.raises(ValueError, match="completed_at"):
        EbookFixityVerificationRun(
            run_id=EntityId.new(),
            baseline_activation_id=EntityId.new(),
            scan_root_id=EntityId.new(),
            source_scan_run_id=EntityId.new(),
            started_at=NOW,
            status=EbookFixityVerificationRunStatus.COMPLETED,
            expectation_revision_no=1,
            expectation_revision_digest=DIGEST_A,
            content_digest=None,
        )
    with pytest.raises(ValueError, match="VERIFIED"):
        verified = _result(EbookFixityVerificationResult.VERIFIED)
        EbookFixityExpectationRevision(
            id=EntityId.new(),
            file_id=verified.file_id,
            source_result_id=verified.result_id,
            action=EbookFixityExpectationAction.ACCEPT_CURRENT,
            result=verified,
            scan_root_id=EntityId.new(),
            baseline_activation_id=EntityId.new(),
            revision_no=1,
            previous_revision_digest=DIGEST_A,
            revision_digest=DIGEST_A,
            review_decision_id=EntityId.new(),
            created_at=NOW,
            evidence_fingerprint=DIGEST_A,
            candidate_set_fingerprint=DIGEST_B,
            expected_observation_id=None,
            expected_size_bytes=None,
        )


def test_fixity_review_pair_is_file_only_and_input_is_stable() -> None:
    result = _result()
    item = ReviewItem(
        id=EntityId.new(),
        review_type=ReviewType.FIXITY_EXPECTATION,
        subject_kind=EntityKind.FILE,
        subject_id=result.file_id,
        candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
        candidate_id=result.result_id,
        producer_name="fixity",
        producer_version="1",
        decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        state=ReviewItemState.PENDING,
        created_at=NOW,
    )
    assert item.review_type is ReviewType.FIXITY_EXPECTATION
    with pytest.raises(ValueError, match="FILE subject"):
        ReviewItem(
            id=EntityId.new(),
            review_type=ReviewType.FIXITY_EXPECTATION,
            subject_kind=EntityKind.FILE_OBSERVATION,
            subject_id=result.file_id,
            candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
            candidate_id=result.result_id,
            producer_name="fixity",
            producer_version="1",
            decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
            evidence_fingerprint=DIGEST_A,
            candidate_set_fingerprint=DIGEST_B,
            state=ReviewItemState.PENDING,
            created_at=NOW,
        )
    assert (
        EbookFixityExpectationDecisionInput(
            result_id=result.result_id,
            run_id=result.run_id,
            file_id=result.file_id,
            action=EbookFixityExpectationAction.ACCEPT_CURRENT,
            evidence_fingerprint=DIGEST_A,
            candidate_set_fingerprint=DIGEST_B,
            review_decision_id=EntityId.new(),
        ).decision_compatibility_version
        == EBOOK_FIXITY_DECISION_PROFILE
    )


@pytest.mark.parametrize(
    ("kind", "failure_code"),
    (
        (EbookFixityVerificationResult.UNREADABLE, "SOURCE_UNREADABLE"),
        (EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN, "SOURCE_CHANGED"),
    ),
)
def test_unsafe_result_shapes_require_exact_failure_codes(
    kind: EbookFixityVerificationResult,
    failure_code: str,
) -> None:
    common = dict(
        result_id=EntityId.new(),
        run_id=EntityId.new(),
        file_id=EntityId.new(),
        result=kind,
        expected_observation_id=EntityId.new(),
        expected_size_bytes=10,
        expected_sha256=DIGEST_A,
        expected_relative_locator="book.epub",
        current_observation_id=EntityId.new(),
        current_size_bytes=11,
        current_sha256=None,
        current_relative_locator="book.epub",
    )
    result = EbookFixityVerificationResultRecord(failure_code=failure_code, **common)
    assert result.failure_code == failure_code
    with pytest.raises(ValueError, match=failure_code):
        EbookFixityVerificationResultRecord(failure_code="WRONG_CODE", **common)


def test_streaming_result_and_completed_run_digests_are_ordered_and_validated() -> None:
    first = _result()
    second = _result()
    count, ordered = verification_results_digest(result for result in (first, second))
    assert count == 2
    assert ordered != verification_results_digest(result for result in (second, first))[1]
    completed_at = NOW.replace(minute=1)
    digest = verification_run_content_digest(
        run_id=first.run_id,
        baseline_activation_id=EntityId.new(),
        scan_root_id=EntityId.new(),
        source_scan_run_id=EntityId.new(),
        expectation_revision_no=0,
        expectation_revision_digest=DIGEST_A,
        result_count=count,
        results_digest=ordered,
        started_at=NOW,
        completed_at=completed_at,
    )
    assert len(digest) == 64
    with pytest.raises(ValueError, match="completed_at"):
        verification_run_content_digest(
            run_id=first.run_id,
            baseline_activation_id=EntityId.new(),
            scan_root_id=EntityId.new(),
            source_scan_run_id=EntityId.new(),
            expectation_revision_no=0,
            expectation_revision_digest=DIGEST_A,
            result_count=count,
            results_digest=ordered,
            started_at=NOW,
            completed_at=NOW.replace(hour=11),
        )


def test_expectation_revisions_bind_accept_current_and_retire_missing() -> None:
    changed = _result()
    accepted = EbookFixityExpectationRevision(
        id=EntityId.new(),
        file_id=changed.file_id,
        source_result_id=changed.result_id,
        action=EbookFixityExpectationAction.ACCEPT_CURRENT,
        result=changed,
        scan_root_id=EntityId.new(),
        baseline_activation_id=EntityId.new(),
        revision_no=1,
        previous_revision_digest=DIGEST_A,
        revision_digest=DIGEST_B,
        review_decision_id=EntityId.new(),
        created_at=NOW,
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        expected_observation_id=changed.current_observation_id,
        expected_size_bytes=changed.current_size_bytes,
        expected_sha256=changed.current_sha256,
        expected_relative_locator=changed.current_relative_locator,
    )
    assert accepted.expected_sha256 == changed.current_sha256

    missing = _result(EbookFixityVerificationResult.MISSING)
    retired = EbookFixityExpectationRevision(
        id=EntityId.new(),
        file_id=missing.file_id,
        source_result_id=missing.result_id,
        action=EbookFixityExpectationAction.RETIRE_MISSING,
        result=missing,
        scan_root_id=EntityId.new(),
        baseline_activation_id=EntityId.new(),
        revision_no=2,
        previous_revision_digest=DIGEST_B,
        revision_digest=DIGEST_A,
        review_decision_id=EntityId.new(),
        created_at=NOW,
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        expected_observation_id=None,
        expected_size_bytes=None,
    )
    assert retired.expected_observation_id is None


@pytest.mark.parametrize(
    ("kind", "action", "allowed"),
    [
        (_RESULT.UNEXPECTED_BYTE_CHANGE, _ACTION.ACCEPT_CURRENT, True),
        (_RESULT.UNBASELINED, _ACTION.ACCEPT_CURRENT, True),
        (_RESULT.MISSING, _ACTION.RETIRE_MISSING, True),
        (_RESULT.UNEXPECTED_BYTE_CHANGE, _ACTION.RETIRE_MISSING, False),
        (_RESULT.UNBASELINED, _ACTION.RETIRE_MISSING, False),
        (_RESULT.MISSING, _ACTION.ACCEPT_CURRENT, False),
        (_RESULT.VERIFIED, _ACTION.ACCEPT_CURRENT, False),
        (_RESULT.VERIFIED, _ACTION.RETIRE_MISSING, False),
        (_RESULT.UNREADABLE, _ACTION.ACCEPT_CURRENT, False),
        (_RESULT.UNREADABLE, _ACTION.RETIRE_MISSING, False),
        (_RESULT.SOURCE_CHANGED_DURING_RUN, _ACTION.ACCEPT_CURRENT, False),
        (_RESULT.SOURCE_CHANGED_DURING_RUN, _ACTION.RETIRE_MISSING, False),
    ],
)
def test_expectation_action_matrix_is_closed(
    kind: EbookFixityVerificationResult,
    action: EbookFixityExpectationAction,
    allowed: bool,
) -> None:
    no_expected = kind is EbookFixityVerificationResult.UNBASELINED
    no_current = kind is EbookFixityVerificationResult.MISSING
    unsafe = kind in {
        EbookFixityVerificationResult.UNREADABLE,
        EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN,
    }
    expected_observation_id = None if no_expected else EntityId.new()
    current_observation_id = None if no_current else EntityId.new()
    expected_size = None if no_expected else 10
    current_size = (
        None
        if no_current
        else 10
        if kind is EbookFixityVerificationResult.VERIFIED
        else 11
    )
    expected_sha = None if no_expected else DIGEST_A
    current_sha = (
        None
        if no_current or unsafe
        else DIGEST_A
        if kind is EbookFixityVerificationResult.VERIFIED
        else DIGEST_B
    )
    result = EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=EntityId.new(),
        file_id=EntityId.new(),
        result=kind,
        expected_observation_id=expected_observation_id,
        expected_size_bytes=expected_size,
        expected_sha256=expected_sha,
        expected_relative_locator=None if no_expected else "book.epub",
        current_observation_id=current_observation_id,
        current_size_bytes=current_size,
        current_sha256=current_sha,
        current_relative_locator=None if no_current else "book.epub",
        failure_code=(
            "SOURCE_UNREADABLE"
            if kind is EbookFixityVerificationResult.UNREADABLE
            else "SOURCE_CHANGED"
            if kind is EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN
            else None
        ),
    )
    expected_values = (
        (
            result.current_observation_id,
            result.current_size_bytes,
            result.current_sha256,
            result.current_relative_locator,
        )
        if action is EbookFixityExpectationAction.ACCEPT_CURRENT
        else (None, None, None, None)
    )
    arguments = dict(
        id=EntityId.new(),
        file_id=result.file_id,
        source_result_id=result.result_id,
        action=action,
        result=result,
        scan_root_id=EntityId.new(),
        baseline_activation_id=EntityId.new(),
        revision_no=1,
        previous_revision_digest=DIGEST_A,
        revision_digest=DIGEST_B,
        review_decision_id=EntityId.new(),
        created_at=NOW,
        evidence_fingerprint=DIGEST_A,
        candidate_set_fingerprint=DIGEST_B,
        expected_observation_id=expected_values[0],
        expected_size_bytes=expected_values[1],
        expected_sha256=expected_values[2],
        expected_relative_locator=expected_values[3],
    )
    if allowed:
        EbookFixityExpectationRevision(**arguments)
    else:
        with pytest.raises(ValueError):
            EbookFixityExpectationRevision(**arguments)
