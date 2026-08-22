"""Read-only, privacy-bounded reports for persisted metadata correction plans."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from foliotone.core import EntityId
from foliotone.metadata_correction import MetadataCorrectionPlan
from foliotone.persistence.metadata_correction import (
    MetadataCorrectionStoreError,
    SQLiteMetadataCorrectionStore,
)


class MetadataCorrectionPlanReportReaderError(RuntimeError):
    """A persisted metadata correction plan cannot be read safely."""


@dataclass(frozen=True, slots=True)
class MetadataCorrectionFieldReport:
    """Value-free summary of one planned field correction."""

    field_path: str
    operation: str
    observed_value_count: int
    selected_value_count: int
    evidence_ref_count: int

    def __post_init__(self) -> None:
        for field_name in ("field_path", "operation"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        _nonnegative_counts(
            self.observed_value_count,
            self.selected_value_count,
            self.evidence_ref_count,
        )

    def payload(self) -> dict[str, object]:
        """Return the stable value-free field projection."""

        return {
            "field_path": self.field_path,
            "operation": self.operation,
            "observed_value_count": self.observed_value_count,
            "selected_value_count": self.selected_value_count,
            "evidence_ref_count": self.evidence_ref_count,
        }


@dataclass(frozen=True, slots=True)
class MetadataCorrectionPlanReportCounts:
    """Bounded aggregate counts for one immutable plan graph."""

    fields: int
    observed_values: int
    selected_values: int
    field_evidence_refs: int
    candidate_evidence_refs: int
    dependencies: int
    preconditions: int
    verification_fields: int
    verification_dependencies: int
    blockers: int
    blocker_evidence_refs: int
    review_items: int
    decisions: int

    def __post_init__(self) -> None:
        _nonnegative_counts(
            self.fields,
            self.observed_values,
            self.selected_values,
            self.field_evidence_refs,
            self.candidate_evidence_refs,
            self.dependencies,
            self.preconditions,
            self.verification_fields,
            self.verification_dependencies,
            self.blockers,
            self.blocker_evidence_refs,
            self.review_items,
            self.decisions,
        )

    def payload(self) -> dict[str, int]:
        """Return stable machine-readable aggregate names."""

        return {
            "fields": self.fields,
            "observed_values": self.observed_values,
            "selected_values": self.selected_values,
            "field_evidence_refs": self.field_evidence_refs,
            "candidate_evidence_refs": self.candidate_evidence_refs,
            "dependencies": self.dependencies,
            "preconditions": self.preconditions,
            "verification_fields": self.verification_fields,
            "verification_dependencies": self.verification_dependencies,
            "blockers": self.blockers,
            "blocker_evidence_refs": self.blocker_evidence_refs,
            "review_items": self.review_items,
            "decisions": self.decisions,
        }


@dataclass(frozen=True, slots=True)
class MetadataCorrectionPlanReport:
    """Safe public projection of one persisted non-executable plan."""

    plan_id: EntityId
    candidate_id: EntityId
    plan_profile: str
    candidate_profile: str
    status: str
    execution_state: str
    content_hash: str
    target_carrier: str
    format_label: str
    review_status: str
    fields: tuple[MetadataCorrectionFieldReport, ...]
    counts: MetadataCorrectionPlanReportCounts
    blocker_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "candidate_id"):
            if not isinstance(getattr(self, field_name), EntityId):
                raise ValueError(f"{field_name} must be an EntityId")
        for field_name in (
            "plan_profile",
            "candidate_profile",
            "status",
            "execution_state",
            "target_carrier",
            "format_label",
            "review_status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        if any(not isinstance(field, MetadataCorrectionFieldReport) for field in self.fields):
            raise ValueError("fields must contain MetadataCorrectionFieldReport values")
        if any(not isinstance(code, str) or not code for code in self.blocker_codes):
            raise ValueError("blocker codes must be non-empty strings")

    @classmethod
    def from_plan(cls, plan: MetadataCorrectionPlan) -> MetadataCorrectionPlanReport:
        """Project only the values allowed by ADR-0062's public report contract."""

        if not isinstance(plan, MetadataCorrectionPlan):
            raise TypeError("plan must be a MetadataCorrectionPlan")
        candidate = plan.candidate
        fields = tuple(
            MetadataCorrectionFieldReport(
                field_path=field.field_path,
                operation=field.operation.value,
                observed_value_count=len(field.observed_values),
                selected_value_count=len(field.selected_values),
                evidence_ref_count=len(field.evidence_refs),
            )
            for field in candidate.field_corrections
        )
        review = plan.review
        return cls(
            plan_id=plan.id,
            candidate_id=candidate.id,
            plan_profile=plan.profile,
            candidate_profile=candidate.profile,
            status=plan.status.value,
            execution_state=plan.execution_state.value,
            content_hash=plan.content_hash,
            target_carrier=candidate.target.carrier.value,
            format_label=candidate.format_label,
            review_status="MISSING" if review is None else review.state.value,
            fields=fields,
            counts=MetadataCorrectionPlanReportCounts(
                fields=len(fields),
                observed_values=sum(field.observed_value_count for field in fields),
                selected_values=sum(field.selected_value_count for field in fields),
                field_evidence_refs=sum(field.evidence_ref_count for field in fields),
                candidate_evidence_refs=len(candidate.evidence_refs),
                dependencies=len(candidate.dependencies),
                preconditions=len(plan.preconditions),
                verification_fields=len(plan.verification.changed_field_paths),
                verification_dependencies=len(plan.verification.dependency_reconciliation),
                blockers=len(plan.blockers),
                blocker_evidence_refs=sum(len(blocker.evidence_refs) for blocker in plan.blockers),
                review_items=int(review is not None and review.review_item_id is not None),
                decisions=int(review is not None and review.decision_id is not None),
            ),
            blocker_codes=tuple(sorted(blocker.code.value for blocker in plan.blockers)),
        )

    def payload(self) -> dict[str, object]:
        """Return the stable metadata-value-free JSON contract."""

        return {
            "schema_version": 1,
            "command": "ebook-metadata-correction-report",
            "ok": True,
            "plan_id": str(self.plan_id),
            "candidate_id": str(self.candidate_id),
            "plan_profile": self.plan_profile,
            "candidate_profile": self.candidate_profile,
            "status": self.status,
            "execution_state": self.execution_state,
            "content_hash": self.content_hash,
            "target_carrier": self.target_carrier,
            "format": self.format_label,
            "review_status": self.review_status,
            "fields": [field.payload() for field in self.fields],
            "counts": self.counts.payload(),
            "blocker_codes": list(self.blocker_codes),
        }


class SQLiteMetadataCorrectionPlanReportReader:
    """Read one plan through the bounded immutable store contract."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(self, plan_id: EntityId) -> MetadataCorrectionPlanReport:
        try:
            plan = SQLiteMetadataCorrectionStore(self._engine).get_plan(plan_id)
        except (MetadataCorrectionStoreError, ValueError) as error:
            raise MetadataCorrectionPlanReportReaderError(str(error)) from error
        if plan is None:
            raise MetadataCorrectionPlanReportReaderError("metadata correction plan does not exist")
        return MetadataCorrectionPlanReport.from_plan(plan)


def _nonnegative_counts(*values: int) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("metadata correction report counts must be nonnegative integers")
