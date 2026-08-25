"""Crash-atomic SQLite adapter for the fixity product surface."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from foliotone.application.contracts import (
    EbookFixityBaselineActivationCommand,
    EbookFixityBaselineActivationResult,
)
from foliotone.core import EntityId
from foliotone.fixity.confirmation import verify_fixity_baseline_confirmation
from foliotone.persistence.fixity import SQLiteEbookFixityBaselineStore
from foliotone.persistence.surface_schema import (
    surface_audit_events,
    surface_command_receipts,
    surface_grants,
    surface_sessions,
)
from foliotone.surface.contracts import Scope

_PROFILE = "ebook-fixity-baseline-activation/v1"


class SQLiteEbookFixityBaselineActivationOperation:
    """Bind receipt, fresh REVIEW authority, activation, and response atomically."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._baseline_store = SQLiteEbookFixityBaselineStore(engine)

    def activate(
        self,
        command: EbookFixityBaselineActivationCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        activated_at: datetime,
    ) -> EbookFixityBaselineActivationResult:
        try:
            return self._activate(
                command,
                actor_id=actor_id,
                session_id=session_id,
                input_digest=input_digest,
                idempotency_digest=idempotency_digest,
                activated_at=activated_at,
            )
        except SQLAlchemyError as error:
            raise RuntimeError("fixity baseline activation transaction failed") from error

    def _activate(
        self,
        command: EbookFixityBaselineActivationCommand,
        *,
        actor_id: str,
        session_id: str,
        input_digest: str,
        idempotency_digest: str,
        activated_at: datetime,
    ) -> EbookFixityBaselineActivationResult:
        with self._engine.begin() as connection:
            # Serialize receipt reservation before reading it so concurrent
            # identical retries cannot both observe an absent receipt.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            # The plaintext is checked only in memory and inside this transaction.
            verify_fixity_baseline_confirmation(command.manifest_id, command.confirmation)
            existing = (
                connection.execute(
                    select(
                        surface_command_receipts.c.input_digest,
                        surface_command_receipts.c.response_json,
                    ).where(
                        and_(
                            surface_command_receipts.c.actor_id == actor_id,
                            surface_command_receipts.c.command_profile == _PROFILE,
                            surface_command_receipts.c.idempotency_digest == idempotency_digest,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if str(existing["input_digest"]) != input_digest:
                    raise ValueError("fixity activation idempotency conflict")
                return self._decode_response(existing["response_json"])
            self._require_fresh_review_grant(
                connection,
                actor_id=actor_id,
                session_id=session_id,
                activated_at=activated_at,
            )
            receipt_id = str(uuid4())
            connection.execute(
                insert(surface_command_receipts).values(
                    id=receipt_id,
                    actor_id=actor_id,
                    command_profile=_PROFILE,
                    input_digest=input_digest,
                    idempotency_digest=idempotency_digest,
                    response_json=None,
                    status="PENDING",
                    created_at=activated_at,
                )
            )
            activation = self._baseline_store.activate_in_transaction(
                connection,
                command.manifest_id,
                command.confirmation,
                activated_at=activated_at,
            )
            response = {
                "activation_id": str(activation.activation_id),
                "manifest_id": str(activation.manifest_id),
                "status": "ACTIVE",
            }
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
                raise RuntimeError("fixity activation receipt completion failed")
            connection.execute(
                insert(surface_audit_events).values(
                    id=str(uuid4()),
                    actor_id=actor_id,
                    event_type="EBOOK_FIXITY_BASELINE_ACTIVATED",
                    decision="ACCEPTED",
                    correlation_id=None,
                    job_id=None,
                    finding_code=None,
                    occurred_at=activated_at,
                )
            )
            return EbookFixityBaselineActivationResult(
                activation_id=activation.activation_id,
                manifest_id=activation.manifest_id,
            )

    @staticmethod
    def _require_fresh_review_grant(
        connection: Connection,
        *,
        actor_id: str,
        session_id: str,
        activated_at: datetime,
    ) -> None:
        grant = connection.execute(
            select(surface_grants.c.id)
            .select_from(surface_grants.join(surface_sessions))
            .where(
                surface_grants.c.session_id == session_id,
                surface_grants.c.scope == Scope.REVIEW.value,
                surface_grants.c.revoked_at.is_(None),
                surface_grants.c.created_at >= activated_at - timedelta(minutes=15),
                surface_grants.c.created_at <= activated_at,
                surface_grants.c.expires_at > activated_at,
                surface_sessions.c.id == session_id,
                surface_sessions.c.user_id == actor_id,
                surface_sessions.c.revoked_at.is_(None),
                surface_sessions.c.expires_at > activated_at,
            )
            .limit(1)
        ).first()
        if grant is None:
            raise ValueError("fresh REVIEW grant is required")

    @staticmethod
    def _decode_response(value: object) -> EbookFixityBaselineActivationResult:
        if value is None:
            raise RuntimeError("fixity activation is pending")
        try:
            response = json.loads(str(value))
            if not isinstance(response, dict) or response.get("status") != "ACTIVE":
                raise ValueError
            return EbookFixityBaselineActivationResult(
                activation_id=EntityId.parse(str(response["activation_id"])),
                manifest_id=EntityId.parse(str(response["manifest_id"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("fixity activation receipt is corrupt") from error
