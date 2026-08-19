"""Read-only, path-free projections for persisted consolidation plans."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from foliotone.consolidation.contracts import ConsolidationBlocker, ConsolidationPlan
from foliotone.core import EntityId
from foliotone.persistence.consolidation import (
    ConsolidationStoreError,
    SQLiteConsolidationStore,
)


class ConsolidationPlanReportReaderError(RuntimeError):
    """A persisted consolidation plan cannot be read safely."""


@dataclass(frozen=True, slots=True)
class ConsolidationPlanReportCounts:
    """Bounded integer counts for one immutable consolidation plan."""

    dependencies: int
    quality_evidence: int
    required_reviews: int
    preconditions: int
    future_operation_intents: int
    blockers: int
    blocker_evidence_refs: int
    review_items: int
    decisions: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                self.dependencies,
                self.quality_evidence,
                self.required_reviews,
                self.preconditions,
                self.future_operation_intents,
                self.blockers,
                self.blocker_evidence_refs,
                self.review_items,
                self.decisions,
            )
        ):
            raise ValueError("consolidation plan report counts must be nonnegative integers")


def _blocker_key(blocker: ConsolidationBlocker) -> tuple[object, ...]:
    return (
        blocker.code.value,
        tuple(
            sorted(
                (
                    ref.role.value,
                    ref.kind.value,
                    ref.ref_id,
                    ref.material_fingerprint,
                )
                for ref in blocker.evidence_refs
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class ConsolidationPlanReport:
    """Safe public projection of one persisted non-executable consolidation plan."""

    plan_id: EntityId
    profile: str
    status: str
    execution_state: str
    content_hash: str
    counts: ConsolidationPlanReportCounts
    blocker_codes: tuple[str, ...]
    keeper_file_id: EntityId | None
    candidate_file_id: EntityId | None

    def __post_init__(self) -> None:
        _id(self.plan_id, "plan_id")
        for name in ("keeper_file_id", "candidate_file_id"):
            value = getattr(self, name)
            if value is not None:
                _id(value, name)
        if not isinstance(self.profile, str) or not self.profile:
            raise ValueError("profile must be a non-empty string")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("status must be a non-empty string")
        if not isinstance(self.execution_state, str) or not self.execution_state:
            raise ValueError("execution_state must be a non-empty string")
        if any(not isinstance(code, str) or not code for code in self.blocker_codes):
            raise ValueError("blocker codes must be non-empty strings")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")

    @classmethod
    def from_plan(cls, plan: ConsolidationPlan) -> ConsolidationPlanReport:
        if not isinstance(plan, ConsolidationPlan):
            raise TypeError("plan must be a ConsolidationPlan")
        ordered_blockers = tuple(sorted(plan.blockers, key=_blocker_key))
        return cls(
            plan_id=plan.id,
            profile=plan.profile,
            status=plan.status.value,
            execution_state=plan.execution_state.value,
            content_hash=plan.content_hash,
            counts=ConsolidationPlanReportCounts(
                dependencies=len(plan.dependencies),
                quality_evidence=len(plan.quality_evidence),
                required_reviews=len(plan.required_reviews),
                preconditions=len(plan.preconditions),
                future_operation_intents=len(plan.future_operation_intents),
                blockers=len(plan.blockers),
                blocker_evidence_refs=sum(len(item.evidence_refs) for item in plan.blockers),
                review_items=sum(
                    review.review_item_id is not None for review in plan.required_reviews
                ),
                decisions=sum(review.decision_id is not None for review in plan.required_reviews),
            ),
            blocker_codes=tuple(item.code.value for item in ordered_blockers),
            keeper_file_id=None if plan.keeper is None else plan.keeper.file_id,
            candidate_file_id=None if plan.candidate is None else plan.candidate.file_id,
        )

    def payload(self) -> dict[str, object]:
        """Return the stable machine-readable report contract."""

        return {
            "schema_version": 1,
            "command": "ebook-consolidation-report",
            "ok": True,
            "plan_id": str(self.plan_id),
            "profile": self.profile,
            "status": self.status,
            "execution_state": self.execution_state,
            "content_hash": self.content_hash,
            "counts": {
                "dependencies": self.counts.dependencies,
                "quality_evidence": self.counts.quality_evidence,
                "required_reviews": self.counts.required_reviews,
                "preconditions": self.counts.preconditions,
                "future_operation_intents": self.counts.future_operation_intents,
                "blockers": self.counts.blockers,
                "blocker_evidence_refs": self.counts.blocker_evidence_refs,
                "review_items": self.counts.review_items,
                "decisions": self.counts.decisions,
            },
            "blocker_codes": list(self.blocker_codes),
            "keeper_file_id": (
                None if self.keeper_file_id is None else str(self.keeper_file_id)
            ),
            "candidate_file_id": (
                None if self.candidate_file_id is None else str(self.candidate_file_id)
            ),
        }


class SQLiteConsolidationPlanReportReader:
    """Read one persisted consolidation plan through the immutable store contract."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(self, plan_id: EntityId) -> ConsolidationPlanReport:
        store = SQLiteConsolidationStore(self._engine)
        try:
            plan = store.get_plan(plan_id)
        except ConsolidationStoreError as error:
            raise ConsolidationPlanReportReaderError(str(error)) from error
        if plan is None:
            raise ConsolidationPlanReportReaderError("consolidation plan does not exist")
        return ConsolidationPlanReport.from_plan(plan)

    plan = read
    report = read


def _id(value: EntityId, field_name: str) -> None:
    if not isinstance(value, EntityId):
        raise ValueError(f"{field_name} must be an EntityId")
