"""Focused current-state persistence coverage for S-W10-05B authorization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, insert, select

from foliotone.consolidation.contracts import ConsolidationReviewState
from foliotone.core import EntityId, ReviewType
from foliotone.persistence import quarantine_schema
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence.quarantine import QuarantineAuthorizationSourceSnapshot
from foliotone.quarantine.capabilities import ResolvedQuarantineCapability
from foliotone.quarantine.source_validation import (
    QuarantineSourceValidationError,
    QuarantineSourceValidationErrorCode,
)
from foliotone.workflows.quarantine_operation import (
    QuarantineOperatorError,
    QuarantineOperatorErrorCode,
    QuarantineOperatorService,
)
from tests.integration.test_consolidation_persistence import (
    _planner_candidate_review_plan,
)

NOW = datetime(2026, 8, 23, 10, 30, tzinfo=UTC)
CAPABILITY_ID = EntityId.parse("de000000-0000-0000-0000-000000000001")


class _Resolver:
    def __init__(self, capability: ResolvedQuarantineCapability) -> None:
        self.capability = capability

    def resolve(self, quarantine_capability_id: EntityId) -> ResolvedQuarantineCapability:
        assert quarantine_capability_id == self.capability.quarantine_capability_id
        return self.capability


class _Verifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sources: list[QuarantineAuthorizationSourceSnapshot] = []

    def verify(
        self,
        *,
        capability: ResolvedQuarantineCapability,
        source: QuarantineAuthorizationSourceSnapshot,
    ) -> None:
        assert capability.quarantine_capability_id == CAPABILITY_ID
        self.sources.append(source)
        if self.fail:
            raise QuarantineSourceValidationError(QuarantineSourceValidationErrorCode.STALE)


def test_authorize_revalidates_and_persists_one_current_plan_snapshot(
    head_database: Path,
    tmp_path: Path,
) -> None:
    store, plan, _inputs = _planner_candidate_review_plan(
        head_database,
        ConsolidationReviewState.ACCEPTED,
    )
    persisted_plan = store.create_or_get_plan(plan)
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    quarantine.mkdir()
    capability = ResolvedQuarantineCapability(
        CAPABILITY_ID,
        plan.scan_root_id,
        root,
        quarantine,
    )
    verifier = _Verifier()
    service = QuarantineOperatorService(
        store._engine,
        capability_resolver=_Resolver(capability),
        source_verifier=verifier,
        clock=lambda: NOW,
    )

    first = service.authorize(
        plan_id=persisted_plan.id,
        plan_content_hash=persisted_plan.content_hash,
        capability_id=CAPABILITY_ID,
    )
    second = service.authorize(
        plan_id=persisted_plan.id,
        plan_content_hash=persisted_plan.content_hash,
        capability_id=CAPABILITY_ID,
    )

    assert first == second
    assert first.status == "AUTHORIZED"
    assert len(verifier.sources) == 4
    assert {source.role.value for source in verifier.sources} == {"KEEPER", "CANDIDATE"}
    with store._engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(quarantine_schema.quarantine_authorizations)
        ).scalar_one() == 1
    store._engine.dispose()


def test_authorize_rejects_a_newer_review_decision_before_source_access(
    head_database: Path,
    tmp_path: Path,
) -> None:
    store, plan, _inputs = _planner_candidate_review_plan(
        head_database,
        ConsolidationReviewState.ACCEPTED,
    )
    persisted_plan = store.create_or_get_plan(plan)
    review = next(
        item
        for item in plan.required_reviews
        if item.review_type is ReviewType.CONSOLIDATION_CANDIDATE
    )
    assert review.review_item_id is not None
    with store._engine.begin() as connection:
        connection.execute(
            insert(review_schema.review_decisions).values(
                id=str(EntityId.new()),
                review_item_id=str(review.review_item_id),
                sequence_no=2,
                decision="REJECT",
                decision_reason="SYNTHETIC_NEWER_DECISION",
                evidence_fingerprint=review.evidence_fingerprint,
                candidate_set_fingerprint=review.candidate_set_fingerprint,
                decision_compatibility_version=review.decision_compatibility_version,
                actor_kind="USER",
                decided_at=NOW.isoformat(),
            )
        )
    verifier = _Verifier()
    service = _service(store._engine, plan.scan_root_id, tmp_path, verifier)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.authorize(
            plan_id=persisted_plan.id,
            plan_content_hash=persisted_plan.content_hash,
            capability_id=CAPABILITY_ID,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.STALE
    assert verifier.sources == []
    assert _authorization_count(store._engine) == 0
    store._engine.dispose()


def test_authorize_persists_nothing_when_physical_source_is_stale(
    head_database: Path,
    tmp_path: Path,
) -> None:
    store, plan, _inputs = _planner_candidate_review_plan(
        head_database,
        ConsolidationReviewState.ACCEPTED,
    )
    persisted_plan = store.create_or_get_plan(plan)
    verifier = _Verifier(fail=True)
    service = _service(store._engine, plan.scan_root_id, tmp_path, verifier)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.authorize(
            plan_id=persisted_plan.id,
            plan_content_hash=persisted_plan.content_hash,
            capability_id=CAPABILITY_ID,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.STALE
    assert _authorization_count(store._engine) == 0
    store._engine.dispose()


def test_authorize_revalidates_plan_again_after_physical_source_checks(
    head_database: Path,
    tmp_path: Path,
) -> None:
    store, plan, _inputs = _planner_candidate_review_plan(
        head_database,
        ConsolidationReviewState.ACCEPTED,
    )
    persisted_plan = store.create_or_get_plan(plan)
    review = next(
        item
        for item in plan.required_reviews
        if item.review_type is ReviewType.CONSOLIDATION_CANDIDATE
    )
    assert review.review_item_id is not None

    class _DriftingVerifier(_Verifier):
        def verify(
            self,
            *,
            capability: ResolvedQuarantineCapability,
            source: QuarantineAuthorizationSourceSnapshot,
        ) -> None:
            super().verify(capability=capability, source=source)
            if len(self.sources) != 2:
                return
            with store._engine.begin() as connection:
                connection.execute(
                    insert(review_schema.review_decisions).values(
                        id=str(EntityId.new()),
                        review_item_id=str(review.review_item_id),
                        sequence_no=2,
                        decision="REJECT",
                        decision_reason="SYNTHETIC_DRIFT_DURING_AUTHORIZATION",
                        evidence_fingerprint=review.evidence_fingerprint,
                        candidate_set_fingerprint=review.candidate_set_fingerprint,
                        decision_compatibility_version=review.decision_compatibility_version,
                        actor_kind="USER",
                        decided_at=NOW.isoformat(),
                    )
                )

    verifier = _DriftingVerifier()
    service = _service(store._engine, plan.scan_root_id, tmp_path, verifier)

    with pytest.raises(QuarantineOperatorError) as captured:
        service.authorize(
            plan_id=persisted_plan.id,
            plan_content_hash=persisted_plan.content_hash,
            capability_id=CAPABILITY_ID,
        )

    assert captured.value.code is QuarantineOperatorErrorCode.STALE
    assert len(verifier.sources) == 2
    assert _authorization_count(store._engine) == 0
    store._engine.dispose()


def _service(
    engine: Engine,
    root_id: EntityId,
    tmp_path: Path,
    verifier: _Verifier,
) -> QuarantineOperatorService:
    root = tmp_path / "source"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    quarantine.mkdir()
    capability = ResolvedQuarantineCapability(CAPABILITY_ID, root_id, root, quarantine)
    return QuarantineOperatorService(
        engine,
        capability_resolver=_Resolver(capability),
        source_verifier=verifier,
        clock=lambda: NOW,
    )


def _authorization_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(quarantine_schema.quarantine_authorizations)
            ).scalar_one()
        )
