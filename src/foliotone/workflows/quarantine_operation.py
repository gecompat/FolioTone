"""Application service for the ADR-0056 quarantine authorization step."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import NoReturn, Protocol

from sqlalchemy import Engine

from foliotone.consolidation.contracts import ConsolidationPlan
from foliotone.core import EntityId
from foliotone.persistence.consolidation import (
    ConsolidationStoreError,
    SQLiteConsolidationStore,
)
from foliotone.persistence.quarantine import (
    QuarantineAuthorizationSourceSnapshot,
    QuarantineStoreError,
    SQLiteQuarantineStore,
)
from foliotone.quarantine import (
    MAX_QUARANTINE_AUTHORIZATION_LIFETIME,
    QuarantineAuthorizationBlockerCode,
    QuarantineAuthorizationSnapshot,
    QuarantineEligibilityStatus,
    build_quarantine_authorization,
)
from foliotone.quarantine.capabilities import (
    QuarantineCapabilityResolver,
    QuarantineCapabilityUnavailable,
    ResolvedQuarantineCapability,
)
from foliotone.quarantine.source_validation import (
    InterimQuarantineSourceVerifier,
    QuarantineSourceValidationError,
    QuarantineSourceValidationErrorCode,
)

QUARANTINE_OPERATOR_PROFILE = "quarantine-operator/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class QuarantineOperatorErrorCode(StrEnum):
    PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    AUTHORIZATION_BLOCKED = "AUTHORIZATION_BLOCKED"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    STALE = "STALE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class QuarantineOperatorError(RuntimeError):
    """One path-, hash-, and filename-free authorization failure."""

    def __init__(
        self,
        code: QuarantineOperatorErrorCode,
        blockers: tuple[QuarantineAuthorizationBlockerCode, ...] = (),
    ) -> None:
        self.code = code
        self.blockers = blockers
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


class QuarantineCapabilityLookup(Protocol):
    def resolve(self, quarantine_capability_id: EntityId) -> ResolvedQuarantineCapability: ...


class QuarantineSourceVerifier(Protocol):
    def verify(
        self,
        *,
        capability: ResolvedQuarantineCapability,
        source: QuarantineAuthorizationSourceSnapshot,
    ) -> None: ...


class QuarantineOperatorService:
    """Authorize one exact current candidate without executing a move."""

    def __init__(
        self,
        engine: Engine,
        *,
        capability_resolver: QuarantineCapabilityLookup | None = None,
        source_verifier: QuarantineSourceVerifier | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = SQLiteConsolidationStore(engine)
        self._quarantine = SQLiteQuarantineStore(engine)
        self._capabilities = capability_resolver or QuarantineCapabilityResolver()
        self._source_verifier = source_verifier or InterimQuarantineSourceVerifier()
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
            _operator_fail(
                QuarantineOperatorErrorCode.TOOL_UNAVAILABLE
                if error.code is QuarantineSourceValidationErrorCode.TOOL_UNAVAILABLE
                else QuarantineOperatorErrorCode.STALE
            )
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

    @staticmethod
    def _authorization(
        plan: ConsolidationPlan,
        capability_id: EntityId,
        authorized_at: datetime,
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
            expires_at=authorized_at + MAX_QUARANTINE_AUTHORIZATION_LIFETIME,
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


def create_quarantine_operator_service(engine: Engine) -> QuarantineOperatorService:
    """Compose the fixed private runtime adapters behind the application boundary."""

    return QuarantineOperatorService(engine)


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
) -> NoReturn:
    raise QuarantineOperatorError(code, blockers) from None


__all__ = [
    "QUARANTINE_OPERATOR_PROFILE",
    "QuarantineAuthorizationResult",
    "QuarantineOperatorError",
    "QuarantineOperatorErrorCode",
    "QuarantineOperatorService",
    "QuarantineSourceVerifier",
    "create_quarantine_operator_service",
]
