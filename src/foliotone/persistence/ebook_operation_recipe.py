"""Bounded insert-only SQLite store for non-executable e-book recipes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from sqlalchemy import Engine, Table, insert, or_, select
from sqlalchemy.engine import Connection, Row, RowMapping
from sqlalchemy.exc import SQLAlchemyError

from foliotone.core import (
    EntityId,
    EntityKind,
    PresenceState,
    ReviewDecisionValue,
    ReviewItemState,
    ScanRunStatus,
)
from foliotone.ebook_operation_recipes import (
    EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE,
    EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY,
    EBOOK_OPERATION_RECIPE_PLAN_PROFILE,
    EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
    EBOOK_OPERATION_RECIPE_PRODUCER_VERSION,
    EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND,
    EBOOK_OPERATION_RECIPE_REVIEW_TYPE,
    MAX_EBOOK_OPERATION_EVIDENCE_REFS,
    MAX_EBOOK_OPERATION_SOURCES,
    EbookOperationBlocker,
    EbookOperationBlockerCode,
    EbookOperationCollisionPolicy,
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationEvidenceReference,
    EbookOperationExecutionState,
    EbookOperationExpectedOutput,
    EbookOperationKind,
    EbookOperationOutputIdentityKind,
    EbookOperationPlanStatus,
    EbookOperationPrecondition,
    EbookOperationPreconditionCode,
    EbookOperationProcessorKind,
    EbookOperationProcessorRequirement,
    EbookOperationRecipeCandidate,
    EbookOperationRecipePlan,
    EbookOperationRecipePlanInputs,
    EbookOperationRecoveryMode,
    EbookOperationReviewSnapshot,
    EbookOperationReviewState,
    EbookOperationSourceRole,
    EbookOperationSourceSnapshot,
    EbookOperationTargetKind,
    EbookOperationTargetSnapshot,
    EbookOperationVerificationCode,
    EbookOperationWorkspaceMode,
    build_ebook_operation_recipe_plan,
    ebook_operation_expected_output_fingerprint,
    ebook_operation_processor_requirement_fingerprint,
    ebook_operation_recipe_candidate_content_hash,
    ebook_operation_recipe_candidate_evidence_fingerprint,
    ebook_operation_recipe_candidate_id,
    ebook_operation_recipe_plan_content_hash,
    ebook_operation_recipe_plan_id,
    ebook_operation_recovery_requirement_fingerprint,
    ebook_operation_source_evidence_fingerprint,
    ebook_operation_verification_fingerprint,
    ebook_operation_workspace_requirement_fingerprint,
)
from foliotone.persistence import (
    archive_collection_schema,
    archive_schema,
    calibre_library_schema,
    consolidation_schema,
    metadata_correction_schema,
    schema,
)
from foliotone.persistence import ebook_operation_recipe_schema as recipe_schema
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db

MAX_EBOOK_OPERATION_PRECONDITIONS = len(EbookOperationPreconditionCode)
MAX_EBOOK_OPERATION_BLOCKERS = len(EbookOperationBlockerCode)
MAX_EBOOK_OPERATION_BLOCKER_EVIDENCE = (
    MAX_EBOOK_OPERATION_BLOCKERS * MAX_EBOOK_OPERATION_EVIDENCE_REFS
)


class EbookOperationRecipeStoreError(RuntimeError):
    """A path-free persistence, integrity, or lineage failure."""


@contextmanager
def _path_free_transaction(engine: Engine) -> Iterator[Connection]:
    try:
        with engine.begin() as connection:
            yield connection
    except SQLAlchemyError:
        raise EbookOperationRecipeStoreError(
            "operation recipe database transaction failed"
        ) from None


@contextmanager
def _path_free_connection(engine: Engine) -> Iterator[Connection]:
    try:
        with engine.connect() as connection:
            yield connection
    except SQLAlchemyError:
        raise EbookOperationRecipeStoreError(
            "operation recipe database read failed"
        ) from None


class SQLiteEbookOperationRecipeStore:
    """Persist and boundedly rehydrate immutable non-executable recipes."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_candidate(
        self,
        candidate: EbookOperationRecipeCandidate,
    ) -> EbookOperationRecipeCandidate:
        """Validate and atomically persist one content-addressed candidate."""

        _validate_candidate_identity(candidate)
        with _path_free_transaction(self._engine) as connection:
            self._validate_candidate_lineage(connection, candidate)
            result = connection.execute(
                insert(recipe_schema.ebook_operation_recipe_candidates)
                .values(**_candidate_row(candidate))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                self._write_candidate_children(connection, candidate)
                return candidate

            table = recipe_schema.ebook_operation_recipe_candidates
            rows = (
                connection.execute(
                    select(table)
                    .where(
                        or_(
                            table.c.id == str(candidate.id),
                            (table.c.profile == candidate.profile)
                            & (table.c.content_hash == candidate.content_hash),
                        )
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(rows) != 1:
                raise EbookOperationRecipeStoreError(
                    "operation recipe candidate could not be persisted"
                )
            persisted = self._read_candidate(connection, rows[0])
            expected = replace(candidate, created_at=persisted.created_at)
            if persisted != expected:
                raise EbookOperationRecipeStoreError(
                    "operation recipe candidate retry payload differs"
                )
            return persisted

    def get_candidate(
        self,
        candidate_id: EntityId,
    ) -> EbookOperationRecipeCandidate | None:
        """Boundedly rehydrate one candidate without opening Source Media."""

        with _path_free_connection(self._engine) as connection:
            return self._candidate_by_id(connection, candidate_id)

    def get_latest_review(
        self,
        candidate_id: EntityId,
    ) -> EbookOperationReviewSnapshot:
        """Resolve the latest compatible review for one persisted candidate."""

        with _path_free_connection(self._engine) as connection:
            candidate = self._candidate_by_id(connection, candidate_id)
            if candidate is None:
                raise EbookOperationRecipeStoreError(
                    "operation recipe candidate does not exist"
                )
            return self._latest_review(connection, candidate)

    def create_or_get_plan(
        self,
        plan: EbookOperationRecipePlan,
    ) -> EbookOperationRecipePlan:
        """Persist one current, canonical, permanently non-executable plan."""

        _validate_plan_identity(plan)
        with _path_free_transaction(self._engine) as connection:
            persisted_candidate = self._candidate_by_id(connection, plan.candidate.id)
            if persisted_candidate is None:
                raise EbookOperationRecipeStoreError("plan candidate is not persisted")
            if persisted_candidate != replace(
                plan.candidate,
                created_at=persisted_candidate.created_at,
            ):
                raise EbookOperationRecipeStoreError("plan candidate payload differs")
            self._validate_candidate_lineage(connection, persisted_candidate)
            normalized = replace(plan, candidate=persisted_candidate)
            self._validate_latest_review(connection, normalized)
            _validate_plan_reducer(normalized)

            table = recipe_schema.ebook_operation_recipe_plans
            result = connection.execute(
                insert(table).values(**_plan_row(normalized)).prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                self._write_plan_children(connection, normalized)
                return normalized

            rows = (
                connection.execute(
                    select(table)
                    .where(
                        or_(
                            table.c.id == str(normalized.id),
                            (table.c.profile == normalized.profile)
                            & (table.c.content_hash == normalized.content_hash),
                        )
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(rows) != 1:
                raise EbookOperationRecipeStoreError(
                    "operation recipe plan could not be persisted"
                )
            persisted = self._read_plan(connection, rows[0])
            expected = replace(normalized, created_at=persisted.created_at)
            if persisted != expected:
                raise EbookOperationRecipeStoreError(
                    "operation recipe plan retry payload differs"
                )
            return persisted

    def get_plan(self, plan_id: EntityId) -> EbookOperationRecipePlan | None:
        """Boundedly rehydrate one immutable plan graph."""

        with _path_free_connection(self._engine) as connection:
            row = (
                connection.execute(
                    select(recipe_schema.ebook_operation_recipe_plans).where(
                        recipe_schema.ebook_operation_recipe_plans.c.id == str(plan_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._read_plan(connection, row)

    def _candidate_by_id(
        self,
        connection: Connection,
        candidate_id: EntityId,
    ) -> EbookOperationRecipeCandidate | None:
        row = (
            connection.execute(
                select(recipe_schema.ebook_operation_recipe_candidates).where(
                    recipe_schema.ebook_operation_recipe_candidates.c.id
                    == str(candidate_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._read_candidate(connection, row)

    def _write_candidate_children(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
    ) -> None:
        candidate_id = str(candidate.id)
        for source in candidate.sources:
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_sources).values(
                    candidate_id=candidate_id,
                    ordinal=source.ordinal,
                    role=source.role.value,
                    scan_root_id=str(source.scan_root_id),
                    source_scan_run_id=str(source.source_scan_run_id),
                    source_scan_run_status=source.source_scan_run_status.value,
                    file_id=str(source.file_id),
                    observation_id=str(source.observation_id),
                    relative_locator=source.relative_locator,
                    format_label=source.format_label,
                    expected_presence_state=source.expected_presence_state.value,
                    expected_full_sha256=source.expected_full_sha256,
                    expected_size_bytes=source.expected_size_bytes,
                    expected_modified_at=datetime_to_db(source.expected_modified_at),
                    expected_observed_at=datetime_to_db(source.expected_observed_at),
                    source_evidence_fingerprint=source.source_evidence_fingerprint,
                )
            )
        for ordinal, dependency in enumerate(candidate.dependencies):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_dependencies).values(
                    candidate_id=candidate_id,
                    ordinal=ordinal,
                    kind=dependency.kind.value,
                    state=dependency.state.value,
                    snapshot_kind=dependency.snapshot_kind,
                    snapshot_id=str(dependency.snapshot_id),
                    material_fingerprint=dependency.material_fingerprint,
                )
            )
        for ordinal, code in enumerate(candidate.verification_codes):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_verifications).values(
                    candidate_id=candidate_id,
                    ordinal=ordinal,
                    code=code.value,
                )
            )
        for ordinal, evidence in enumerate(candidate.evidence_refs):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_evidence).values(
                    candidate_id=candidate_id,
                    ordinal=ordinal,
                    kind=evidence.kind,
                    ref_id=str(evidence.ref_id),
                    material_fingerprint=evidence.material_fingerprint,
                )
            )

    def _read_candidate(
        self,
        connection: Connection,
        row: RowMapping,
    ) -> EbookOperationRecipeCandidate:
        candidate_id = str(row["id"])
        source_count = int(row["source_count"])
        dependency_count = int(row["dependency_count"])
        verification_count = int(row["verification_count"])
        evidence_count = int(row["evidence_count"])
        if not 1 <= source_count <= MAX_EBOOK_OPERATION_SOURCES:
            raise EbookOperationRecipeStoreError("persisted source count is invalid")
        if dependency_count != len(EbookOperationDependencyKind):
            raise EbookOperationRecipeStoreError("persisted dependency count is invalid")
        if not 1 <= verification_count <= len(EbookOperationVerificationCode):
            raise EbookOperationRecipeStoreError("persisted verification count is invalid")
        if not 1 <= evidence_count <= MAX_EBOOK_OPERATION_EVIDENCE_REFS:
            raise EbookOperationRecipeStoreError("persisted evidence count is invalid")

        source_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_sources,
            recipe_schema.ebook_operation_recipe_sources.c.candidate_id == candidate_id,
            (recipe_schema.ebook_operation_recipe_sources.c.ordinal,),
            source_count,
            MAX_EBOOK_OPERATION_SOURCES,
            "candidate sources",
        )
        dependency_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_dependencies,
            recipe_schema.ebook_operation_recipe_dependencies.c.candidate_id
            == candidate_id,
            (recipe_schema.ebook_operation_recipe_dependencies.c.ordinal,),
            dependency_count,
            len(EbookOperationDependencyKind),
            "candidate dependencies",
        )
        verification_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_verifications,
            recipe_schema.ebook_operation_recipe_verifications.c.candidate_id
            == candidate_id,
            (recipe_schema.ebook_operation_recipe_verifications.c.ordinal,),
            verification_count,
            len(EbookOperationVerificationCode),
            "candidate verifications",
        )
        evidence_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_evidence,
            recipe_schema.ebook_operation_recipe_evidence.c.candidate_id
            == candidate_id,
            (recipe_schema.ebook_operation_recipe_evidence.c.ordinal,),
            evidence_count,
            MAX_EBOOK_OPERATION_EVIDENCE_REFS,
            "candidate evidence",
        )
        try:
            candidate = EbookOperationRecipeCandidate(
                id=EntityId.parse(candidate_id),
                operation_kind=EbookOperationKind(str(row["operation_kind"])),
                sources=tuple(_source_from_row(item) for item in source_rows),
                target=EbookOperationTargetSnapshot(
                    kind=EbookOperationTargetKind(str(row["target_kind"])),
                    scope_id=EntityId.parse(str(row["target_scope_id"])),
                    relative_locator=str(row["target_relative_locator"]),
                    target_state_fingerprint=str(row["target_state_fingerprint"]),
                ),
                expected_output=EbookOperationExpectedOutput(
                    identity_kind=EbookOperationOutputIdentityKind(
                        str(row["output_identity_kind"])
                    ),
                    format_label=str(row["output_format_label"]),
                    expected_full_sha256=str(row["output_expected_full_sha256"]),
                    expected_size_bytes=int(row["output_expected_size_bytes"]),
                    output_specification_fingerprint=str(
                        row["output_specification_fingerprint"]
                    ),
                ),
                collision_policy=EbookOperationCollisionPolicy(
                    str(row["collision_policy"])
                ),
                workspace_mode=EbookOperationWorkspaceMode(str(row["workspace_mode"])),
                recovery_mode=EbookOperationRecoveryMode(str(row["recovery_mode"])),
                processor_requirement=EbookOperationProcessorRequirement(
                    kind=EbookOperationProcessorKind(str(row["processor_kind"])),
                    processor_profile=str(row["processor_profile"]),
                    configuration_fingerprint=str(
                        row["processor_configuration_fingerprint"]
                    ),
                    material_fingerprint=str(row["processor_material_fingerprint"]),
                    provider_id=_optional_text(row["processor_provider_id"]),
                    tool_version=_optional_text(row["processor_tool_version"]),
                    adapter_version=_optional_text(row["processor_adapter_version"]),
                ),
                dependencies=tuple(
                    EbookOperationDependencySnapshot(
                        kind=EbookOperationDependencyKind(str(item["kind"])),
                        state=EbookOperationDependencyState(str(item["state"])),
                        snapshot_kind=str(item["snapshot_kind"]),
                        snapshot_id=EntityId.parse(str(item["snapshot_id"])),
                        material_fingerprint=str(item["material_fingerprint"]),
                    )
                    for item in dependency_rows
                ),
                verification_codes=tuple(
                    EbookOperationVerificationCode(str(item["code"]))
                    for item in verification_rows
                ),
                workspace_requirement_fingerprint=str(
                    row["workspace_requirement_fingerprint"]
                ),
                recovery_requirement_fingerprint=str(
                    row["recovery_requirement_fingerprint"]
                ),
                verification_fingerprint=str(row["verification_fingerprint"]),
                evidence_refs=tuple(_evidence_from_row(item) for item in evidence_rows),
                evidence_fingerprint=str(row["evidence_fingerprint"]),
                content_hash=str(row["content_hash"]),
                created_at=required_datetime_from_db(str(row["created_at"])),
                profile=str(row["profile"]),
                serializer_version=str(row["serializer_version"]),
            )
            _validate_candidate_identity(candidate)
        except (TypeError, ValueError) as error:
            raise EbookOperationRecipeStoreError(
                "persisted operation recipe candidate is invalid"
            ) from error
        self._validate_candidate_lineage(
            connection,
            candidate,
            require_current_file=False,
        )
        return candidate

    def _write_plan_children(
        self,
        connection: Connection,
        plan: EbookOperationRecipePlan,
    ) -> None:
        plan_id = str(plan.id)
        review = plan.review
        connection.execute(
            insert(recipe_schema.ebook_operation_recipe_plan_reviews).values(
                plan_id=plan_id,
                candidate_id=str(review.candidate_id),
                state=review.state.value,
                evidence_fingerprint=review.evidence_fingerprint,
                candidate_set_fingerprint=review.candidate_set_fingerprint,
                producer_name=review.producer_name,
                producer_version=review.producer_version,
                decision_compatibility_version=review.decision_compatibility_version,
                review_type=review.review_type,
                candidate_kind=review.candidate_kind,
                review_item_id=(
                    None if review.review_item_id is None else str(review.review_item_id)
                ),
                decision_id=(
                    None if review.decision_id is None else str(review.decision_id)
                ),
                decision_sequence_no=review.decision_sequence_no,
            )
        )
        for ordinal, precondition in enumerate(plan.preconditions):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_plan_preconditions).values(
                    plan_id=plan_id,
                    ordinal=ordinal,
                    code=precondition.code.value,
                    expected_fingerprint=precondition.expected_fingerprint,
                )
            )
        for blocker_ordinal, blocker in enumerate(plan.blockers):
            connection.execute(
                insert(recipe_schema.ebook_operation_recipe_plan_blockers).values(
                    plan_id=plan_id,
                    ordinal=blocker_ordinal,
                    code=blocker.code.value,
                    evidence_count=len(blocker.evidence_refs),
                )
            )
            for ordinal, evidence in enumerate(blocker.evidence_refs):
                connection.execute(
                    insert(
                        recipe_schema.ebook_operation_recipe_plan_blocker_evidence
                    ).values(
                        plan_id=plan_id,
                        blocker_ordinal=blocker_ordinal,
                        ordinal=ordinal,
                        kind=evidence.kind,
                        ref_id=str(evidence.ref_id),
                        material_fingerprint=evidence.material_fingerprint,
                    )
                )

    def _read_plan(
        self,
        connection: Connection,
        row: RowMapping,
    ) -> EbookOperationRecipePlan:
        plan_id = str(row["id"])
        if int(row["review_count"]) != 1:
            raise EbookOperationRecipeStoreError("persisted plan review count is invalid")
        precondition_count = int(row["precondition_count"])
        blocker_count = int(row["blocker_count"])
        review_rows = _exact_rows(
            connection,
            recipe_schema.ebook_operation_recipe_plan_reviews,
            recipe_schema.ebook_operation_recipe_plan_reviews.c.plan_id == plan_id,
            (recipe_schema.ebook_operation_recipe_plan_reviews.c.plan_id,),
            1,
            1,
            "plan reviews",
        )
        precondition_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_plan_preconditions,
            recipe_schema.ebook_operation_recipe_plan_preconditions.c.plan_id == plan_id,
            (recipe_schema.ebook_operation_recipe_plan_preconditions.c.ordinal,),
            precondition_count,
            MAX_EBOOK_OPERATION_PRECONDITIONS,
            "plan preconditions",
        )
        blocker_rows = _ordered_rows(
            connection,
            recipe_schema.ebook_operation_recipe_plan_blockers,
            recipe_schema.ebook_operation_recipe_plan_blockers.c.plan_id == plan_id,
            (recipe_schema.ebook_operation_recipe_plan_blockers.c.ordinal,),
            blocker_count,
            MAX_EBOOK_OPERATION_BLOCKERS,
            "plan blockers",
        )
        expected_blocker_evidence = sum(
            int(item["evidence_count"]) for item in blocker_rows
        )
        blocker_evidence_rows = _exact_rows(
            connection,
            recipe_schema.ebook_operation_recipe_plan_blocker_evidence,
            recipe_schema.ebook_operation_recipe_plan_blocker_evidence.c.plan_id
            == plan_id,
            (
                recipe_schema.ebook_operation_recipe_plan_blocker_evidence.c.blocker_ordinal,
                recipe_schema.ebook_operation_recipe_plan_blocker_evidence.c.ordinal,
            ),
            expected_blocker_evidence,
            MAX_EBOOK_OPERATION_BLOCKER_EVIDENCE,
            "plan blocker evidence",
        )
        candidate = self._candidate_by_id(
            connection,
            EntityId.parse(str(row["candidate_id"])),
        )
        if candidate is None:
            raise EbookOperationRecipeStoreError("persisted plan candidate is missing")

        blockers: list[EbookOperationBlocker] = []
        for blocker_row in blocker_rows:
            ordinal = int(blocker_row["ordinal"])
            selected = tuple(
                item
                for item in blocker_evidence_rows
                if int(item["blocker_ordinal"]) == ordinal
            )
            if tuple(int(item["ordinal"]) for item in selected) != tuple(
                range(len(selected))
            ) or len(selected) != int(blocker_row["evidence_count"]):
                raise EbookOperationRecipeStoreError(
                    "persisted blocker evidence is incomplete"
                )
            blockers.append(
                EbookOperationBlocker(
                    code=EbookOperationBlockerCode(str(blocker_row["code"])),
                    evidence_refs=tuple(_evidence_from_row(item) for item in selected),
                )
            )
        try:
            plan = EbookOperationRecipePlan(
                id=EntityId.parse(plan_id),
                candidate=candidate,
                review=_review_from_row(review_rows[0]),
                preconditions=tuple(
                    EbookOperationPrecondition(
                        code=EbookOperationPreconditionCode(str(item["code"])),
                        expected_fingerprint=str(item["expected_fingerprint"]),
                    )
                    for item in precondition_rows
                ),
                blockers=tuple(blockers),
                status=EbookOperationPlanStatus(str(row["status"])),
                execution_state=EbookOperationExecutionState(
                    str(row["execution_state"])
                ),
                content_hash=str(row["content_hash"]),
                created_at=required_datetime_from_db(str(row["created_at"])),
                profile=str(row["profile"]),
                serializer_version=str(row["serializer_version"]),
            )
            _validate_plan_identity(plan)
            _validate_plan_reducer(plan)
        except (TypeError, ValueError) as error:
            raise EbookOperationRecipeStoreError(
                "persisted operation recipe plan is invalid"
            ) from error
        self._validate_historical_review(connection, plan)
        return plan

    def _validate_candidate_lineage(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
        *,
        require_current_file: bool = True,
    ) -> None:
        for source in candidate.sources:
            self._validate_source(
                connection,
                source,
                require_current_file=require_current_file,
            )
        self._validate_target_scope(connection, candidate)
        material_by_reference: dict[tuple[str, EntityId], str] = {}
        for evidence in candidate.evidence_refs:
            self._validate_evidence_reference(
                connection,
                candidate,
                evidence,
                material_by_reference,
            )
        for dependency in candidate.dependencies:
            self._validate_dependency(connection, candidate, dependency)

    def _validate_source(
        self,
        connection: Connection,
        source: EbookOperationSourceSnapshot,
        *,
        require_current_file: bool,
    ) -> None:
        row = connection.execute(
            select(
                schema.scan_roots.c.media_type,
                schema.scan_runs.c.scan_root_id.label("run_root_id"),
                schema.scan_runs.c.status.label("run_status"),
                schema.scan_runs.c.completed_at,
                schema.file_records.c.scan_root_id.label("file_root_id"),
                schema.file_records.c.media_type.label("file_media_type"),
                schema.file_records.c.relative_path.label("file_relative_locator"),
                schema.file_records.c.presence_state,
                schema.file_records.c.size_bytes.label("file_size_bytes"),
                schema.file_records.c.modified_at.label("file_modified_at"),
                schema.file_observations.c.file_id.label("observation_file_id"),
                schema.file_observations.c.scan_run_id.label("observation_scan_run_id"),
                schema.file_observations.c.relative_path.label(
                    "observation_relative_locator"
                ),
                schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                schema.file_observations.c.modified_at.label(
                    "observation_modified_at"
                ),
                schema.file_observations.c.observed_at,
            )
            .select_from(
                schema.scan_roots.join(
                    schema.scan_runs,
                    schema.scan_runs.c.scan_root_id == schema.scan_roots.c.id,
                )
                .join(
                    schema.file_records,
                    schema.file_records.c.scan_root_id == schema.scan_roots.c.id,
                )
                .join(
                    schema.file_observations,
                    schema.file_observations.c.file_id == schema.file_records.c.id,
                )
            )
            .where(
                schema.scan_roots.c.id == str(source.scan_root_id),
                schema.scan_runs.c.id == str(source.source_scan_run_id),
                schema.file_records.c.id == str(source.file_id),
                schema.file_observations.c.id == str(source.observation_id),
            )
        ).one_or_none()
        if row is None:
            raise EbookOperationRecipeStoreError("operation source lineage is missing")
        if (
            str(row.media_type) != "EBOOK"
            or str(row.file_media_type) != "EBOOK"
            or str(row.run_root_id) != str(source.scan_root_id)
            or str(row.run_status) != ScanRunStatus.COMPLETED.value
            or row.completed_at is None
            or str(row.file_root_id) != str(source.scan_root_id)
            or str(row.observation_file_id) != str(source.file_id)
            or str(row.observation_scan_run_id) != str(source.source_scan_run_id)
            or str(row.observation_relative_locator) != source.relative_locator
            or int(row.observation_size_bytes) != source.expected_size_bytes
            or required_datetime_from_db(str(row.observation_modified_at))
            != source.expected_modified_at
            or required_datetime_from_db(str(row.observed_at))
            != source.expected_observed_at
            or (
                require_current_file
                and (
                    str(row.file_relative_locator) != source.relative_locator
                    or str(row.presence_state) != source.expected_presence_state.value
                    or int(row.file_size_bytes) != source.expected_size_bytes
                    or required_datetime_from_db(str(row.file_modified_at))
                    != source.expected_modified_at
                )
            )
        ):
            raise EbookOperationRecipeStoreError("operation source lineage differs")
        full_hash = connection.execute(
            select(schema.fingerprints.c.id)
            .where(
                schema.fingerprints.c.target_kind
                == EntityKind.FILE_OBSERVATION.value,
                schema.fingerprints.c.target_id == str(source.observation_id),
                schema.fingerprints.c.kind == "FILE_SHA256",
                schema.fingerprints.c.algorithm == "sha256",
                schema.fingerprints.c.algorithm_version == "1",
                schema.fingerprints.c.value == source.expected_full_sha256,
            )
            .limit(1)
        ).scalar_one_or_none()
        if full_hash is None:
            raise EbookOperationRecipeStoreError(
                "operation source full hash evidence is missing"
            )

    def _validate_target_scope(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
    ) -> None:
        if candidate.target.kind not in {
            EbookOperationTargetKind.MANAGED_SCAN_ROOT_FILE,
            EbookOperationTargetKind.SOURCE_REPLACEMENT,
        }:
            return
        media_type = connection.execute(
            select(schema.scan_roots.c.media_type).where(
                schema.scan_roots.c.id == str(candidate.target.scope_id)
            )
        ).scalar_one_or_none()
        if str(media_type) != "EBOOK":
            raise EbookOperationRecipeStoreError("operation target scope is unavailable")

    def _validate_evidence_reference(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
        evidence: EbookOperationEvidenceReference,
        material_by_reference: dict[tuple[str, EntityId], str],
    ) -> None:
        key = (evidence.kind, evidence.ref_id)
        previous = material_by_reference.setdefault(key, evidence.material_fingerprint)
        if previous != evidence.material_fingerprint:
            raise EbookOperationRecipeStoreError("evidence material binding differs")
        sources = candidate.sources
        observation_ids = {source.observation_id for source in sources}
        file_ids = {source.file_id for source in sources}
        if evidence.kind == "FILE_OBSERVATION":
            if evidence.ref_id not in observation_ids:
                raise EbookOperationRecipeStoreError(
                    "observation evidence has foreign lineage"
                )
            return
        if evidence.kind == "FILE_RECORD":
            if evidence.ref_id not in file_ids:
                raise EbookOperationRecipeStoreError("file evidence has foreign lineage")
            return
        if evidence.kind == "QUALITY_ASSESSMENT":
            table = consolidation_schema.consolidation_quality_evidence
            row = connection.execute(
                select(
                    table.c.scan_root_id,
                    table.c.source_scan_run_id,
                    table.c.observation_id,
                ).where(table.c.id == str(evidence.ref_id))
            ).one_or_none()
            if row is None or (
                str(row.scan_root_id),
                str(row.source_scan_run_id),
            ) != _primary_lineage(candidate) or EntityId.parse(
                str(row.observation_id)
            ) not in observation_ids:
                raise EbookOperationRecipeStoreError(
                    "quality evidence has missing or foreign lineage"
                )
            return
        if evidence.kind == "CONSOLIDATION_PLAN":
            table = consolidation_schema.consolidation_plans
            row = connection.execute(
                select(table.c.scan_root_id, table.c.source_scan_run_id).where(
                    table.c.id == str(evidence.ref_id)
                )
            ).one_or_none()
            _require_primary_lineage(candidate, row, "consolidation evidence")
            return
        if evidence.kind == "METADATA_CORRECTION_PLAN":
            plan = metadata_correction_schema.metadata_correction_plans
            correction = metadata_correction_schema.metadata_correction_candidates
            row = connection.execute(
                select(
                    correction.c.scan_root_id,
                    correction.c.source_scan_run_id,
                    correction.c.observation_id,
                )
                .select_from(plan.join(correction, plan.c.candidate_id == correction.c.id))
                .where(plan.c.id == str(evidence.ref_id))
            ).one_or_none()
            if row is None or (
                str(row.scan_root_id),
                str(row.source_scan_run_id),
            ) != _primary_lineage(candidate) or EntityId.parse(
                str(row.observation_id)
            ) not in observation_ids:
                raise EbookOperationRecipeStoreError(
                    "metadata correction evidence has missing or foreign lineage"
                )
            return
        if evidence.kind == "ARCHIVE_OBSERVATION":
            row = connection.execute(
                select(
                    archive_schema.archive_observations.c.scan_root_id,
                    archive_schema.archive_observations.c.source_scan_run_id,
                ).where(
                    archive_schema.archive_observations.c.id == str(evidence.ref_id)
                )
            ).one_or_none()
            _require_primary_lineage(candidate, row, "archive evidence")
            return
        if evidence.kind == "REVIEW_DECISION":
            decision = review_schema.review_decisions
            item = review_schema.review_items
            row = connection.execute(
                select(item.c.subject_kind, item.c.subject_id)
                .select_from(
                    decision.join(item, decision.c.review_item_id == item.c.id)
                )
                .where(decision.c.id == str(evidence.ref_id))
            ).one_or_none()
            if row is None or (
                str(row.subject_kind) != EntityKind.FILE.value
                or str(row.subject_id) not in {str(file_id) for file_id in file_ids}
            ):
                raise EbookOperationRecipeStoreError(
                    "review decision evidence has missing or foreign lineage"
                )
            return
        evidence_table = _EVIDENCE_TABLES.get(evidence.kind)
        if evidence_table is None:
            raise EbookOperationRecipeStoreError("evidence kind is not supported")
        evidence_row = (
            connection.execute(
                select(evidence_table).where(
                    evidence_table.c.id == str(evidence.ref_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if evidence_row is None:
            raise EbookOperationRecipeStoreError("evidence reference does not exist")
        target_kind = str(evidence_row["target_kind"])
        target_id = EntityId.parse(str(evidence_row["target_id"]))
        if not (
            target_kind == EntityKind.FILE.value and target_id in file_ids
        ) and not (
            target_kind == EntityKind.FILE_OBSERVATION.value
            and target_id in observation_ids
        ):
            raise EbookOperationRecipeStoreError("evidence has foreign source lineage")

    def _validate_dependency(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
        dependency: EbookOperationDependencySnapshot,
    ) -> None:
        generic_profile = f"ebook-{dependency.kind.value.lower()}-dependency/v1"
        primary = candidate.sources[0]
        if dependency.snapshot_kind in {
            generic_profile,
            "FILE_OBSERVATION",
            "ebook-file-rename-dependency-scope/v1",
        }:
            if dependency.snapshot_id != primary.observation_id:
                raise EbookOperationRecipeStoreError(
                    "dependency snapshot has foreign lineage"
                )
            return

        kind = dependency.snapshot_kind
        if kind == "TOOL_RESULT":
            lineage = _tool_result_lineage(
                connection,
                dependency.snapshot_id,
                primary.observation_id,
            )
        elif kind == "ARCHIVE_COLLECTION_RUN":
            lineage = _archive_collection_lineage(
                connection,
                dependency.snapshot_id,
            )
        elif dependency.kind is EbookOperationDependencyKind.CALIBRE:
            lineage = _calibre_lineage(connection, kind, dependency.snapshot_id)
        elif dependency.kind is EbookOperationDependencyKind.SIDECAR:
            lineage = _sidecar_lineage(connection, kind, dependency.snapshot_id)
        elif dependency.kind in {
            EbookOperationDependencyKind.ARCHIVE,
            EbookOperationDependencyKind.VOLUME_GROUP,
        } and kind == "ARCHIVE_OBSERVATION":
            lineage = _archive_lineage(connection, dependency.snapshot_id)
        elif dependency.kind is EbookOperationDependencyKind.EXTERNAL_LIBRARY:
            lineage = _calibre_lineage(connection, kind, dependency.snapshot_id)
        else:
            lineage = None
        if lineage != _primary_lineage(candidate):
            raise EbookOperationRecipeStoreError(
                "dependency snapshot has missing or foreign lineage"
            )

    def _latest_review(
        self,
        connection: Connection,
        candidate: EbookOperationRecipeCandidate,
    ) -> EbookOperationReviewSnapshot:
        primary = candidate.sources[0]
        item = (
            connection.execute(
                select(review_schema.review_items)
                .where(
                    review_schema.review_items.c.review_type
                    == EBOOK_OPERATION_RECIPE_REVIEW_TYPE,
                    review_schema.review_items.c.subject_kind == EntityKind.FILE.value,
                    review_schema.review_items.c.subject_id == str(primary.file_id),
                    review_schema.review_items.c.candidate_kind
                    == EBOOK_OPERATION_RECIPE_REVIEW_CANDIDATE_KIND,
                    review_schema.review_items.c.candidate_id == str(candidate.id),
                    review_schema.review_items.c.producer_name
                    == EBOOK_OPERATION_RECIPE_PRODUCER_NAME,
                    review_schema.review_items.c.decision_compatibility_version
                    == EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY,
                    review_schema.review_items.c.evidence_fingerprint
                    == candidate.evidence_fingerprint,
                    review_schema.review_items.c.candidate_set_fingerprint
                    == candidate.content_hash,
                )
                .order_by(
                    review_schema.review_items.c.created_at.desc(),
                    review_schema.review_items.c.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if item is None:
            return EbookOperationReviewSnapshot(
                candidate_id=candidate.id,
                state=EbookOperationReviewState.MISSING,
                evidence_fingerprint=candidate.evidence_fingerprint,
                candidate_set_fingerprint=candidate.content_hash,
            )
        if str(item["producer_version"]) != EBOOK_OPERATION_RECIPE_PRODUCER_VERSION:
            raise EbookOperationRecipeStoreError(
                "review producer version is incompatible"
            )
        item_id = EntityId.parse(str(item["id"]))
        decision = (
            connection.execute(
                select(review_schema.review_decisions)
                .where(review_schema.review_decisions.c.review_item_id == str(item_id))
                .order_by(review_schema.review_decisions.c.sequence_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        item_state = ReviewItemState(str(item["state"]))
        if item_state is ReviewItemState.STALE:
            state = EbookOperationReviewState.STALE
            decision = None
        elif decision is None:
            if item_state is ReviewItemState.DECIDED:
                raise EbookOperationRecipeStoreError("decided review has no decision")
            state = (
                EbookOperationReviewState.DEFERRED
                if item_state is ReviewItemState.DEFERRED
                else EbookOperationReviewState.PENDING
            )
        else:
            if (
                str(decision["evidence_fingerprint"])
                != candidate.evidence_fingerprint
                or str(decision["candidate_set_fingerprint"]) != candidate.content_hash
                or str(decision["decision_compatibility_version"])
                != EBOOK_OPERATION_RECIPE_DECISION_COMPATIBILITY
            ):
                raise EbookOperationRecipeStoreError(
                    "latest review decision is stale"
                )
            value = ReviewDecisionValue(str(decision["decision"]))
            if value is ReviewDecisionValue.DEFER:
                if item_state is not ReviewItemState.DEFERRED:
                    raise EbookOperationRecipeStoreError(
                        "deferred review state differs"
                    )
                state = EbookOperationReviewState.DEFERRED
                decision = None
            else:
                if item_state is not ReviewItemState.DECIDED:
                    raise EbookOperationRecipeStoreError("decided review state differs")
                state = (
                    EbookOperationReviewState.ACCEPTED
                    if value is ReviewDecisionValue.ACCEPT
                    else EbookOperationReviewState.REJECTED
                )
        return EbookOperationReviewSnapshot(
            candidate_id=candidate.id,
            state=state,
            evidence_fingerprint=candidate.evidence_fingerprint,
            candidate_set_fingerprint=candidate.content_hash,
            producer_version=str(item["producer_version"]),
            review_item_id=item_id,
            decision_id=(
                None if decision is None else EntityId.parse(str(decision["id"]))
            ),
            decision_sequence_no=(
                None if decision is None else int(decision["sequence_no"])
            ),
        )

    def _validate_latest_review(
        self,
        connection: Connection,
        plan: EbookOperationRecipePlan,
    ) -> None:
        if plan.review != self._latest_review(connection, plan.candidate):
            raise EbookOperationRecipeStoreError(
                "plan review is not the latest compatible review"
            )

    def _validate_historical_review(
        self,
        connection: Connection,
        plan: EbookOperationRecipePlan,
    ) -> None:
        review = plan.review
        if (
            review.candidate_id != plan.candidate.id
            or review.evidence_fingerprint != plan.candidate.evidence_fingerprint
            or review.candidate_set_fingerprint != plan.candidate.content_hash
        ):
            raise EbookOperationRecipeStoreError("persisted plan review binding differs")
        if review.state is EbookOperationReviewState.MISSING:
            return
        if review.review_item_id is None:
            raise EbookOperationRecipeStoreError("persisted plan review item is missing")
        item = (
            connection.execute(
                select(review_schema.review_items).where(
                    review_schema.review_items.c.id == str(review.review_item_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        primary = plan.candidate.sources[0]
        if item is None or (
            str(item["review_type"]) != review.review_type
            or str(item["subject_kind"]) != EntityKind.FILE.value
            or str(item["subject_id"]) != str(primary.file_id)
            or str(item["candidate_kind"]) != review.candidate_kind
            or str(item["candidate_id"]) != str(plan.candidate.id)
            or str(item["producer_name"]) != review.producer_name
            or str(item["producer_version"]) != review.producer_version
            or str(item["decision_compatibility_version"])
            != review.decision_compatibility_version
            or str(item["evidence_fingerprint"]) != review.evidence_fingerprint
            or str(item["candidate_set_fingerprint"])
            != review.candidate_set_fingerprint
        ):
            raise EbookOperationRecipeStoreError("persisted plan review item differs")
        if review.state not in {
            EbookOperationReviewState.ACCEPTED,
            EbookOperationReviewState.REJECTED,
        }:
            return
        decision = (
            connection.execute(
                select(review_schema.review_decisions).where(
                    review_schema.review_decisions.c.id == str(review.decision_id),
                    review_schema.review_decisions.c.review_item_id
                    == str(review.review_item_id),
                    review_schema.review_decisions.c.sequence_no
                    == review.decision_sequence_no,
                )
            )
            .mappings()
            .one_or_none()
        )
        expected_value = (
            ReviewDecisionValue.ACCEPT
            if review.state is EbookOperationReviewState.ACCEPTED
            else ReviewDecisionValue.REJECT
        )
        if (
            decision is None
            or ReviewDecisionValue(str(decision["decision"])) is not expected_value
            or str(decision["evidence_fingerprint"]) != review.evidence_fingerprint
            or str(decision["candidate_set_fingerprint"])
            != review.candidate_set_fingerprint
            or str(decision["decision_compatibility_version"])
            != review.decision_compatibility_version
        ):
            raise EbookOperationRecipeStoreError(
                "persisted plan review decision differs"
            )


def _candidate_row(candidate: EbookOperationRecipeCandidate) -> dict[str, object]:
    target = candidate.target
    output = candidate.expected_output
    processor = candidate.processor_requirement
    return {
        "id": str(candidate.id),
        "profile": candidate.profile,
        "serializer_version": candidate.serializer_version,
        "operation_kind": candidate.operation_kind.value,
        "source_count": len(candidate.sources),
        "target_kind": target.kind.value,
        "target_scope_id": str(target.scope_id),
        "target_relative_locator": target.relative_locator,
        "target_state_fingerprint": target.target_state_fingerprint,
        "output_identity_kind": output.identity_kind.value,
        "output_format_label": output.format_label,
        "output_expected_full_sha256": output.expected_full_sha256,
        "output_expected_size_bytes": output.expected_size_bytes,
        "output_specification_fingerprint": output.output_specification_fingerprint,
        "collision_policy": candidate.collision_policy.value,
        "workspace_mode": candidate.workspace_mode.value,
        "recovery_mode": candidate.recovery_mode.value,
        "processor_kind": processor.kind.value,
        "processor_profile": processor.processor_profile,
        "processor_configuration_fingerprint": processor.configuration_fingerprint,
        "processor_material_fingerprint": processor.material_fingerprint,
        "processor_provider_id": processor.provider_id,
        "processor_tool_version": processor.tool_version,
        "processor_adapter_version": processor.adapter_version,
        "dependency_count": len(candidate.dependencies),
        "verification_count": len(candidate.verification_codes),
        "evidence_count": len(candidate.evidence_refs),
        "workspace_requirement_fingerprint": (
            candidate.workspace_requirement_fingerprint
        ),
        "recovery_requirement_fingerprint": (
            candidate.recovery_requirement_fingerprint
        ),
        "verification_fingerprint": candidate.verification_fingerprint,
        "evidence_fingerprint": candidate.evidence_fingerprint,
        "content_hash": candidate.content_hash,
        "created_at": datetime_to_db(candidate.created_at),
    }


def _plan_row(plan: EbookOperationRecipePlan) -> dict[str, object]:
    return {
        "id": str(plan.id),
        "profile": plan.profile,
        "serializer_version": plan.serializer_version,
        "candidate_id": str(plan.candidate.id),
        "review_count": 1,
        "precondition_count": len(plan.preconditions),
        "blocker_count": len(plan.blockers),
        "status": plan.status.value,
        "execution_state": plan.execution_state.value,
        "content_hash": plan.content_hash,
        "created_at": datetime_to_db(plan.created_at),
    }


def _validate_candidate_identity(candidate: EbookOperationRecipeCandidate) -> None:
    if candidate.profile != EBOOK_OPERATION_RECIPE_CANDIDATE_PROFILE:
        raise EbookOperationRecipeStoreError("candidate profile is incompatible")
    try:
        if any(
            source.source_evidence_fingerprint
            != ebook_operation_source_evidence_fingerprint(source)
            for source in candidate.sources
        ):
            raise EbookOperationRecipeStoreError("source evidence fingerprint differs")
        if (
            candidate.expected_output.output_specification_fingerprint
            != ebook_operation_expected_output_fingerprint(candidate.expected_output)
        ):
            raise EbookOperationRecipeStoreError("output identity fingerprint differs")
        if (
            candidate.processor_requirement.material_fingerprint
            != ebook_operation_processor_requirement_fingerprint(
                candidate.processor_requirement
            )
        ):
            raise EbookOperationRecipeStoreError("processor fingerprint differs")
        if (
            candidate.workspace_requirement_fingerprint
            != ebook_operation_workspace_requirement_fingerprint(
                candidate.operation_kind,
                candidate.workspace_mode,
            )
        ):
            raise EbookOperationRecipeStoreError("workspace fingerprint differs")
        if (
            candidate.recovery_requirement_fingerprint
            != ebook_operation_recovery_requirement_fingerprint(
                candidate.operation_kind,
                candidate.recovery_mode,
                candidate.collision_policy,
            )
        ):
            raise EbookOperationRecipeStoreError("recovery fingerprint differs")
        if (
            candidate.verification_fingerprint
            != ebook_operation_verification_fingerprint(
                candidate.operation_kind,
                candidate.verification_codes,
            )
        ):
            raise EbookOperationRecipeStoreError("verification fingerprint differs")
        if (
            ebook_operation_recipe_candidate_evidence_fingerprint(candidate)
            != candidate.evidence_fingerprint
        ):
            raise EbookOperationRecipeStoreError("candidate evidence fingerprint differs")
        if ebook_operation_recipe_candidate_content_hash(candidate) != candidate.content_hash:
            raise EbookOperationRecipeStoreError("candidate content hash differs")
        if ebook_operation_recipe_candidate_id(candidate.content_hash) != candidate.id:
            raise EbookOperationRecipeStoreError("candidate content identity differs")
    except ValueError as error:
        raise EbookOperationRecipeStoreError("candidate identity is invalid") from error


def _validate_plan_identity(plan: EbookOperationRecipePlan) -> None:
    if plan.profile != EBOOK_OPERATION_RECIPE_PLAN_PROFILE:
        raise EbookOperationRecipeStoreError("plan profile is incompatible")
    _validate_candidate_identity(plan.candidate)
    try:
        if ebook_operation_recipe_plan_content_hash(plan) != plan.content_hash:
            raise EbookOperationRecipeStoreError("plan content hash differs")
        if ebook_operation_recipe_plan_id(plan.content_hash) != plan.id:
            raise EbookOperationRecipeStoreError("plan content identity differs")
    except ValueError as error:
        raise EbookOperationRecipeStoreError("plan identity is invalid") from error


def _validate_plan_reducer(plan: EbookOperationRecipePlan) -> None:
    blocker_codes = {value.code for value in plan.blockers}
    expected = build_ebook_operation_recipe_plan(
        EbookOperationRecipePlanInputs(
            candidate=plan.candidate,
            review=plan.review,
            lineage_matches=(
                EbookOperationBlockerCode.LINEAGE_MISMATCH not in blocker_codes
            ),
            source_evidence_complete=(
                EbookOperationBlockerCode.SOURCE_EVIDENCE_INCOMPLETE
                not in blocker_codes
            ),
            target_valid=(
                EbookOperationBlockerCode.TARGET_INVALID not in blocker_codes
            ),
            output_identity_valid=(
                EbookOperationBlockerCode.OUTPUT_IDENTITY_INVALID
                not in blocker_codes
            ),
            processor_requirement_valid=(
                EbookOperationBlockerCode.PROCESSOR_REQUIREMENT_INVALID
                not in blocker_codes
            ),
            preconditions_complete=(
                EbookOperationBlockerCode.PRECONDITION_INCOMPLETE
                not in blocker_codes
            ),
            recovery_contract_complete=(
                EbookOperationBlockerCode.RECOVERY_CONTRACT_INCOMPLETE
                not in blocker_codes
            ),
            verification_contract_complete=(
                EbookOperationBlockerCode.VERIFICATION_CONTRACT_INCOMPLETE
                not in blocker_codes
            ),
        ),
        clock=lambda: plan.created_at,
    )
    if expected != plan:
        raise EbookOperationRecipeStoreError("plan differs from the canonical reducer")


def _ordered_rows(
    connection: Connection,
    table: Table,
    where: Any,
    order_by: tuple[Any, ...],
    expected: int,
    maximum: int,
    label: str,
) -> list[RowMapping]:
    rows = _exact_rows(
        connection,
        table,
        where,
        order_by,
        expected,
        maximum,
        label,
    )
    if tuple(int(row["ordinal"]) for row in rows) != tuple(range(expected)):
        raise EbookOperationRecipeStoreError(f"persisted {label} are not contiguous")
    return rows


def _exact_rows(
    connection: Connection,
    table: Table,
    where: Any,
    order_by: tuple[Any, ...],
    expected: int,
    maximum: int,
    label: str,
) -> list[RowMapping]:
    if expected < 0 or expected > maximum:
        raise EbookOperationRecipeStoreError(f"persisted {label} count exceeds bound")
    rows = (
        connection.execute(
            select(table).where(where).order_by(*order_by).limit(maximum + 1)
        )
        .mappings()
        .all()
    )
    if len(rows) != expected:
        raise EbookOperationRecipeStoreError(f"persisted {label} count differs")
    return list(rows)


def _source_from_row(row: RowMapping) -> EbookOperationSourceSnapshot:
    return EbookOperationSourceSnapshot(
        ordinal=int(row["ordinal"]),
        role=EbookOperationSourceRole(str(row["role"])),
        scan_root_id=EntityId.parse(str(row["scan_root_id"])),
        source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])),
        source_scan_run_status=ScanRunStatus(str(row["source_scan_run_status"])),
        file_id=EntityId.parse(str(row["file_id"])),
        observation_id=EntityId.parse(str(row["observation_id"])),
        relative_locator=str(row["relative_locator"]),
        format_label=str(row["format_label"]),
        expected_presence_state=PresenceState(str(row["expected_presence_state"])),
        expected_full_sha256=str(row["expected_full_sha256"]),
        expected_size_bytes=int(row["expected_size_bytes"]),
        expected_modified_at=required_datetime_from_db(str(row["expected_modified_at"])),
        expected_observed_at=required_datetime_from_db(str(row["expected_observed_at"])),
        source_evidence_fingerprint=str(row["source_evidence_fingerprint"]),
    )


def _evidence_from_row(row: RowMapping) -> EbookOperationEvidenceReference:
    return EbookOperationEvidenceReference(
        kind=str(row["kind"]),
        ref_id=EntityId.parse(str(row["ref_id"])),
        material_fingerprint=str(row["material_fingerprint"]),
    )


def _review_from_row(row: RowMapping) -> EbookOperationReviewSnapshot:
    return EbookOperationReviewSnapshot(
        candidate_id=EntityId.parse(str(row["candidate_id"])),
        state=EbookOperationReviewState(str(row["state"])),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        candidate_set_fingerprint=str(row["candidate_set_fingerprint"]),
        producer_name=str(row["producer_name"]),
        producer_version=str(row["producer_version"]),
        decision_compatibility_version=str(row["decision_compatibility_version"]),
        review_type=str(row["review_type"]),
        candidate_kind=str(row["candidate_kind"]),
        review_item_id=(
            None
            if row["review_item_id"] is None
            else EntityId.parse(str(row["review_item_id"]))
        ),
        decision_id=(
            None
            if row["decision_id"] is None
            else EntityId.parse(str(row["decision_id"]))
        ),
        decision_sequence_no=(
            None
            if row["decision_sequence_no"] is None
            else int(row["decision_sequence_no"])
        ),
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _primary_lineage(candidate: EbookOperationRecipeCandidate) -> tuple[str, str]:
    primary = candidate.sources[0]
    return str(primary.scan_root_id), str(primary.source_scan_run_id)


def _require_primary_lineage(
    candidate: EbookOperationRecipeCandidate,
    row: Row[Any] | None,
    label: str,
) -> None:
    lineage = (
        None
        if row is None
        else (
            str(row._mapping["scan_root_id"]),
            str(row._mapping["source_scan_run_id"]),
        )
    )
    if lineage != _primary_lineage(candidate):
        raise EbookOperationRecipeStoreError(f"{label} has missing or foreign lineage")


def _calibre_lineage(
    connection: Connection,
    kind: str,
    reference_id: EntityId,
) -> tuple[str, str] | None:
    snapshot = calibre_library_schema.calibre_library_snapshots
    record = calibre_library_schema.calibre_library_records
    if kind == "CALIBRE_SNAPSHOT":
        statement = select(snapshot.c.scan_root_id, snapshot.c.source_scan_run_id).where(
            snapshot.c.id == str(reference_id)
        )
    elif kind == "CALIBRE_RECORD":
        statement = (
            select(snapshot.c.scan_root_id, snapshot.c.source_scan_run_id)
            .select_from(record.join(snapshot, record.c.snapshot_id == snapshot.c.id))
            .where(record.c.id == str(reference_id))
        )
    elif kind in {"CALIBRE_FORMAT", "CALIBRE_SIDECAR"}:
        child = (
            calibre_library_schema.calibre_library_formats
            if kind == "CALIBRE_FORMAT"
            else calibre_library_schema.calibre_library_sidecars
        )
        statement = (
            select(snapshot.c.scan_root_id, snapshot.c.source_scan_run_id)
            .select_from(
                child.join(record, child.c.record_snapshot_id == record.c.id).join(
                    snapshot,
                    record.c.snapshot_id == snapshot.c.id,
                )
            )
            .where(child.c.id == str(reference_id))
        )
    elif kind == "CALIBRE_FINDING":
        finding = calibre_library_schema.calibre_reconciliation_findings
        statement = (
            select(snapshot.c.scan_root_id, snapshot.c.source_scan_run_id)
            .select_from(finding.join(snapshot, finding.c.snapshot_id == snapshot.c.id))
            .where(finding.c.id == str(reference_id))
        )
    else:
        return None
    row = connection.execute(statement).one_or_none()
    return None if row is None else (str(row.scan_root_id), str(row.source_scan_run_id))


def _archive_lineage(
    connection: Connection,
    reference_id: EntityId,
) -> tuple[str, str] | None:
    row = connection.execute(
        select(
            archive_schema.archive_observations.c.scan_root_id,
            archive_schema.archive_observations.c.source_scan_run_id,
        ).where(archive_schema.archive_observations.c.id == str(reference_id))
    ).one_or_none()
    return None if row is None else (str(row.scan_root_id), str(row.source_scan_run_id))


def _sidecar_lineage(
    connection: Connection,
    kind: str,
    reference_id: EntityId,
) -> tuple[str, str] | None:
    calibre = _calibre_lineage(connection, kind, reference_id)
    if calibre is not None or kind != "ARCHIVE_SIDECAR_INVENTORY":
        return calibre
    table = archive_schema.archive_sidecar_inventories
    row = connection.execute(
        select(table.c.scan_root_id, table.c.source_scan_run_id).where(
            table.c.id == str(reference_id)
        )
    ).one_or_none()
    return None if row is None else (str(row.scan_root_id), str(row.source_scan_run_id))


def _archive_collection_lineage(
    connection: Connection,
    reference_id: EntityId,
) -> tuple[str, str] | None:
    table = archive_collection_schema.archive_collection_runs
    row = connection.execute(
        select(table.c.scan_root_id, table.c.source_scan_run_id).where(
            table.c.id == str(reference_id)
        )
    ).one_or_none()
    return None if row is None else (str(row.scan_root_id), str(row.source_scan_run_id))


def _tool_result_lineage(
    connection: Connection,
    reference_id: EntityId,
    observation_id: EntityId,
) -> tuple[str, str] | None:
    result = schema.tool_results
    observation = schema.file_observations
    record = schema.file_records
    row = connection.execute(
        select(record.c.scan_root_id, observation.c.scan_run_id)
        .select_from(
            result.join(
                observation,
                (result.c.target_kind == EntityKind.FILE_OBSERVATION.value)
                & (result.c.target_id == observation.c.id),
            ).join(record, observation.c.file_id == record.c.id)
        )
        .where(
            result.c.id == str(reference_id),
            observation.c.id == str(observation_id),
        )
    ).one_or_none()
    return None if row is None else (str(row.scan_root_id), str(row.scan_run_id))


_EVIDENCE_TABLES: dict[str, Table] = {
    "VALUE_ASSERTION": schema.value_assertions,
    "TOOL_RESULT": schema.tool_results,
    "FINGERPRINT": schema.fingerprints,
    "EXTERNAL_IDENTIFIER": schema.external_identifiers,
    "CLASSIFICATION_ASSERTION": schema.classification_assertions,
}

__all__ = [
    "MAX_EBOOK_OPERATION_BLOCKERS",
    "MAX_EBOOK_OPERATION_PRECONDITIONS",
    "EbookOperationRecipeStoreError",
    "SQLiteEbookOperationRecipeStore",
]
