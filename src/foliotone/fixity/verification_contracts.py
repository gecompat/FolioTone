"""Immutable, path-free contracts for the book-only fixity verification slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from foliotone.core._validation import require_aware_datetime
from foliotone.core.ids import EntityId
from foliotone.fixity.contracts import require_private_relative_locator, require_sha256

EBOOK_FIXITY_VERIFICATION_PROFILE = "ebook-fixity-verification/v1"
EBOOK_FIXITY_DECISION_PROFILE = "ebook-fixity-decision/v1"


class EbookFixityVerificationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class EbookFixityVerificationEventKind(StrEnum):
    STARTED = "STARTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class EbookFixityVerificationResult(StrEnum):
    VERIFIED = "VERIFIED"
    UNEXPECTED_BYTE_CHANGE = "UNEXPECTED_BYTE_CHANGE"
    MISSING = "MISSING"
    UNBASELINED = "UNBASELINED"
    UNREADABLE = "UNREADABLE"
    SOURCE_CHANGED_DURING_RUN = "SOURCE_CHANGED_DURING_RUN"


class EbookFixityExpectationAction(StrEnum):
    ACCEPT_CURRENT = "ACCEPT_CURRENT"
    RETIRE_MISSING = "RETIRE_MISSING"


def _id(value: EntityId, name: str) -> EntityId:
    if not isinstance(value, EntityId):
        raise ValueError(f"{name} must be an EntityId")
    return value


def _count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationRun:
    run_id: EntityId
    baseline_activation_id: EntityId
    scan_root_id: EntityId
    source_scan_run_id: EntityId
    expectation_revision_no: int
    expectation_revision_digest: str
    started_at: datetime
    status: EbookFixityVerificationRunStatus
    content_digest: str | None = field(default=None, repr=False)
    completed_at: datetime | None = None
    result_count: int = 0

    def __post_init__(self) -> None:
        for name in ("run_id", "baseline_activation_id", "scan_root_id", "source_scan_run_id"):
            _id(getattr(self, name), name)
        _count(self.expectation_revision_no, "expectation_revision_no")
        require_sha256(self.expectation_revision_digest, "expectation_revision_digest")
        require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not precede started_at")
        terminal = self.status is not EbookFixityVerificationRunStatus.RUNNING
        if terminal != (self.completed_at is not None):
            raise ValueError("only terminal verification runs require completed_at")
        _count(self.result_count, "result_count")
        if self.status is EbookFixityVerificationRunStatus.COMPLETED:
            if self.content_digest is None:
                raise ValueError("completed verification run requires content_digest")
            require_sha256(self.content_digest, "content_digest")
        elif self.content_digest is not None:
            raise ValueError("non-completed verification run cannot have content_digest")


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationEvent:
    run_id: EntityId
    ordinal: int
    kind: EbookFixityVerificationEventKind
    occurred_at: datetime
    failure_code: str | None = None

    def __post_init__(self) -> None:
        _id(self.run_id, "run_id")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a nonnegative integer")
        require_aware_datetime(self.occurred_at, "occurred_at")
        if self.kind is EbookFixityVerificationEventKind.FAILED:
            if (
                not self.failure_code
                or not self.failure_code.isascii()
                or not self.failure_code.replace("_", "").isalnum()
                or not self.failure_code.isupper()
            ):
                raise ValueError("failed verification event requires an uppercase failure code")
        elif self.failure_code is not None:
            raise ValueError("only failed verification events may carry failure_code")


@dataclass(frozen=True, slots=True)
class EbookFixityVerificationResultRecord:
    result_id: EntityId
    run_id: EntityId
    file_id: EntityId
    result: EbookFixityVerificationResult
    expected_observation_id: EntityId | None
    expected_size_bytes: int | None
    expected_sha256: str | None = field(repr=False)
    expected_relative_locator: str | None = field(default=None, repr=False)
    current_observation_id: EntityId | None = None
    current_size_bytes: int | None = None
    current_sha256: str | None = field(default=None, repr=False)
    current_relative_locator: str | None = field(default=None, repr=False)
    failure_code: str | None = None
    content_digest: str = field(default="", repr=False)

    @property
    def result_type(self) -> EbookFixityVerificationResult:
        return self.result

    @property
    def observed_size_bytes(self) -> int | None:
        return self.current_size_bytes

    @property
    def observed_sha256(self) -> str | None:
        return self.current_sha256

    def __post_init__(self) -> None:
        for name in ("result_id", "run_id", "file_id"):
            _id(getattr(self, name), name)
        if self.expected_observation_id is not None:
            _id(self.expected_observation_id, "expected_observation_id")
        if self.current_observation_id is not None:
            _id(self.current_observation_id, "current_observation_id")
        for name in ("expected_size_bytes", "observed_size_bytes"):
            value = getattr(self, name)
            if value is not None:
                _count(value, name)
        for name in ("expected_sha256", "observed_sha256"):
            value = getattr(self, name)
            if value is not None:
                require_sha256(value, name)
        for name in ("expected_relative_locator", "current_relative_locator"):
            value = getattr(self, name)
            if value is not None:
                require_private_relative_locator(value)
        expected_values = (
            self.expected_observation_id,
            self.expected_size_bytes,
            self.expected_sha256,
            self.expected_relative_locator,
        )
        full_expected = all(value is not None for value in expected_values)
        no_expected = all(value is None for value in expected_values)
        full_current = all(
            value is not None
            for value in (
                self.current_observation_id,
                self.current_size_bytes,
                self.current_sha256,
                self.current_relative_locator,
            )
        )
        current_without_hash = (
            self.current_observation_id is not None
            and self.current_size_bytes is not None
            and self.current_sha256 is None
            and self.current_relative_locator is not None
        )
        if not (full_expected or no_expected):
            raise ValueError("expected state must be complete or entirely null")
        if self.result is EbookFixityVerificationResult.MISSING:
            if (
                not full_expected
                or self.current_observation_id is not None
                or self.current_sha256 is not None
                or self.current_size_bytes is not None
                or self.current_relative_locator is not None
                or self.failure_code is not None
            ):
                raise ValueError("MISSING requires expected state and null current state")
        elif self.result is EbookFixityVerificationResult.UNBASELINED:
            if not no_expected or not full_current or self.failure_code is not None:
                raise ValueError("UNBASELINED requires null expected and full current state")
        elif self.result is EbookFixityVerificationResult.VERIFIED:
            if (
                not full_expected
                or not full_current
                or self.failure_code is not None
                or self.expected_sha256 is None
                or self.current_sha256 is None
                or self.expected_sha256 != self.current_sha256
                or self.expected_size_bytes != self.current_size_bytes
            ):
                raise ValueError("VERIFIED requires an identical expected and observed state")
        elif self.result is EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE:
            if (
                not full_expected
                or not full_current
                or self.failure_code is not None
                or self.expected_sha256 is None
                or self.current_sha256 is None
                or (
                    self.expected_sha256 == self.current_sha256
                    and self.expected_size_bytes == self.current_size_bytes
                )
            ):
                raise ValueError("UNEXPECTED_BYTE_CHANGE requires a changed observed state")
        elif self.result in {
            EbookFixityVerificationResult.UNREADABLE,
            EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN,
        }:
            if not (full_expected or no_expected) or not current_without_hash:
                raise ValueError("unsafe verification result requires current state without hash")
            expected_code = (
                "SOURCE_UNREADABLE"
                if self.result is EbookFixityVerificationResult.UNREADABLE
                else "SOURCE_CHANGED"
            )
            if self.failure_code != expected_code:
                raise ValueError(f"unsafe verification result requires {expected_code}")
        from foliotone.fixity.verification_fingerprints import verification_result_fingerprint

        expected_digest = verification_result_fingerprint(self)
        if not self.content_digest:
            object.__setattr__(self, "content_digest", expected_digest)
        elif self.content_digest != expected_digest:
            raise ValueError("result_digest does not match canonical result data")
        require_sha256(self.content_digest, "content_digest")


@dataclass(frozen=True, slots=True)
class EbookFixityExpectationDecisionInput:
    result_id: EntityId
    run_id: EntityId
    file_id: EntityId
    action: EbookFixityExpectationAction
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    review_decision_id: EntityId
    decision_compatibility_version: str = EBOOK_FIXITY_DECISION_PROFILE
    expectation_revision_id: EntityId = field(default_factory=EntityId.new)

    def __post_init__(self) -> None:
        for name in ("result_id", "run_id", "file_id"):
            _id(getattr(self, name), name)
        _id(self.expectation_revision_id, "expectation_revision_id")
        _id(self.review_decision_id, "review_decision_id")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        require_sha256(self.candidate_set_fingerprint, "candidate_set_fingerprint")
        if self.decision_compatibility_version != EBOOK_FIXITY_DECISION_PROFILE:
            raise ValueError("fixity decision compatibility version is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityExpectationRevision:
    id: EntityId
    file_id: EntityId
    source_result_id: EntityId
    action: EbookFixityExpectationAction
    result: EbookFixityVerificationResultRecord
    scan_root_id: EntityId
    baseline_activation_id: EntityId
    revision_no: int
    previous_revision_digest: str
    revision_digest: str
    review_decision_id: EntityId
    created_at: datetime
    evidence_fingerprint: str
    candidate_set_fingerprint: str
    expected_observation_id: EntityId | None = field(repr=False)
    expected_size_bytes: int | None = field(repr=False)
    expected_sha256: str | None = field(default=None, repr=False)
    expected_relative_locator: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name in (
            "id",
            "file_id",
            "source_result_id",
            "scan_root_id",
            "baseline_activation_id",
            "review_decision_id",
        ):
            _id(getattr(self, name), name)
        if self.file_id != self.result.file_id or self.source_result_id != self.result.result_id:
            raise ValueError("expectation revision is not bound to its result")
        if (
            isinstance(self.revision_no, bool)
            or not isinstance(self.revision_no, int)
            or self.revision_no < 1
        ):
            raise ValueError("revision_no must be positive")
        require_sha256(self.previous_revision_digest, "previous_revision_digest")
        for name in (
            "revision_digest",
            "evidence_fingerprint",
            "candidate_set_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        require_aware_datetime(self.created_at, "created_at")
        if self.result.expected_relative_locator is not None:
            require_private_relative_locator(self.result.expected_relative_locator)
        if self.action is EbookFixityExpectationAction.ACCEPT_CURRENT:
            if self.result.result not in {
                EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
                EbookFixityVerificationResult.UNBASELINED,
            }:
                raise ValueError("ACCEPT_CURRENT requires a changed or unbaselined result")
            if (
                self.expected_observation_id != self.result.current_observation_id
                or self.expected_size_bytes != self.result.current_size_bytes
                or self.expected_sha256 != self.result.current_sha256
                or self.expected_relative_locator != self.result.current_relative_locator
            ):
                raise ValueError("ACCEPT_CURRENT expected state must equal current result state")
        elif self.result.result is not EbookFixityVerificationResult.MISSING:
            raise ValueError("RETIRE_MISSING requires a missing result")
        elif any(
            value is not None
            for value in (
                self.expected_observation_id,
                self.expected_size_bytes,
                self.expected_sha256,
                self.expected_relative_locator,
            )
        ):
            raise ValueError("RETIRE_MISSING expected state must be null")
        if self.expected_relative_locator is not None:
            require_private_relative_locator(self.expected_relative_locator)
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        require_sha256(self.candidate_set_fingerprint, "candidate_set_fingerprint")


# Descriptive aliases used by adapters while retaining the compact v1 names.
EbookFixityVerificationResultKind = EbookFixityVerificationResult
EbookFixityVerificationResultType = EbookFixityVerificationResult
EbookFixityVerificationFinding = EbookFixityVerificationResultRecord
EbookFixityVerificationRunEvent = EbookFixityVerificationEvent
