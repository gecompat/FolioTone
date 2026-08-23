"""Application service for non-mutating e-book rename planning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import Engine, func, select
from sqlalchemy.engine import Connection, RowMapping

from foliotone.core import (
    EntityId,
    EntityKind,
    PresenceState,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
    ScanRunStatus,
)
from foliotone.ebook_operation_recipes import (
    EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY,
    EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
    EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationEvidenceReference,
    EbookOperationKind,
    EbookOperationPlanStatus,
    EbookOperationProcessorKind,
    EbookOperationRecipeCandidate,
    EbookOperationRecipeCandidateInputs,
    EbookOperationRecipePlan,
    EbookOperationRecipePlanInputs,
    EbookOperationReviewSnapshot,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationTargetSnapshot,
    build_ebook_operation_expected_output,
    build_ebook_operation_processor_requirement,
    build_ebook_operation_recipe_candidate,
    build_ebook_operation_recipe_plan,
    build_ebook_operation_source_snapshot,
    operation_target_kind,
    required_verification_codes,
)
from foliotone.ebook_rename import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EBOOK_RENAME_PROCESSOR_PROFILE,
    EbookRenameDependencyScopeMode,
    EbookRenameDependencyScopeUnavailable,
    EbookRenameDependencySnapshotKind,
    EbookRenameTargetError,
    ResolvedEbookRenameDependencyScope,
    build_ebook_rename_target_locator,
    ebook_rename_dependency_axis_material_fingerprint,
    ebook_rename_dependency_scope_material_fingerprint,
)
from foliotone.persistence import (
    EbookOperationRecipeStoreError,
    ResolutionReviewStoreError,
    SQLiteEbookOperationRecipeStore,
    SQLiteResolutionReviewStore,
    archive_collection_schema,
    archive_schema,
    calibre_library_schema,
    schema,
)
from foliotone.persistence._mapping import required_datetime_from_db

_DEPENDENCY_COVERAGE_PROFILE = "ebook-rename-dependency-coverage/v1"
_DEPENDENCY_COVERAGE_PROVIDER = "foliotone-ebook-dependency-audit"
_DEPENDENCY_COVERAGE_ADAPTER = "ebook-rename-dependency-audit/1"


class EbookRenamePlanningError(RuntimeError):
    """One stable path-free error from the RN01 application boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EbookRenameDependencyScopePort(Protocol):
    def resolve(
        self,
        dependency_scope_id: EntityId,
    ) -> ResolvedEbookRenameDependencyScope: ...

    def all_scopes(self) -> tuple[ResolvedEbookRenameDependencyScope, ...]: ...


@dataclass(frozen=True, slots=True)
class EbookRenameProposalResult:
    candidate_id: EntityId
    review_item_id: EntityId
    review_state: EbookOperationReviewState
    dependency_states: tuple[EbookOperationDependencyState, ...]


@dataclass(frozen=True, slots=True)
class EbookRenamePreview:
    candidate_id: EntityId
    candidate_profile: str
    operation_kind: EbookOperationKind
    status: EbookOperationPlanStatus
    review_state: EbookOperationReviewState
    source_count: int
    dependency_count: int
    evidence_count: int
    blocker_codes: tuple[str, ...]
    source_relative_locator: str = field(repr=False)
    target_relative_locator: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class EbookRenameReviewResult:
    candidate_id: EntityId
    review_item_id: EntityId
    decision_id: EntityId
    decision: ReviewDecisionValue
    sequence_no: int


@dataclass(frozen=True, slots=True)
class EbookRenamePlanResult:
    plan_id: EntityId
    candidate_id: EntityId
    status: EbookOperationPlanStatus
    review_state: EbookOperationReviewState
    blocker_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CurrentSource:
    scan_root_id: EntityId
    scan_run_id: EntityId
    file_id: EntityId
    observation_id: EntityId
    relative_locator: str = field(repr=False)
    size_bytes: int
    modified_at: datetime
    observed_at: datetime
    full_sha256: str = field(repr=False)
    fingerprint_id: EntityId
    fingerprint_material: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _DependencyPresence:
    snapshot_kind: str
    snapshot_id: EntityId
    snapshot_material: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PlanChecks:
    lineage_matches: bool
    source_evidence_complete: bool
    target_valid: bool
    output_identity_valid: bool
    processor_requirement_valid: bool
    preconditions_complete: bool
    recovery_contract_complete: bool
    verification_contract_complete: bool


