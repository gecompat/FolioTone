"""Application service for the bounded ADR-0056 quarantine operator."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import NoReturn, Protocol

from sqlalchemy import Engine

from foliotone.consolidation.contracts import (
    ConsolidationFileRole,
    ConsolidationPlan,
)
from foliotone.core import EntityId
from foliotone.persistence.consolidation import (
    ConsolidationStoreError,
    SQLiteConsolidationStore,
)
from foliotone.persistence.quarantine import (
    QuarantineAuthorizationConsumedError,
    QuarantineAuthorizationSourceSnapshot,
    QuarantineExecutionRun,
    QuarantineStoreError,
    SQLiteQuarantineStore,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteLeaseError,
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)
from foliotone.quarantine import (
    MAX_QUARANTINE_AUTHORIZATION_LIFETIME,
    QuarantineAuthorizationBlockerCode,
    QuarantineAuthorizationSnapshot,
    QuarantineEligibilityStatus,
    QuarantineRunStatus,
    build_quarantine_authorization,
)
from foliotone.quarantine.capabilities import (
    QuarantineCapabilityResolver,
    QuarantineCapabilityUnavailable,
    ResolvedQuarantineCapability,
)
from foliotone.quarantine.confirmation import (
    QuarantineConfirmationError,
    quarantine_confirmation_digest,
    quarantine_confirmation_text,
)
from foliotone.quarantine.executor import (
    InterimQuarantineError,
    InterimQuarantineExecutionResult,
    InterimQuarantinePaths,
    execute_interim_quarantine,
)
from foliotone.quarantine.source_validation import (
    InterimQuarantineSourceVerifier,
    QuarantineSourceValidationError,
    QuarantineSourceValidationErrorCode,
)

QUARANTINE_OPERATOR_PROFILE = "quarantine-operator/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LEASE_DURATION = timedelta(minutes=30)
_TARGET_DOMAIN = b"foliotone:quarantine-target/v1\x00"


class QuarantineOperatorErrorCode(StrEnum):
    PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    AUTHORIZATION_BLOCKED = "AUTHORIZATION_BLOCKED"
    AUTHORIZATION_UNAVAILABLE = "AUTHORIZATION_UNAVAILABLE"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_CONSUMED = "AUTHORIZATION_CONSUMED"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    STALE = "STALE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FENCED_OUT = "FENCED_OUT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class QuarantineOperatorError(RuntimeError):
    """One fixed path-, hash-, and filename-free operator failure."""

    def __init__(
        self,
        code: QuarantineOperatorErrorCode,
        blockers: tuple[QuarantineAuthorizationBlockerCode, ...] = (),
        *,
        run_id: EntityId | None = None,
    ) -> None:
        self.code = code
        self.blockers = blockers
        self.run_id = run_id
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class QuarantineAuthorizationResult:
    authorization_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    authorized_at: datetime
    expires_at: datetime
    status: str = "AUTHORIZED"
    profile: str = QUARANTINE_OPERATOR_PROFILE


@dataclass(frozen=True, slots=True)
class QuarantineOperationResult:
    authorization_id: EntityId
    run_id: EntityId
    plan_id: EntityId
    scan_root_id: EntityId
    status: QuarantineRunStatus
    profile: str = QUARANTINE_OPERATOR_PROFILE


class QuarantineCapabilityLookup(Protocol):
    def resolve(self, quarantine_capability_id: EntityId) -> ResolvedQuarantineCapability: ...


class QuarantineSourceVerifier(Protocol):
    def verify(
        self,
        *,
        capability: ResolvedQuarantineCapability,
        source: QuarantineAuthorizationSourceSnapshot,
    ) -> None: ...


QuarantineExecutor = Callable[..., InterimQuarantineExecutionResult]


class QuarantineOperatorService:
    """Authorize or execute one exact current ADR-0056 candidate."""

    def __init__(
        self,
        engine: Engine,
        *,
        capability_resolver: QuarantineCapabilityLookup | None = None,
        source_verifier: QuarantineSourceVerifier | None = None,
        executor: QuarantineExecutor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = SQLiteConsolidationStore(engine)
        self._quarantine = SQLiteQuarantineStore(engine)
        self._leases = SQLiteScanRootWriteLeaseStore(engine)
        self._capabilities = capability_resolver or QuarantineCapabilityResolver()
        self._source_verifier = source_verifier or InterimQuarantineSourceVerifier()
        self._executor = executor or execute_interim_quarantine
        self._clock = clock or _system_clock

    def authorize(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
    ) -> QuarantineAuthorizationResult:
        plan = self._plan(plan_id, plan_content_hash)
        capability = self._capability(capability_id, plan)
        precheck_at = _now(self._clock).replace(microsecond=0)
        self._authorization(plan, capability_id, precheck_at)
        try:
            sources = self._quarantine.require_authorization_sources(plan)
            for source in sources:
                self._source_verifier.verify(capability=capability, source=source)
            authorized_at = _now(self._clock).replace(microsecond=0)
            authorization = self._authorization(plan, capability_id, authorized_at)
            persisted = self._quarantine.create_or_get_authorization(
                authorization,
                plan,
                persisted_at=_now(self._clock),
            )
        except QuarantineOperatorError:
            raise
        except QuarantineCapabilityUnavailable:
            _operator_fail(QuarantineOperatorErrorCode.TOOL_UNAVAILABLE)
        except QuarantineSourceValidationError as error:
            _operator_fail(_source_error_code(error))
        except (ConsolidationStoreError, QuarantineStoreError):
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        except (TypeError, ValueError):
            _operator_fail(QuarantineOperatorErrorCode.INTERNAL_ERROR)
        return QuarantineAuthorizationResult(
            authorization_id=persisted.id,
            plan_id=persisted.plan_id,
            scan_root_id=persisted.scan_root_id,
            authorized_at=persisted.authorized_at,
            expires_at=persisted.expires_at,
        )

    def confirmation_prompt(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
    ) -> str:
        """Return the sole prompt after current opaque binder revalidation."""

        plan, authorization, _capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
            checked_at=_now(self._clock),
        )
        self._current_sources(plan, authorization)
        return quarantine_confirmation_text(authorization)

    def execute(
        self,
        *,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
        confirmation_text: str,
    ) -> QuarantineOperationResult:
        confirmed_at = _now(self._clock).replace(microsecond=0)
        plan, authorization, capability = self._bound_material(
            plan_id,
            plan_content_hash,
            capability_id,
            authorization_id,
            checked_at=confirmed_at,
        )
        try:
            confirmation_digest = quarantine_confirmation_digest(
                authorization,
                confirmation_text,
                confirmed_at=confirmed_at,
            )
        except QuarantineConfirmationError:
            _operator_fail(QuarantineOperatorErrorCode.CONFIRMATION_INVALID)
        try:
            consumed = self._quarantine.get_run_for_authorization(authorization.id)
        except QuarantineStoreError:
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        if consumed is not None:
            _operator_fail(
                QuarantineOperatorErrorCode.AUTHORIZATION_CONSUMED,
                run_id=consumed.id,
            )

        run_id = EntityId.new()
        lease = self._acquire_run_lease(run_id, authorization.scan_root_id)
        run = _execution_run(authorization, run_id, confirmed_at)
        executor_started = False
        try:
            plan, authorization, capability = self._bound_material(
                plan_id,
                plan_content_hash,
                capability_id,
                authorization_id,
                checked_at=_now(self._clock),
            )
            sources = self._current_sources(plan, authorization)
            for source in sources:
                self._source_verifier.verify(capability=capability, source=source)
            candidate = next(
                source
                for source in sources
                if source.role is ConsolidationFileRole.CANDIDATE
            )
            persisted_at = _now(self._clock)
            if persisted_at >= authorization.expires_at:
                _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_EXPIRED)
            executor_started = True
            execution = self._executor(
                store=self._quarantine,
                authorization=authorization,
                run=run,
                lease=lease,
                paths=_execution_paths(capability, candidate),
                occurred_at=confirmed_at,
                plan=plan,
                confirmation_digest=confirmation_digest,
                persisted_at=persisted_at,
            )
        except QuarantineOperatorError:
            raise
        except QuarantineAuthorizationConsumedError:
            _operator_fail(
                QuarantineOperatorErrorCode.AUTHORIZATION_CONSUMED,
                run_id=self._consuming_run_id(authorization.id),
            )
        except QuarantineCapabilityUnavailable:
            _operator_fail(QuarantineOperatorErrorCode.TOOL_UNAVAILABLE)
        except QuarantineSourceValidationError as error:
            _operator_fail(_source_error_code(error))
        except InterimQuarantineError:
            status = self._latest_run_status(run.id)
            _operator_fail(
                QuarantineOperatorErrorCode.VALIDATION_FAILED
                if status is QuarantineRunStatus.VALIDATION_FAILED
                else QuarantineOperatorErrorCode.MANUAL_REVIEW,
                run_id=run.id,
            )
        except ScanRootWriteLeaseError:
            _operator_fail(QuarantineOperatorErrorCode.FENCED_OUT, run_id=run.id)
        except ConsolidationStoreError:
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        except QuarantineStoreError:
            _operator_fail(
                QuarantineOperatorErrorCode.MANUAL_REVIEW
                if executor_started
                else QuarantineOperatorErrorCode.STALE,
                run_id=run.id if executor_started else None,
            )
        except (StopIteration, TypeError, ValueError):
            _operator_fail(
                QuarantineOperatorErrorCode.MANUAL_REVIEW
                if executor_started
                else QuarantineOperatorErrorCode.INTERNAL_ERROR,
                run_id=run.id if executor_started else None,
            )
        except Exception:
            _operator_fail(
                QuarantineOperatorErrorCode.MANUAL_REVIEW
                if executor_started
                else QuarantineOperatorErrorCode.INTERNAL_ERROR,
                run_id=run.id if executor_started else None,
            )
        finally:
            self._release_lease(lease)
        return QuarantineOperationResult(
            authorization_id=authorization.id,
            run_id=execution.run_id,
            plan_id=authorization.plan_id,
            scan_root_id=authorization.scan_root_id,
            status=execution.status,
        )

    def _plan(self, plan_id: EntityId, plan_content_hash: str) -> ConsolidationPlan:
        if (
            not isinstance(plan_id, EntityId)
            or not isinstance(plan_content_hash, str)
            or _SHA256.fullmatch(plan_content_hash) is None
        ):
            _operator_fail(QuarantineOperatorErrorCode.PLAN_MISMATCH)
        try:
            plan = self._plans.get_plan(plan_id)
        except (ConsolidationStoreError, TypeError, ValueError):
            _operator_fail(QuarantineOperatorErrorCode.PLAN_UNAVAILABLE)
        if plan is None:
            _operator_fail(QuarantineOperatorErrorCode.PLAN_UNAVAILABLE)
        if plan.content_hash != plan_content_hash:
            _operator_fail(QuarantineOperatorErrorCode.PLAN_MISMATCH)
        return plan

    def _capability(
        self,
        capability_id: EntityId,
        plan: ConsolidationPlan,
    ) -> ResolvedQuarantineCapability:
        if not isinstance(capability_id, EntityId):
            _operator_fail(QuarantineOperatorErrorCode.CAPABILITY_MISMATCH)
        try:
            capability = self._capabilities.resolve(capability_id)
        except QuarantineCapabilityUnavailable:
            _operator_fail(QuarantineOperatorErrorCode.TOOL_UNAVAILABLE)
        if (
            capability.quarantine_capability_id != capability_id
            or capability.scan_root_id != plan.scan_root_id
        ):
            _operator_fail(QuarantineOperatorErrorCode.CAPABILITY_MISMATCH)
        return capability

    def _bound_material(
        self,
        plan_id: EntityId,
        plan_content_hash: str,
        capability_id: EntityId,
        authorization_id: EntityId,
        *,
        checked_at: datetime,
    ) -> tuple[
        ConsolidationPlan,
        QuarantineAuthorizationSnapshot,
        ResolvedQuarantineCapability,
    ]:
        plan = self._plan(plan_id, plan_content_hash)
        try:
            authorization = self._quarantine.get_authorization(authorization_id)
        except (QuarantineStoreError, TypeError, ValueError):
            _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_UNAVAILABLE)
        if authorization is None:
            _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_UNAVAILABLE)
        capability = self._capability(capability_id, plan)
        if (
            authorization.id != authorization_id
            or authorization.plan_id != plan.id
            or authorization.plan_content_hash != plan.content_hash
            or authorization.quarantine_capability_id != capability_id
            or authorization.scan_root_id != capability.scan_root_id
        ):
            _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_MISMATCH)
        expected = self._authorization(
            plan,
            capability_id,
            authorization.authorized_at,
            expires_at=authorization.expires_at,
        )
        if expected != authorization:
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        if not authorization.authorized_at <= checked_at < authorization.expires_at:
            _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_EXPIRED)
        return plan, authorization, capability

    def _current_sources(
        self,
        plan: ConsolidationPlan,
        authorization: QuarantineAuthorizationSnapshot,
    ) -> tuple[
        QuarantineAuthorizationSourceSnapshot,
        QuarantineAuthorizationSourceSnapshot,
    ]:
        try:
            sources = self._quarantine.require_authorization_sources(plan)
        except (ConsolidationStoreError, QuarantineStoreError):
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        by_role = {source.role: source for source in sources}
        keeper = by_role.get(ConsolidationFileRole.KEEPER)
        candidate = by_role.get(ConsolidationFileRole.CANDIDATE)
        if (
            keeper is None
            or candidate is None
            or keeper.file_id != authorization.keeper_file_id
            or keeper.observation_id != authorization.keeper_observation_id
            or keeper.expected_full_sha256 != authorization.keeper_full_sha256
            or candidate.file_id != authorization.candidate_file_id
            or candidate.observation_id != authorization.candidate_observation_id
            or candidate.expected_full_sha256 != authorization.candidate_full_sha256
        ):
            _operator_fail(QuarantineOperatorErrorCode.STALE)
        return keeper, candidate

    @staticmethod
    def _authorization(
        plan: ConsolidationPlan,
        capability_id: EntityId,
        authorized_at: datetime,
        *,
        expires_at: datetime | None = None,
    ) -> QuarantineAuthorizationSnapshot:
        if plan.keeper is None or plan.candidate is None:
            _operator_fail(QuarantineOperatorErrorCode.AUTHORIZATION_BLOCKED)
        assessment = build_quarantine_authorization(
            plan=plan,
            current_keeper=plan.keeper,
            current_candidate=plan.candidate,
            current_dependencies=plan.dependencies,
            current_reviews=plan.required_reviews,
            quarantine_capability_id=capability_id,
            authorized_at=authorized_at,
            expires_at=(
                expires_at
                if expires_at is not None
                else authorized_at + MAX_QUARANTINE_AUTHORIZATION_LIFETIME
            ),
        )
        if (
            assessment.status is not QuarantineEligibilityStatus.ELIGIBLE
            or assessment.authorization is None
        ):
            _operator_fail(
                QuarantineOperatorErrorCode.AUTHORIZATION_BLOCKED,
                assessment.blockers,
            )
        return assessment.authorization

    def _acquire_run_lease(
        self,
        run_id: EntityId,
        scan_root_id: EntityId,
    ) -> OwnedScanRootWriteLease:
        acquired_at = _now(self._clock)
        try:
            current = self._leases.current(scan_root_id)
        except Exception:
            _operator_fail(QuarantineOperatorErrorCode.FENCED_OUT)
        if current is not None:
            if (
                current.owner_kind
                is ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN
                and current.lease_expires_at <= acquired_at
            ):
                try:
                    return self._quarantine.takeover_expired_preparedless_lease(
                        current,
                        run_id,
                        lease_token=str(EntityId.new()),
                        acquired_at=acquired_at,
                        lease_expires_at=acquired_at + _LEASE_DURATION,
                    )
                except (
                    QuarantineStoreError,
                    ScanRootWriteLeaseError,
                    TypeError,
                    ValueError,
                ):
                    pass
            _operator_fail(QuarantineOperatorErrorCode.FENCED_OUT)
        try:
            return self._leases.acquire(
                scan_root_id,
                ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
                run_id,
                lease_token=str(EntityId.new()),
                acquired_at=acquired_at,
                lease_expires_at=acquired_at + _LEASE_DURATION,
            )
        except Exception:
            _operator_fail(QuarantineOperatorErrorCode.FENCED_OUT)

    def _release_lease(self, lease: OwnedScanRootWriteLease) -> None:
        try:
            current = self._leases.current(lease.scan_root_id)
            if current == lease:
                self._leases.release(lease, released_at=_now(self._clock))
        except Exception:
            pass

    def _latest_run_status(self, run_id: EntityId) -> QuarantineRunStatus | None:
        try:
            events = self._quarantine.events_for_run(run_id)
        except Exception:
            return None
        return None if not events else events[-1].status

    def _consuming_run_id(self, authorization_id: EntityId) -> EntityId | None:
        try:
            run = self._quarantine.get_run_for_authorization(authorization_id)
        except Exception:
            return None
        return None if run is None else run.id


def create_quarantine_operator_service(engine: Engine) -> QuarantineOperatorService:
    """Compose the fixed private runtime adapters behind the application boundary."""

    return QuarantineOperatorService(engine)


def _execution_run(
    authorization: QuarantineAuthorizationSnapshot,
    run_id: EntityId,
    created_at: datetime,
) -> QuarantineExecutionRun:
    target_material = f"{authorization.id}:{authorization.content_hash}".encode("ascii")
    target_token = hashlib.sha256(_TARGET_DOMAIN + target_material).hexdigest()
    return QuarantineExecutionRun(
        run_id,
        authorization.id,
        authorization.plan_id,
        authorization.scan_root_id,
        authorization.keeper_file_id,
        authorization.candidate_file_id,
        target_token,
        created_at,
    )


def _execution_paths(
    capability: ResolvedQuarantineCapability,
    candidate: QuarantineAuthorizationSourceSnapshot,
) -> InterimQuarantinePaths:
    parts = PurePosixPath(candidate.relative_path.replace("\\", "/")).parts
    return InterimQuarantinePaths(
        capability.scan_root_directory.joinpath(*parts),
        capability.scan_root_directory,
        capability.quarantine_directory,
    )


def _source_error_code(
    error: QuarantineSourceValidationError,
) -> QuarantineOperatorErrorCode:
    return (
        QuarantineOperatorErrorCode.TOOL_UNAVAILABLE
        if error.code is QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE
        else QuarantineOperatorErrorCode.STALE
    )


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _now(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception:
        _operator_fail(QuarantineOperatorErrorCode.INTERNAL_ERROR)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _operator_fail(QuarantineOperatorErrorCode.INTERNAL_ERROR)
    return value.astimezone(UTC)


def _operator_fail(
    code: QuarantineOperatorErrorCode,
    blockers: tuple[QuarantineAuthorizationBlockerCode, ...] = (),
    *,
    run_id: EntityId | None = None,
) -> NoReturn:
    raise QuarantineOperatorError(code, blockers, run_id=run_id) from None


__all__ = [
    "QUARANTINE_OPERATOR_PROFILE",
    "QuarantineAuthorizationResult",
    "QuarantineOperationResult",
    "QuarantineOperatorError",
    "QuarantineOperatorErrorCode",
    "QuarantineOperatorService",
    "QuarantineSourceVerifier",
    "create_quarantine_operator_service",
]
