"""Read-only, privacy-bounded reports for persisted e-book operation recipes."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import EbookOperationRecipePlan
from foliotone.persistence import ebook_operation_recipe_schema as recipe_schema
from foliotone.persistence.ebook_operation_recipe import (
    EbookOperationRecipeStoreError,
    SQLiteEbookOperationRecipeStore,
)


class EbookOperationRecipePlanReportReaderError(RuntimeError):
    """A persisted operation recipe plan cannot be read safely."""


class EbookOperationRecipePlanReportSchemaError(
    EbookOperationRecipePlanReportReaderError
):
    """The database predates the operation recipe persistence contract."""


@dataclass(frozen=True, slots=True)
class EbookOperationRecipePlanReportCounts:
    """Bounded aggregate counts without private recipe material."""

    sources: int
    dependencies: int
    verifications: int
    candidate_evidence_refs: int
    preconditions: int
    blockers: int
    blocker_evidence_refs: int
    review_items: int
    decisions: int

    def __post_init__(self) -> None:
        _nonnegative_counts(
            self.sources,
            self.dependencies,
            self.verifications,
            self.candidate_evidence_refs,
            self.preconditions,
            self.blockers,
            self.blocker_evidence_refs,
            self.review_items,
            self.decisions,
        )

    def payload(self) -> dict[str, int]:
        """Return stable machine-readable aggregate names."""

        return {
            "sources": self.sources,
            "dependencies": self.dependencies,
            "verifications": self.verifications,
            "candidate_evidence_refs": self.candidate_evidence_refs,
            "preconditions": self.preconditions,
            "blockers": self.blockers,
            "blocker_evidence_refs": self.blocker_evidence_refs,
            "review_items": self.review_items,
            "decisions": self.decisions,
        }


@dataclass(frozen=True, slots=True)
class EbookOperationRecipePlanReport:
    """Safe public projection of one persisted non-executable recipe plan."""

    plan_id: EntityId
    candidate_id: EntityId
    plan_profile: str
    candidate_profile: str
    operation_kind: str
    status: str
    execution_state: str
    review_status: str
    counts: EbookOperationRecipePlanReportCounts
    blocker_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "candidate_id"):
            if not isinstance(getattr(self, field_name), EntityId):
                raise ValueError(f"{field_name} must be an EntityId")
        for field_name in (
            "plan_profile",
            "candidate_profile",
            "operation_kind",
            "status",
            "execution_state",
            "review_status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.counts, EbookOperationRecipePlanReportCounts):
            raise ValueError("counts must be an EbookOperationRecipePlanReportCounts")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise ValueError("blocker_codes must be sorted and unique")
        if any(not isinstance(code, str) or not code for code in self.blocker_codes):
            raise ValueError("blocker codes must be non-empty strings")

    @classmethod
    def from_plan(
        cls,
        plan: EbookOperationRecipePlan,
    ) -> EbookOperationRecipePlanReport:
        """Project only the fields allowed by ADR-0065's standard report."""

        if not isinstance(plan, EbookOperationRecipePlan):
            raise TypeError("plan must be an EbookOperationRecipePlan")
        candidate = plan.candidate
        review = plan.review
        return cls(
            plan_id=plan.id,
            candidate_id=candidate.id,
            plan_profile=plan.profile,
            candidate_profile=candidate.profile,
            operation_kind=candidate.operation_kind.value,
            status=plan.status.value,
            execution_state=plan.execution_state.value,
            review_status=review.state.value,
            counts=EbookOperationRecipePlanReportCounts(
                sources=len(candidate.sources),
                dependencies=len(candidate.dependencies),
                verifications=len(candidate.verification_codes),
                candidate_evidence_refs=len(candidate.evidence_refs),
                preconditions=len(plan.preconditions),
                blockers=len(plan.blockers),
                blocker_evidence_refs=sum(
                    len(blocker.evidence_refs) for blocker in plan.blockers
                ),
                review_items=int(review.review_item_id is not None),
                decisions=int(review.decision_id is not None),
            ),
            blocker_codes=tuple(sorted(blocker.code.value for blocker in plan.blockers)),
        )

    def payload(self) -> dict[str, object]:
        """Return the stable locator-, material-, and hash-free JSON contract."""

        return {
            "schema_version": 1,
            "command": "ebook-operation-recipe-report",
            "ok": True,
            "plan_id": str(self.plan_id),
            "candidate_id": str(self.candidate_id),
            "plan_profile": self.plan_profile,
            "candidate_profile": self.candidate_profile,
            "operation_kind": self.operation_kind,
            "status": self.status,
            "execution_state": self.execution_state,
            "review_status": self.review_status,
            "counts": self.counts.payload(),
            "blocker_codes": list(self.blocker_codes),
        }


class SQLiteEbookOperationRecipePlanReportReader:
    """Read one plan through the bounded immutable store contract."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(self, plan_id: EntityId) -> EbookOperationRecipePlanReport:
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    select(recipe_schema.ebook_operation_recipe_plans.c.id).limit(0)
                ).all()
        except OperationalError:
            raise EbookOperationRecipePlanReportSchemaError(
                "operation recipe report schema is unavailable"
            ) from None

        try:
            plan = SQLiteEbookOperationRecipeStore(self._engine).get_plan(plan_id)
        except (EbookOperationRecipeStoreError, TypeError, ValueError):
            raise EbookOperationRecipePlanReportReaderError(
                "operation recipe plan is unavailable"
            ) from None
        if plan is None:
            raise EbookOperationRecipePlanReportReaderError(
                "operation recipe plan does not exist"
            )
        try:
            return EbookOperationRecipePlanReport.from_plan(plan)
        except (TypeError, ValueError):
            raise EbookOperationRecipePlanReportReaderError(
                "operation recipe report projection is invalid"
            ) from None


def _nonnegative_counts(*values: int) -> None:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values
    ):
        raise ValueError("operation recipe report counts must be nonnegative integers")


__all__ = [
    "EbookOperationRecipePlanReport",
    "EbookOperationRecipePlanReportCounts",
    "EbookOperationRecipePlanReportReaderError",
    "EbookOperationRecipePlanReportSchemaError",
    "SQLiteEbookOperationRecipePlanReportReader",
]