class EbookRenamePlanningService:
    """Create and review exactly one non-executable same-parent rename recipe."""

    def __init__(
        self,
        engine: Engine,
        dependency_scopes: EbookRenameDependencyScopePort,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], EntityId] | None = None,
    ) -> None:
        self._engine = engine
        self._dependency_scopes = dependency_scopes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or EntityId.new
        self._recipes = SQLiteEbookOperationRecipeStore(engine)
        self._reviews = SQLiteResolutionReviewStore(engine)

    def propose(
        self,
        observation_id: EntityId,
        dependency_scope_id: EntityId,
        target_basename: str,
    ) -> EbookRenameProposalResult:
        try:
            source = self._load_current_source(observation_id)
            target_locator, format_label = build_ebook_rename_target_locator(
                source.relative_locator,
                target_basename,
            )
            if self._target_has_history(source.scan_root_id, target_locator):
                raise EbookRenamePlanningError("TARGET_HISTORY_PRESENT")
            scope = self._dependency_scopes.resolve(dependency_scope_id)
            if scope.scan_root_id != source.scan_root_id:
                raise EbookRenamePlanningError("DEPENDENCY_SCOPE_MISMATCH")
            with self._engine.connect() as connection:
                dependencies, dependency_evidence = self._resolve_dependencies(
                    connection,
                    source,
                    scope,
                )
            candidate = self._build_candidate(
                source,
                target_locator,
                format_label,
                dependencies,
                dependency_evidence,
            )
            stored_candidate = self._recipes.create_or_get_candidate(candidate)
            review = self._recipes.get_latest_review(stored_candidate.id)
            review_item_id = review.review_item_id
            if review_item_id is None:
                item = self._reviews.enqueue_or_get_review(
                    ReviewItem(
                        id=self._id_factory(),
                        review_type=ReviewType.EBOOK_OPERATION_RECIPE,
                        subject_kind=EntityKind.FILE,
                        subject_id=stored_candidate.sources[0].file_id,
                        candidate_kind=(
                            ReviewCandidateKind.EBOOK_OPERATION_RECIPE_CANDIDATE
                        ),
                        candidate_id=stored_candidate.id,
                        producer_name=EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
                        producer_version=EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
                        decision_compatibility_version=(
                            EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY
                        ),
                        evidence_fingerprint=stored_candidate.evidence_fingerprint,
                        candidate_set_fingerprint=stored_candidate.content_hash,
                        state=ReviewItemState.PENDING,
                        created_at=self._now(),
                    )
                )
                review_item_id = item.id
                review = self._recipes.get_latest_review(stored_candidate.id)
            return EbookRenameProposalResult(
                candidate_id=stored_candidate.id,
                review_item_id=review_item_id,
                review_state=review.state,
                dependency_states=tuple(
                    value.state for value in stored_candidate.dependencies
                ),
            )
        except EbookRenamePlanningError:
            raise
        except EbookRenameTargetError as error:
            raise EbookRenamePlanningError(error.code) from None
        except EbookRenameDependencyScopeUnavailable:
            raise EbookRenamePlanningError("DEPENDENCY_SCOPE_UNAVAILABLE") from None
        except (EbookOperationRecipeStoreError, ResolutionReviewStoreError):
            raise EbookRenamePlanningError("PERSISTENCE_FAILED") from None

    def preview(self, candidate_id: EntityId) -> EbookRenamePreview:
        candidate = self._require_rename_candidate(candidate_id)
        review = self._recipes.get_latest_review(candidate.id)
        plan = self._build_current_plan(candidate, review)
        return EbookRenamePreview(
            candidate_id=candidate.id,
            candidate_profile=candidate.profile,
            operation_kind=candidate.operation_kind,
            status=plan.status,
            review_state=plan.review.state,
            source_count=len(candidate.sources),
            dependency_count=len(candidate.dependencies),
            evidence_count=len(candidate.evidence_refs),
            blocker_codes=tuple(value.code.value for value in plan.blockers),
            source_relative_locator=candidate.sources[0].relative_locator,
            target_relative_locator=candidate.target.relative_locator,
        )

    def review(
        self,
        candidate_id: EntityId,
        decision: ReviewDecisionValue,
    ) -> EbookRenameReviewResult:
        candidate = self._require_rename_candidate(candidate_id)
        if not isinstance(decision, ReviewDecisionValue):
            raise EbookRenamePlanningError("REVIEW_DECISION_INVALID")
        snapshot = self._recipes.get_latest_review(candidate.id)
        if snapshot.review_item_id is None:
            raise EbookRenamePlanningError("REVIEW_ITEM_UNAVAILABLE")
        latest = self._reviews.get_effective_decision(snapshot.review_item_id)
        reason = {
            ReviewDecisionValue.ACCEPT: "EBOOK_RENAME_ACCEPTED",
            ReviewDecisionValue.REJECT: "EBOOK_RENAME_REJECTED",
            ReviewDecisionValue.DEFER: "EBOOK_RENAME_DEFERRED",
        }[decision]
        try:
            stored = self._reviews.append_decision(
                ReviewDecision(
                    id=self._id_factory(),
                    review_item_id=snapshot.review_item_id,
                    sequence_no=1 if latest is None else latest.sequence_no + 1,
                    decision=decision,
                    decision_reason=reason,
                    evidence_fingerprint=candidate.evidence_fingerprint,
                    candidate_set_fingerprint=candidate.content_hash,
                    decision_compatibility_version=(
                        EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY
                    ),
                    actor_kind=ReviewActorKind.USER,
                    decided_at=self._now(),
                ),
                expected_latest_decision_id=None if latest is None else latest.id,
            )
        except ResolutionReviewStoreError:
            raise EbookRenamePlanningError("REVIEW_HISTORY_CHANGED") from None
        return EbookRenameReviewResult(
            candidate_id=candidate.id,
            review_item_id=stored.review_item_id,
            decision_id=stored.id,
            decision=stored.decision,
            sequence_no=stored.sequence_no,
        )

    def plan(self, candidate_id: EntityId) -> EbookRenamePlanResult:
        candidate = self._require_rename_candidate(candidate_id)
        review = self._recipes.get_latest_review(candidate.id)
        plan = self._build_current_plan(candidate, review)
        try:
            stored = self._recipes.create_or_get_plan(plan)
        except EbookOperationRecipeStoreError:
            raise EbookRenamePlanningError("PLAN_STATE_CHANGED") from None
        return EbookRenamePlanResult(
            plan_id=stored.id,
            candidate_id=stored.candidate.id,
            status=stored.status,
            review_state=stored.review.state,
            blocker_codes=tuple(value.code.value for value in stored.blockers),
        )

    def current_dependency_scope(
        self,
        plan: EbookOperationRecipePlan,
    ) -> ResolvedEbookRenameDependencyScope:
        """Resolve the sole current owner-only scope already bound by a plan."""

        if not isinstance(plan, EbookOperationRecipePlan):
            raise EbookRenamePlanningError("DEPENDENCY_SCOPE_UNAVAILABLE")
        candidate = plan.candidate
        try:
            source = self._load_current_source(candidate.sources[0].observation_id)
            scopes = self._dependency_scopes.all_scopes()
            matches: list[ResolvedEbookRenameDependencyScope] = []
            with self._engine.connect() as connection:
                for scope in scopes:
                    if scope.scan_root_id != candidate.sources[0].scan_root_id:
                        continue
                    resolved, _evidence = self._resolve_dependencies(
                        connection,
                        source,
                        scope,
                    )
                    if resolved == candidate.dependencies:
                        matches.append(scope)
        except (IndexError, EbookRenameDependencyScopeUnavailable, EbookRenamePlanningError):
            raise EbookRenamePlanningError("DEPENDENCY_SCOPE_UNAVAILABLE") from None
        if len(matches) != 1:
            raise EbookRenamePlanningError("DEPENDENCY_SCOPE_UNAVAILABLE")
        return matches[0]

    def _require_rename_candidate(
        self,
        candidate_id: EntityId,
    ) -> EbookOperationRecipeCandidate:
        try:
            candidate = self._recipes.get_candidate(candidate_id)
        except EbookOperationRecipeStoreError:
            raise EbookRenamePlanningError("CANDIDATE_UNAVAILABLE") from None
        if candidate is None:
            raise EbookRenamePlanningError("CANDIDATE_NOT_FOUND")
        if (
            candidate.operation_kind is not EbookOperationKind.FILE_RENAME
            or len(candidate.sources) != 1
            or candidate.processor_requirement.processor_profile
            != EBOOK_RENAME_PROCESSOR_PROFILE
        ):
            raise EbookRenamePlanningError("CANDIDATE_NOT_ELIGIBLE")
        return candidate

    def _build_candidate(
        self,
        source: _CurrentSource,
        target_locator: str,
        format_label: str,
        dependencies: tuple[EbookOperationDependencySnapshot, ...],
        dependency_evidence: tuple[EbookOperationEvidenceReference, ...],
    ) -> EbookOperationRecipeCandidate:
        source_snapshot = build_ebook_operation_source_snapshot(
            ordinal=0,
            role=EbookOperationSourceRole.PRIMARY,
            scan_root_id=source.scan_root_id,
            source_scan_run_id=source.scan_run_id,
            source_scan_run_status=ScanRunStatus.COMPLETED,
            file_id=source.file_id,
            observation_id=source.observation_id,
            relative_locator=source.relative_locator,
            format_label=format_label,
            expected_presence_state=PresenceState.PRESENT,
            expected_full_sha256=source.full_sha256,
            expected_size_bytes=source.size_bytes,
            expected_modified_at=source.modified_at,
            expected_observed_at=source.observed_at,
        )
        target = EbookOperationTargetSnapshot(
            kind=operation_target_kind(EbookOperationKind.FILE_RENAME),
            scope_id=source.scan_root_id,
            relative_locator=target_locator,
            target_state_fingerprint=_target_state_fingerprint(
                source.scan_root_id,
                target_locator,
            ),
        )
        processor = build_ebook_operation_processor_requirement(
            kind=EbookOperationProcessorKind.FOLIOTONE_NATIVE,
            processor_profile=EBOOK_RENAME_PROCESSOR_PROFILE,
            configuration_fingerprint=_digest(
                "foliotone:ebook-rename-processor-configuration/v1",
                {"processor_profile": EBOOK_RENAME_PROCESSOR_PROFILE},
            ),
        )
        expected = build_ebook_operation_expected_output(
            operation_kind=EbookOperationKind.FILE_RENAME,
            format_label=format_label,
            expected_full_sha256=source.full_sha256,
            expected_size_bytes=source.size_bytes,
        )
        base_evidence = (
            EbookOperationEvidenceReference(
                kind="FILE_OBSERVATION",
                ref_id=source.observation_id,
                material_fingerprint=source_snapshot.source_evidence_fingerprint,
            ),
            EbookOperationEvidenceReference(
                kind="FINGERPRINT",
                ref_id=source.fingerprint_id,
                material_fingerprint=source.fingerprint_material,
            ),
        )
        evidence_by_identity = {
            (value.kind, value.ref_id): value
            for value in (*base_evidence, *dependency_evidence)
        }
        return build_ebook_operation_recipe_candidate(
            EbookOperationRecipeCandidateInputs(
                operation_kind=EbookOperationKind.FILE_RENAME,
                sources=(source_snapshot,),
                target=target,
                expected_output=expected,
                processor_requirement=processor,
                dependencies=dependencies,
                evidence_refs=tuple(evidence_by_identity.values()),
            ),
            clock=self._now,
        )

    def _build_current_plan(
        self,
        candidate: EbookOperationRecipeCandidate,
        review: EbookOperationReviewSnapshot,
    ) -> EbookOperationRecipePlan:
        checks = self._current_checks(candidate)
        return build_ebook_operation_recipe_plan(
            EbookOperationRecipePlanInputs(
                candidate=candidate,
                review=review,
                lineage_matches=checks.lineage_matches,
                source_evidence_complete=checks.source_evidence_complete,
                target_valid=checks.target_valid,
                output_identity_valid=checks.output_identity_valid,
                processor_requirement_valid=checks.processor_requirement_valid,
                preconditions_complete=checks.preconditions_complete,
                recovery_contract_complete=checks.recovery_contract_complete,
                verification_contract_complete=checks.verification_contract_complete,
            ),
            clock=self._now,
        )

    def _current_checks(self, candidate: EbookOperationRecipeCandidate) -> _PlanChecks:
        primary = candidate.sources[0]
        try:
            current = self._load_current_source(primary.observation_id)
            rebuilt, format_label = build_ebook_rename_target_locator(
                current.relative_locator,
                candidate.target.relative_locator.rpartition("/")[2],
            )
            lineage = (
                current.scan_root_id == primary.scan_root_id
                and current.scan_run_id == primary.source_scan_run_id
                and current.file_id == primary.file_id
                and current.observation_id == primary.observation_id
                and current.relative_locator == primary.relative_locator
                and current.size_bytes == primary.expected_size_bytes
                and current.modified_at == primary.expected_modified_at
                and current.observed_at == primary.expected_observed_at
            )
            source_complete = (
                lineage
                and current.full_sha256 == primary.expected_full_sha256
                and format_label == primary.format_label
            )
            target_valid = (
                rebuilt == candidate.target.relative_locator
                and candidate.target.scope_id == primary.scan_root_id
                and not self._target_has_history(
                    primary.scan_root_id,
                    candidate.target.relative_locator,
                )
                and candidate.target.target_state_fingerprint
                == _target_state_fingerprint(
                    primary.scan_root_id,
                    candidate.target.relative_locator,
                )
            )
        except (EbookRenamePlanningError, EbookRenameTargetError):
            lineage = False
            source_complete = False
            target_valid = False

        output = candidate.expected_output
        output_valid = (
            output.format_label == primary.format_label
            and output.expected_full_sha256 == primary.expected_full_sha256
            and output.expected_size_bytes == primary.expected_size_bytes
        )
        processor = candidate.processor_requirement
        processor_valid = (
            processor.kind is EbookOperationProcessorKind.FOLIOTONE_NATIVE
            and processor.processor_profile == EBOOK_RENAME_PROCESSOR_PROFILE
            and processor.configuration_fingerprint
            == _digest(
                "foliotone:ebook-rename-processor-configuration/v1",
                {"processor_profile": EBOOK_RENAME_PROCESSOR_PROFILE},
            )
        )
        dependencies_current = self._dependency_scope_is_current(candidate)
        dependencies_eligible = all(
            value.state
            in {
                EbookOperationDependencyState.KNOWN_NONE,
                EbookOperationDependencyState.NOT_APPLICABLE,
            }
            for value in candidate.dependencies
        )
        return _PlanChecks(
            lineage_matches=lineage,
            source_evidence_complete=source_complete,
            target_valid=target_valid,
            output_identity_valid=output_valid,
            processor_requirement_valid=processor_valid,
            preconditions_complete=dependencies_current and dependencies_eligible,
            recovery_contract_complete=(
                candidate.operation_kind is EbookOperationKind.FILE_RENAME
                and candidate.recovery_mode.value == "REVERSE_RELOCATION"
                and candidate.workspace_mode.value == "NOT_REQUIRED"
                and candidate.collision_policy.value == "REQUIRE_TARGET_ABSENT"
            ),
            verification_contract_complete=(
                candidate.verification_codes
                == required_verification_codes(EbookOperationKind.FILE_RENAME)
            ),
        )

    def _dependency_scope_is_current(
        self,
        candidate: EbookOperationRecipeCandidate,
    ) -> bool:
        primary = candidate.sources[0]
        try:
            source = self._load_current_source(primary.observation_id)
            scopes = self._dependency_scopes.all_scopes()
        except (EbookRenamePlanningError, EbookRenameDependencyScopeUnavailable):
            return False
        matches = 0
        with self._engine.connect() as connection:
            for scope in scopes:
                if scope.scan_root_id != primary.scan_root_id:
                    continue
                resolved, _evidence = self._resolve_dependencies(
                    connection,
                    source,
                    scope,
                )
                if resolved == candidate.dependencies:
                    matches += 1
        return matches == 1

    def _load_current_source(self, observation_id: EntityId) -> _CurrentSource:
        observation = schema.file_observations
        record = schema.file_records
        run = schema.scan_runs
        root = schema.scan_roots
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        root.c.id.label("scan_root_id"),
                        root.c.media_type.label("root_media_type"),
                        run.c.id.label("scan_run_id"),
                        run.c.status.label("scan_status"),
                        run.c.completed_at,
                        record.c.id.label("file_id"),
                        record.c.relative_path.label("record_locator"),
                        record.c.size_bytes.label("record_size"),
                        record.c.modified_at.label("record_modified_at"),
                        record.c.media_type.label("record_media_type"),
                        record.c.presence_state,
                        observation.c.id.label("observation_id"),
                        observation.c.relative_path.label("observation_locator"),
                        observation.c.size_bytes.label("observation_size"),
                        observation.c.modified_at.label("observation_modified_at"),
                        observation.c.observed_at,
                    )
                    .select_from(
                        observation.join(record, observation.c.file_id == record.c.id)
                        .join(run, observation.c.scan_run_id == run.c.id)
                        .join(root, record.c.scan_root_id == root.c.id)
                    )
                    .where(observation.c.id == str(observation_id))
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EbookRenamePlanningError("SOURCE_NOT_FOUND")
            latest_scan = connection.execute(
                select(run.c.id)
                .where(
                    run.c.scan_root_id == str(row["scan_root_id"]),
                    run.c.status == ScanRunStatus.COMPLETED.value,
                    run.c.completed_at.is_not(None),
                )
                .order_by(run.c.completed_at.desc(), run.c.started_at.desc(), run.c.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if (
                str(row["root_media_type"]) != "EBOOK"
                or str(row["record_media_type"]) != "EBOOK"
                or str(row["scan_status"]) != ScanRunStatus.COMPLETED.value
                or row["completed_at"] is None
                or str(latest_scan) != str(row["scan_run_id"])
                or str(row["presence_state"]) != PresenceState.PRESENT.value
                or str(row["record_locator"]) != str(row["observation_locator"])
                or int(row["record_size"]) != int(row["observation_size"])
                or required_datetime_from_db(str(row["record_modified_at"]))
                != required_datetime_from_db(str(row["observation_modified_at"]))
            ):
                raise EbookRenamePlanningError("SOURCE_NOT_CURRENT")
            fingerprint_filter = (
                schema.fingerprints.c.target_kind
                == EntityKind.FILE_OBSERVATION.value,
                schema.fingerprints.c.target_id == str(observation_id),
                schema.fingerprints.c.kind == "FILE_SHA256",
                schema.fingerprints.c.algorithm == "sha256",
                schema.fingerprints.c.algorithm_version == "1",
            )
            distinct_fingerprint_values = connection.execute(
                select(func.count(schema.fingerprints.c.value.distinct())).where(
                    *fingerprint_filter
                )
            ).scalar_one()
            fingerprint = (
                connection.execute(
                    select(schema.fingerprints).where(*fingerprint_filter)
                    .order_by(
                        schema.fingerprints.c.created_at.desc(),
                        schema.fingerprints.c.id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if fingerprint is None or int(distinct_fingerprint_values) != 1:
            raise EbookRenamePlanningError("SOURCE_HASH_UNAVAILABLE")
        full_sha256 = str(fingerprint["value"])
        if len(full_sha256) != 64 or any(value not in "0123456789abcdef" for value in full_sha256):
            raise EbookRenamePlanningError("SOURCE_HASH_UNAVAILABLE")
        return _CurrentSource(
            scan_root_id=EntityId.parse(str(row["scan_root_id"])),
            scan_run_id=EntityId.parse(str(row["scan_run_id"])),
            file_id=EntityId.parse(str(row["file_id"])),
            observation_id=EntityId.parse(str(row["observation_id"])),
            relative_locator=str(row["observation_locator"]),
            size_bytes=int(row["observation_size"]),
            modified_at=required_datetime_from_db(str(row["observation_modified_at"])),
            observed_at=required_datetime_from_db(str(row["observed_at"])),
            full_sha256=full_sha256,
            fingerprint_id=EntityId.parse(str(fingerprint["id"])),
            fingerprint_material=_digest(
                "foliotone:ebook-rename-fingerprint-evidence/v1",
                {
                    "id": str(fingerprint["id"]),
                    "target_kind": str(fingerprint["target_kind"]),
                    "target_id": str(fingerprint["target_id"]),
                    "kind": str(fingerprint["kind"]),
                    "algorithm": str(fingerprint["algorithm"]),
                    "algorithm_version": str(fingerprint["algorithm_version"]),
                    "value": full_sha256,
                    "created_at": str(fingerprint["created_at"]),
                },
            ),
        )

    def _target_has_history(
        self,
        scan_root_id: EntityId,
        relative_locator: str,
    ) -> bool:
        with self._engine.connect() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(schema.file_records)
                .where(
                    schema.file_records.c.scan_root_id == str(scan_root_id),
                    schema.file_records.c.relative_path == relative_locator,
                )
            ).scalar_one()
        return int(count) != 0

    def _resolve_dependencies(
        self,
        connection: Connection,
        source: _CurrentSource,
        scope: ResolvedEbookRenameDependencyScope,
    ) -> tuple[
        tuple[EbookOperationDependencySnapshot, ...],
        tuple[EbookOperationEvidenceReference, ...],
    ]:
        scope_material = ebook_rename_dependency_scope_material_fingerprint(scope)
        dependencies: list[EbookOperationDependencySnapshot] = []
        evidence: dict[tuple[str, EntityId], EbookOperationEvidenceReference] = {}
        for axis in scope.axes:
            presence = self._existing_dependency_presence(connection, source, axis.kind)
            if presence is not None:
                state = EbookOperationDependencyState.KNOWN_PRESENT
                snapshot_kind = presence.snapshot_kind
                snapshot_id = presence.snapshot_id
                snapshot_material = presence.snapshot_material
                if snapshot_kind == "TOOL_RESULT":
                    reference = EbookOperationEvidenceReference(
                        kind="TOOL_RESULT",
                        ref_id=snapshot_id,
                        material_fingerprint=snapshot_material,
                    )
                    evidence[(reference.kind, reference.ref_id)] = reference
            elif axis.mode is EbookRenameDependencyScopeMode.NOT_APPLICABLE:
                state = EbookOperationDependencyState.NOT_APPLICABLE
                snapshot_kind = EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE
                snapshot_id = source.observation_id
                snapshot_material = scope_material
            else:
                managed = self._resolve_managed_dependency(
                    connection,
                    source,
                    axis.kind,
                    axis.snapshot_kind,
                    axis.snapshot_id,
                )
                if managed is None:
                    state = EbookOperationDependencyState.UNKNOWN
                    snapshot_kind = EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE
                    snapshot_id = source.observation_id
                    snapshot_material = scope_material
                else:
                    state, presence, managed_reference = managed
                    snapshot_kind = presence.snapshot_kind
                    snapshot_id = presence.snapshot_id
                    snapshot_material = presence.snapshot_material
                    if managed_reference is not None:
                        evidence[
                            (managed_reference.kind, managed_reference.ref_id)
                        ] = managed_reference
            dependencies.append(
                EbookOperationDependencySnapshot(
                    kind=axis.kind,
                    state=state,
                    snapshot_kind=snapshot_kind,
                    snapshot_id=snapshot_id,
                    material_fingerprint=ebook_rename_dependency_axis_material_fingerprint(
                        scope_material_fingerprint=scope_material,
                        scan_root_id=source.scan_root_id,
                        source_scan_run_id=source.scan_run_id,
                        observation_id=source.observation_id,
                        kind=axis.kind,
                        state=state,
                        snapshot_kind=snapshot_kind,
                        snapshot_id=snapshot_id,
                        snapshot_material=snapshot_material,
                    ),
                )
            )
        return tuple(dependencies), tuple(evidence.values())

    def _existing_dependency_presence(
        self,
        connection: Connection,
        source: _CurrentSource,
        kind: EbookOperationDependencyKind,
    ) -> _DependencyPresence | None:
        explicit = _dependency_coverage_result(
            connection,
            source,
            kind,
            result_id=None,
            required_state=EbookOperationDependencyState.KNOWN_PRESENT,
        )
        if explicit is not None:
            return _presence_from_row("TOOL_RESULT", explicit)
        if kind in {
            EbookOperationDependencyKind.CALIBRE,
            EbookOperationDependencyKind.EXTERNAL_LIBRARY,
        }:
            row = _calibre_format_for_source(connection, source)
            return None if row is None else _presence_from_row("CALIBRE_FORMAT", row)
        if kind is EbookOperationDependencyKind.SIDECAR:
            row = _calibre_sidecar_for_source(connection, source)
            if row is not None:
                return _presence_from_row("CALIBRE_SIDECAR", row)
            row = _archive_sidecar_for_source(connection, source)
            return (
                None
                if row is None
                else _presence_from_row("ARCHIVE_SIDECAR_INVENTORY", row)
            )
        if kind in {
            EbookOperationDependencyKind.ARCHIVE,
            EbookOperationDependencyKind.VOLUME_GROUP,
        }:
            row = _archive_for_source(
                connection,
                source,
                require_multiple=(kind is EbookOperationDependencyKind.VOLUME_GROUP),
            )
            return None if row is None else _presence_from_row("ARCHIVE_OBSERVATION", row)
        return None

    def _resolve_managed_dependency(
        self,
        connection: Connection,
        source: _CurrentSource,
        kind: EbookOperationDependencyKind,
        snapshot_kind: EbookRenameDependencySnapshotKind | None,
        snapshot_id: EntityId | None,
    ) -> tuple[
        EbookOperationDependencyState,
        _DependencyPresence,
        EbookOperationEvidenceReference | None,
    ] | None:
        if snapshot_kind is None or snapshot_id is None:
            return None
        if snapshot_kind is EbookRenameDependencySnapshotKind.CALIBRE_SNAPSHOT:
            if kind not in {
                EbookOperationDependencyKind.CALIBRE,
                EbookOperationDependencyKind.SIDECAR,
                EbookOperationDependencyKind.EXTERNAL_LIBRARY,
            }:
                return None
            row = _current_calibre_snapshot(connection, source, snapshot_id)
            if row is None:
                return None
            if kind is EbookOperationDependencyKind.SIDECAR:
                present = _calibre_sidecar_for_source(
                    connection,
                    source,
                    snapshot_id=snapshot_id,
                )
            else:
                present = _calibre_format_for_source(
                    connection,
                    source,
                    snapshot_id=snapshot_id,
                )
            state = (
                EbookOperationDependencyState.KNOWN_PRESENT
                if present is not None
                else EbookOperationDependencyState.KNOWN_NONE
            )
            return state, _presence_from_row("CALIBRE_SNAPSHOT", row), None
        if (
            snapshot_kind
            is EbookRenameDependencySnapshotKind.ARCHIVE_COLLECTION_RUN
        ):
            if kind not in {
                EbookOperationDependencyKind.ARCHIVE,
                EbookOperationDependencyKind.VOLUME_GROUP,
            }:
                return None
            row = _current_archive_collection_run(connection, source, snapshot_id)
            if row is None:
                return None
            present = _archive_collection_item_for_source(
                connection,
                source,
                snapshot_id,
                require_multiple=(
                    kind is EbookOperationDependencyKind.VOLUME_GROUP
                ),
            )
            state = (
                EbookOperationDependencyState.KNOWN_PRESENT
                if present is not None
                else EbookOperationDependencyState.KNOWN_NONE
            )
            return (
                state,
                _presence_from_row("ARCHIVE_COLLECTION_RUN", row),
                None,
            )
        if snapshot_kind is EbookRenameDependencySnapshotKind.TOOL_RESULT:
            row = _dependency_coverage_result(
                connection,
                source,
                kind,
                result_id=snapshot_id,
            )
            if row is None:
                return None
            try:
                state = EbookOperationDependencyState(str(row["value"]))
            except ValueError:
                return None
            if state not in {
                EbookOperationDependencyState.KNOWN_NONE,
                EbookOperationDependencyState.KNOWN_PRESENT,
            }:
                return None
            material = _row_material("TOOL_RESULT", row)
            return (
                state,
                _DependencyPresence("TOOL_RESULT", snapshot_id, material),
                EbookOperationEvidenceReference(
                    kind="TOOL_RESULT",
                    ref_id=snapshot_id,
                    material_fingerprint=material,
                ),
            )
        return None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise EbookRenamePlanningError("CLOCK_INVALID")
        return value


def _calibre_format_for_source(
    connection: Connection,
    source: _CurrentSource,
    *,
    snapshot_id: EntityId | None = None,
) -> RowMapping | None:
    snapshot = calibre_library_schema.calibre_library_snapshots
    record = calibre_library_schema.calibre_library_records
    format_row = calibre_library_schema.calibre_library_formats
    statement = (
        select(format_row, snapshot.c.library_identity_digest)
        .select_from(
            format_row.join(record, format_row.c.record_snapshot_id == record.c.id).join(
                snapshot,
                record.c.snapshot_id == snapshot.c.id,
            )
        )
        .where(
            format_row.c.observation_id == str(source.observation_id),
            snapshot.c.scan_root_id == str(source.scan_root_id),
            snapshot.c.source_scan_run_id == str(source.scan_run_id),
            snapshot.c.status == "COMPLETED",
            snapshot.c.initial_inventory_digest.is_not(None),
            snapshot.c.final_inventory_digest
            == snapshot.c.initial_inventory_digest,
        )
        .order_by(snapshot.c.completed_at.desc(), format_row.c.id)
        .limit(1)
    )
    if snapshot_id is not None:
        statement = statement.where(snapshot.c.id == str(snapshot_id))
    return connection.execute(statement).mappings().one_or_none()


def _calibre_sidecar_for_source(
    connection: Connection,
    source: _CurrentSource,
    *,
    snapshot_id: EntityId | None = None,
) -> RowMapping | None:
    snapshot = calibre_library_schema.calibre_library_snapshots
    record = calibre_library_schema.calibre_library_records
    format_row = calibre_library_schema.calibre_library_formats
    sidecar = calibre_library_schema.calibre_library_sidecars
    statement = (
        select(sidecar)
        .select_from(
            format_row.join(record, format_row.c.record_snapshot_id == record.c.id)
            .join(sidecar, sidecar.c.record_snapshot_id == record.c.id)
            .join(snapshot, record.c.snapshot_id == snapshot.c.id)
        )
        .where(
            format_row.c.observation_id == str(source.observation_id),
            snapshot.c.scan_root_id == str(source.scan_root_id),
            snapshot.c.source_scan_run_id == str(source.scan_run_id),
            snapshot.c.status == "COMPLETED",
            snapshot.c.initial_inventory_digest.is_not(None),
            snapshot.c.final_inventory_digest
            == snapshot.c.initial_inventory_digest,
        )
        .order_by(snapshot.c.completed_at.desc(), sidecar.c.id)
        .limit(1)
    )
    if snapshot_id is not None:
        statement = statement.where(snapshot.c.id == str(snapshot_id))
    return connection.execute(statement).mappings().one_or_none()


def _archive_for_source(
    connection: Connection,
    source: _CurrentSource,
    *,
    require_multiple: bool,
) -> RowMapping | None:
    parent = archive_schema.archive_observations
    child = archive_schema.archive_observation_sources
    count_alias = archive_schema.archive_observation_sources.alias("source_count_rows")
    statement = (
        select(parent)
        .select_from(parent.join(child, child.c.archive_observation_id == parent.c.id))
        .where(
            child.c.file_observation_id == str(source.observation_id),
            parent.c.scan_root_id == str(source.scan_root_id),
            parent.c.source_scan_run_id == str(source.scan_run_id),
        )
        .order_by(parent.c.observed_at.desc(), parent.c.id)
        .limit(1)
    )
    if require_multiple:
        statement = statement.where(
            select(func.count())
            .select_from(count_alias)
            .where(count_alias.c.archive_observation_id == parent.c.id)
            .scalar_subquery()
            > 1
        )
    return connection.execute(statement).mappings().one_or_none()


def _archive_sidecar_for_source(
    connection: Connection,
    source: _CurrentSource,
) -> RowMapping | None:
    parent = archive_schema.archive_observations
    child = archive_schema.archive_observation_sources
    inventory = archive_schema.archive_sidecar_inventories
    return (
        connection.execute(
            select(inventory)
            .select_from(
                parent.join(child, child.c.archive_observation_id == parent.c.id).join(
                    inventory,
                    inventory.c.archive_observation_id == parent.c.id,
                )
            )
            .where(
                child.c.file_observation_id == str(source.observation_id),
                parent.c.scan_root_id == str(source.scan_root_id),
                parent.c.source_scan_run_id == str(source.scan_run_id),
                inventory.c.sidecar_count > 0,
            )
            .order_by(inventory.c.created_at.desc(), inventory.c.id)
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _current_calibre_snapshot(
    connection: Connection,
    source: _CurrentSource,
    snapshot_id: EntityId,
) -> RowMapping | None:
    table = calibre_library_schema.calibre_library_snapshots
    return (
        connection.execute(
            select(table).where(
                table.c.id == str(snapshot_id),
                table.c.scan_root_id == str(source.scan_root_id),
                table.c.source_scan_run_id == str(source.scan_run_id),
                table.c.status == "COMPLETED",
                table.c.completed_at.is_not(None),
                table.c.initial_inventory_digest.is_not(None),
                table.c.final_inventory_digest
                == table.c.initial_inventory_digest,
            )
        )
        .mappings()
        .one_or_none()
    )


def _current_archive_collection_run(
    connection: Connection,
    source: _CurrentSource,
    run_id: EntityId,
) -> RowMapping | None:
    table = archive_collection_schema.archive_collection_runs
    item = archive_collection_schema.archive_collection_items
    return (
        connection.execute(
            select(table).where(
                table.c.id == str(run_id),
                table.c.scan_root_id == str(source.scan_root_id),
                table.c.source_scan_run_id == str(source.scan_run_id),
                table.c.status == "COMPLETED",
                table.c.completed_at.is_not(None),
                table.c.plan_limit.is_(None),
                table.c.hash_evidence_missing_count == 0,
                table.c.missing_volume_count == 0,
                table.c.unsupported_volume_count == 0,
                table.c.ambiguous_volume_count == 0,
                table.c.name_collision_count == 0,
                table.c.orphan_volume_count == 0,
                select(func.count())
                .select_from(item)
                .where(item.c.run_id == table.c.id)
                .scalar_subquery()
                == table.c.planned_count,
                select(func.count())
                .select_from(item)
                .where(
                    item.c.run_id == table.c.id,
                    item.c.status != "SUCCEEDED",
                )
                .scalar_subquery()
                == 0,
            )
        )
        .mappings()
        .one_or_none()
    )


def _archive_collection_item_for_source(
    connection: Connection,
    source: _CurrentSource,
    run_id: EntityId,
    *,
    require_multiple: bool,
) -> RowMapping | None:
    item = archive_collection_schema.archive_collection_items
    item_source = archive_collection_schema.archive_collection_item_sources
    count_alias = archive_collection_schema.archive_collection_item_sources.alias(
        "archive_collection_source_count"
    )
    statement = (
        select(item)
        .select_from(
            item.join(
                item_source,
                (item_source.c.run_id == item.c.run_id)
                & (item_source.c.item_id == item.c.id),
            )
        )
        .where(
            item.c.run_id == str(run_id),
            item_source.c.file_observation_id == str(source.observation_id),
            item.c.status == "SUCCEEDED",
        )
        .order_by(item.c.plan_ordinal, item.c.id)
        .limit(1)
    )
    if require_multiple:
        statement = statement.where(
            select(func.count())
            .select_from(count_alias)
            .where(
                count_alias.c.run_id == item.c.run_id,
                count_alias.c.item_id == item.c.id,
            )
            .scalar_subquery()
            > 1
        )
    return connection.execute(statement).mappings().one_or_none()


def _dependency_coverage_result(
    connection: Connection,
    source: _CurrentSource,
    kind: EbookOperationDependencyKind,
    result_id: EntityId | None,
    required_state: EbookOperationDependencyState | None = None,
) -> RowMapping | None:
    result = schema.tool_results
    execution = schema.tool_executions
    statement = (
        select(
            result,
            execution.c.provider_id,
            execution.c.tool_version,
            execution.c.adapter_version,
            execution.c.capability,
            execution.c.input_identity,
            execution.c.config_identity,
            execution.c.finished_at,
            execution.c.status,
        )
        .select_from(result.join(execution, result.c.execution_id == execution.c.id))
        .where(
            result.c.result_type == _DEPENDENCY_COVERAGE_PROFILE,
            result.c.target_kind == EntityKind.FILE_OBSERVATION.value,
            result.c.target_id == str(source.observation_id),
            result.c.key == kind.value,
            result.c.value.in_(("KNOWN_NONE", "KNOWN_PRESENT")),
            result.c.confidence == 1.0,
            execution.c.provider_id == _DEPENDENCY_COVERAGE_PROVIDER,
            execution.c.adapter_version == _DEPENDENCY_COVERAGE_ADAPTER,
            execution.c.capability == "COMPLETENESS_ANALYSIS",
            execution.c.input_identity == f"file-observation:{source.observation_id}",
            execution.c.status == "SUCCEEDED",
            execution.c.finished_at.is_not(None),
        )
        .order_by(execution.c.finished_at.desc(), result.c.id.desc())
        .limit(1)
    )
    if result_id is not None:
        statement = statement.where(result.c.id == str(result_id))
    if required_state is not None:
        statement = statement.where(result.c.value == required_state.value)
    return connection.execute(statement).mappings().one_or_none()


def _target_state_fingerprint(
    scan_root_id: EntityId,
    relative_locator: str,
) -> str:
    return _digest(
        "foliotone:ebook-rename-target-state/v1",
        {
            "scan_root_id": str(scan_root_id),
            "relative_locator": relative_locator,
            "historical_file_record_count": 0,
        },
    )


def _presence_from_row(kind: str, row: RowMapping) -> _DependencyPresence:
    return _DependencyPresence(
        snapshot_kind=kind,
        snapshot_id=EntityId.parse(str(row["id"])),
        snapshot_material=_row_material(kind, row),
    )


def _row_material(kind: str, row: RowMapping) -> str:
    material = {
        str(key): _json_scalar(value)
        for key, value in sorted(row.items(), key=lambda item: str(item[0]))
    }
    return _digest(
        "foliotone:ebook-rename-persisted-dependency-snapshot/v1",
        {"snapshot_kind": kind, "row": material},
    )


def _json_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _digest(domain: str, material: object) -> str:
    payload = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + payload).hexdigest()


__all__ = [
    "EbookRenameDependencyScopePort",
    "EbookRenamePlanResult",
    "EbookRenamePlanningError",
    "EbookRenamePlanningService",
    "EbookRenamePreview",
    "EbookRenameProposalResult",
    "EbookRenameReviewResult",
]
