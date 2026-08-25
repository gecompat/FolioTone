"""Crash-atomic SQLite commands for Fixity review and expectation changes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from foliotone.application.contracts import (
    EbookFixityExpectationRevisionCommand,
    EbookFixityExpectationRevisionResult,
    EbookFixityReviewCommand,
    EbookFixityReviewResult,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    ReviewActorKind,
    ReviewCandidateKind,
    ReviewDecision,
    ReviewDecisionValue,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.fixity.verification_contracts import (
    EBOOK_FIXITY_DECISION_PROFILE,
    EbookFixityExpectationAction,
    EbookFixityExpectationDecisionInput,
)
from foliotone.persistence.fixity_verification import SQLiteEbookFixityVerificationStore
from foliotone.persistence.resolution_review import SQLiteResolutionReviewStore
from foliotone.persistence.surface_schema import (
    surface_audit_events,
    surface_command_receipts,
    surface_grants,
    surface_sessions,
)
from foliotone.surface.contracts import Scope

_REVIEW_PROFILE = "ebook-fixity-result-review/v1"
_EXPECTATION_PROFILE = "ebook-fixity-expectation-revision/v1"
_PRODUCER_NAME = "ebook-fixity-verification"
_PRODUCER_VERSION = "1"


class SQLiteEbookFixityCommandOperation:
    """Bind receipt, REVIEW authority, review ledger, and revision atomically."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._reviews = SQLiteResolutionReviewStore(engine)
        self._verification = SQLiteEbookFixityVerificationStore(engine)

    def review_result(
        self,
        command: EbookFixityReviewCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        decided_at: datetime,
    ) -> EbookFixityReviewResult:
        self._require_digest(input_digest, "input_digest")
        self._require_digest(idempotency_digest, "idempotency_digest")
        try:
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    result = self._review_result_in_transaction(
                        connection,
                        command,
                        actor_id=actor_id,
                        session_id=session_id,
                        input_digest=input_digest,
                        idempotency_digest=idempotency_digest,
                        decided_at=decided_at,
                    )
                except Exception:
                    connection.rollback()
                    raise
                connection.commit()
                return result
        except SQLAlchemyError as error:
            raise RuntimeError("fixity review transaction failed") from error

    def revise_expectation(
        self,
        command: EbookFixityExpectationRevisionCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        created_at: datetime,
    ) -> EbookFixityExpectationRevisionResult:
        self._require_digest(input_digest, "input_digest")
        self._require_digest(idempotency_digest, "idempotency_digest")
        try:
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    result = self._revise_expectation_in_transaction(
                        connection,
                        command,
                        actor_id=actor_id,
                        session_id=session_id,
                        input_digest=input_digest,
                        idempotency_digest=idempotency_digest,
                        created_at=created_at,
                    )
                except Exception:
                    connection.rollback()
                    raise
                connection.commit()
                return result
        except SQLAlchemyError as error:
            raise RuntimeError("fixity expectation transaction failed") from error

    def _review_result_in_transaction(
        self,
        connection: Connection,
        command: EbookFixityReviewCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        decided_at: datetime,
    ) -> EbookFixityReviewResult:
        self._require_fresh_review_grant(
            connection,
            actor_id=actor_id,
            session_id=session_id,
            occurred_at=decided_at,
        )
        receipt_id, replay = self._reserve_receipt(
            connection,
            actor_id=actor_id,
            command_profile=_REVIEW_PROFILE,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            occurred_at=decided_at,
        )
        if replay is not None:
            return self._decode_review_response(replay)
        record, evidence, candidates = self._verification.review_material_in_transaction(
            connection,
            command.result_id,
        )
        template = ReviewItem(
            id=EntityId.new(),
            review_type=ReviewType.FIXITY_EXPECTATION,
            subject_kind=EntityKind.FILE,
            subject_id=record.file_id,
            candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
            candidate_id=record.result_id,
            producer_name=_PRODUCER_NAME,
            producer_version=_PRODUCER_VERSION,
            decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
            evidence_fingerprint=evidence,
            candidate_set_fingerprint=candidates,
            state=ReviewItemState.PENDING,
            created_at=decided_at,
        )
        item = self._reviews.exact_review_in_transaction(connection, template)
        if item is None:
            item = self._reviews.enqueue_or_get_review_in_transaction(connection, template)
        latest = self._reviews.latest_decision_in_transaction(connection, item.id)
        decision = ReviewDecision(
            id=EntityId.new(),
            review_item_id=item.id,
            sequence_no=1 if latest is None else latest.sequence_no + 1,
            decision=ReviewDecisionValue(command.decision),
            decision_reason="REVIEWED_FIXITY_RESULT",
            evidence_fingerprint=evidence,
            candidate_set_fingerprint=candidates,
            decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
            actor_kind=ReviewActorKind.USER,
            decided_at=decided_at,
        )
        stored = self._reviews.append_decision_in_transaction(
            connection,
            decision,
            expected_latest_decision_id=None if latest is None else latest.id,
        )
        result = EbookFixityReviewResult(
            result_id=record.result_id,
            review_item_id=item.id,
            decision_id=stored.id,
            decision=stored.decision.value,
            sequence_no=stored.sequence_no,
        )
        self._complete_receipt(
            connection,
            receipt_id,
            self._review_response(result),
        )
        self._audit(connection, actor_id, "EBOOK_FIXITY_RESULT_REVIEWED", decided_at)
        return result

    def _revise_expectation_in_transaction(
        self,
        connection: Connection,
        command: EbookFixityExpectationRevisionCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        created_at: datetime,
    ) -> EbookFixityExpectationRevisionResult:
        self._require_fresh_review_grant(
            connection,
            actor_id=actor_id,
            session_id=session_id,
            occurred_at=created_at,
        )
        receipt_id, replay = self._reserve_receipt(
            connection,
            actor_id=actor_id,
            command_profile=_EXPECTATION_PROFILE,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
            occurred_at=created_at,
        )
        if replay is not None:
            return self._decode_expectation_response(replay)
        record, evidence, candidates = self._verification.review_material_in_transaction(
            connection,
            command.result_id,
        )
        template = ReviewItem(
            id=EntityId.new(),
            review_type=ReviewType.FIXITY_EXPECTATION,
            subject_kind=EntityKind.FILE,
            subject_id=record.file_id,
            candidate_kind=ReviewCandidateKind.FIXITY_RESULT,
            candidate_id=record.result_id,
            producer_name=_PRODUCER_NAME,
            producer_version=_PRODUCER_VERSION,
            decision_compatibility_version=EBOOK_FIXITY_DECISION_PROFILE,
            evidence_fingerprint=evidence,
            candidate_set_fingerprint=candidates,
            state=ReviewItemState.PENDING,
            created_at=created_at,
        )
        item = self._reviews.exact_review_in_transaction(connection, template)
        if item is None:
            raise ValueError("accepted current fixity review is required")
        latest = self._reviews.latest_decision_in_transaction(connection, item.id)
        if latest is None or latest.decision is not ReviewDecisionValue.ACCEPT:
            raise ValueError("latest fixity review decision must be ACCEPT")
        decision_input = EbookFixityExpectationDecisionInput(
            result_id=record.result_id,
            run_id=record.run_id,
            file_id=record.file_id,
            action=EbookFixityExpectationAction(command.action),
            evidence_fingerprint=evidence,
            candidate_set_fingerprint=candidates,
            review_decision_id=latest.id,
        )
        revision = self._verification.append_expectation_revision_in_transaction(
            connection,
            decision_input,
            created_at=created_at,
            lease_token=uuid4().hex,
            lease_expires_at=created_at + timedelta(minutes=5),
        )
        result = EbookFixityExpectationRevisionResult(
            result_id=record.result_id,
            revision_id=revision.id,
            action=revision.action.value,
            revision_no=revision.revision_no,
        )
        self._complete_receipt(
            connection,
            receipt_id,
            self._expectation_response(result),
        )
        self._audit(connection, actor_id, "EBOOK_FIXITY_EXPECTATION_REVISED", created_at)
        return result

    @staticmethod
    def _require_fresh_review_grant(
        connection: Connection,
        *,
        actor_id: str,
        session_id: str,
        occurred_at: datetime,
    ) -> None:
        grant = connection.execute(
            select(surface_grants.c.id)
            .select_from(surface_grants.join(surface_sessions))
            .where(
                surface_grants.c.session_id == session_id,
                surface_grants.c.scope == Scope.REVIEW.value,
                surface_grants.c.revoked_at.is_(None),
                surface_grants.c.created_at >= occurred_at - timedelta(minutes=15),
                surface_grants.c.created_at <= occurred_at,
                surface_grants.c.expires_at > occurred_at,
                surface_sessions.c.id == session_id,
                surface_sessions.c.user_id == actor_id,
                surface_sessions.c.revoked_at.is_(None),
                surface_sessions.c.expires_at > occurred_at,
            )
            .limit(1)
        ).first()
        if grant is None:
            raise ValueError("fresh REVIEW grant is required")

    @staticmethod
    def _reserve_receipt(
        connection: Connection,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
        occurred_at: datetime,
    ) -> tuple[str, object | None]:
        existing = (
            connection.execute(
                select(
                    surface_command_receipts.c.id,
                    surface_command_receipts.c.input_digest,
                    surface_command_receipts.c.response_json,
                    surface_command_receipts.c.status,
                ).where(
                    and_(
                        surface_command_receipts.c.actor_id == actor_id,
                        surface_command_receipts.c.command_profile == command_profile,
                        surface_command_receipts.c.idempotency_digest == idempotency_digest,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if str(existing["input_digest"]) != input_digest:
                raise ValueError("fixity command idempotency conflict")
            if existing["response_json"] is None:
                raise RuntimeError("fixity command receipt is pending")
            if str(existing["status"]) != "COMPLETED":
                raise RuntimeError("fixity command receipt is corrupt")
            return str(existing["id"]), existing["response_json"]
        receipt_id = str(uuid4())
        connection.execute(
            insert(surface_command_receipts).values(
                id=receipt_id,
                actor_id=actor_id,
                command_profile=command_profile,
                input_digest=input_digest,
                idempotency_digest=idempotency_digest,
                response_json=None,
                status="PENDING",
                created_at=occurred_at,
            )
        )
        return receipt_id, None

    @staticmethod
    def _require_digest(value: str, name: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"{name} must be a SHA-256 digest")

    @staticmethod
    def _complete_receipt(
        connection: Connection,
        receipt_id: str,
        response: dict[str, object],
    ) -> None:
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
        changed = connection.execute(
            update(surface_command_receipts)
            .where(
                surface_command_receipts.c.id == receipt_id,
                surface_command_receipts.c.status == "PENDING",
                surface_command_receipts.c.response_json.is_(None),
            )
            .values(response_json=encoded, status="COMPLETED")
        ).rowcount
        if changed != 1:
            raise RuntimeError("fixity command receipt completion failed")

    @staticmethod
    def _review_response(result: EbookFixityReviewResult) -> dict[str, object]:
        return {
            "result_id": str(result.result_id),
            "review_item_id": str(result.review_item_id),
            "decision_id": str(result.decision_id),
            "decision": result.decision,
            "sequence_no": result.sequence_no,
        }

    @classmethod
    def _decode_review_response(cls, value: object) -> EbookFixityReviewResult:
        payload = cls._decode_response(value)
        try:
            return EbookFixityReviewResult(
                result_id=EntityId.parse(str(payload["result_id"])),
                review_item_id=EntityId.parse(str(payload["review_item_id"])),
                decision_id=EntityId.parse(str(payload["decision_id"])),
                decision=str(payload["decision"]),
                sequence_no=int(str(payload["sequence_no"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("fixity review receipt is corrupt") from error

    @staticmethod
    def _expectation_response(
        result: EbookFixityExpectationRevisionResult,
    ) -> dict[str, object]:
        return {
            "result_id": str(result.result_id),
            "revision_id": str(result.revision_id),
            "action": result.action,
            "revision_no": result.revision_no,
        }

    @classmethod
    def _decode_expectation_response(
        cls,
        value: object,
    ) -> EbookFixityExpectationRevisionResult:
        payload = cls._decode_response(value)
        try:
            return EbookFixityExpectationRevisionResult(
                result_id=EntityId.parse(str(payload["result_id"])),
                revision_id=EntityId.parse(str(payload["revision_id"])),
                action=str(payload["action"]),
                revision_no=int(str(payload["revision_no"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("fixity expectation receipt is corrupt") from error

    @staticmethod
    def _decode_response(value: object) -> dict[str, object]:
        try:
            payload = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("fixity command receipt is corrupt") from error
        if not isinstance(payload, dict):
            raise RuntimeError("fixity command receipt is corrupt")
        return payload

    @staticmethod
    def _audit(
        connection: Connection,
        actor_id: str,
        event_type: str,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            insert(surface_audit_events).values(
                id=str(uuid4()),
                actor_id=actor_id,
                event_type=event_type,
                decision="ACCEPTED",
                correlation_id=None,
                job_id=None,
                finding_code=None,
                occurred_at=occurred_at,
            )
        )
