"""Insert-only SQLite persistence for S-EB08-06 consolidation snapshots."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import Engine, Table, insert, select
from sqlalchemy.engine import Connection, RowMapping

from foliotone.consolidation.contracts import (
    CONSOLIDATION_CANDIDATE_DECISION,
    CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationCandidateSnapshot,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationEvidenceKind,
    ConsolidationEvidenceReference,
    ConsolidationEvidenceRole,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFilePreconditionSnapshot,
    ConsolidationFileRole,
    ConsolidationFutureOperationIntent,
    ConsolidationIdentitySnapshot,
    ConsolidationIntentCode,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    ConsolidationPreconditionCode,
    ConsolidationQualityDimension,
    ConsolidationQualityEvidence,
    ConsolidationQualityEvidenceSnapshot,
    ConsolidationQualityExecutionDisposition,
    ConsolidationQualityFinding,
    ConsolidationQualityItemExecution,
    ConsolidationReviewSnapshot,
    ConsolidationReviewState,
    KeepPreferenceOutcome,
    KeepPreferenceReasonCode,
    KeepPreferenceStatus,
)
from foliotone.consolidation.planner import (
    consolidation_candidate_material_fingerprints,
    consolidation_candidate_physical_preconditions,
)
from foliotone.consolidation.serialization import consolidation_plan_content_hash
from foliotone.core import (
    EbookCollectionItemStatus,
    EbookCollectionRunStatus,
    EntityId,
    EntityKind,
    MatchStatus,
    PresenceState,
    RelationType,
    ReviewCandidateKind,
    ReviewType,
    ScanRunStatus,
)
from foliotone.persistence import calibre_library_schema as calibre
from foliotone.persistence import consolidation_schema as cs
from foliotone.persistence import relation_candidate_schema as rc
from foliotone.persistence import resolution_review_schema as rr
from foliotone.persistence import schema, w3_schema
from foliotone.persistence._mapping import datetime_from_db, datetime_to_db
from foliotone.persistence.codecs import codec_for
from foliotone.tooling import ToolExecution, ToolResult
from foliotone.workflows.ebook import (
    EbookAnalysisStepDisposition,
    EbookAnalysisStepOutcome,
)
from foliotone.workflows.quality import (
    EbookQualityAssessment,
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityFindingSeverity,
    EbookQualityStatus,
    evaluate_ebook_quality,
)


class ConsolidationStoreError(RuntimeError):
    """A path-free immutable consolidation persistence failure."""


class _Lineage(NamedTuple):
    scan_root_id: object
    source_scan_run_id: object


_REVIEW_CONTRACT = {
    ReviewType.KEEP_PREFERENCE: (
        "ebook-keep-preference",
        CONSOLIDATION_KEEP_PREFERENCE_DECISION,
    ),
    ReviewType.CONSOLIDATION_CANDIDATE: (
        "ebook-consolidation-candidate",
        CONSOLIDATION_CANDIDATE_DECISION,
    ),
}


def _review_targets_plan(
    plan: ConsolidationPlan, review: ConsolidationReviewSnapshot
) -> bool:
    """Check the review snapshot against immutable plan material, not just its row."""

    expected = _REVIEW_CONTRACT.get(review.review_type)
    if expected is None or (
        review.producer_name != expected[0]
        or review.decision_compatibility_version != expected[1]
    ):
        return False
    if review.review_type is ReviewType.KEEP_PREFERENCE:
        target: KeepPreferenceOutcome | ConsolidationCandidateSnapshot | None = (
            plan.keep_preference
        )
    else:
        target = plan.consolidation_candidate
    return (
        target is not None
        and review.evidence_fingerprint == target.evidence_fingerprint
        and review.candidate_set_fingerprint == target.candidate_set_fingerprint
    )


def _plan_status_is_consistent(plan: ConsolidationPlan) -> bool:
    """Project ADR-0034 status priority from the immutable plan graph."""

    if plan.blockers:
        return plan.status is ConsolidationPlanStatus.BLOCKED
    reviews = {item.review_type: item for item in plan.required_reviews}
    waiting = {
        review_type: item
        for review_type, item in reviews.items()
        if item.state in {ConsolidationReviewState.PENDING, ConsolidationReviewState.DEFERRED}
    }
    if waiting:
        keep = reviews.get(ReviewType.KEEP_PREFERENCE)
        candidate = reviews.get(ReviewType.CONSOLIDATION_CANDIDATE)
        undirected_keep_waiting = (
            set(reviews) == {ReviewType.KEEP_PREFERENCE}
            and keep is not None
            and keep.review_item_id is not None
            and _review_targets_plan(plan, keep)
            and plan.keep_preference is not None
            and plan.keep_preference.status is KeepPreferenceStatus.PREFERRED
            and plan.keeper is None
            and plan.candidate is None
            and plan.consolidation_candidate is None
            and not plan.preconditions
            and not plan.future_operation_intents
        )
        directed_candidate_waiting = (
            set(reviews) == {ReviewType.KEEP_PREFERENCE, ReviewType.CONSOLIDATION_CANDIDATE}
            and keep is not None
            and candidate is not None
            and candidate.review_item_id is not None
            and keep.state is ConsolidationReviewState.ACCEPTED
            and candidate.review_type in waiting
            and _review_targets_plan(plan, keep)
            and _review_targets_plan(plan, candidate)
            and plan.keeper is not None
            and plan.candidate is not None
            and plan.consolidation_candidate is not None
            and _has_exact_candidate_physical_preconditions(plan)
        )
        return (
            plan.status is ConsolidationPlanStatus.REVIEW_REQUIRED
            and (undirected_keep_waiting or directed_candidate_waiting)
        )
    required_precondition_codes = {
        ConsolidationPreconditionCode.FILE_RECORD_UNCHANGED,
        ConsolidationPreconditionCode.FILE_OBSERVATION_CURRENT,
        ConsolidationPreconditionCode.PRESENCE_IS_PRESENT,
        ConsolidationPreconditionCode.FULL_SHA256_MATCHES,
        ConsolidationPreconditionCode.SIZE_MATCHES,
        ConsolidationPreconditionCode.MODIFIED_AT_MATCHES,
        ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED,
        ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED,
        ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED,
        ConsolidationPreconditionCode.REVIEW_APPROVALS_UNCHANGED,
    }
    preconditions_by_role = {
        role: {
            item.code for item in plan.preconditions if item.file_role is role
        }
        for role in ConsolidationFileRole
    }
    approved = (
        set(reviews) == {ReviewType.KEEP_PREFERENCE, ReviewType.CONSOLIDATION_CANDIDATE}
        and all(item.state is ConsolidationReviewState.ACCEPTED for item in reviews.values())
        and all(_review_targets_plan(plan, item) for item in reviews.values())
        and plan.keeper is not None
        and plan.candidate is not None
        and plan.consolidation_candidate is not None
        and plan.identity is not None
        and plan.identity.relation_type is RelationType.EXACT_DUPLICATE
        and plan.identity.left_kind is EntityKind.FILE
        and plan.identity.right_kind is EntityKind.FILE
        and plan.identity.status is MatchStatus.CONFIRMED
        and len(plan.dependencies) == len(ConsolidationFileRole) * len(ConsolidationDependencyKind)
        and {
            (item.file_role, item.kind) for item in plan.dependencies
        }
        == {
            (role, kind)
            for role in ConsolidationFileRole
            for kind in ConsolidationDependencyKind
        }
        and len(plan.quality_evidence) == len(ConsolidationFileRole)
        and all(_dependency_is_safe_for_approved_plan(item) for item in plan.dependencies)
        and set(preconditions_by_role[ConsolidationFileRole.CANDIDATE])
        == required_precondition_codes
        and set(preconditions_by_role[ConsolidationFileRole.KEEPER])
        == required_precondition_codes | {ConsolidationPreconditionCode.KEEPER_READABLE}
        and len(plan.preconditions) == 21
    )
    return approved and plan.status is ConsolidationPlanStatus.APPROVED_NON_EXECUTABLE


def _has_exact_candidate_physical_preconditions(plan: ConsolidationPlan) -> bool:
    if plan.keeper is None or plan.candidate is None:
        return False
    try:
        expected = consolidation_candidate_physical_preconditions(
            (plan.keeper, plan.candidate), plan.dependencies
        )
    except ValueError:
        return False
    return len(plan.preconditions) == len(expected) and set(plan.preconditions) == set(expected)


def _dependency_is_safe_for_approved_plan(dependency: ConsolidationDependency) -> bool:
    if dependency.state is ConsolidationDependencyState.UNKNOWN:
        return False
    if (
        dependency.file_role is ConsolidationFileRole.CANDIDATE
        and dependency.state is ConsolidationDependencyState.KNOWN_PRESENT
    ):
        return False
    return (
        dependency.state is not ConsolidationDependencyState.NOT_APPLICABLE
        or (
            dependency.snapshot_kind is not None
            and dependency.snapshot_id is not None
        )
    )


class SQLiteConsolidationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_quality(self, value: ConsolidationQualityEvidence) -> ConsolidationQualityEvidence:
        created = value.created_at or datetime.now(UTC)
        value = replace(value, created_at=created)
        with self._engine.begin() as connection:
            self._validate_quality_lineage(connection, value)
            row = _quality_row(value)
            inserted = connection.execute(insert(cs.consolidation_quality_evidence).values(**row).prefix_with("OR IGNORE"))
            if inserted.rowcount == 0:
                existing = connection.execute(select(cs.consolidation_quality_evidence).where(cs.consolidation_quality_evidence.c.collection_item_id == str(value.collection_item_id), cs.consolidation_quality_evidence.c.profile == value.profile, cs.consolidation_quality_evidence.c.quality_profile == value.quality_profile)).mappings().one_or_none()
                if existing is None or _quality_material(existing) != _quality_material(row):
                    raise ConsolidationStoreError("quality snapshot retry payload differs")
                persisted = self.get_quality(EntityId.parse(str(existing["id"])), connection=connection)
                assert persisted is not None
                return persisted
        return value

    def get_quality(self, evidence_id: EntityId, *, connection: Connection | None = None) -> ConsolidationQualityEvidence | None:
        if connection is None:
            with self._engine.connect() as opened:
                return self.get_quality(evidence_id, connection=opened)
        row = connection.execute(select(cs.consolidation_quality_evidence).where(cs.consolidation_quality_evidence.c.id == str(evidence_id))).mappings().one_or_none()
        if row is None:
            return None
        executions, findings = _collection_children(connection, str(row["collection_item_id"]))
        dimensions = tuple(ConsolidationQualityDimension(name, EbookQualityDimensionStatus(str(row[f"{name.value.lower()}_status"]))) for name in EbookQualityDimensionName)
        value = ConsolidationQualityEvidence(
            id=EntityId.parse(str(row["id"])), profile=str(row["profile"]), collection_run_id=EntityId.parse(str(row["collection_run_id"])), collection_item_id=EntityId.parse(str(row["collection_item_id"])), observation_id=EntityId.parse(str(row["observation_id"])), scan_root_id=EntityId.parse(str(row["scan_root_id"])), source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])), collection_profile=str(row["collection_profile"]), analysis_profile=str(row["analysis_profile"]), quality_profile=str(row["quality_profile"]), format_label=str(row["format_label"]), item_status=EbookCollectionItemStatus(str(row["item_status"])), aggregate_quality_status=EbookQualityStatus(str(row["aggregate_quality_status"])), reused_step_count=int(row["reused_step_count"]), executed_step_count=int(row["executed_step_count"]), finding_count=int(row["finding_count"]), dimensions=dimensions, item_executions=executions, findings=findings, assessment_fingerprint=str(row["assessment_fingerprint"]), created_at=datetime_from_db(str(row["created_at"])),
        )
        self._validate_quality_lineage(connection, value)
        return value

    def create_or_get_plan(self, plan: ConsolidationPlan) -> ConsolidationPlan:
        if consolidation_plan_content_hash(plan) != plan.content_hash:
            raise ConsolidationStoreError("plan content hash differs from canonical bytes")
        created = plan.created_at or datetime.now(UTC)
        plan = replace(plan, created_at=created)
        if plan.consolidation_candidate is not None and plan.consolidation_candidate.created_at is None:
            plan = replace(
                plan,
                consolidation_candidate=replace(
                    plan.consolidation_candidate,
                    created_at=created,
                ),
            )
        with self._engine.begin() as connection:
            self._validate_plan_lineage(connection, plan)
            for snapshot in plan.quality_evidence:
                existing_quality = self.get_quality(snapshot.id, connection=connection)
                if existing_quality is None or existing_quality.snapshot(snapshot.role) != snapshot or existing_quality.scan_root_id != plan.scan_root_id or existing_quality.source_scan_run_id != plan.source_scan_run_id:
                    raise ConsolidationStoreError("plan quality snapshot is not persisted")
            if plan.keep_preference is not None:
                preference = plan.keep_preference
                slots = {item.observation_id: item.id for item in preference.quality_evidence}
                preference_row: dict[str, object] = {
                    "id": str(preference.preference_id), "profile": preference.profile,
                    "profile_version": preference.profile_version,
                    "left_file_id": str(preference.left_file_id),
                    "left_observation_id": str(preference.left_observation_id),
                    "right_file_id": str(preference.right_file_id),
                    "right_observation_id": str(preference.right_observation_id),
                    "left_quality_evidence_id": str(slots[preference.left_observation_id]),
                    "right_quality_evidence_id": str(slots[preference.right_observation_id]),
                    "status": preference.status.value,
                    "keeper_file_id": None if preference.keeper_file_id is None else str(preference.keeper_file_id),
                    "candidate_file_id": None if preference.candidate_file_id is None else str(preference.candidate_file_id),
                    "configuration_fingerprint": preference.configuration_fingerprint,
                    "evidence_fingerprint": preference.evidence_fingerprint,
                    "candidate_set_fingerprint": preference.candidate_set_fingerprint,
                    "created_at": datetime_to_db(created),
                }
                _insert_exact(connection, cs.consolidation_keep_preferences, preference_row)
                for ordinal, code in enumerate(preference.reason_codes):
                    _insert_exact(connection, cs.consolidation_keep_preference_reasons, {"preference_id": str(preference.preference_id), "ordinal": ordinal, "code": code.value})
                for ordinal, snapshot in enumerate(preference.quality_evidence):
                    _insert_exact(connection, cs.consolidation_keep_preference_evidence, {"preference_id": str(preference.preference_id), "ordinal": ordinal, "role": snapshot.role.value, "kind": ConsolidationEvidenceKind.QUALITY_EVIDENCE.value, "ref_id": str(snapshot.id), "material_fingerprint": snapshot.assessment_fingerprint})
            if plan.consolidation_candidate is not None:
                candidate = plan.consolidation_candidate
                candidate_row: dict[str, object] = {
                    "id": str(candidate.candidate_id), "profile": candidate.profile,
                    "scan_root_id": str(candidate.scan_root_id), "source_scan_run_id": str(candidate.source_scan_run_id),
                    "relation_candidate_id": str(candidate.relation_candidate_id), "relation_fingerprint": candidate.relation_fingerprint,
                    "keep_preference_id": str(candidate.keep_preference_id), "keep_preference_fingerprint": candidate.keep_preference_fingerprint,
                    "keeper_file_id": str(candidate.keeper_file_id), "candidate_file_id": str(candidate.candidate_file_id),
                    "dependency_fingerprint": candidate.dependency_fingerprint, "precondition_fingerprint": candidate.precondition_fingerprint,
                    "evidence_fingerprint": candidate.evidence_fingerprint, "candidate_set_fingerprint": candidate.candidate_set_fingerprint,
                    "created_at": datetime_to_db(candidate.created_at or created),
                }
                _insert_exact(connection, cs.consolidation_candidates, candidate_row)
                for intent in candidate.intents:
                    _insert_exact(connection, cs.consolidation_candidate_intents, {"consolidation_candidate_id": str(candidate.candidate_id), "ordinal": intent.ordinal, "code": intent.code.value, "file_role": intent.file_role.value})
            row = _plan_row(plan)
            inserted = connection.execute(insert(cs.consolidation_plans).values(**row).prefix_with("OR IGNORE"))
            if inserted.rowcount == 0:
                existing_plan = connection.execute(select(cs.consolidation_plans).where(cs.consolidation_plans.c.profile == plan.profile, cs.consolidation_plans.c.content_hash == plan.content_hash)).mappings().one_or_none()
                if existing_plan is None or any(existing_plan[key] != value for key, value in row.items() if key not in {"id", "created_at"}):
                    raise ConsolidationStoreError("plan retry payload differs")
                persisted = self._read_plan(connection, existing_plan)
                if consolidation_plan_content_hash(persisted) != persisted.content_hash:
                    raise ConsolidationStoreError("persisted retry graph is nondeterministic")
                return persisted
            self._write_plan_children(connection, plan)
        return plan

    def get_plan(self, plan_id: EntityId) -> ConsolidationPlan | None:
        """Boundedly rehydrate and revalidate one immutable plan graph."""
        with self._engine.connect() as connection:
            row = connection.execute(select(cs.consolidation_plans).where(cs.consolidation_plans.c.id == str(plan_id))).mappings().one_or_none()
            if row is None:
                return None
            plan = self._read_plan(connection, row)
            if consolidation_plan_content_hash(plan) != plan.content_hash:
                raise ConsolidationStoreError("persisted plan content hash is invalid")
            return plan

    def _read_plan(self, connection: Connection, row: RowMapping) -> ConsolidationPlan:
        plan_id = str(row["id"])
        def rows(table: Table, limit: int) -> list[RowMapping]:
            values = connection.execute(select(table).where(table.c.plan_id == plan_id).order_by(table.c.ordinal).limit(limit + 1)).mappings().all()
            if len(values) > limit or tuple(int(x["ordinal"]) for x in values) != tuple(range(len(values))):
                raise ConsolidationStoreError("persisted plan children are not bounded and contiguous")
            return list(values)
        dependency_rows = rows(cs.consolidation_plan_dependencies, 6)
        review_rows = rows(cs.consolidation_plan_reviews, 16)
        precondition_rows = rows(cs.consolidation_plan_preconditions, 32)
        intent_rows = rows(cs.consolidation_plan_intents, 16)
        blocker_rows = rows(cs.consolidation_plan_blockers, 32)
        evidence_rows = rows(cs.consolidation_plan_evidence, 1024)
        dependencies = tuple(ConsolidationDependency(ConsolidationFileRole(str(x["file_role"])), ConsolidationDependencyKind(str(x["kind"])), ConsolidationDependencyState(str(x["state"])), str(x["material_fingerprint"]), None if x["snapshot_kind"] is None else str(x["snapshot_kind"]), None if x["snapshot_id"] is None else EntityId.parse(str(x["snapshot_id"]))) for x in dependency_rows)
        reviews = tuple(ConsolidationReviewSnapshot(ReviewType(str(x["review_type"])), ConsolidationReviewState(str(x["state"])), str(x["evidence_fingerprint"]), str(x["candidate_set_fingerprint"]), ReviewCandidateKind.KEEP_PREFERENCE if str(x["review_type"]) == ReviewType.KEEP_PREFERENCE.value else ReviewCandidateKind.CONSOLIDATION_CANDIDATE, str(x["producer_name"]), str(x["decision_compatibility_version"]), None if x["review_item_id"] is None else EntityId.parse(str(x["review_item_id"])), None if x["decision_id"] is None else EntityId.parse(str(x["decision_id"])), None if x["decision_sequence_no"] is None else int(x["decision_sequence_no"])) for x in review_rows)
        preconditions = tuple(_precondition_from_row(x) for x in precondition_rows)
        intents = tuple(ConsolidationFutureOperationIntent(int(x["ordinal"]), ConsolidationIntentCode(str(x["code"])), ConsolidationFileRole(str(x["file_role"]))) for x in intent_rows)
        evidence = tuple(ConsolidationEvidenceReference(ConsolidationEvidenceKind(str(x["kind"])), str(x["ref_id"]), ConsolidationEvidenceRole(str(x["role"])), str(x["material_fingerprint"])) for x in evidence_rows)
        quality_values: list[ConsolidationQualityEvidenceSnapshot] = []
        quality_roles = {
            ConsolidationEvidenceRole.KEEPER_QUALITY: ConsolidationFileRole.KEEPER,
            ConsolidationEvidenceRole.CANDIDATE_QUALITY: ConsolidationFileRole.CANDIDATE,
        }
        for reference in evidence:
            role = quality_roles.get(reference.role)
            if reference.kind is not ConsolidationEvidenceKind.QUALITY_EVIDENCE or role is None:
                continue
            value = self.get_quality(EntityId.parse(reference.ref_id), connection=connection)
            if value is None or value.assessment_fingerprint != reference.material_fingerprint:
                raise ConsolidationStoreError("persisted plan quality evidence is invalid")
            quality_values.append(value.snapshot(role))
        quality = tuple(quality_values)
        blockers = []
        for blocker in blocker_rows:
            links = connection.execute(select(cs.consolidation_plan_blocker_evidence).where(cs.consolidation_plan_blocker_evidence.c.plan_id == plan_id, cs.consolidation_plan_blocker_evidence.c.blocker_ordinal == int(blocker["ordinal"])).order_by(cs.consolidation_plan_blocker_evidence.c.evidence_ordinal).limit(65)).mappings().all()
            if len(links) > 64 or tuple(int(x["evidence_ordinal"]) for x in links) != tuple(range(len(links))) or any(int(x["evidence_plan_ordinal"]) >= len(evidence) for x in links):
                raise ConsolidationStoreError("persisted blocker evidence is invalid or exceeds bound")
            blockers.append(ConsolidationBlocker(ConsolidationBlockerCode(str(blocker["code"])), tuple(evidence[int(link["evidence_plan_ordinal"])] for link in links)))
        preference, _ = self._read_preference(connection, row["keep_preference_id"])
        candidate = self._read_candidate(connection, row["consolidation_candidate_id"])
        identity = self._read_identity(connection, row["relation_candidate_id"])
        endpoints = {role: next((x for x in preconditions if x.file_role is role), None) for role in ConsolidationFileRole}
        formats = {x.role: x.format_label for x in quality}
        def endpoint(role: ConsolidationFileRole, file_key: str, observation_key: str) -> ConsolidationFileEndpoint | None:
            if row[file_key] is None:
                return None
            condition = endpoints[role]
            if condition is None:
                raise ConsolidationStoreError("persisted directed endpoint lacks a precondition snapshot")
            return ConsolidationFileEndpoint(role, EntityId.parse(str(row[file_key])), EntityId.parse(str(row[observation_key])), condition.expected_scan_root_id, condition.expected_scan_run_id, condition.expected_presence_state, condition.expected_full_sha256, condition.expected_size_bytes, condition.expected_modified_at, condition.expected_observed_at, formats[role])
        return ConsolidationPlan(EntityId.parse(plan_id), str(row["profile"]), int(row["plan_version"]), str(row["serializer_version"]), EntityId.parse(str(row["scan_root_id"])), EntityId.parse(str(row["source_scan_run_id"])), identity, endpoint(ConsolidationFileRole.KEEPER, "keeper_file_id", "keeper_observation_id"), endpoint(ConsolidationFileRole.CANDIDATE, "candidate_file_id", "candidate_observation_id"), preference, candidate, dependencies, quality, reviews, preconditions, intents, tuple(blockers), ConsolidationPlanStatus(str(row["status"])), ConsolidationExecutionState(str(row["execution_state"])), str(row["content_hash"]), datetime_from_db(str(row["created_at"])))

    def _read_preference(self, connection: Connection, preference_id: object) -> tuple[KeepPreferenceOutcome | None, tuple[ConsolidationQualityEvidenceSnapshot, ...]]:
        if preference_id is None:
            return None, ()
        row = connection.execute(select(cs.consolidation_keep_preferences).where(cs.consolidation_keep_preferences.c.id == str(preference_id))).mappings().one()
        left = self.get_quality(EntityId.parse(str(row["left_quality_evidence_id"])), connection=connection)
        right = self.get_quality(EntityId.parse(str(row["right_quality_evidence_id"])), connection=connection)
        if left is None or right is None:
            raise ConsolidationStoreError("persisted preference quality evidence is missing")
        status = KeepPreferenceStatus(str(row["status"]))
        quality_by_id = {
            left.id: left,
            right.id: right,
        }
        evidence_rows = connection.execute(select(cs.consolidation_keep_preference_evidence).where(cs.consolidation_keep_preference_evidence.c.preference_id == str(preference_id)).order_by(cs.consolidation_keep_preference_evidence.c.ordinal).limit(3)).mappings().all()
        if len(evidence_rows) != 2 or tuple(int(x["ordinal"]) for x in evidence_rows) != (0, 1):
            raise ConsolidationStoreError("persisted preference quality slots are incomplete")
        quality = tuple(
            quality_by_id[EntityId.parse(str(item["ref_id"]))].snapshot(
                ConsolidationFileRole(str(item["role"]))
            )
            for item in evidence_rows
        )
        expected_slots = {
            str(row["left_quality_evidence_id"]),
            str(row["right_quality_evidence_id"]),
        }
        if (
            {str(item.id) for item in quality} != expected_slots
            or any(str(item["kind"]) != ConsolidationEvidenceKind.QUALITY_EVIDENCE.value for item in evidence_rows)
            or any(
                str(item["material_fingerprint"]) != snapshot.assessment_fingerprint
                for item, snapshot in zip(evidence_rows, quality, strict=True)
            )
        ):
            raise ConsolidationStoreError("persisted preference quality slots differ")
        reason_rows = connection.execute(select(cs.consolidation_keep_preference_reasons).where(cs.consolidation_keep_preference_reasons.c.preference_id == str(preference_id)).order_by(cs.consolidation_keep_preference_reasons.c.ordinal).limit(65)).mappings().all()
        if len(reason_rows) > 64 or tuple(int(x["ordinal"]) for x in reason_rows) != tuple(range(len(reason_rows))):
            raise ConsolidationStoreError("persisted preference reasons are invalid or exceed bound")
        preference = KeepPreferenceOutcome(EntityId.parse(str(row["id"])), str(row["profile"]), str(row["profile_version"]), EntityId.parse(str(row["left_file_id"])), EntityId.parse(str(row["left_observation_id"])), EntityId.parse(str(row["right_file_id"])), EntityId.parse(str(row["right_observation_id"])), status, None if row["keeper_file_id"] is None else EntityId.parse(str(row["keeper_file_id"])), None if row["candidate_file_id"] is None else EntityId.parse(str(row["candidate_file_id"])), tuple(KeepPreferenceReasonCode(str(x["code"])) for x in reason_rows), str(row["configuration_fingerprint"]), str(row["evidence_fingerprint"]), quality, str(row["candidate_set_fingerprint"]))
        return preference, quality

    @staticmethod
    def _read_candidate(connection: Connection, candidate_id: object) -> ConsolidationCandidateSnapshot | None:
        if candidate_id is None:
            return None
        row = connection.execute(select(cs.consolidation_candidates).where(cs.consolidation_candidates.c.id == str(candidate_id))).mappings().one()
        children = connection.execute(select(cs.consolidation_candidate_intents).where(cs.consolidation_candidate_intents.c.consolidation_candidate_id == str(candidate_id)).order_by(cs.consolidation_candidate_intents.c.ordinal).limit(17)).mappings().all()
        if len(children) > 16 or tuple(int(x["ordinal"]) for x in children) != tuple(range(len(children))):
            raise ConsolidationStoreError("persisted candidate intents are invalid or exceed bound")
        intents = tuple(ConsolidationFutureOperationIntent(int(x["ordinal"]), ConsolidationIntentCode(str(x["code"])), ConsolidationFileRole(str(x["file_role"]))) for x in children)
        return ConsolidationCandidateSnapshot(EntityId.parse(str(row["id"])), str(row["profile"]), EntityId.parse(str(row["scan_root_id"])), EntityId.parse(str(row["source_scan_run_id"])), EntityId.parse(str(row["relation_candidate_id"])), str(row["relation_fingerprint"]), EntityId.parse(str(row["keep_preference_id"])), str(row["keep_preference_fingerprint"]), EntityId.parse(str(row["keeper_file_id"])), EntityId.parse(str(row["candidate_file_id"])), str(row["dependency_fingerprint"]), str(row["precondition_fingerprint"]), str(row["evidence_fingerprint"]), str(row["candidate_set_fingerprint"]), intents, datetime_from_db(str(row["created_at"])))

    @staticmethod
    def _read_identity(connection: Connection, relation_id: object) -> ConsolidationIdentitySnapshot | None:
        if relation_id is None:
            return None
        row = connection.execute(select(rc.relation_candidates).where(rc.relation_candidates.c.id == str(relation_id))).mappings().one_or_none()
        if row is None:
            return None
        return ConsolidationIdentitySnapshot(EntityId.parse(str(row["id"])), RelationType(str(row["relation_type"])), EntityKind(str(row["left_kind"])), EntityKind(str(row["right_kind"])), EntityId.parse(str(row["left_id"])), EntityId.parse(str(row["right_id"])), EntityId.parse(str(row["scan_root_id"])), EntityId.parse(str(row["source_scan_run_id"])), MatchStatus(str(row["status"])), str(row["matcher_version"]), str(row["decision_compatibility_version"]), str(row["evidence_fingerprint"]), str(row["candidate_set_fingerprint"]))

    def _validate_quality_lineage(self, connection: Connection, value: ConsolidationQualityEvidence) -> None:
        run = w3_schema.ebook_collection_runs
        item = w3_schema.ebook_collection_items
        row = connection.execute(select(run.c.scan_root_id, run.c.source_scan_run_id, run.c.profile, run.c.analysis_profile, run.c.status.label("run_status"), item.c.observation_id, item.c.format_name, item.c.status.label("item_status"), item.c.quality_status, item.c.reused_step_count, item.c.executed_step_count, item.c.finding_count, schema.file_observations.c.scan_run_id.label("observation_scan_run_id"), schema.file_records.c.scan_root_id.label("file_scan_root_id")).select_from(item.join(run, item.c.run_id == run.c.id).join(schema.file_observations, item.c.observation_id == schema.file_observations.c.id).join(schema.file_records, schema.file_observations.c.file_id == schema.file_records.c.id)).where(run.c.id == str(value.collection_run_id), item.c.id == str(value.collection_item_id))).one_or_none()
        if row is None or str(row.run_status) not in {EbookCollectionRunStatus.COMPLETED.value, EbookCollectionRunStatus.COMPLETED_WITH_FAILURES.value} or str(row.scan_root_id) != str(value.scan_root_id) or str(row.file_scan_root_id) != str(value.scan_root_id) or str(row.source_scan_run_id) != str(value.source_scan_run_id) or str(row.observation_scan_run_id) != str(value.source_scan_run_id) or str(row.profile) != value.collection_profile or str(row.analysis_profile) != value.analysis_profile or str(row.observation_id) != str(value.observation_id) or str(row.format_name) != value.format_label or str(row.item_status) != value.item_status.value or str(row.quality_status) != value.aggregate_quality_status.value or int(row.reused_step_count) != value.reused_step_count or int(row.executed_step_count) != value.executed_step_count or int(row.finding_count) != value.finding_count:
            raise ConsolidationStoreError("quality evidence does not match terminal collection lineage")
        executions, findings = _collection_children(connection, str(value.collection_item_id))
        if executions != value.item_executions or findings != value.findings:
            raise ConsolidationStoreError("quality evidence children differ from collection lineage")
        try:
            assessment = _persisted_quality_assessment(connection, value, executions)
        except ValueError as error:
            raise ConsolidationStoreError("persisted tool evidence cannot reproduce quality") from error
        projected_dimensions = tuple(
            ConsolidationQualityDimension(item.name, item.status)
            for item in assessment.dimensions
        )
        projected_findings = tuple(
            ConsolidationQualityFinding(
                ordinal,
                item.code,
                item.dimension,
                item.severity,
                item.source_execution_ids,
            )
            for ordinal, item in enumerate(assessment.findings)
        )
        if (
            assessment.profile != value.quality_profile
            or assessment.observation_id != value.observation_id
            or assessment.format_name != value.format_label
            or assessment.status is not value.aggregate_quality_status
            or projected_dimensions != value.dimensions
            or projected_findings != value.findings
            or assessment.source_execution_ids
            != tuple(item.execution_id for item in value.item_executions)
        ):
            raise ConsolidationStoreError("quality evidence differs from persisted tool projection")

    @staticmethod
    def _validate_plan_lineage(connection: Connection, plan: ConsolidationPlan) -> None:
        if not _plan_status_is_consistent(plan):
            raise ConsolidationStoreError("plan status is inconsistent with ADR-0034 priority")
        if (
            plan.keeper is not None
            and plan.candidate is not None
            and plan.keeper.observation_id == plan.candidate.observation_id
        ):
            raise ConsolidationStoreError("plan keeper and candidate observations must differ")
        scan = connection.execute(select(schema.scan_runs.c.scan_root_id, schema.scan_runs.c.status).where(schema.scan_runs.c.id == str(plan.source_scan_run_id))).one_or_none()
        if scan is None or str(scan.scan_root_id) != str(plan.scan_root_id) or str(scan.status) != ScanRunStatus.COMPLETED.value:
            raise ConsolidationStoreError("plan requires its completed source scan")
        if plan.identity is not None:
            identity = SQLiteConsolidationStore._read_identity(
                connection, plan.identity.relation_candidate_id
            )
            if identity != plan.identity:
                raise ConsolidationStoreError("plan identity differs from persisted relation")
        if plan.keep_preference is not None:
            preference = plan.keep_preference
            for file_id, observation_id in (
                (preference.left_file_id, preference.left_observation_id),
                (preference.right_file_id, preference.right_observation_id),
            ):
                endpoint = connection.execute(select(schema.file_records.c.scan_root_id, schema.file_observations.c.scan_run_id).select_from(schema.file_records.join(schema.file_observations, schema.file_observations.c.file_id == schema.file_records.c.id)).where(schema.file_records.c.id == str(file_id), schema.file_observations.c.id == str(observation_id))).one_or_none()
                if endpoint is None or str(endpoint.scan_root_id) != str(plan.scan_root_id) or str(endpoint.scan_run_id) != str(plan.source_scan_run_id):
                    raise ConsolidationStoreError("plan preference endpoints belong to foreign lineage")
        if plan.consolidation_candidate is not None:
            candidate = plan.consolidation_candidate
            if (
                plan.identity is None
                or plan.keep_preference is None
                or plan.keep_preference.status is not KeepPreferenceStatus.PREFERRED
                or plan.keeper is None
                or plan.candidate is None
                or candidate.relation_candidate_id != plan.identity.relation_candidate_id
                or candidate.keep_preference_id != plan.keep_preference.preference_id
                or candidate.keeper_file_id != plan.keeper.file_id
                or candidate.candidate_file_id != plan.candidate.file_id
            ):
                raise ConsolidationStoreError("plan candidate requires fully directed identity and preference")
            relation = connection.execute(select(rc.relation_candidates.c.scan_root_id, rc.relation_candidates.c.source_scan_run_id, rc.relation_candidates.c.evidence_fingerprint).where(rc.relation_candidates.c.id == str(candidate.relation_candidate_id))).one_or_none()
            if relation is None or str(relation.scan_root_id) != str(plan.scan_root_id) or str(relation.source_scan_run_id) != str(plan.source_scan_run_id) or str(relation.evidence_fingerprint) != candidate.relation_fingerprint:
                raise ConsolidationStoreError("plan candidate relation belongs to foreign or stale lineage")
            if plan.keep_preference is not None and (
                candidate.keeper_file_id != plan.keep_preference.keeper_file_id
                or candidate.candidate_file_id != plan.keep_preference.candidate_file_id
            ):
                raise ConsolidationStoreError("plan candidate direction differs from preference")
            assert plan.identity is not None
            assert plan.keep_preference is not None
            assert plan.keeper is not None
            assert plan.candidate is not None
            candidate_preconditions = (
                plan.preconditions
                if plan.preconditions
                else consolidation_candidate_physical_preconditions(
                    (plan.keeper, plan.candidate), plan.dependencies
                )
            )
            try:
                material = consolidation_candidate_material_fingerprints(
                    identity=plan.identity,
                    preference=plan.keep_preference,
                    keeper=plan.keeper,
                    candidate=plan.candidate,
                    dependencies=plan.dependencies,
                    preconditions=candidate_preconditions,
                    intents=plan.future_operation_intents,
                )
            except ValueError as error:
                raise ConsolidationStoreError(
                    "plan candidate material is incomplete"
                ) from error
            if material != (
                candidate.dependency_fingerprint,
                candidate.precondition_fingerprint,
                candidate.evidence_fingerprint,
                candidate.candidate_set_fingerprint,
            ):
                raise ConsolidationStoreError("plan candidate material fingerprint differs")
        evidence_tables = {
            "RELATION_CANDIDATE": rc.relation_candidates,
            "RELATION_CANDIDATE_EVIDENCE": rc.relation_candidate_evidence,
            "REVIEW_DECISION": rr.review_decisions,
            "FINGERPRINT": schema.fingerprints,
            "TOOL_EXECUTION": schema.tool_executions,
            "TOOL_RESULT": schema.tool_results,
            "EBOOK_COLLECTION_ITEM": w3_schema.ebook_collection_items,
            "EBOOK_COLLECTION_FINDING": w3_schema.ebook_collection_findings,
            "QUALITY_EVIDENCE": cs.consolidation_quality_evidence,
            "CALIBRE_SNAPSHOT": calibre.calibre_library_snapshots,
            "CALIBRE_FINDING": calibre.calibre_reconciliation_findings,
            "CALIBRE_FORMAT": calibre.calibre_library_formats,
            "CALIBRE_SIDECAR": calibre.calibre_library_sidecars,
        }
        for blocker in plan.blockers:
            for ref in blocker.evidence_refs:
                table = evidence_tables.get(ref.kind.value)
                if table is None or connection.execute(select(table.c.id).where(table.c.id == ref.ref_id)).scalar_one_or_none() is None:
                    raise ConsolidationStoreError("plan evidence reference is unknown or missing")
                _validate_reference_lineage(connection, ref.kind.value, ref.ref_id, plan)
        dependency_tables = {
            "CALIBRE_SNAPSHOT": calibre.calibre_library_snapshots,
            "CALIBRE_FINDING": calibre.calibre_reconciliation_findings,
            "CALIBRE_FORMAT": calibre.calibre_library_formats,
            "CALIBRE_SIDECAR": calibre.calibre_library_sidecars,
        }
        for dependency in plan.dependencies:
            if (dependency.snapshot_kind is None) is not (dependency.snapshot_id is None):
                raise ConsolidationStoreError("plan dependency snapshot kind and id must be paired")
            if dependency.snapshot_id is None:
                continue
            table = dependency_tables.get(dependency.snapshot_kind or "")
            if table is None or connection.execute(select(table.c.id).where(table.c.id == str(dependency.snapshot_id))).scalar_one_or_none() is None:
                raise ConsolidationStoreError("plan dependency snapshot is unknown or missing")
            _validate_reference_lineage(
                connection,
                dependency.snapshot_kind or "",
                str(dependency.snapshot_id),
                plan,
            )
        for precondition in plan.preconditions:
            expected_dependency_kind = {
                ConsolidationPreconditionCode.CALIBRE_RELATIONSHIP_UNCHANGED: ConsolidationDependencyKind.CALIBRE,
                ConsolidationPreconditionCode.SIDECAR_RELATIONSHIP_UNCHANGED: ConsolidationDependencyKind.SIDECAR,
                ConsolidationPreconditionCode.ARCHIVE_RELATIONSHIP_UNCHANGED: ConsolidationDependencyKind.ARCHIVE,
            }.get(precondition.code)
            if expected_dependency_kind is not None and precondition.dependency_kind is not expected_dependency_kind:
                raise ConsolidationStoreError("precondition relationship code and dependency kind differ")
            precondition_endpoint = (
                plan.keeper
                if precondition.file_role is ConsolidationFileRole.KEEPER
                else plan.candidate
            )
            if precondition_endpoint is None or (
                precondition.expected_file_id != precondition_endpoint.file_id
                or precondition.expected_observation_id != precondition_endpoint.observation_id
                or precondition.expected_scan_root_id != precondition_endpoint.scan_root_id
                or precondition.expected_scan_run_id != precondition_endpoint.source_scan_run_id
                or precondition.expected_presence_state is not precondition_endpoint.expected_presence_state
                or precondition.expected_full_sha256 != precondition_endpoint.expected_full_sha256
                or precondition.expected_size_bytes != precondition_endpoint.expected_size_bytes
                or precondition.expected_modified_at != precondition_endpoint.expected_modified_at
                or precondition.expected_observed_at != precondition_endpoint.expected_observed_at
            ):
                raise ConsolidationStoreError("plan precondition does not match its role endpoint")
            source = connection.execute(select(schema.file_records.c.scan_root_id, schema.file_records.c.presence_state, schema.file_records.c.size_bytes.label("file_size"), schema.file_records.c.modified_at.label("file_modified"), schema.file_observations.c.file_id, schema.file_observations.c.scan_run_id, schema.file_observations.c.size_bytes.label("observation_size"), schema.file_observations.c.modified_at.label("observation_modified"), schema.file_observations.c.observed_at).select_from(schema.file_records.join(schema.file_observations, schema.file_observations.c.file_id == schema.file_records.c.id)).where(schema.file_records.c.id == str(precondition.expected_file_id), schema.file_observations.c.id == str(precondition.expected_observation_id))).one_or_none()
            if source is None or str(source.scan_root_id) != str(precondition.expected_scan_root_id) or str(source.scan_run_id) != str(precondition.expected_scan_run_id) or str(source.scan_root_id) != str(plan.scan_root_id) or str(source.scan_run_id) != str(plan.source_scan_run_id) or str(source.presence_state) != precondition.expected_presence_state.value or int(source.file_size) != precondition.expected_size_bytes or int(source.observation_size) != precondition.expected_size_bytes or datetime_from_db(str(source.file_modified)) != precondition.expected_modified_at or datetime_from_db(str(source.observation_modified)) != precondition.expected_modified_at or datetime_from_db(str(source.observed_at)) != precondition.expected_observed_at:
                raise ConsolidationStoreError("plan precondition source snapshot is stale")
            full_hash = connection.execute(select(schema.fingerprints.c.id).where(schema.fingerprints.c.target_kind == EntityKind.FILE_OBSERVATION.value, schema.fingerprints.c.target_id == str(precondition.expected_observation_id), schema.fingerprints.c.kind == "FILE_SHA256", schema.fingerprints.c.algorithm == "sha256", schema.fingerprints.c.algorithm_version == "1", schema.fingerprints.c.value == precondition.expected_full_sha256).limit(1)).scalar_one_or_none()
            if full_hash is None:
                raise ConsolidationStoreError("plan precondition full hash evidence is missing")
            if (precondition.dependency_snapshot_kind is None) is not (precondition.dependency_snapshot_id is None):
                raise ConsolidationStoreError("precondition dependency snapshot kind and id must be paired")
            if precondition.dependency_snapshot_id is not None:
                table = dependency_tables.get(precondition.dependency_snapshot_kind or "")
                if table is None or connection.execute(select(table.c.id).where(table.c.id == str(precondition.dependency_snapshot_id))).scalar_one_or_none() is None:
                    raise ConsolidationStoreError("precondition dependency snapshot is unknown or missing")
                _validate_reference_lineage(connection, precondition.dependency_snapshot_kind or "", str(precondition.dependency_snapshot_id), plan)
            if precondition.dependency_kind is not None:
                bound_dependency = next((item for item in plan.dependencies if item.file_role is precondition.file_role and item.kind is precondition.dependency_kind), None)
                if bound_dependency is None or bound_dependency.state is not precondition.dependency_state or bound_dependency.material_fingerprint != precondition.dependency_fingerprint or bound_dependency.snapshot_kind != precondition.dependency_snapshot_kind or bound_dependency.snapshot_id != precondition.dependency_snapshot_id:
                    raise ConsolidationStoreError("precondition dependency binding differs from plan")
            if precondition.review_item_id is not None:
                expected_review_type = ReviewType.KEEP_PREFERENCE if precondition.file_role is ConsolidationFileRole.KEEPER else ReviewType.CONSOLIDATION_CANDIDATE
                compatible = next((review for review in plan.required_reviews if review.review_type is expected_review_type and review.state is ConsolidationReviewState.ACCEPTED and review.review_item_id == precondition.review_item_id and review.decision_id == precondition.review_decision_id and review.decision_sequence_no == precondition.review_decision_sequence_no and review.decision_compatibility_version == precondition.review_decision_compatibility_version and review.evidence_fingerprint == precondition.review_evidence_fingerprint and review.candidate_set_fingerprint == precondition.review_candidate_set_fingerprint), None)
                if compatible is None:
                    raise ConsolidationStoreError("precondition review binding is stale")
        for review in plan.required_reviews:
            if not _review_targets_plan(plan, review):
                raise ConsolidationStoreError("plan review does not match its target material")
            if review.review_type is ReviewType.KEEP_PREFERENCE:
                undirected = (
                    plan.keep_preference is not None
                    and plan.keep_preference.status is KeepPreferenceStatus.PREFERRED
                    and plan.keeper is None
                    and plan.candidate is None
                    and plan.consolidation_candidate is None
                    and not plan.preconditions
                    and not plan.future_operation_intents
                    and all(
                        item.review_type is not ReviewType.CONSOLIDATION_CANDIDATE
                        for item in plan.required_reviews
                    )
                )
                directed = (
                    plan.keep_preference is not None
                    and plan.keep_preference.status is KeepPreferenceStatus.PREFERRED
                    and plan.keeper is not None
                    and plan.candidate is not None
                    and plan.keep_preference.keeper_file_id == plan.keeper.file_id
                    and plan.keep_preference.candidate_file_id == plan.candidate.file_id
                )
                if review.state is ConsolidationReviewState.ACCEPTED:
                    valid_shape = directed
                else:
                    expected_status = (
                        ConsolidationPlanStatus.REVIEW_REQUIRED
                        if review.state
                        in {
                            ConsolidationReviewState.PENDING,
                            ConsolidationReviewState.DEFERRED,
                        }
                        and not plan.blockers
                        else ConsolidationPlanStatus.BLOCKED
                    )
                    valid_shape = undirected and plan.status is expected_status
                if not valid_shape:
                    raise ConsolidationStoreError(
                        "keep-preference review requires exact preferred direction"
                    )
            if review.state in {
                ConsolidationReviewState.PENDING,
                ConsolidationReviewState.DEFERRED,
            } and review.review_item_id is None:
                raise ConsolidationStoreError("waiting plan review requires a review item")
            if review.review_item_id is None:
                continue
            item = connection.execute(
                select(rr.review_items).where(rr.review_items.c.id == str(review.review_item_id))
            ).mappings().one_or_none()
            expected_candidate_id: EntityId | None
            expected_subject_id: EntityId | None
            if review.review_type is ReviewType.KEEP_PREFERENCE:
                expected_candidate_id = None if plan.keep_preference is None else plan.keep_preference.preference_id
                expected_subject_id = None if plan.keep_preference is None else plan.keep_preference.left_file_id
            else:
                expected_candidate_id = None if plan.consolidation_candidate is None else plan.consolidation_candidate.candidate_id
                expected_subject_id = None if plan.consolidation_candidate is None else plan.consolidation_candidate.candidate_file_id
            if item is None or expected_candidate_id is None or expected_subject_id is None or str(item["review_type"]) != review.review_type.value or str(item["candidate_kind"]) != review.candidate_kind.value or str(item["candidate_id"]) != str(expected_candidate_id) or str(item["subject_kind"]) != EntityKind.FILE.value or str(item["subject_id"]) != str(expected_subject_id) or str(item["producer_name"]) != review.producer_name or str(item["producer_version"]) != "1" or str(item["evidence_fingerprint"]) != review.evidence_fingerprint or str(item["candidate_set_fingerprint"]) != review.candidate_set_fingerprint or str(item["decision_compatibility_version"]) != review.decision_compatibility_version:
                raise ConsolidationStoreError("plan review item is incompatible")
            _target_lineage(connection, str(item["subject_kind"]), str(item["subject_id"]), plan)
            latest = connection.execute(
                select(rr.review_decisions)
                .where(rr.review_decisions.c.review_item_id == str(review.review_item_id))
                .order_by(rr.review_decisions.c.sequence_no.desc())
                .limit(1)
            ).mappings().one_or_none()
            expected_item_state = {
                ConsolidationReviewState.PENDING: "PENDING",
                ConsolidationReviewState.DEFERRED: "DEFERRED",
                ConsolidationReviewState.ACCEPTED: "DECIDED",
                ConsolidationReviewState.REJECTED: "DECIDED",
                ConsolidationReviewState.STALE: "STALE",
            }.get(review.state)
            if expected_item_state is None or str(item["state"]) != expected_item_state:
                raise ConsolidationStoreError("plan review item state is stale")
            if review.state is ConsolidationReviewState.PENDING and latest is not None:
                raise ConsolidationStoreError("plan pending review has an unexpected decision")
            if review.state is ConsolidationReviewState.DEFERRED and (
                latest is None
                or str(latest["decision"]) != "DEFER"
                or str(latest["evidence_fingerprint"]) != review.evidence_fingerprint
                or str(latest["candidate_set_fingerprint"])
                != review.candidate_set_fingerprint
                or str(latest["decision_compatibility_version"])
                != review.decision_compatibility_version
            ):
                raise ConsolidationStoreError("plan deferred review lacks its latest decision")
            if review.decision_id is not None and (
                latest is None
                or str(latest["id"]) != str(review.decision_id)
                or int(latest["sequence_no"]) != review.decision_sequence_no
                or str(latest["decision"]) != ("ACCEPT" if review.state is ConsolidationReviewState.ACCEPTED else "REJECT")
                or str(latest["evidence_fingerprint"]) != review.evidence_fingerprint
                or str(latest["candidate_set_fingerprint"]) != review.candidate_set_fingerprint
                or str(latest["decision_compatibility_version"]) != review.decision_compatibility_version
            ):
                raise ConsolidationStoreError("plan review decision is not the compatible latest decision")

    @staticmethod
    def _write_plan_children(connection: Connection, plan: ConsolidationPlan) -> None:
        def many(table: Table, rows: list[dict[str, object]]) -> None:
            if rows:
                connection.execute(insert(table), rows)
        evidence: list[tuple[str, str, str, str]] = []
        quality_roles = {
            ConsolidationFileRole.KEEPER: ConsolidationEvidenceRole.KEEPER_QUALITY,
            ConsolidationFileRole.CANDIDATE: ConsolidationEvidenceRole.CANDIDATE_QUALITY,
        }
        for snapshot in plan.quality_evidence:
            evidence.append((
                quality_roles[snapshot.role].value,
                ConsolidationEvidenceKind.QUALITY_EVIDENCE.value,
                str(snapshot.id),
                snapshot.assessment_fingerprint,
            ))
        for blocker in plan.blockers:
            for ref in blocker.evidence_refs:
                descriptor = (
                    ref.role.value,
                    ref.kind.value,
                    ref.ref_id,
                    ref.material_fingerprint,
                )
                if descriptor not in evidence:
                    evidence.append(descriptor)
        if len(evidence) > 1024:
            raise ConsolidationStoreError("plan evidence exceeds bound")
        many(cs.consolidation_plan_evidence, [{"plan_id": str(plan.id), "ordinal": i, "role": role, "kind": kind, "ref_id": ref_id, "material_fingerprint": fingerprint} for i, (role, kind, ref_id, fingerprint) in enumerate(evidence)])
        many(cs.consolidation_plan_dependencies, [{"plan_id": str(plan.id), "ordinal": i, "file_role": x.file_role.value, "kind": x.kind.value, "state": x.state.value, "snapshot_kind": x.snapshot_kind, "snapshot_id": None if x.snapshot_id is None else str(x.snapshot_id), "material_fingerprint": x.material_fingerprint} for i, x in enumerate(plan.dependencies)])
        many(cs.consolidation_plan_reviews, [{"plan_id": str(plan.id), "ordinal": i, "review_type": x.review_type.value, "state": x.state.value, "review_item_id": None if x.review_item_id is None else str(x.review_item_id), "decision_id": None if x.decision_id is None else str(x.decision_id), "decision_sequence_no": x.decision_sequence_no, "producer_name": x.producer_name, "producer_version": "1", "decision_compatibility_version": x.decision_compatibility_version, "evidence_fingerprint": x.evidence_fingerprint, "candidate_set_fingerprint": x.candidate_set_fingerprint} for i, x in enumerate(plan.required_reviews)])
        many(cs.consolidation_plan_preconditions, [_precondition_row(plan, i, x) for i, x in enumerate(plan.preconditions)])
        many(cs.consolidation_plan_intents, [{"plan_id": str(plan.id), "ordinal": i, "code": x.code.value, "file_role": x.file_role.value} for i, x in enumerate(plan.future_operation_intents)])
        many(cs.consolidation_plan_blockers, [{"plan_id": str(plan.id), "ordinal": i, "code": x.code.value} for i, x in enumerate(plan.blockers)])
        links: list[dict[str, object]] = []
        for blocker_ordinal, blocker in enumerate(plan.blockers):
            for evidence_ordinal, ref in enumerate(blocker.evidence_refs):
                descriptor = (ref.role.value, ref.kind.value, ref.ref_id, ref.material_fingerprint)
                links.append({"plan_id": str(plan.id), "blocker_ordinal": blocker_ordinal, "evidence_ordinal": evidence_ordinal, "evidence_plan_ordinal": evidence.index(descriptor)})
        many(cs.consolidation_plan_blocker_evidence, links)


def _collection_children(connection: Connection, item_id: str) -> tuple[tuple[ConsolidationQualityItemExecution, ...], tuple[ConsolidationQualityFinding, ...]]:
    execution_rows = connection.execute(select(w3_schema.ebook_collection_item_executions).where(w3_schema.ebook_collection_item_executions.c.item_id == item_id).order_by(w3_schema.ebook_collection_item_executions.c.ordinal).limit(65)).mappings().all()
    if len(execution_rows) > 64:
        raise ConsolidationStoreError("quality item executions exceed bound")
    executions = tuple(ConsolidationQualityItemExecution(int(row["ordinal"]), str(row["step_name"]), ConsolidationQualityExecutionDisposition(str(row["disposition"])), EntityId.parse(str(row["execution_id"]))) for row in execution_rows)
    finding_rows = connection.execute(select(w3_schema.ebook_collection_findings).where(w3_schema.ebook_collection_findings.c.item_id == item_id).order_by(w3_schema.ebook_collection_findings.c.ordinal).limit(257)).mappings().all()
    if len(finding_rows) > 256:
        raise ConsolidationStoreError("quality findings exceed bound")
    findings = []
    for row in finding_rows:
        refs = connection.execute(select(w3_schema.ebook_collection_finding_executions.c.ordinal, w3_schema.ebook_collection_finding_executions.c.execution_id).where(w3_schema.ebook_collection_finding_executions.c.finding_id == str(row["id"])).order_by(w3_schema.ebook_collection_finding_executions.c.ordinal).limit(65)).all()
        if len(refs) > 64 or tuple(int(ref.ordinal) for ref in refs) != tuple(range(len(refs))):
            raise ConsolidationStoreError("quality finding references are invalid or exceed bound")
        findings.append(ConsolidationQualityFinding(int(row["ordinal"]), str(row["code"]), EbookQualityDimensionName(str(row["dimension"])), EbookQualityFindingSeverity(str(row["severity"])), tuple(EntityId.parse(str(ref.execution_id)) for ref in refs)))
    return executions, tuple(findings)


def _persisted_quality_assessment(
    connection: Connection,
    value: ConsolidationQualityEvidence,
    item_executions: tuple[ConsolidationQualityItemExecution, ...],
) -> EbookQualityAssessment:
    execution_ids = tuple(str(item.execution_id) for item in item_executions)
    execution_codec = codec_for(ToolExecution)
    result_codec = codec_for(ToolResult)
    execution_rows = (
        connection.execute(select(schema.tool_executions).where(schema.tool_executions.c.id.in_(execution_ids)).limit(65)).mappings().all()
        if execution_ids
        else []
    )
    if len(execution_rows) != len(execution_ids):
        raise ConsolidationStoreError("quality tool execution is missing")
    executions = {str(row["id"]): execution_codec.decode(row) for row in execution_rows}
    expected_input = f"file-observation:{value.observation_id}"
    if any(execution.input_identity != expected_input for execution in executions.values()):
        raise ConsolidationStoreError("quality tool execution belongs to foreign observation")
    result_rows = (
        connection.execute(select(schema.tool_results).where(schema.tool_results.c.execution_id.in_(execution_ids)).order_by(schema.tool_results.c.id).limit(16_385)).mappings().all()
        if execution_ids
        else []
    )
    if len(result_rows) > 16_384:
        raise ConsolidationStoreError("quality tool results exceed bound")
    results = tuple(result_codec.decode(row) for row in result_rows)
    if any(result.target_kind is not EntityKind.FILE_OBSERVATION or result.target_id != value.observation_id for result in results):
        raise ConsolidationStoreError("quality tool result belongs to foreign observation")
    results_by_execution = {
        execution_id: tuple(result for result in results if str(result.execution_id) == execution_id)
        for execution_id in execution_ids
    }
    steps_by_name: dict[str, EbookAnalysisStepOutcome] = {}
    index = 0
    while index < len(item_executions):
        first = item_executions[index]
        group: list[ConsolidationQualityItemExecution] = []
        while index < len(item_executions) and item_executions[index].step_name == first.step_name:
            group.append(item_executions[index])
            index += 1
        group_executions = tuple(executions[str(item.execution_id)] for item in group)
        group_results = tuple(
            result
            for item in group
            for result in results_by_execution[str(item.execution_id)]
        )
        facts = _quality_step_facts(first.step_name, group_executions, group_results, results_by_execution)
        disposition = (
            EbookAnalysisStepDisposition.REUSED
            if first.disposition is ConsolidationQualityExecutionDisposition.REUSED
            else EbookAnalysisStepDisposition.EXECUTED
        )
        steps_by_name[first.step_name] = EbookAnalysisStepOutcome(first.step_name, group_executions, facts, disposition=disposition)
    expected_names = (
        ("pdf-analysis",)
        if value.format_label == "PDF"
        else ("metadata", "text", "cover")
        + (("structural-validation",) if value.format_label == "EPUB" else ())
    )
    if not set(steps_by_name) <= set(expected_names):
        raise ConsolidationStoreError("quality tool execution has an unexpected workflow step")
    steps = tuple(
        steps_by_name.get(name) or EbookAnalysisStepOutcome(name, error="persisted step unavailable")
        for name in expected_names
    )
    return evaluate_ebook_quality(value.observation_id, value.format_label, steps)


def _quality_step_facts(
    step_name: str,
    executions: tuple[ToolExecution, ...],
    results: tuple[ToolResult, ...],
    results_by_execution: dict[str, tuple[ToolResult, ...]],
) -> tuple[tuple[str, str], ...]:
    succeeded = all(execution.status.value == "SUCCEEDED" for execution in executions)
    values = {result.key: result.value for result in results}
    if step_name == "metadata":
        observations = tuple(result for result in results if result.result_type == "calibre_metadata")
        candidates = tuple(result for result in results if result.result_type == "ebook_metadata_candidate")
        if not succeeded:
            return ()
        return (
            ("metadata_observation_count", str(len(observations))),
            ("metadata_candidate_count", str(len(candidates))),
            *_metadata_presence_facts(results),
        )
    if step_name == "text":
        return _selected_facts(values, ("text_status", "normalized_character_count"))
    if step_name == "cover":
        return _selected_facts(values, ("cover_status", "image_format", "display_width", "display_height"))
    if step_name == "structural-validation":
        facts = _selected_facts(values, ("conformance_status", "fatal_count", "error_count", "warning_count", "usage_count", "info_count"))
        if succeeded:
            facts += (("diagnostic_code_count", str(sum(key.startswith("diagnostic.") for key in values))),)
        return facts
    if step_name == "pdf-analysis":
        if len(executions) != 2:
            return ()
        info_results = results_by_execution[str(executions[0].id)]
        text_results = results_by_execution[str(executions[1].id)]
        info_values = {result.key: result.value for result in info_results}
        text_values = {result.key: result.value for result in text_results}
        pdf_facts: tuple[tuple[str, str], ...] = ()
        if executions[0].status.value == "SUCCEEDED":
            pdf_facts = (("metadata_observation_count", str(len(info_results))),)
            pdf_facts += _pdf_metadata_presence_facts(info_values)
            pdf_facts += _selected_facts(info_values, ("page_count", "encrypted", "pdf_version", "pdf_subtype"))
        pdf_facts += _selected_facts(text_values, ("text_status", "normalized_character_count"))
        return pdf_facts
    return ()


def _selected_facts(
    values: dict[str, str],
    keys: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple((key, values[key]) for key in keys if key in values)


def _metadata_presence_facts(results: tuple[ToolResult, ...]) -> tuple[tuple[str, str], ...]:
    values = {result.key: result.value for result in results}
    contributor_keys = tuple((key.split("."), value) for key, value in values.items())
    contributor_present = any(len(parts) >= 3 and parts[0] == "contributor" and parts[2] == "name" and bool(value.strip()) for parts, value in contributor_keys)
    author_present = any(len(parts) >= 3 and parts[0] == "contributor" and ((parts[2] == "role" and value.strip().lower() == "author") or (parts[2] == "source_element" and value.strip().lower() == "creator")) for parts, value in contributor_keys)
    identifier_present = any(len(parts) >= 3 and parts[0] == "identifier" and parts[2] == "value" and bool(value.strip()) for parts, value in contributor_keys)
    series_present = any(len(parts) >= 3 and parts[0] == "series" and parts[2] == "name" and bool(value.strip()) for parts, value in contributor_keys)
    series_position_present = any(len(parts) >= 3 and parts[0] == "series" and parts[2] == "position" and bool(value.strip()) for parts, value in contributor_keys)
    presence = (
        ("title_present", bool(values.get("title", "").strip())),
        ("author_present", author_present),
        ("contributor_present", contributor_present),
        ("language_present", bool(values.get("language", "").strip())),
        ("identifier_present", identifier_present),
        ("publisher_present", bool(values.get("publisher", "").strip())),
        ("publication_date_present", bool(values.get("publication_date", "").strip())),
        ("series_present", series_present),
        ("series_position_present", series_position_present),
    )
    return tuple((key, "true" if present else "false") for key, present in presence)


def _pdf_metadata_presence_facts(values: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return (
        ("title_present", "true" if values.get("title", "").strip() else "false"),
        ("author_present", "true" if values.get("author", "").strip() else "false"),
    )


def _quality_row(x: ConsolidationQualityEvidence) -> dict[str, object]:
    dimensions = {item.name.value.lower(): item.status.value for item in x.dimensions}
    return {"id": str(x.id), "profile": x.profile, "collection_run_id": str(x.collection_run_id), "collection_item_id": str(x.collection_item_id), "observation_id": str(x.observation_id), "scan_root_id": str(x.scan_root_id), "source_scan_run_id": str(x.source_scan_run_id), "collection_profile": x.collection_profile, "analysis_profile": x.analysis_profile, "quality_profile": x.quality_profile, "format_label": x.format_label, "item_status": x.item_status.value, "aggregate_quality_status": x.aggregate_quality_status.value, "reused_step_count": x.reused_step_count, "executed_step_count": x.executed_step_count, "finding_count": x.finding_count, **{f"{key}_status": value for key, value in dimensions.items()}, "assessment_fingerprint": x.assessment_fingerprint, "created_at": datetime_to_db(x.created_at)}


def _quality_material(row: RowMapping | dict[str, object]) -> tuple[object, ...]:
    return tuple(row[key] for key in cs.consolidation_quality_evidence.c.keys() if key not in {"id", "created_at"})


def _insert_exact(connection: Connection, table: Table, row: dict[str, object]) -> None:
    inserted = connection.execute(insert(table).values(**row).prefix_with("OR IGNORE"))
    if inserted.rowcount == 1:
        return
    primary = tuple(table.primary_key.columns)
    existing = connection.execute(select(table).where(*(column == row[column.name] for column in primary))).mappings().one_or_none()
    if existing is None or any(existing[key] != value for key, value in row.items() if key != "created_at"):
        raise ConsolidationStoreError("consolidation child retry payload differs")


def _validate_reference_lineage(
    connection: Connection,
    kind: str,
    ref_id: str,
    plan: ConsolidationPlan,
) -> None:
    lineage: Any = None
    if kind == "RELATION_CANDIDATE":
        lineage = connection.execute(select(rc.relation_candidates.c.scan_root_id, rc.relation_candidates.c.source_scan_run_id).where(rc.relation_candidates.c.id == ref_id)).one_or_none()
    elif kind == "RELATION_CANDIDATE_EVIDENCE":
        lineage = connection.execute(select(rc.relation_candidates.c.scan_root_id, rc.relation_candidates.c.source_scan_run_id).select_from(rc.relation_candidate_evidence.join(rc.relation_candidates, rc.relation_candidate_evidence.c.relation_candidate_id == rc.relation_candidates.c.id)).where(rc.relation_candidate_evidence.c.id == ref_id)).one_or_none()
    elif kind == "QUALITY_EVIDENCE":
        lineage = connection.execute(select(cs.consolidation_quality_evidence.c.scan_root_id, cs.consolidation_quality_evidence.c.source_scan_run_id).where(cs.consolidation_quality_evidence.c.id == ref_id)).one_or_none()
    elif kind == "EBOOK_COLLECTION_ITEM":
        lineage = connection.execute(select(w3_schema.ebook_collection_runs.c.scan_root_id, w3_schema.ebook_collection_runs.c.source_scan_run_id).select_from(w3_schema.ebook_collection_items.join(w3_schema.ebook_collection_runs, w3_schema.ebook_collection_items.c.run_id == w3_schema.ebook_collection_runs.c.id)).where(w3_schema.ebook_collection_items.c.id == ref_id)).one_or_none()
    elif kind == "EBOOK_COLLECTION_FINDING":
        lineage = connection.execute(select(w3_schema.ebook_collection_runs.c.scan_root_id, w3_schema.ebook_collection_runs.c.source_scan_run_id).select_from(w3_schema.ebook_collection_findings.join(w3_schema.ebook_collection_items, w3_schema.ebook_collection_findings.c.item_id == w3_schema.ebook_collection_items.c.id).join(w3_schema.ebook_collection_runs, w3_schema.ebook_collection_items.c.run_id == w3_schema.ebook_collection_runs.c.id)).where(w3_schema.ebook_collection_findings.c.id == ref_id)).one_or_none()
    elif kind == "FINGERPRINT":
        target = connection.execute(select(schema.fingerprints.c.target_kind, schema.fingerprints.c.target_id).where(schema.fingerprints.c.id == ref_id)).one()
        lineage = _target_lineage(connection, str(target.target_kind), str(target.target_id), plan)
    elif kind == "TOOL_RESULT":
        target = connection.execute(select(schema.tool_results.c.target_kind, schema.tool_results.c.target_id).where(schema.tool_results.c.id == ref_id)).one()
        lineage = _target_lineage(connection, str(target.target_kind), str(target.target_id), plan)
    elif kind == "TOOL_EXECUTION":
        lineages: list[tuple[object, object]] = []
        collection_rows = connection.execute(select(w3_schema.ebook_collection_runs.c.scan_root_id, w3_schema.ebook_collection_runs.c.source_scan_run_id).select_from(w3_schema.ebook_collection_item_executions.join(w3_schema.ebook_collection_items, w3_schema.ebook_collection_item_executions.c.item_id == w3_schema.ebook_collection_items.c.id).join(w3_schema.ebook_collection_runs, w3_schema.ebook_collection_items.c.run_id == w3_schema.ebook_collection_runs.c.id)).where(w3_schema.ebook_collection_item_executions.c.execution_id == ref_id)).all()
        lineages.extend((row.scan_root_id, row.source_scan_run_id) for row in collection_rows)
        target_rows = connection.execute(select(schema.fingerprints.c.target_kind, schema.fingerprints.c.target_id).where(schema.fingerprints.c.tool_execution_id == ref_id)).all()
        result_rows = connection.execute(select(schema.tool_results.c.target_kind, schema.tool_results.c.target_id).where(schema.tool_results.c.execution_id == ref_id)).all()
        for target in (*target_rows, *result_rows):
            resolved = _target_lineage(connection, str(target.target_kind), str(target.target_id), plan)
            lineages.append((resolved.scan_root_id, resolved.source_scan_run_id))
        if not lineages:
            raise ConsolidationStoreError("tool execution evidence has no collection lineage")
        if any(str(root_id) != str(plan.scan_root_id) or str(scan_id) != str(plan.source_scan_run_id) for root_id, scan_id in lineages):
            raise ConsolidationStoreError("plan evidence reference belongs to foreign lineage")
        return
    elif kind == "REVIEW_DECISION":
        decision = connection.execute(select(rr.review_decisions, rr.review_items.c.subject_kind, rr.review_items.c.subject_id, rr.review_items.c.state.label("review_state"), rr.review_items.c.evidence_fingerprint.label("item_evidence_fingerprint"), rr.review_items.c.candidate_set_fingerprint.label("item_candidate_set_fingerprint"), rr.review_items.c.decision_compatibility_version.label("item_compatibility")).select_from(rr.review_decisions.join(rr.review_items, rr.review_decisions.c.review_item_id == rr.review_items.c.id)).where(rr.review_decisions.c.id == ref_id)).mappings().one()
        latest_id = connection.execute(select(rr.review_decisions.c.id).where(rr.review_decisions.c.review_item_id == str(decision["review_item_id"])).order_by(rr.review_decisions.c.sequence_no.desc()).limit(1)).scalar_one()
        if (
            str(latest_id) != ref_id
            or str(decision["review_state"]) == "STALE"
            or str(decision["evidence_fingerprint"]) != str(decision["item_evidence_fingerprint"])
            or str(decision["candidate_set_fingerprint"]) != str(decision["item_candidate_set_fingerprint"])
            or str(decision["decision_compatibility_version"]) != str(decision["item_compatibility"])
        ):
            raise ConsolidationStoreError("review decision evidence is stale")
        lineage = _target_lineage(connection, str(decision["subject_kind"]), str(decision["subject_id"]), plan)
    elif kind == "CALIBRE_SNAPSHOT":
        lineage = connection.execute(select(calibre.calibre_library_snapshots.c.scan_root_id, calibre.calibre_library_snapshots.c.source_scan_run_id).where(calibre.calibre_library_snapshots.c.id == ref_id)).one_or_none()
    elif kind == "CALIBRE_FINDING":
        lineage = connection.execute(select(calibre.calibre_library_snapshots.c.scan_root_id, calibre.calibre_library_snapshots.c.source_scan_run_id).select_from(calibre.calibre_reconciliation_findings.join(calibre.calibre_library_snapshots, calibre.calibre_reconciliation_findings.c.snapshot_id == calibre.calibre_library_snapshots.c.id)).where(calibre.calibre_reconciliation_findings.c.id == ref_id)).one_or_none()
    elif kind in {"CALIBRE_FORMAT", "CALIBRE_SIDECAR"}:
        child = calibre.calibre_library_formats if kind == "CALIBRE_FORMAT" else calibre.calibre_library_sidecars
        lineage = connection.execute(select(calibre.calibre_library_snapshots.c.scan_root_id, calibre.calibre_library_snapshots.c.source_scan_run_id).select_from(child.join(calibre.calibre_library_records, child.c.record_snapshot_id == calibre.calibre_library_records.c.id).join(calibre.calibre_library_snapshots, calibre.calibre_library_records.c.snapshot_id == calibre.calibre_library_snapshots.c.id)).where(child.c.id == ref_id)).one_or_none()
    if lineage is None:
        raise ConsolidationStoreError("plan evidence reference has no verifiable lineage")
    if (
        str(lineage.scan_root_id) != str(plan.scan_root_id)
        or str(lineage.source_scan_run_id) != str(plan.source_scan_run_id)
    ):
        raise ConsolidationStoreError("plan evidence reference belongs to foreign lineage")


def _target_lineage(
    connection: Connection,
    target_kind: str,
    target_id: str,
    plan: ConsolidationPlan,
) -> _Lineage:
    if target_kind == EntityKind.FILE.value:
        row = connection.execute(select(schema.file_records.c.scan_root_id, schema.file_observations.c.scan_run_id.label("source_scan_run_id")).select_from(schema.file_records.join(schema.file_observations, schema.file_observations.c.file_id == schema.file_records.c.id)).where(schema.file_records.c.id == target_id, schema.file_observations.c.scan_run_id == str(plan.source_scan_run_id))).one_or_none()
    elif target_kind == EntityKind.FILE_OBSERVATION.value:
        row = connection.execute(select(schema.file_records.c.scan_root_id, schema.file_observations.c.scan_run_id.label("source_scan_run_id")).select_from(schema.file_observations.join(schema.file_records, schema.file_observations.c.file_id == schema.file_records.c.id)).where(schema.file_observations.c.id == target_id)).one_or_none()
    else:
        raise ConsolidationStoreError("evidence target kind has no file lineage")
    if row is None:
        raise ConsolidationStoreError("evidence target is missing or stale")
    return _Lineage(row.scan_root_id, row.source_scan_run_id)


def _plan_row(x: ConsolidationPlan) -> dict[str, object]:
    return {"id": str(x.id), "profile": x.profile, "plan_version": x.plan_version, "serializer_version": x.serializer_version, "scan_root_id": str(x.scan_root_id), "source_scan_run_id": str(x.source_scan_run_id), "relation_candidate_id": None if x.identity is None else str(x.identity.relation_candidate_id), "keep_preference_id": None if x.keep_preference is None else str(x.keep_preference.preference_id), "consolidation_candidate_id": None if x.consolidation_candidate is None else str(x.consolidation_candidate.candidate_id), "keeper_file_id": None if x.keeper is None else str(x.keeper.file_id), "keeper_observation_id": None if x.keeper is None else str(x.keeper.observation_id), "candidate_file_id": None if x.candidate is None else str(x.candidate.file_id), "candidate_observation_id": None if x.candidate is None else str(x.candidate.observation_id), "status": x.status.value, "execution_state": x.execution_state.value, "content_hash": x.content_hash, "created_at": datetime_to_db(x.created_at)}


def _precondition_row(plan: ConsolidationPlan, ordinal: int, x: ConsolidationFilePreconditionSnapshot) -> dict[str, object]:
    return {"plan_id": str(plan.id), "ordinal": ordinal, "file_role": x.file_role.value, "code": x.code.value, "expected_file_id": str(x.expected_file_id), "expected_observation_id": str(x.expected_observation_id), "expected_scan_root_id": str(x.expected_scan_root_id), "expected_scan_run_id": str(x.expected_scan_run_id), "expected_presence_state": x.expected_presence_state.value, "expected_full_sha256": x.expected_full_sha256, "expected_size_bytes": x.expected_size_bytes, "expected_modified_at": datetime_to_db(x.expected_modified_at), "expected_observed_at": datetime_to_db(x.expected_observed_at), "dependency_kind": None if x.dependency_kind is None else x.dependency_kind.value, "dependency_state": None if x.dependency_state is None else x.dependency_state.value, "dependency_fingerprint": x.dependency_fingerprint, "dependency_snapshot_kind": x.dependency_snapshot_kind, "dependency_snapshot_id": None if x.dependency_snapshot_id is None else str(x.dependency_snapshot_id), "review_item_id": None if x.review_item_id is None else str(x.review_item_id), "review_decision_id": None if x.review_decision_id is None else str(x.review_decision_id), "review_decision_sequence_no": x.review_decision_sequence_no, "review_decision_compatibility_version": x.review_decision_compatibility_version, "review_evidence_fingerprint": x.review_evidence_fingerprint, "review_candidate_set_fingerprint": x.review_candidate_set_fingerprint}


def _precondition_from_row(x: RowMapping) -> ConsolidationFilePreconditionSnapshot:
    return ConsolidationFilePreconditionSnapshot(
        ConsolidationFileRole(str(x["file_role"])),
        ConsolidationPreconditionCode(str(x["code"])),
        EntityId.parse(str(x["expected_file_id"])),
        EntityId.parse(str(x["expected_observation_id"])),
        EntityId.parse(str(x["expected_scan_root_id"])),
        EntityId.parse(str(x["expected_scan_run_id"])),
        PresenceState(str(x["expected_presence_state"])),
        str(x["expected_full_sha256"]),
        int(x["expected_size_bytes"]),
        datetime.fromisoformat(str(x["expected_modified_at"])),
        datetime.fromisoformat(str(x["expected_observed_at"])),
        None if x["dependency_kind"] is None else ConsolidationDependencyKind(str(x["dependency_kind"])),
        None if x["dependency_state"] is None else ConsolidationDependencyState(str(x["dependency_state"])),
        None if x["dependency_fingerprint"] is None else str(x["dependency_fingerprint"]),
        None if x["dependency_snapshot_kind"] is None else str(x["dependency_snapshot_kind"]),
        None if x["dependency_snapshot_id"] is None else EntityId.parse(str(x["dependency_snapshot_id"])),
        None if x["review_item_id"] is None else EntityId.parse(str(x["review_item_id"])),
        None if x["review_decision_id"] is None else EntityId.parse(str(x["review_decision_id"])),
        None if x["review_decision_sequence_no"] is None else int(x["review_decision_sequence_no"]),
        None if x["review_decision_compatibility_version"] is None else str(x["review_decision_compatibility_version"]),
        None if x["review_evidence_fingerprint"] is None else str(x["review_evidence_fingerprint"]),
        None if x["review_candidate_set_fingerprint"] is None else str(x["review_candidate_set_fingerprint"]),
    )


__all__ = ["ConsolidationStoreError", "SQLiteConsolidationStore"]
