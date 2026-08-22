"""Bounded insert-only SQLite store for metadata correction planning."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import Engine, Table, insert, or_, select
from sqlalchemy.engine import Connection, RowMapping

from foliotone.core import (
    EntityId,
    EntityKind,
    PresenceState,
    ReviewDecisionValue,
    ReviewItemState,
    ScanRunStatus,
    ValueState,
)
from foliotone.metadata_correction import (
    MAX_METADATA_CORRECTION_FIELDS,
    MAX_METADATA_EVIDENCE_REFS,
    MAX_METADATA_FIELD_EVIDENCE_REFS,
    MAX_METADATA_VALUES_PER_CANDIDATE,
    METADATA_CORRECTION_CANDIDATE_PROFILE,
    METADATA_CORRECTION_DECISION_COMPATIBILITY,
    METADATA_CORRECTION_PLAN_PROFILE,
    METADATA_CORRECTION_PRODUCER_NAME,
    METADATA_CORRECTION_PRODUCER_VERSION,
    METADATA_CORRECTION_REVIEW_CANDIDATE_KIND,
    METADATA_CORRECTION_REVIEW_TYPE,
    MetadataCorrectionBlocker,
    MetadataCorrectionBlockerCode,
    MetadataCorrectionCandidate,
    MetadataCorrectionExecutionState,
    MetadataCorrectionOperation,
    MetadataCorrectionPlan,
    MetadataCorrectionPlanInputs,
    MetadataCorrectionPlanStatus,
    MetadataCorrectionPrecondition,
    MetadataCorrectionPreconditionCode,
    MetadataCorrectionReviewSnapshot,
    MetadataCorrectionReviewState,
    MetadataCorrectionVerification,
    MetadataDependencyKind,
    MetadataDependencySnapshot,
    MetadataDependencyState,
    MetadataEvidenceReference,
    MetadataFieldCorrection,
    MetadataTargetCarrier,
    MetadataTargetReferenceKind,
    MetadataTargetSnapshot,
    MetadataValueSnapshot,
    MetadataWriterRequirement,
    build_metadata_correction_plan,
    metadata_correction_candidate_content_hash,
    metadata_correction_candidate_evidence_fingerprint,
    metadata_correction_candidate_id,
    metadata_correction_plan_content_hash,
    metadata_correction_plan_id,
    metadata_field_selection_fingerprint,
    metadata_writer_requirement_fingerprint,
)
from foliotone.persistence import archive_schema, calibre_library_schema, schema
from foliotone.persistence import metadata_correction_schema as mc_schema
from foliotone.persistence import resolution_review_schema as review_schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db

MAX_METADATA_CORRECTION_PRECONDITIONS = len(MetadataCorrectionPreconditionCode)
MAX_METADATA_CORRECTION_BLOCKERS = len(MetadataCorrectionBlockerCode)


class MetadataCorrectionStoreError(RuntimeError):
    """A path-free persistence, integrity, or lineage failure."""


class SQLiteMetadataCorrectionStore:
    """Persist and boundedly rehydrate immutable non-executable snapshots."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get_candidate(
        self,
        candidate: MetadataCorrectionCandidate,
    ) -> MetadataCorrectionCandidate:
        """Validate and atomically persist one content-addressed candidate."""

        _validate_candidate_identity(candidate)
        with self._engine.begin() as connection:
            self._validate_candidate_lineage(connection, candidate)
            result = connection.execute(
                insert(mc_schema.metadata_correction_candidates)
                .values(**_candidate_row(candidate))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                self._write_candidate_children(connection, candidate)
                return candidate

            rows = (
                connection.execute(
                    select(mc_schema.metadata_correction_candidates)
                    .where(
                        or_(
                            mc_schema.metadata_correction_candidates.c.id == str(candidate.id),
                            (
                                mc_schema.metadata_correction_candidates.c.profile
                                == candidate.profile
                            )
                            & (
                                mc_schema.metadata_correction_candidates.c.content_hash
                                == candidate.content_hash
                            ),
                        )
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(rows) != 1:
                raise MetadataCorrectionStoreError("candidate snapshot could not be persisted")
            persisted = self._read_candidate(connection, rows[0])
            expected = replace(candidate, created_at=persisted.created_at)
            if persisted != expected:
                raise MetadataCorrectionStoreError("candidate retry payload differs")
            return persisted

    def get_candidate(self, candidate_id: EntityId) -> MetadataCorrectionCandidate | None:
        """Boundedly rehydrate one immutable candidate without opening Source Media."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(mc_schema.metadata_correction_candidates).where(
                        mc_schema.metadata_correction_candidates.c.id == str(candidate_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._read_candidate(connection, row)

    def get_latest_review(
        self,
        candidate_id: EntityId,
    ) -> MetadataCorrectionReviewSnapshot:
        """Resolve the latest compatible review state for one persisted candidate."""

        with self._engine.connect() as connection:
            candidate = self._candidate_by_id(connection, candidate_id)
            if candidate is None:
                raise MetadataCorrectionStoreError("metadata correction candidate does not exist")
            return self._latest_review(connection, candidate)

    def create_or_get_plan(self, plan: MetadataCorrectionPlan) -> MetadataCorrectionPlan:
        """Validate current lineage and atomically persist one non-executable plan."""

        _validate_plan_identity(plan)
        with self._engine.begin() as connection:
            persisted_candidate = self._candidate_by_id(connection, plan.candidate.id)
            if persisted_candidate is None:
                raise MetadataCorrectionStoreError("plan candidate is not persisted")
            if persisted_candidate != replace(
                plan.candidate,
                created_at=persisted_candidate.created_at,
            ):
                raise MetadataCorrectionStoreError("plan candidate payload differs")
            self._validate_candidate_lineage(connection, persisted_candidate)
            normalized = replace(plan, candidate=persisted_candidate)
            self._validate_latest_review(connection, normalized)
            _validate_plan_reducer(normalized)

            result = connection.execute(
                insert(mc_schema.metadata_correction_plans)
                .values(**_plan_row(normalized))
                .prefix_with("OR IGNORE")
            )
            if result.rowcount == 1:
                self._write_plan_children(connection, normalized)
                return normalized

            rows = (
                connection.execute(
                    select(mc_schema.metadata_correction_plans)
                    .where(
                        or_(
                            mc_schema.metadata_correction_plans.c.id == str(normalized.id),
                            (mc_schema.metadata_correction_plans.c.profile == normalized.profile)
                            & (
                                mc_schema.metadata_correction_plans.c.content_hash
                                == normalized.content_hash
                            ),
                        )
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(rows) != 1:
                raise MetadataCorrectionStoreError("plan snapshot could not be persisted")
            persisted = self._read_plan(connection, rows[0])
            expected = replace(normalized, created_at=persisted.created_at)
            if persisted != expected:
                raise MetadataCorrectionStoreError("plan retry payload differs")
            return persisted

    def get_plan(self, plan_id: EntityId) -> MetadataCorrectionPlan | None:
        """Boundedly rehydrate one immutable plan graph."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(mc_schema.metadata_correction_plans).where(
                        mc_schema.metadata_correction_plans.c.id == str(plan_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._read_plan(connection, row)

    def require_current_approved_plan_in_transaction(
        self,
        connection: Connection,
        plan: MetadataCorrectionPlan,
    ) -> None:
        """Revalidate one exact persisted plan before a separate W10 authorization."""

        self.require_persisted_approved_plan_in_transaction(connection, plan)
        self._validate_candidate_lineage(
            connection,
            plan.candidate,
            require_current_file=True,
        )
        self._validate_latest_review(connection, plan)

    def require_persisted_approved_plan_in_transaction(
        self,
        connection: Connection,
        plan: MetadataCorrectionPlan,
    ) -> None:
        """Require the exact immutable approved plan without current-state checks.

        This narrower variant exists only for crash recovery of an already
        authorized operation.  It intentionally does not treat authorization
        expiry, later review decisions, or a changed current FileRecord as a
        reason to abandon recovery of the original bytes.
        """

        _validate_plan_identity(plan)
        _validate_plan_reducer(plan)
        row = (
            connection.execute(
                select(mc_schema.metadata_correction_plans).where(
                    mc_schema.metadata_correction_plans.c.id == str(plan.id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or self._read_plan(connection, row) != plan:
            raise MetadataCorrectionStoreError("metadata correction plan differs")
        if (
            plan.status is not MetadataCorrectionPlanStatus.APPROVED_NON_EXECUTABLE
            or plan.execution_state is not MetadataCorrectionExecutionState.NOT_EXECUTABLE
            or plan.blockers
        ):
            raise MetadataCorrectionStoreError("metadata correction plan is not approved")

    def _candidate_by_id(
        self,
        connection: Connection,
        candidate_id: EntityId,
    ) -> MetadataCorrectionCandidate | None:
        row = (
            connection.execute(
                select(mc_schema.metadata_correction_candidates).where(
                    mc_schema.metadata_correction_candidates.c.id == str(candidate_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._read_candidate(connection, row)

    def _write_candidate_children(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
    ) -> None:
        candidate_id = str(candidate.id)
        for field_ordinal, correction in enumerate(candidate.field_corrections):
            connection.execute(
                insert(mc_schema.metadata_correction_fields).values(
                    candidate_id=candidate_id,
                    ordinal=field_ordinal,
                    field_path=correction.field_path,
                    operation=correction.operation.value,
                    selection_fingerprint=correction.selection_fingerprint,
                    observed_count=len(correction.observed_values),
                    selected_count=len(correction.selected_values),
                    evidence_count=len(correction.evidence_refs),
                )
            )
            for value_set, values in (
                ("OBSERVED", correction.observed_values),
                ("SELECTED", correction.selected_values),
            ):
                for value in values:
                    connection.execute(
                        insert(mc_schema.metadata_correction_values).values(
                            candidate_id=candidate_id,
                            field_ordinal=field_ordinal,
                            value_set=value_set,
                            ordinal=value.ordinal,
                            value_state=value.state.value,
                            source_kind=value.source_ref.kind,
                            source_id=str(value.source_ref.ref_id),
                            source_material_fingerprint=(value.source_ref.material_fingerprint),
                            value=value.value,
                        )
                    )
            for ordinal, evidence in enumerate(correction.evidence_refs):
                connection.execute(
                    insert(mc_schema.metadata_correction_field_evidence).values(
                        candidate_id=candidate_id,
                        field_ordinal=field_ordinal,
                        ordinal=ordinal,
                        kind=evidence.kind,
                        ref_id=str(evidence.ref_id),
                        material_fingerprint=evidence.material_fingerprint,
                    )
                )
        for ordinal, evidence in enumerate(candidate.evidence_refs):
            connection.execute(
                insert(mc_schema.metadata_correction_evidence).values(
                    candidate_id=candidate_id,
                    ordinal=ordinal,
                    kind=evidence.kind,
                    ref_id=str(evidence.ref_id),
                    material_fingerprint=evidence.material_fingerprint,
                )
            )
        for ordinal, dependency in enumerate(candidate.dependencies):
            connection.execute(
                insert(mc_schema.metadata_correction_dependencies).values(
                    candidate_id=candidate_id,
                    ordinal=ordinal,
                    kind=dependency.kind.value,
                    state=dependency.state.value,
                    snapshot_kind=dependency.snapshot_kind,
                    snapshot_id=str(dependency.snapshot_id),
                    material_fingerprint=dependency.material_fingerprint,
                )
            )

    def _read_candidate(
        self,
        connection: Connection,
        row: RowMapping,
    ) -> MetadataCorrectionCandidate:
        candidate_id = str(row["id"])
        field_count = int(row["field_count"])
        dependency_count = int(row["dependency_count"])
        evidence_count = int(row["evidence_count"])
        if not 1 <= field_count <= MAX_METADATA_CORRECTION_FIELDS:
            raise MetadataCorrectionStoreError("persisted candidate field count is invalid")
        if dependency_count != len(MetadataDependencyKind):
            raise MetadataCorrectionStoreError("persisted dependency count is invalid")
        if not 1 <= evidence_count <= MAX_METADATA_EVIDENCE_REFS:
            raise MetadataCorrectionStoreError("persisted candidate evidence count is invalid")

        field_rows = _ordered_rows(
            connection,
            mc_schema.metadata_correction_fields,
            mc_schema.metadata_correction_fields.c.candidate_id == candidate_id,
            (mc_schema.metadata_correction_fields.c.ordinal,),
            field_count,
            MAX_METADATA_CORRECTION_FIELDS,
            "candidate fields",
        )
        expected_values = sum(
            int(item["observed_count"]) + int(item["selected_count"]) for item in field_rows
        )
        if expected_values > MAX_METADATA_VALUES_PER_CANDIDATE:
            raise MetadataCorrectionStoreError("persisted candidate values exceed bound")
        value_rows = _exact_rows(
            connection,
            mc_schema.metadata_correction_values,
            mc_schema.metadata_correction_values.c.candidate_id == candidate_id,
            (
                mc_schema.metadata_correction_values.c.field_ordinal,
                mc_schema.metadata_correction_values.c.value_set,
                mc_schema.metadata_correction_values.c.ordinal,
            ),
            expected_values,
            MAX_METADATA_VALUES_PER_CANDIDATE,
            "candidate values",
        )
        expected_field_evidence = sum(int(item["evidence_count"]) for item in field_rows)
        if expected_field_evidence > (
            MAX_METADATA_CORRECTION_FIELDS * MAX_METADATA_FIELD_EVIDENCE_REFS
        ):
            raise MetadataCorrectionStoreError("persisted field evidence exceeds bound")
        field_evidence_rows = _exact_rows(
            connection,
            mc_schema.metadata_correction_field_evidence,
            mc_schema.metadata_correction_field_evidence.c.candidate_id == candidate_id,
            (
                mc_schema.metadata_correction_field_evidence.c.field_ordinal,
                mc_schema.metadata_correction_field_evidence.c.ordinal,
            ),
            expected_field_evidence,
            MAX_METADATA_CORRECTION_FIELDS * MAX_METADATA_FIELD_EVIDENCE_REFS,
            "field evidence",
        )
        corrections: list[MetadataFieldCorrection] = []
        for field_row in field_rows:
            field_ordinal = int(field_row["ordinal"])
            observed = _values_for_field(value_rows, field_ordinal, "OBSERVED")
            selected = _values_for_field(value_rows, field_ordinal, "SELECTED")
            evidence = _evidence_for_field(field_evidence_rows, field_ordinal)
            if len(observed) != int(field_row["observed_count"]):
                raise MetadataCorrectionStoreError("persisted observed values are incomplete")
            if len(selected) != int(field_row["selected_count"]):
                raise MetadataCorrectionStoreError("persisted selected values are incomplete")
            if len(evidence) != int(field_row["evidence_count"]):
                raise MetadataCorrectionStoreError("persisted field evidence is incomplete")
            corrections.append(
                MetadataFieldCorrection(
                    field_path=str(field_row["field_path"]),
                    operation=MetadataCorrectionOperation(str(field_row["operation"])),
                    observed_values=observed,
                    selected_values=selected,
                    evidence_refs=evidence,
                    selection_fingerprint=str(field_row["selection_fingerprint"]),
                )
            )

        evidence_rows = _ordered_rows(
            connection,
            mc_schema.metadata_correction_evidence,
            mc_schema.metadata_correction_evidence.c.candidate_id == candidate_id,
            (mc_schema.metadata_correction_evidence.c.ordinal,),
            evidence_count,
            MAX_METADATA_EVIDENCE_REFS,
            "candidate evidence",
        )
        dependency_rows = _ordered_rows(
            connection,
            mc_schema.metadata_correction_dependencies,
            mc_schema.metadata_correction_dependencies.c.candidate_id == candidate_id,
            (mc_schema.metadata_correction_dependencies.c.ordinal,),
            dependency_count,
            len(MetadataDependencyKind),
            "candidate dependencies",
        )
        candidate = MetadataCorrectionCandidate(
            id=EntityId.parse(candidate_id),
            scan_root_id=EntityId.parse(str(row["scan_root_id"])),
            source_scan_run_id=EntityId.parse(str(row["source_scan_run_id"])),
            source_scan_run_status=ScanRunStatus(str(row["source_scan_run_status"])),
            file_id=EntityId.parse(str(row["file_id"])),
            observation_id=EntityId.parse(str(row["observation_id"])),
            format_label=str(row["format_label"]),
            expected_presence_state=PresenceState(str(row["expected_presence_state"])),
            expected_full_sha256=str(row["expected_full_sha256"]),
            expected_size_bytes=int(row["expected_size_bytes"]),
            expected_modified_at=required_datetime_from_db(str(row["expected_modified_at"])),
            expected_observed_at=required_datetime_from_db(str(row["expected_observed_at"])),
            metadata_evidence_fingerprint=str(row["metadata_evidence_fingerprint"]),
            target=MetadataTargetSnapshot(
                carrier=MetadataTargetCarrier(str(row["target_carrier"])),
                reference_kind=MetadataTargetReferenceKind(str(row["target_reference_kind"])),
                reference_id=EntityId.parse(str(row["target_reference_id"])),
                carrier_state_fingerprint=str(row["target_state_fingerprint"]),
            ),
            field_corrections=tuple(corrections),
            dependencies=tuple(
                MetadataDependencySnapshot(
                    kind=MetadataDependencyKind(str(item["kind"])),
                    state=MetadataDependencyState(str(item["state"])),
                    snapshot_kind=str(item["snapshot_kind"]),
                    snapshot_id=EntityId.parse(str(item["snapshot_id"])),
                    material_fingerprint=str(item["material_fingerprint"]),
                )
                for item in dependency_rows
            ),
            writer_requirement=MetadataWriterRequirement(
                profile=str(row["writer_profile"]),
                format_label=str(row["writer_format_label"]),
                target_carrier=MetadataTargetCarrier(str(row["writer_target_carrier"])),
                material_fingerprint=str(row["writer_material_fingerprint"]),
            ),
            evidence_refs=tuple(_evidence_from_row(item) for item in evidence_rows),
            evidence_fingerprint=str(row["evidence_fingerprint"]),
            content_hash=str(row["content_hash"]),
            created_at=required_datetime_from_db(str(row["created_at"])),
            profile=str(row["profile"]),
            serializer_version=str(row["serializer_version"]),
        )
        _validate_candidate_identity(candidate)
        self._validate_candidate_lineage(
            connection,
            candidate,
            require_current_file=False,
        )
        return candidate

    def _write_plan_children(self, connection: Connection, plan: MetadataCorrectionPlan) -> None:
        plan_id = str(plan.id)
        if plan.review is not None:
            review = plan.review
            connection.execute(
                insert(mc_schema.metadata_correction_plan_reviews).values(
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
                    decision_id=None if review.decision_id is None else str(review.decision_id),
                    decision_sequence_no=review.decision_sequence_no,
                )
            )
        for ordinal, precondition in enumerate(plan.preconditions):
            connection.execute(
                insert(mc_schema.metadata_correction_plan_preconditions).values(
                    plan_id=plan_id,
                    ordinal=ordinal,
                    code=precondition.code.value,
                    expected_fingerprint=precondition.expected_fingerprint,
                )
            )
        verification = plan.verification
        connection.execute(
            insert(mc_schema.metadata_correction_verifications).values(
                plan_id=plan_id,
                profile=verification.profile,
                analysis_profile=verification.analysis_profile,
                format_label=verification.format_label,
                target_carrier=verification.target_carrier.value,
                expected_selected_fields_fingerprint=(
                    verification.expected_selected_fields_fingerprint
                ),
                preserved_fields_fingerprint=verification.preserved_fields_fingerprint,
                changed_field_count=len(verification.changed_field_paths),
                format_validation_required=verification.format_validation_required,
                readability_validation_required=verification.readability_validation_required,
                dependency_count=len(verification.dependency_reconciliation),
            )
        )
        for ordinal, field_path in enumerate(verification.changed_field_paths):
            connection.execute(
                insert(mc_schema.metadata_correction_verification_fields).values(
                    plan_id=plan_id,
                    ordinal=ordinal,
                    field_path=field_path,
                )
            )
        for ordinal, dependency in enumerate(verification.dependency_reconciliation):
            connection.execute(
                insert(mc_schema.metadata_correction_verification_dependencies).values(
                    plan_id=plan_id,
                    ordinal=ordinal,
                    kind=dependency.value,
                )
            )
        for blocker_ordinal, blocker in enumerate(plan.blockers):
            connection.execute(
                insert(mc_schema.metadata_correction_plan_blockers).values(
                    plan_id=plan_id,
                    ordinal=blocker_ordinal,
                    code=blocker.code.value,
                    evidence_count=len(blocker.evidence_refs),
                )
            )
            for ordinal, evidence in enumerate(blocker.evidence_refs):
                connection.execute(
                    insert(mc_schema.metadata_correction_plan_blocker_evidence).values(
                        plan_id=plan_id,
                        blocker_ordinal=blocker_ordinal,
                        ordinal=ordinal,
                        kind=evidence.kind,
                        ref_id=str(evidence.ref_id),
                        material_fingerprint=evidence.material_fingerprint,
                    )
                )

    def _read_plan(self, connection: Connection, row: RowMapping) -> MetadataCorrectionPlan:
        plan_id = str(row["id"])
        review_count = int(row["review_count"])
        precondition_count = int(row["precondition_count"])
        blocker_count = int(row["blocker_count"])
        if review_count not in {0, 1}:
            raise MetadataCorrectionStoreError("persisted plan review count is invalid")
        if not 0 <= precondition_count <= MAX_METADATA_CORRECTION_PRECONDITIONS:
            raise MetadataCorrectionStoreError("persisted plan precondition count is invalid")
        if not 0 <= blocker_count <= MAX_METADATA_CORRECTION_BLOCKERS:
            raise MetadataCorrectionStoreError("persisted plan blocker count is invalid")

        candidate = self._candidate_by_id(
            connection,
            EntityId.parse(str(row["candidate_id"])),
        )
        if candidate is None:
            raise MetadataCorrectionStoreError("persisted plan candidate is missing")
        review_rows = _exact_rows(
            connection,
            mc_schema.metadata_correction_plan_reviews,
            mc_schema.metadata_correction_plan_reviews.c.plan_id == plan_id,
            (mc_schema.metadata_correction_plan_reviews.c.plan_id,),
            review_count,
            1,
            "plan review",
        )
        review = None if not review_rows else _review_from_row(review_rows[0])
        precondition_rows = _ordered_rows(
            connection,
            mc_schema.metadata_correction_plan_preconditions,
            mc_schema.metadata_correction_plan_preconditions.c.plan_id == plan_id,
            (mc_schema.metadata_correction_plan_preconditions.c.ordinal,),
            precondition_count,
            MAX_METADATA_CORRECTION_PRECONDITIONS,
            "plan preconditions",
        )
        verification_row = (
            connection.execute(
                select(mc_schema.metadata_correction_verifications).where(
                    mc_schema.metadata_correction_verifications.c.plan_id == plan_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if verification_row is None:
            raise MetadataCorrectionStoreError("persisted plan verification is missing")
        changed_field_count = int(verification_row["changed_field_count"])
        dependency_count = int(verification_row["dependency_count"])
        changed_fields = _ordered_rows(
            connection,
            mc_schema.metadata_correction_verification_fields,
            mc_schema.metadata_correction_verification_fields.c.plan_id == plan_id,
            (mc_schema.metadata_correction_verification_fields.c.ordinal,),
            changed_field_count,
            MAX_METADATA_CORRECTION_FIELDS,
            "verification fields",
        )
        verification_dependencies = _ordered_rows(
            connection,
            mc_schema.metadata_correction_verification_dependencies,
            mc_schema.metadata_correction_verification_dependencies.c.plan_id == plan_id,
            (mc_schema.metadata_correction_verification_dependencies.c.ordinal,),
            dependency_count,
            len(MetadataDependencyKind),
            "verification dependencies",
        )
        blocker_rows = _ordered_rows(
            connection,
            mc_schema.metadata_correction_plan_blockers,
            mc_schema.metadata_correction_plan_blockers.c.plan_id == plan_id,
            (mc_schema.metadata_correction_plan_blockers.c.ordinal,),
            blocker_count,
            MAX_METADATA_CORRECTION_BLOCKERS,
            "plan blockers",
        )
        expected_blocker_evidence = sum(int(item["evidence_count"]) for item in blocker_rows)
        blocker_evidence_rows = _exact_rows(
            connection,
            mc_schema.metadata_correction_plan_blocker_evidence,
            mc_schema.metadata_correction_plan_blocker_evidence.c.plan_id == plan_id,
            (
                mc_schema.metadata_correction_plan_blocker_evidence.c.blocker_ordinal,
                mc_schema.metadata_correction_plan_blocker_evidence.c.ordinal,
            ),
            expected_blocker_evidence,
            MAX_METADATA_CORRECTION_BLOCKERS * MAX_METADATA_FIELD_EVIDENCE_REFS,
            "blocker evidence",
        )
        blockers = tuple(
            MetadataCorrectionBlocker(
                code=MetadataCorrectionBlockerCode(str(blocker["code"])),
                evidence_refs=tuple(
                    _evidence_from_row(evidence)
                    for evidence in blocker_evidence_rows
                    if int(evidence["blocker_ordinal"]) == int(blocker["ordinal"])
                ),
            )
            for blocker in blocker_rows
        )
        for blocker, blocker_row in zip(blockers, blocker_rows, strict=True):
            if len(blocker.evidence_refs) != int(blocker_row["evidence_count"]):
                raise MetadataCorrectionStoreError("persisted blocker evidence is incomplete")

        plan = MetadataCorrectionPlan(
            id=EntityId.parse(plan_id),
            candidate=candidate,
            review=review,
            preconditions=tuple(
                MetadataCorrectionPrecondition(
                    code=MetadataCorrectionPreconditionCode(str(item["code"])),
                    expected_fingerprint=str(item["expected_fingerprint"]),
                )
                for item in precondition_rows
            ),
            verification=MetadataCorrectionVerification(
                profile=str(verification_row["profile"]),
                analysis_profile=str(verification_row["analysis_profile"]),
                format_label=str(verification_row["format_label"]),
                target_carrier=MetadataTargetCarrier(str(verification_row["target_carrier"])),
                expected_selected_fields_fingerprint=str(
                    verification_row["expected_selected_fields_fingerprint"]
                ),
                preserved_fields_fingerprint=str(verification_row["preserved_fields_fingerprint"]),
                changed_field_paths=tuple(str(item["field_path"]) for item in changed_fields),
                format_validation_required=bool(verification_row["format_validation_required"]),
                readability_validation_required=bool(
                    verification_row["readability_validation_required"]
                ),
                dependency_reconciliation=tuple(
                    MetadataDependencyKind(str(item["kind"])) for item in verification_dependencies
                ),
            ),
            blockers=blockers,
            status=MetadataCorrectionPlanStatus(str(row["status"])),
            execution_state=MetadataCorrectionExecutionState(str(row["execution_state"])),
            content_hash=str(row["content_hash"]),
            created_at=required_datetime_from_db(str(row["created_at"])),
            profile=str(row["profile"]),
            serializer_version=str(row["serializer_version"]),
        )
        _validate_plan_identity(plan)
        _validate_plan_reducer(plan)
        self._validate_historical_review(connection, plan)
        return plan

    def _validate_candidate_lineage(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
        *,
        require_current_file: bool = True,
    ) -> None:
        source = connection.execute(
            select(
                schema.scan_roots.c.media_type,
                schema.scan_runs.c.scan_root_id.label("run_root_id"),
                schema.scan_runs.c.status.label("run_status"),
                schema.scan_runs.c.completed_at,
                schema.file_records.c.scan_root_id.label("file_root_id"),
                schema.file_records.c.media_type.label("file_media_type"),
                schema.file_records.c.presence_state,
                schema.file_records.c.size_bytes.label("file_size_bytes"),
                schema.file_records.c.modified_at.label("file_modified_at"),
                schema.file_observations.c.file_id.label("observation_file_id"),
                schema.file_observations.c.scan_run_id.label("observation_scan_run_id"),
                schema.file_observations.c.size_bytes.label("observation_size_bytes"),
                schema.file_observations.c.modified_at.label("observation_modified_at"),
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
                schema.scan_roots.c.id == str(candidate.scan_root_id),
                schema.scan_runs.c.id == str(candidate.source_scan_run_id),
                schema.file_records.c.id == str(candidate.file_id),
                schema.file_observations.c.id == str(candidate.observation_id),
            )
        ).one_or_none()
        if source is None:
            raise MetadataCorrectionStoreError("candidate source lineage is missing")
        if (
            str(source.media_type) != "EBOOK"
            or str(source.file_media_type) != "EBOOK"
            or str(source.run_root_id) != str(candidate.scan_root_id)
            or str(source.run_status) != ScanRunStatus.COMPLETED.value
            or source.completed_at is None
            or str(source.file_root_id) != str(candidate.scan_root_id)
            or str(source.observation_file_id) != str(candidate.file_id)
            or str(source.observation_scan_run_id) != str(candidate.source_scan_run_id)
            or int(source.observation_size_bytes) != candidate.expected_size_bytes
            or required_datetime_from_db(str(source.observation_modified_at))
            != candidate.expected_modified_at
            or required_datetime_from_db(str(source.observed_at)) != candidate.expected_observed_at
            or (
                require_current_file
                and (
                    str(source.presence_state) != candidate.expected_presence_state.value
                    or int(source.file_size_bytes) != candidate.expected_size_bytes
                    or required_datetime_from_db(str(source.file_modified_at))
                    != candidate.expected_modified_at
                )
            )
        ):
            raise MetadataCorrectionStoreError("candidate source lineage differs")
        full_hash = connection.execute(
            select(schema.fingerprints.c.id)
            .where(
                schema.fingerprints.c.target_kind == EntityKind.FILE_OBSERVATION.value,
                schema.fingerprints.c.target_id == str(candidate.observation_id),
                schema.fingerprints.c.kind == "FILE_SHA256",
                schema.fingerprints.c.algorithm == "sha256",
                schema.fingerprints.c.algorithm_version == "1",
                schema.fingerprints.c.value == candidate.expected_full_sha256,
            )
            .limit(1)
        ).scalar_one_or_none()
        if full_hash is None:
            raise MetadataCorrectionStoreError("candidate full hash evidence is missing")

        self._validate_target(connection, candidate)
        material_by_reference: dict[tuple[str, EntityId], str] = {}
        for field in candidate.field_corrections:
            for value in (*field.observed_values, *field.selected_values):
                self._validate_evidence_reference(
                    connection,
                    candidate,
                    value.source_ref,
                    material_by_reference,
                    field_path=field.field_path,
                    expected_value=value.value,
                    expected_state=value.state,
                )
            for evidence in field.evidence_refs:
                self._validate_evidence_reference(
                    connection,
                    candidate,
                    evidence,
                    material_by_reference,
                    field_path=field.field_path,
                )
        for evidence in candidate.evidence_refs:
            self._validate_evidence_reference(
                connection,
                candidate,
                evidence,
                material_by_reference,
            )
        for dependency in candidate.dependencies:
            self._validate_dependency(connection, candidate, dependency)

    def _validate_target(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
    ) -> None:
        target = candidate.target
        if target.carrier is MetadataTargetCarrier.SOURCE_METADATA:
            if target.reference_id != candidate.file_id:
                raise MetadataCorrectionStoreError("source metadata target differs")
            return
        if target.carrier is MetadataTargetCarrier.FOLIOTONE_PROJECTION:
            if not _entity_exists(connection, target.reference_id):
                raise MetadataCorrectionStoreError("projection target does not exist")
            return
        if target.carrier is MetadataTargetCarrier.CALIBRE_LIBRARY:
            lineage = _calibre_lineage(
                connection,
                "CALIBRE_RECORD",
                target.reference_id,
            )
            _require_lineage(candidate, lineage, "Calibre target")
            return
        if target.carrier is MetadataTargetCarrier.SIDECAR:
            lineage = _calibre_lineage(
                connection,
                "CALIBRE_SIDECAR",
                target.reference_id,
            )
            if lineage is not None:
                _require_lineage(candidate, lineage, "sidecar target")
            return
        # EXTERNAL_TOOL references are deliberately opaque and provider-neutral.

    def _validate_evidence_reference(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
        evidence: MetadataEvidenceReference,
        material_by_reference: dict[tuple[str, EntityId], str],
        *,
        field_path: str | None = None,
        expected_value: str | None = None,
        expected_state: ValueState | None = None,
    ) -> None:
        key = (evidence.kind, evidence.ref_id)
        previous = material_by_reference.setdefault(key, evidence.material_fingerprint)
        if previous != evidence.material_fingerprint:
            raise MetadataCorrectionStoreError("evidence material binding differs")
        if evidence.kind == "FILE_OBSERVATION":
            if evidence.ref_id != candidate.observation_id:
                raise MetadataCorrectionStoreError("observation evidence has foreign lineage")
            return

        table = _EVIDENCE_TABLES.get(evidence.kind)
        if table is None:
            raise MetadataCorrectionStoreError("evidence kind is not supported")
        row = (
            connection.execute(select(table).where(table.c.id == str(evidence.ref_id)))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise MetadataCorrectionStoreError("evidence reference does not exist")
        if evidence.kind in {
            "VALUE_ASSERTION",
            "TOOL_RESULT",
            "FINGERPRINT",
            "EXTERNAL_IDENTIFIER",
            "CLASSIFICATION_ASSERTION",
        }:
            _validate_target_lineage(connection, candidate, row)
        if evidence.kind == "VALUE_ASSERTION" and field_path is not None:
            if str(row["field_name"]) != field_path:
                raise MetadataCorrectionStoreError("value assertion field differs")
            if expected_value is not None and str(row["value"]) != expected_value:
                raise MetadataCorrectionStoreError("value assertion payload differs")
            if expected_state is not None and str(row["state"]) != expected_state.value:
                raise MetadataCorrectionStoreError("value assertion state differs")
        if evidence.kind == "TOOL_RESULT" and field_path is not None:
            if str(row["key"]) != field_path:
                raise MetadataCorrectionStoreError("tool result field differs")
            if expected_value is not None and str(row["value"]) != expected_value:
                raise MetadataCorrectionStoreError("tool result payload differs")

    def _validate_dependency(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
        dependency: MetadataDependencySnapshot,
    ) -> None:
        profile_kind = {
            MetadataDependencyKind.CALIBRE: "calibre-dependency/v1",
            MetadataDependencyKind.SIDECAR: "sidecar-dependency/v1",
            MetadataDependencyKind.ARCHIVE: "archive-dependency/v1",
        }[dependency.kind]
        if dependency.snapshot_kind == profile_kind:
            if dependency.snapshot_id != candidate.observation_id:
                raise MetadataCorrectionStoreError("dependency snapshot has foreign lineage")
            return
        if dependency.snapshot_kind == "FILE_OBSERVATION":
            if dependency.snapshot_id != candidate.observation_id:
                raise MetadataCorrectionStoreError("dependency observation has foreign lineage")
            return
        allowed = _DEPENDENCY_KINDS[dependency.kind]
        if dependency.snapshot_kind not in allowed:
            raise MetadataCorrectionStoreError("dependency snapshot kind is incompatible")
        if dependency.snapshot_kind == "ARCHIVE_OBSERVATION":
            row = connection.execute(
                select(
                    archive_schema.archive_observations.c.scan_root_id,
                    archive_schema.archive_observations.c.source_scan_run_id,
                ).where(archive_schema.archive_observations.c.id == str(dependency.snapshot_id))
            ).one_or_none()
            lineage = None if row is None else (str(row.scan_root_id), str(row.source_scan_run_id))
        else:
            lineage = _calibre_lineage(
                connection,
                dependency.snapshot_kind,
                dependency.snapshot_id,
            )
        _require_lineage(candidate, lineage, "dependency snapshot")

    def _latest_review(
        self,
        connection: Connection,
        candidate: MetadataCorrectionCandidate,
    ) -> MetadataCorrectionReviewSnapshot:
        item = (
            connection.execute(
                select(review_schema.review_items)
                .where(
                    review_schema.review_items.c.review_type == METADATA_CORRECTION_REVIEW_TYPE,
                    review_schema.review_items.c.subject_kind == EntityKind.FILE.value,
                    review_schema.review_items.c.subject_id == str(candidate.file_id),
                    review_schema.review_items.c.candidate_kind
                    == METADATA_CORRECTION_REVIEW_CANDIDATE_KIND,
                    review_schema.review_items.c.candidate_id == str(candidate.id),
                    review_schema.review_items.c.producer_name == METADATA_CORRECTION_PRODUCER_NAME,
                    review_schema.review_items.c.decision_compatibility_version
                    == METADATA_CORRECTION_DECISION_COMPATIBILITY,
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
            return MetadataCorrectionReviewSnapshot(
                candidate_id=candidate.id,
                state=MetadataCorrectionReviewState.MISSING,
                evidence_fingerprint=candidate.evidence_fingerprint,
                candidate_set_fingerprint=candidate.content_hash,
            )
        if str(item["producer_version"]) != METADATA_CORRECTION_PRODUCER_VERSION:
            raise MetadataCorrectionStoreError("review producer version is incompatible")
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
            state = MetadataCorrectionReviewState.STALE
            decision = None
        elif decision is None:
            if item_state is ReviewItemState.DECIDED:
                raise MetadataCorrectionStoreError("decided review has no decision")
            state = (
                MetadataCorrectionReviewState.DEFERRED
                if item_state is ReviewItemState.DEFERRED
                else MetadataCorrectionReviewState.PENDING
            )
        else:
            if (
                str(decision["evidence_fingerprint"]) != candidate.evidence_fingerprint
                or str(decision["candidate_set_fingerprint"]) != candidate.content_hash
                or str(decision["decision_compatibility_version"])
                != METADATA_CORRECTION_DECISION_COMPATIBILITY
            ):
                raise MetadataCorrectionStoreError("latest review decision is stale")
            value = ReviewDecisionValue(str(decision["decision"]))
            if value is ReviewDecisionValue.DEFER:
                if item_state is not ReviewItemState.DEFERRED:
                    raise MetadataCorrectionStoreError("deferred review state differs")
                state = MetadataCorrectionReviewState.DEFERRED
                decision = None
            else:
                if item_state is not ReviewItemState.DECIDED:
                    raise MetadataCorrectionStoreError("decided review state differs")
                state = (
                    MetadataCorrectionReviewState.ACCEPTED
                    if value is ReviewDecisionValue.ACCEPT
                    else MetadataCorrectionReviewState.REJECTED
                )
        return MetadataCorrectionReviewSnapshot(
            candidate_id=candidate.id,
            state=state,
            evidence_fingerprint=candidate.evidence_fingerprint,
            candidate_set_fingerprint=candidate.content_hash,
            producer_version=str(item["producer_version"]),
            review_item_id=item_id,
            decision_id=(None if decision is None else EntityId.parse(str(decision["id"]))),
            decision_sequence_no=(None if decision is None else int(decision["sequence_no"])),
        )

    def _validate_latest_review(
        self,
        connection: Connection,
        plan: MetadataCorrectionPlan,
    ) -> None:
        latest = self._latest_review(connection, plan.candidate)
        if plan.review is None:
            if latest.state is not MetadataCorrectionReviewState.MISSING:
                raise MetadataCorrectionStoreError("plan omits an existing compatible review")
            return
        if plan.review != latest:
            raise MetadataCorrectionStoreError("plan review is not the latest compatible review")

    def _validate_historical_review(
        self,
        connection: Connection,
        plan: MetadataCorrectionPlan,
    ) -> None:
        """Validate immutable review bindings without requiring them to remain latest."""

        review = plan.review
        if review is None:
            return
        if (
            review.candidate_id != plan.candidate.id
            or review.evidence_fingerprint != plan.candidate.evidence_fingerprint
            or review.candidate_set_fingerprint != plan.candidate.content_hash
        ):
            raise MetadataCorrectionStoreError("persisted plan review binding differs")
        if review.state is MetadataCorrectionReviewState.MISSING:
            return
        if review.review_item_id is None:
            raise MetadataCorrectionStoreError("persisted plan review item is missing")
        item = (
            connection.execute(
                select(review_schema.review_items).where(
                    review_schema.review_items.c.id == str(review.review_item_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if item is None:
            raise MetadataCorrectionStoreError("persisted plan review item is missing")
        if (
            str(item["review_type"]) != review.review_type
            or str(item["subject_kind"]) != EntityKind.FILE.value
            or str(item["subject_id"]) != str(plan.candidate.file_id)
            or str(item["candidate_kind"]) != review.candidate_kind
            or str(item["candidate_id"]) != str(plan.candidate.id)
            or str(item["producer_name"]) != review.producer_name
            or str(item["producer_version"]) != review.producer_version
            or str(item["decision_compatibility_version"]) != review.decision_compatibility_version
            or str(item["evidence_fingerprint"]) != review.evidence_fingerprint
            or str(item["candidate_set_fingerprint"]) != review.candidate_set_fingerprint
        ):
            raise MetadataCorrectionStoreError("persisted plan review item differs")

        if review.state not in {
            MetadataCorrectionReviewState.ACCEPTED,
            MetadataCorrectionReviewState.REJECTED,
        }:
            return
        decision = (
            connection.execute(
                select(review_schema.review_decisions).where(
                    review_schema.review_decisions.c.id == str(review.decision_id),
                    review_schema.review_decisions.c.review_item_id == str(review.review_item_id),
                    review_schema.review_decisions.c.sequence_no == review.decision_sequence_no,
                )
            )
            .mappings()
            .one_or_none()
        )
        expected_value = (
            ReviewDecisionValue.ACCEPT
            if review.state is MetadataCorrectionReviewState.ACCEPTED
            else ReviewDecisionValue.REJECT
        )
        if (
            decision is None
            or ReviewDecisionValue(str(decision["decision"])) is not expected_value
            or str(decision["evidence_fingerprint"]) != review.evidence_fingerprint
            or str(decision["candidate_set_fingerprint"]) != review.candidate_set_fingerprint
            or str(decision["decision_compatibility_version"])
            != review.decision_compatibility_version
        ):
            raise MetadataCorrectionStoreError("persisted plan review decision differs")


def _candidate_row(candidate: MetadataCorrectionCandidate) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "profile": candidate.profile,
        "serializer_version": candidate.serializer_version,
        "scan_root_id": str(candidate.scan_root_id),
        "source_scan_run_id": str(candidate.source_scan_run_id),
        "source_scan_run_status": candidate.source_scan_run_status.value,
        "file_id": str(candidate.file_id),
        "observation_id": str(candidate.observation_id),
        "format_label": candidate.format_label,
        "expected_presence_state": candidate.expected_presence_state.value,
        "expected_full_sha256": candidate.expected_full_sha256,
        "expected_size_bytes": candidate.expected_size_bytes,
        "expected_modified_at": datetime_to_db(candidate.expected_modified_at),
        "expected_observed_at": datetime_to_db(candidate.expected_observed_at),
        "metadata_evidence_fingerprint": candidate.metadata_evidence_fingerprint,
        "target_carrier": candidate.target.carrier.value,
        "target_reference_kind": candidate.target.reference_kind.value,
        "target_reference_id": str(candidate.target.reference_id),
        "target_state_fingerprint": candidate.target.carrier_state_fingerprint,
        "writer_profile": candidate.writer_requirement.profile,
        "writer_format_label": candidate.writer_requirement.format_label,
        "writer_target_carrier": candidate.writer_requirement.target_carrier.value,
        "writer_material_fingerprint": candidate.writer_requirement.material_fingerprint,
        "field_count": len(candidate.field_corrections),
        "dependency_count": len(candidate.dependencies),
        "evidence_count": len(candidate.evidence_refs),
        "evidence_fingerprint": candidate.evidence_fingerprint,
        "content_hash": candidate.content_hash,
        "created_at": datetime_to_db(candidate.created_at),
    }


def _plan_row(plan: MetadataCorrectionPlan) -> dict[str, object]:
    return {
        "id": str(plan.id),
        "profile": plan.profile,
        "serializer_version": plan.serializer_version,
        "candidate_id": str(plan.candidate.id),
        "review_count": 0 if plan.review is None else 1,
        "precondition_count": len(plan.preconditions),
        "blocker_count": len(plan.blockers),
        "status": plan.status.value,
        "execution_state": plan.execution_state.value,
        "content_hash": plan.content_hash,
        "created_at": datetime_to_db(plan.created_at),
    }


def _validate_candidate_identity(candidate: MetadataCorrectionCandidate) -> None:
    if candidate.profile != METADATA_CORRECTION_CANDIDATE_PROFILE:
        raise MetadataCorrectionStoreError("candidate profile is incompatible")
    if metadata_correction_candidate_evidence_fingerprint(candidate) != (
        candidate.evidence_fingerprint
    ):
        raise MetadataCorrectionStoreError("candidate evidence fingerprint differs")
    if metadata_correction_candidate_content_hash(candidate) != candidate.content_hash:
        raise MetadataCorrectionStoreError("candidate content hash differs")
    if metadata_correction_candidate_id(candidate.content_hash) != candidate.id:
        raise MetadataCorrectionStoreError("candidate content identity differs")
    for field in candidate.field_corrections:
        if (
            metadata_field_selection_fingerprint(
                field_path=field.field_path,
                operation=field.operation,
                observed_values=field.observed_values,
                selected_values=field.selected_values,
            )
            != field.selection_fingerprint
        ):
            raise MetadataCorrectionStoreError("field selection fingerprint differs")
    requirement = candidate.writer_requirement
    if (
        metadata_writer_requirement_fingerprint(
            format_label=requirement.format_label,
            target_carrier=requirement.target_carrier,
        )
        != requirement.material_fingerprint
    ):
        raise MetadataCorrectionStoreError("writer requirement fingerprint differs")


def _validate_plan_identity(plan: MetadataCorrectionPlan) -> None:
    if plan.profile != METADATA_CORRECTION_PLAN_PROFILE:
        raise MetadataCorrectionStoreError("plan profile is incompatible")
    _validate_candidate_identity(plan.candidate)
    if metadata_correction_plan_content_hash(plan) != plan.content_hash:
        raise MetadataCorrectionStoreError("plan content hash differs")
    if metadata_correction_plan_id(plan.content_hash) != plan.id:
        raise MetadataCorrectionStoreError("plan content identity differs")


def _validate_plan_reducer(plan: MetadataCorrectionPlan) -> None:
    expected = build_metadata_correction_plan(
        MetadataCorrectionPlanInputs(
            candidate=plan.candidate,
            review=plan.review,
            preserved_fields_fingerprint=plan.verification.preserved_fields_fingerprint,
            analysis_profile=plan.verification.analysis_profile,
            lineage_matches=True,
            source_evidence_complete=True,
            field_selection_valid=True,
            target_carrier_valid=True,
            writer_requirement_valid=True,
            preconditions_complete=True,
            verification_contract_complete=True,
        ),
        clock=lambda: plan.created_at,
    )
    if expected != plan:
        raise MetadataCorrectionStoreError("plan differs from the canonical reducer")


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
    ordinals = tuple(int(row["ordinal"]) for row in rows)
    if ordinals != tuple(range(expected)):
        raise MetadataCorrectionStoreError(f"persisted {label} are not contiguous")
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
        raise MetadataCorrectionStoreError(f"persisted {label} count exceeds bound")
    rows = (
        connection.execute(select(table).where(where).order_by(*order_by).limit(maximum + 1))
        .mappings()
        .all()
    )
    if len(rows) != expected:
        raise MetadataCorrectionStoreError(f"persisted {label} count differs")
    return list(rows)


def _evidence_from_row(row: RowMapping) -> MetadataEvidenceReference:
    return MetadataEvidenceReference(
        kind=str(row["kind"]),
        ref_id=EntityId.parse(str(row["ref_id"])),
        material_fingerprint=str(row["material_fingerprint"]),
    )


def _value_from_row(row: RowMapping) -> MetadataValueSnapshot:
    return MetadataValueSnapshot(
        ordinal=int(row["ordinal"]),
        state=ValueState(str(row["value_state"])),
        source_ref=MetadataEvidenceReference(
            kind=str(row["source_kind"]),
            ref_id=EntityId.parse(str(row["source_id"])),
            material_fingerprint=str(row["source_material_fingerprint"]),
        ),
        value=str(row["value"]),
    )


def _values_for_field(
    rows: list[RowMapping],
    field_ordinal: int,
    value_set: str,
) -> tuple[MetadataValueSnapshot, ...]:
    values = tuple(
        _value_from_row(row)
        for row in rows
        if int(row["field_ordinal"]) == field_ordinal and str(row["value_set"]) == value_set
    )
    if tuple(value.ordinal for value in values) != tuple(range(len(values))):
        raise MetadataCorrectionStoreError("persisted value ordinals are not contiguous")
    return values


def _evidence_for_field(
    rows: list[RowMapping],
    field_ordinal: int,
) -> tuple[MetadataEvidenceReference, ...]:
    selected = tuple(row for row in rows if int(row["field_ordinal"]) == field_ordinal)
    if tuple(int(row["ordinal"]) for row in selected) != tuple(range(len(selected))):
        raise MetadataCorrectionStoreError("persisted field evidence is not contiguous")
    return tuple(_evidence_from_row(row) for row in selected)


def _review_from_row(row: RowMapping) -> MetadataCorrectionReviewSnapshot:
    return MetadataCorrectionReviewSnapshot(
        candidate_id=EntityId.parse(str(row["candidate_id"])),
        state=MetadataCorrectionReviewState(str(row["state"])),
        evidence_fingerprint=str(row["evidence_fingerprint"]),
        candidate_set_fingerprint=str(row["candidate_set_fingerprint"]),
        producer_name=str(row["producer_name"]),
        producer_version=str(row["producer_version"]),
        decision_compatibility_version=str(row["decision_compatibility_version"]),
        review_type=str(row["review_type"]),
        candidate_kind=str(row["candidate_kind"]),
        review_item_id=(
            None if row["review_item_id"] is None else EntityId.parse(str(row["review_item_id"]))
        ),
        decision_id=(
            None if row["decision_id"] is None else EntityId.parse(str(row["decision_id"]))
        ),
        decision_sequence_no=(
            None if row["decision_sequence_no"] is None else int(row["decision_sequence_no"])
        ),
    )


def _validate_target_lineage(
    connection: Connection,
    candidate: MetadataCorrectionCandidate,
    row: RowMapping,
) -> None:
    target_kind = str(row["target_kind"])
    target_id = EntityId.parse(str(row["target_id"]))
    if target_kind == EntityKind.FILE.value:
        if target_id != candidate.file_id:
            raise MetadataCorrectionStoreError("evidence targets a foreign file")
        return
    if target_kind == EntityKind.FILE_OBSERVATION.value:
        if target_id != candidate.observation_id:
            raise MetadataCorrectionStoreError("evidence targets a foreign observation")
        return
    try:
        entity_kind = EntityKind(target_kind)
    except ValueError as error:
        raise MetadataCorrectionStoreError("evidence target kind is unsupported") from error
    table = _ENTITY_TABLES.get(entity_kind)
    if (
        table is None
        or connection.execute(
            select(table.c.id).where(table.c.id == str(target_id))
        ).scalar_one_or_none()
        is None
    ):
        raise MetadataCorrectionStoreError("evidence target does not exist")


def _entity_exists(connection: Connection, entity_id: EntityId) -> bool:
    return any(
        connection.execute(
            select(table.c.id).where(table.c.id == str(entity_id))
        ).scalar_one_or_none()
        is not None
        for table in (schema.works, schema.editions, schema.series)
    )


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


def _require_lineage(
    candidate: MetadataCorrectionCandidate,
    lineage: tuple[str, str] | None,
    label: str,
) -> None:
    if lineage != (str(candidate.scan_root_id), str(candidate.source_scan_run_id)):
        raise MetadataCorrectionStoreError(f"{label} has missing or foreign lineage")


_ENTITY_TABLES = {
    EntityKind.AGENT: schema.agents,
    EntityKind.WORK: schema.works,
    EntityKind.EDITION: schema.editions,
    EntityKind.SERIES: schema.series,
    EntityKind.MUSIC_WORK: schema.music_works,
    EntityKind.RECORDING: schema.recordings,
    EntityKind.RELEASE_GROUP: schema.release_groups,
    EntityKind.RELEASE: schema.releases,
}

_EVIDENCE_TABLES = {
    "VALUE_ASSERTION": schema.value_assertions,
    "TOOL_RESULT": schema.tool_results,
    "FINGERPRINT": schema.fingerprints,
    "EXTERNAL_IDENTIFIER": schema.external_identifiers,
    "CLASSIFICATION_ASSERTION": schema.classification_assertions,
    "REVIEW_DECISION": review_schema.review_decisions,
}

_DEPENDENCY_KINDS = {
    MetadataDependencyKind.CALIBRE: frozenset(
        {"CALIBRE_SNAPSHOT", "CALIBRE_RECORD", "CALIBRE_FORMAT", "CALIBRE_FINDING"}
    ),
    MetadataDependencyKind.SIDECAR: frozenset({"CALIBRE_SIDECAR"}),
    MetadataDependencyKind.ARCHIVE: frozenset({"ARCHIVE_OBSERVATION"}),
}

__all__ = [
    "MAX_METADATA_CORRECTION_BLOCKERS",
    "MAX_METADATA_CORRECTION_PRECONDITIONS",
    "MetadataCorrectionStoreError",
    "SQLiteMetadataCorrectionStore",
]
