"""SQLite stores for authentication, audit records, and fenced application jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from foliotone.application.contracts import (
    EbookFixityAnalysisJobProfile,
    EbookRenameOperatorJobProfile,
)
from foliotone.core import EntityId
from foliotone.ebook_rename.confirmation import (
    EbookRenameConfirmationError,
    ebook_rename_confirmation_digest,
)
from foliotone.persistence.ebook_rename import SQLiteEbookRenameStore
from foliotone.persistence.surface_schema import (
    application_job_events,
    application_jobs,
    ebook_fixity_analysis_job_binders,
    ebook_fixity_analysis_job_results,
    ebook_rename_operator_job_binders,
    ebook_rename_operator_job_results,
    surface_audit_events,
    surface_auth_attempts,
    surface_bootstrap_tokens,
    surface_command_receipts,
    surface_grants,
    surface_sessions,
    surface_users,
)
from foliotone.surface.contracts import JobStatus, ProcessRole, Scope


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _timestamp(value: object) -> str:
    """Normalize SQLite's text timestamps without leaking adapter internals."""
    return value.isoformat() if isinstance(value, datetime) else str(value)


@dataclass(frozen=True, slots=True)
class SurfaceUser:
    id: str
    username: str
    password_hash: str
    active: bool


@dataclass(frozen=True, slots=True)
class SurfaceSession:
    id: str
    user_id: str
    csrf_digest: str
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    actor_id: str
    fence_epoch: int
    lease_token: str


@dataclass(frozen=True, slots=True)
class EbookRenameOperatorJobBinder:
    """Immutable, path-free envelope for one ADR-0069 operator job."""

    profile: EbookRenameOperatorJobProfile
    plan_id: str | None
    plan_content_hash: str | None
    capability_id: str | None
    operate_grant_id: str
    authorization_id: str | None = None
    run_id: str | None = None
    confirmation_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.operate_grant_id:
            raise ValueError("e-book rename operator job binder is incomplete")
        shapes = {
            EbookRenameOperatorJobProfile.AUTHORIZE: (
                "required",
                "required",
                "required",
                None,
                None,
                None,
            ),
            EbookRenameOperatorJobProfile.EXECUTE: (
                "required",
                "required",
                "required",
                "required",
                None,
                "required",
            ),
            EbookRenameOperatorJobProfile.RECOVER: (None, None, None, None, "required", None),
        }
        expected = shapes[self.profile]
        actual = (
            self.plan_id,
            self.plan_content_hash,
            self.capability_id,
            self.authorization_id,
            self.run_id,
            self.confirmation_digest,
        )
        if any(
            (need == "required") != bool(value)
            for need, value in zip(expected, actual, strict=True)
        ):
            raise ValueError("e-book rename operator job binder shape is invalid")


@dataclass(frozen=True, slots=True)
class EbookFixityAnalysisJobBinder:
    """Immutable path-free binder for one manually queued fixity job."""

    profile: EbookFixityAnalysisJobProfile
    scan_root_id: str
    worker_count: int = 1

    def __post_init__(self) -> None:
        if not self.scan_root_id or not 1 <= self.worker_count <= 2:
            raise ValueError("fixity analysis job binder is invalid")


class SQLiteSurfaceStore:
    """Explicit SQLAlchemy Core persistence with append-only audit and job events."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ebook_rename_confirmation_digest(
        self,
        *,
        plan_id: str,
        plan_content_hash: str,
        capability_id: str,
        authorization_id: str,
        confirmation_text: str,
    ) -> str:
        """Validate the raw API confirmation using persisted authority, never capability config."""
        try:
            authorization = SQLiteEbookRenameStore(self._engine).get_authorization(
                EntityId.parse(authorization_id)
            )
            if (
                authorization is None
                or str(authorization.plan_id) != plan_id
                or authorization.plan_content_hash != plan_content_hash
                or str(authorization.ebook_rename_capability_id) != capability_id
            ):
                raise ValueError("authorization does not match immutable binders")
            return ebook_rename_confirmation_digest(authorization, confirmation_text)
        except (EbookRenameConfirmationError, TypeError, ValueError):
            raise ValueError("e-book rename confirmation is invalid") from None

    def has_user(self) -> bool:
        with self._engine.connect() as connection:
            return connection.execute(select(surface_users.c.id).limit(1)).first() is not None

    def create_bootstrap(self, digest: str, *, expires_at: datetime) -> None:
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(surface_bootstrap_tokens).values(
                    id=str(uuid4()),
                    token_digest=digest,
                    created_at=now,
                    expires_at=expires_at,
                    attempt_count=0,
                    consumed_at=None,
                )
            )
            self._audit(connection, None, "BOOTSTRAP_CREATED", "ACCEPTED")

    def create_first_user(
        self,
        *,
        token_digest: str,
        username: str,
        username_key: str,
        password_hash: str,
        password_profile: str,
    ) -> SurfaceUser | None:
        now = _now()
        with self._engine.begin() as connection:
            if connection.execute(select(surface_users.c.id).limit(1)).first() is not None:
                return None
            token = (
                connection.execute(
                    select(surface_bootstrap_tokens).where(
                        and_(
                            surface_bootstrap_tokens.c.token_digest == token_digest,
                            surface_bootstrap_tokens.c.consumed_at.is_(None),
                            surface_bootstrap_tokens.c.expires_at > now,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if token is None or int(token["attempt_count"]) >= 5:
                return None
            user = SurfaceUser(str(uuid4()), username, password_hash, True)
            connection.execute(
                insert(surface_users).values(
                    id=user.id,
                    username=username,
                    username_key=username_key,
                    password_hash=password_hash,
                    password_profile=password_profile,
                    created_at=now,
                    active=True,
                )
            )
            connection.execute(
                update(surface_bootstrap_tokens)
                .where(surface_bootstrap_tokens.c.id == token["id"])
                .values(consumed_at=now)
            )
            self._audit(connection, user.id, "SETUP_COMPLETED", "ACCEPTED")
            return user

    def register_bootstrap_failure(self, digest: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_bootstrap_tokens)
                .where(surface_bootstrap_tokens.c.token_digest == digest)
                .values(attempt_count=surface_bootstrap_tokens.c.attempt_count + 1)
            )
            self._audit(connection, None, "SETUP_ATTEMPT", "REJECTED")

    def find_user(self, username_key: str) -> SurfaceUser | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(surface_users).where(surface_users.c.username_key == username_key)
                )
                .mappings()
                .one_or_none()
            )
        return (
            None
            if row is None
            else SurfaceUser(
                str(row["id"]), str(row["username"]), str(row["password_hash"]), bool(row["active"])
            )
        )

    def find_user_by_id(self, user_id: str) -> SurfaceUser | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(select(surface_users).where(surface_users.c.id == user_id))
                .mappings()
                .one_or_none()
            )
        return (
            None
            if row is None
            else SurfaceUser(
                str(row["id"]), str(row["username"]), str(row["password_hash"]), bool(row["active"])
            )
        )

    def login_allowed(self, principal_digest: str) -> bool:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(surface_auth_attempts.c.next_allowed_at).where(
                    and_(
                        surface_auth_attempts.c.principal_digest == principal_digest,
                        surface_auth_attempts.c.attempt_kind == "LOGIN",
                    )
                )
            ).one_or_none()
        return row is None or row.next_allowed_at <= _now()

    def record_login_failure(self, principal_digest: str) -> None:
        now = _now()
        with self._engine.begin() as connection:
            row = connection.execute(
                select(surface_auth_attempts.c.attempt_count).where(
                    and_(
                        surface_auth_attempts.c.principal_digest == principal_digest,
                        surface_auth_attempts.c.attempt_kind == "LOGIN",
                    )
                )
            ).one_or_none()
            attempts = 1 if row is None else int(row.attempt_count) + 1
            values = {
                "attempt_count": attempts,
                "next_allowed_at": now + timedelta(seconds=min(2**attempts, 300)),
            }
            if row is None:
                connection.execute(
                    insert(surface_auth_attempts).values(
                        principal_digest=principal_digest,
                        attempt_kind="LOGIN",
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(surface_auth_attempts)
                    .where(
                        and_(
                            surface_auth_attempts.c.principal_digest == principal_digest,
                            surface_auth_attempts.c.attempt_kind == "LOGIN",
                        )
                    )
                    .values(**values)
                )
            self._audit(connection, None, "LOGIN_ATTEMPT", "REJECTED")

    def clear_login_failures(self, principal_digest: str, actor_id: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_auth_attempts)
                .where(
                    and_(
                        surface_auth_attempts.c.principal_digest == principal_digest,
                        surface_auth_attempts.c.attempt_kind == "LOGIN",
                    )
                )
                .values(attempt_count=0, next_allowed_at=_now())
            )
            self._audit(connection, actor_id, "LOGIN_ATTEMPT", "ACCEPTED")

    def only_user(self) -> SurfaceUser | None:
        with self._engine.connect() as connection:
            rows = connection.execute(select(surface_users).limit(2)).mappings().all()
        if len(rows) != 1:
            return None
        row = rows[0]
        return SurfaceUser(
            str(row["id"]), str(row["username"]), str(row["password_hash"]), bool(row["active"])
        )

    def create_session(
        self, *, user_id: str, token_digest: str, csrf_digest: str
    ) -> SurfaceSession:
        now = _now()
        session = SurfaceSession(
            str(uuid4()),
            user_id,
            csrf_digest,
            now,
            now + timedelta(hours=8),
        )
        with self._engine.begin() as connection:
            connection.execute(
                insert(surface_sessions).values(
                    id=session.id,
                    user_id=user_id,
                    token_digest=token_digest,
                    csrf_digest=csrf_digest,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=session.expires_at,
                    revoked_at=None,
                )
            )
            self._audit(connection, user_id, "SESSION_CREATED", "ACCEPTED")
        return session

    def rotate_session(
        self,
        prior: SurfaceSession,
        *,
        token_digest: str,
        csrf_digest: str,
    ) -> SurfaceSession:
        """Revoke one authenticated session and replace it atomically."""
        now = _now()
        rotated = SurfaceSession(
            str(uuid4()),
            prior.user_id,
            csrf_digest,
            now,
            now + timedelta(hours=8),
        )
        with self._engine.begin() as connection:
            revoked = connection.execute(
                update(surface_sessions)
                .where(
                    and_(
                        surface_sessions.c.id == prior.id,
                        surface_sessions.c.revoked_at.is_(None),
                        surface_sessions.c.expires_at > now,
                    )
                )
                .values(revoked_at=now)
            ).rowcount
            if revoked != 1:
                raise ValueError("session is no longer active")
            connection.execute(
                update(surface_grants)
                .where(
                    and_(
                        surface_grants.c.session_id == prior.id,
                        surface_grants.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now)
            )
            connection.execute(
                insert(surface_sessions).values(
                    id=rotated.id,
                    user_id=rotated.user_id,
                    token_digest=token_digest,
                    csrf_digest=rotated.csrf_digest,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=rotated.expires_at,
                    revoked_at=None,
                )
            )
            self._audit(connection, rotated.user_id, "SESSION_ROTATED", "ACCEPTED")
        return rotated

    def session_for_token(self, token_digest: str) -> SurfaceSession | None:
        now = _now()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(surface_sessions).where(
                        and_(
                            surface_sessions.c.token_digest == token_digest,
                            surface_sessions.c.revoked_at.is_(None),
                            surface_sessions.c.last_seen_at > now - timedelta(minutes=30),
                            surface_sessions.c.expires_at > now,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            connection.execute(
                update(surface_sessions)
                .where(surface_sessions.c.id == row["id"])
                .values(last_seen_at=now)
            )
        return SurfaceSession(
            str(row["id"]),
            str(row["user_id"]),
            str(row["csrf_digest"]),
            row["last_seen_at"],
            row["expires_at"],
        )

    def revoke_session(self, session_id: str, *, actor_id: str | None = None) -> None:
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_sessions)
                .where(surface_sessions.c.id == session_id)
                .values(revoked_at=now)
            )
            connection.execute(
                update(surface_grants)
                .where(
                    and_(
                        surface_grants.c.session_id == session_id,
                        surface_grants.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now)
            )
            self._audit(connection, actor_id, "SESSION_REVOKED", "ACCEPTED")

    def revoke_all_for_user(self, user_id: str) -> None:
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_sessions)
                .where(surface_sessions.c.user_id == user_id)
                .values(revoked_at=now)
            )
            connection.execute(
                update(surface_grants)
                .where(
                    and_(
                        surface_grants.c.revoked_at.is_(None),
                        surface_grants.c.session_id.in_(
                            select(surface_sessions.c.id).where(
                                surface_sessions.c.user_id == user_id
                            )
                        ),
                    )
                )
                .values(revoked_at=now)
            )
            self._audit(connection, user_id, "AUTH_RESET", "ACCEPTED")

    def reset_password(self, user_id: str, password_hash: str, password_profile: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_users)
                .where(surface_users.c.id == user_id)
                .values(password_hash=password_hash, password_profile=password_profile)
            )
        self.revoke_all_for_user(user_id)

    def create_grant(self, session: SurfaceSession, scope: Scope) -> str:
        now = _now()
        with self._engine.begin() as connection:
            grant_id = str(uuid4())
            connection.execute(
                insert(surface_grants).values(
                    id=grant_id,
                    session_id=session.id,
                    scope=scope.value,
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                    revoked_at=None,
                )
            )
            self._audit(connection, session.user_id, "SESSION_GRANT_CREATED", "ACCEPTED")
        return grant_id

    def active_operate_grant_id(self, session: SurfaceSession) -> str | None:
        """Return one current exact OPERATE grant for a job binder, never a capability."""
        now = _now()
        with self._engine.connect() as connection:
            value = connection.execute(
                select(surface_grants.c.id)
                .where(
                    and_(
                        surface_grants.c.session_id == session.id,
                        surface_grants.c.scope == Scope.OPERATE.value,
                        surface_grants.c.revoked_at.is_(None),
                        surface_grants.c.expires_at > now,
                    )
                )
                .order_by(surface_grants.c.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def has_active_operate_grant(self, *, grant_id: str, actor_id: str) -> bool:
        """Recheck the exact grant bound to a claimed W10 job."""
        now = _now()
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    select(surface_grants.c.id)
                    .select_from(surface_grants.join(surface_sessions))
                    .where(
                        and_(
                            surface_grants.c.id == grant_id,
                            surface_grants.c.scope == Scope.OPERATE.value,
                            surface_grants.c.revoked_at.is_(None),
                            surface_grants.c.expires_at > now,
                            surface_sessions.c.user_id == actor_id,
                            surface_sessions.c.revoked_at.is_(None),
                            surface_sessions.c.expires_at > now,
                        )
                    )
                    .limit(1)
                ).first()
                is not None
            )

    def has_active_grant(self, session_id: str, scope: Scope) -> bool:
        """Return whether exactly this still-active session has an unexpired scope grant."""
        now = _now()
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    select(surface_grants.c.id)
                    .select_from(
                        surface_grants.join(
                            surface_sessions,
                            surface_grants.c.session_id == surface_sessions.c.id,
                        )
                    )
                    .where(
                        and_(
                            surface_grants.c.session_id == session_id,
                            surface_grants.c.scope == scope.value,
                            surface_grants.c.revoked_at.is_(None),
                            surface_grants.c.expires_at > now,
                            surface_sessions.c.revoked_at.is_(None),
                            surface_sessions.c.expires_at > now,
                        )
                    )
                    .limit(1)
                ).first()
                is not None
            )

    def list_jobs(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Return a bounded public projection without job inputs, digests, or leases."""
        statement = (
            select(
                application_jobs.c.id,
                application_jobs.c.command_profile,
                application_jobs.c.created_at,
                application_jobs.c.status,
                application_jobs.c.worker_role,
            )
            .order_by(application_jobs.c.id)
            .limit(limit + 1)
        )
        if after_id is not None:
            statement = statement.where(application_jobs.c.id > after_id)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        visible = rows[:limit]
        return (
            tuple(
                {
                    "job_id": str(row["id"]),
                    "command_profile": str(row["command_profile"]),
                    "created_at": _timestamp(row["created_at"]),
                    "status": str(row["status"]),
                    "worker_role": str(row["worker_role"]),
                }
                for row in visible
            ),
            None if len(rows) <= limit else str(visible[-1]["id"]),
        )

    def job_detail(self, job_id: str) -> dict[str, object] | None:
        """Return one public job plus bounded state events, never its input envelope."""
        with self._engine.connect() as connection:
            job = (
                connection.execute(
                    select(
                        application_jobs.c.id,
                        application_jobs.c.command_profile,
                        application_jobs.c.created_at,
                        application_jobs.c.status,
                        application_jobs.c.worker_role,
                    ).where(application_jobs.c.id == job_id)
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            events = (
                connection.execute(
                    select(
                        application_job_events.c.sequence_no,
                        application_job_events.c.status,
                        application_job_events.c.occurred_at,
                        application_job_events.c.finding_code,
                    )
                    .where(application_job_events.c.job_id == job_id)
                    .order_by(application_job_events.c.sequence_no)
                    .limit(100)
                )
                .mappings()
                .all()
            )
        return {
            "job_id": str(job["id"]),
            "command_profile": str(job["command_profile"]),
            "created_at": _timestamp(job["created_at"]),
            "status": str(job["status"]),
            "worker_role": str(job["worker_role"]),
            "events": [
                {
                    "sequence": int(event["sequence_no"]),
                    "status": str(event["status"]),
                    "occurred_at": _timestamp(event["occurred_at"]),
                    "finding_code": event["finding_code"],
                }
                for event in events
            ],
        }

    def list_audit_events(
        self, *, after_id: str | None, limit: int
    ) -> tuple[tuple[dict[str, object], ...], str | None]:
        """Return an opaque, bounded append-only audit projection."""
        statement = (
            select(
                surface_audit_events.c.id,
                surface_audit_events.c.event_type,
                surface_audit_events.c.decision,
                surface_audit_events.c.job_id,
                surface_audit_events.c.finding_code,
                surface_audit_events.c.occurred_at,
            )
            .order_by(surface_audit_events.c.id)
            .limit(limit + 1)
        )
        if after_id is not None:
            statement = statement.where(surface_audit_events.c.id > after_id)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        visible = rows[:limit]
        return (
            tuple(
                {
                    "audit_id": str(row["id"]),
                    "event_type": str(row["event_type"]),
                    "decision": str(row["decision"]),
                    "job_id": None if row["job_id"] is None else str(row["job_id"]),
                    "finding_code": row["finding_code"],
                    "occurred_at": _timestamp(row["occurred_at"]),
                }
                for row in visible
            ),
            None if len(rows) <= limit else str(visible[-1]["id"]),
        )

    def enqueue_job(
        self,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
        worker_role: ProcessRole,
    ) -> str:
        if worker_role is ProcessRole.OPERATOR_WORKER:
            raise ValueError("operator jobs require an e-book rename binder")
        if worker_role is ProcessRole.ANALYSIS_WORKER:
            raise ValueError("analysis jobs require a fixed fixity binder")
        now = _now()
        with self._engine.begin() as connection:
            existing = connection.execute(
                select(application_jobs.c.id, application_jobs.c.input_digest).where(
                    and_(
                        application_jobs.c.actor_id == actor_id,
                        application_jobs.c.command_profile == command_profile,
                        application_jobs.c.idempotency_digest == idempotency_digest,
                    )
                )
            ).one_or_none()
            if existing is not None:
                if str(existing.input_digest) != input_digest:
                    raise ValueError("idempotency key was reused with different input")
                return str(existing.id)
            job_id = str(uuid4())
            connection.execute(
                insert(application_jobs).values(
                    id=job_id,
                    actor_id=actor_id,
                    command_profile=command_profile,
                    input_digest=input_digest,
                    idempotency_digest=idempotency_digest,
                    created_at=now,
                    status=JobStatus.WAITING.value,
                    worker_role=worker_role.value,
                    lease_digest=None,
                    lease_expires_at=None,
                    fence_epoch=0,
                )
            )
            self._event(connection, job_id, 1, JobStatus.WAITING, now)
            self._audit(connection, actor_id, "JOB_ACCEPTED", "ACCEPTED", job_id=job_id)
            return job_id

    def enqueue_ebook_fixity_analysis_job(
        self,
        *,
        actor_id: str,
        input_digest: str,
        idempotency_digest: str,
        binder: EbookFixityAnalysisJobBinder,
    ) -> str:
        """Atomically insert a fixed read-only job and its minimal binder."""
        now = _now()
        replay = self._ebook_fixity_job_replay(
            actor_id=actor_id,
            profile=binder.profile,
            input_digest=input_digest,
            idempotency_digest=idempotency_digest,
        )
        if replay is not None:
            return replay
        try:
            with self._engine.begin() as connection:
                job_id = str(uuid4())
                connection.execute(
                    insert(application_jobs).values(
                        id=job_id,
                        actor_id=actor_id,
                        command_profile=binder.profile.value,
                        input_digest=input_digest,
                        idempotency_digest=idempotency_digest,
                        created_at=now,
                        status=JobStatus.WAITING.value,
                        worker_role=ProcessRole.ANALYSIS_WORKER.value,
                        lease_digest=None,
                        lease_expires_at=None,
                        fence_epoch=0,
                    )
                )
                connection.execute(
                    insert(ebook_fixity_analysis_job_binders).values(
                        job_id=job_id,
                        profile=binder.profile.value,
                        scan_root_id=binder.scan_root_id,
                        worker_count=binder.worker_count,
                    )
                )
                self._event(connection, job_id, 1, JobStatus.WAITING, now)
                self._audit(
                    connection,
                    actor_id,
                    "JOB_ACCEPTED",
                    "ACCEPTED",
                    job_id=job_id,
                )
                return job_id
        except IntegrityError:
            replay = self._ebook_fixity_job_replay(
                actor_id=actor_id,
                profile=binder.profile,
                input_digest=input_digest,
                idempotency_digest=idempotency_digest,
            )
            if replay is not None:
                return replay
            raise

    def _ebook_fixity_job_replay(
        self,
        *,
        actor_id: str,
        profile: EbookFixityAnalysisJobProfile,
        input_digest: str,
        idempotency_digest: str,
    ) -> str | None:
        with self._engine.connect() as connection:
            existing = connection.execute(
                select(application_jobs.c.id, application_jobs.c.input_digest).where(
                    and_(
                        application_jobs.c.actor_id == actor_id,
                        application_jobs.c.command_profile == profile.value,
                        application_jobs.c.idempotency_digest == idempotency_digest,
                    )
                )
            ).one_or_none()
        if existing is None:
            return None
        if str(existing.input_digest) != input_digest:
            raise ValueError("idempotency key was reused with different input")
        return str(existing.id)

    def ebook_fixity_analysis_job_binder(self, job_id: str) -> EbookFixityAnalysisJobBinder | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(ebook_fixity_analysis_job_binders).where(
                        ebook_fixity_analysis_job_binders.c.job_id == job_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        try:
            return EbookFixityAnalysisJobBinder(
                profile=EbookFixityAnalysisJobProfile(str(row["profile"])),
                scan_root_id=str(row["scan_root_id"]),
                worker_count=int(row["worker_count"]),
            )
        except (TypeError, ValueError) as error:
            raise RuntimeError("fixity analysis job binder is corrupt") from error

    def complete_ebook_fixity_analysis_job(
        self,
        claim: ClaimedJob,
        *,
        manifest_id: str | None = None,
        verification_run_id: str | None = None,
    ) -> bool:
        """Atomically bind one result and terminally succeed its exact current claim."""
        if (manifest_id is None) == (verification_run_id is None):
            raise ValueError("fixity analysis job result is invalid")
        now = _now()
        with self._engine.begin() as connection:
            binder = connection.execute(
                select(ebook_fixity_analysis_job_binders.c.profile).where(
                    ebook_fixity_analysis_job_binders.c.job_id == claim.id
                )
            ).one_or_none()
            if binder is None:
                raise ValueError("fixity analysis job binder is unavailable")
            profile = EbookFixityAnalysisJobProfile(str(binder.profile))
            if (profile is EbookFixityAnalysisJobProfile.BASELINE_BUILD) != (
                manifest_id is not None
            ):
                raise ValueError("fixity analysis job result shape is invalid")
            changed = connection.execute(
                update(application_jobs)
                .where(
                    and_(
                        application_jobs.c.id == claim.id,
                        application_jobs.c.status == JobStatus.ACTIVE.value,
                        application_jobs.c.fence_epoch == claim.fence_epoch,
                        application_jobs.c.lease_digest == claim.lease_token,
                        application_jobs.c.lease_expires_at > now,
                    )
                )
                .values(status=JobStatus.SUCCEEDED.value, lease_expires_at=now)
            ).rowcount
            if changed != 1:
                return False
            connection.execute(
                insert(ebook_fixity_analysis_job_results).values(
                    job_id=claim.id,
                    manifest_id=manifest_id,
                    verification_run_id=verification_run_id,
                )
            )
            self._event(
                connection,
                claim.id,
                self._next_sequence(connection, claim.id),
                JobStatus.SUCCEEDED,
                now,
            )
            self._audit(
                connection,
                None,
                "EBOOK_FIXITY_JOB_FINISHED",
                JobStatus.SUCCEEDED.value,
                job_id=claim.id,
            )
            return True

    def command_receipt(
        self,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
    ) -> dict[str, object] | None:
        """Return a prior safe response or reject one key with changed semantic input."""
        with self._engine.connect() as connection:
            existing = (
                connection.execute(
                    select(
                        surface_command_receipts.c.input_digest,
                        surface_command_receipts.c.response_json,
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
        if existing is None:
            return None
        if str(existing["input_digest"]) != input_digest:
            raise ValueError("idempotency key was reused with different input")
        if existing["response_json"] is None:
            raise RuntimeError("idempotency command is pending")
        response = json.loads(str(existing["response_json"]))
        if not isinstance(response, dict):
            raise RuntimeError("surface command receipt is corrupt")
        return response

    def claim_command_receipt(
        self,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
    ) -> dict[str, object] | None:
        """Atomically reserve one planning command before it can mutate review state."""
        now = _now()
        try:
            with self._engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(
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
                        raise ValueError("idempotency key was reused with different input")
                    if existing["response_json"] is None:
                        raise RuntimeError("idempotency command is pending")
                    response = json.loads(str(existing["response_json"]))
                    if not isinstance(response, dict):
                        raise RuntimeError("surface command receipt is corrupt")
                    return response
                connection.execute(
                    insert(surface_command_receipts).values(
                        id=str(uuid4()),
                        actor_id=actor_id,
                        command_profile=command_profile,
                        input_digest=input_digest,
                        idempotency_digest=idempotency_digest,
                        response_json=None,
                        status="PENDING",
                        created_at=now,
                    )
                )
                return None
        except IntegrityError:
            return self.claim_command_receipt(
                actor_id=actor_id,
                command_profile=command_profile,
                input_digest=input_digest,
                idempotency_digest=idempotency_digest,
            )

    def complete_command_receipt(
        self,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
        response: dict[str, object],
    ) -> dict[str, object]:
        """Persist a path-free response for one accepted planning command retry."""
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(surface_command_receipts)
                .where(
                    and_(
                        surface_command_receipts.c.actor_id == actor_id,
                        surface_command_receipts.c.command_profile == command_profile,
                        surface_command_receipts.c.input_digest == input_digest,
                        surface_command_receipts.c.idempotency_digest == idempotency_digest,
                        surface_command_receipts.c.status == "PENDING",
                        surface_command_receipts.c.response_json.is_(None),
                    )
                )
                .values(response_json=encoded, status="COMPLETED")
            ).rowcount
            if changed != 1:
                raise RuntimeError("surface command receipt completion differs")
        return response

    # Compatibility names preserve the shipped rename adapter while new
    # features use the media-neutral receipt contract.
    def ebook_rename_command_receipt(self, **arguments: str) -> dict[str, object] | None:
        return self.command_receipt(**arguments)

    def claim_ebook_rename_command_receipt(
        self, **arguments: str
    ) -> dict[str, object] | None:
        return self.claim_command_receipt(**arguments)

    def record_ebook_rename_command_receipt(
        self, *, response: dict[str, object], **arguments: str
    ) -> dict[str, object]:
        return self.complete_command_receipt(**arguments, response=response)

    def enqueue_ebook_rename_operator_job(
        self,
        *,
        actor_id: str,
        input_digest: str,
        idempotency_digest: str,
        binder: EbookRenameOperatorJobBinder,
    ) -> str:
        """Atomically persist exactly one fixed ADR-0069 job envelope."""
        now = _now()
        profile = binder.profile.value
        with self._engine.begin() as connection:
            existing = connection.execute(
                select(application_jobs.c.id, application_jobs.c.input_digest).where(
                    and_(
                        application_jobs.c.actor_id == actor_id,
                        application_jobs.c.command_profile == profile,
                        application_jobs.c.idempotency_digest == idempotency_digest,
                    )
                )
            ).one_or_none()
            if existing is not None:
                if str(existing.input_digest) != input_digest:
                    raise ValueError("idempotency key was reused with different input")
                return str(existing.id)
            job_id = str(uuid4())
            connection.execute(
                insert(application_jobs).values(
                    id=job_id,
                    actor_id=actor_id,
                    command_profile=profile,
                    input_digest=input_digest,
                    idempotency_digest=idempotency_digest,
                    created_at=now,
                    status=JobStatus.WAITING.value,
                    worker_role=ProcessRole.OPERATOR_WORKER.value,
                    lease_digest=None,
                    lease_expires_at=None,
                    fence_epoch=0,
                )
            )
            connection.execute(
                insert(ebook_rename_operator_job_binders).values(
                    job_id=job_id,
                    profile=profile,
                    plan_id=binder.plan_id,
                    plan_content_hash=binder.plan_content_hash,
                    capability_id=binder.capability_id,
                    operate_grant_id=binder.operate_grant_id,
                    authorization_id=binder.authorization_id,
                    run_id=binder.run_id,
                    confirmation_digest=binder.confirmation_digest,
                )
            )
            self._event(connection, job_id, 1, JobStatus.WAITING, now)
            self._audit(
                connection,
                actor_id,
                "EBOOK_RENAME_JOB_ACCEPTED",
                "ACCEPTED",
                job_id=job_id,
            )
            return job_id

    def ebook_rename_operator_job_binder(self, job_id: str) -> EbookRenameOperatorJobBinder | None:
        """Load one immutable ADR-0069 envelope without exposing it publicly."""
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(ebook_rename_operator_job_binders).where(
                        ebook_rename_operator_job_binders.c.job_id == job_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        try:
            return EbookRenameOperatorJobBinder(
                profile=EbookRenameOperatorJobProfile(str(row["profile"])),
                plan_id=None if row["plan_id"] is None else str(row["plan_id"]),
                plan_content_hash=(
                    None if row["plan_content_hash"] is None else str(row["plan_content_hash"])
                ),
                capability_id=(None if row["capability_id"] is None else str(row["capability_id"])),
                operate_grant_id=str(row["operate_grant_id"]),
                authorization_id=(
                    None if row["authorization_id"] is None else str(row["authorization_id"])
                ),
                run_id=None if row["run_id"] is None else str(row["run_id"]),
                confirmation_digest=(
                    None if row["confirmation_digest"] is None else str(row["confirmation_digest"])
                ),
            )
        except ValueError as error:
            raise RuntimeError("e-book rename operator job binder is corrupt") from error

    def record_ebook_rename_operator_job_result(
        self,
        *,
        job_id: str,
        outcome: str,
        authorization_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Insert the one opaque outcome reference for a completed rename job."""
        if not outcome or (authorization_id is not None and run_id is not None):
            raise ValueError("e-book rename operator job result is invalid")
        expected = {
            "job_id": job_id,
            "outcome": outcome,
            "authorization_id": authorization_id,
            "run_id": run_id,
        }
        with self._engine.begin() as connection:
            binder = connection.execute(
                select(ebook_rename_operator_job_binders.c.profile).where(
                    ebook_rename_operator_job_binders.c.job_id == job_id
                )
            ).one_or_none()
            if binder is None:
                raise ValueError("e-book rename operator job binder is unavailable")
            profile = EbookRenameOperatorJobProfile(str(binder.profile))
            if (
                (profile is EbookRenameOperatorJobProfile.AUTHORIZE)
                != (authorization_id is not None and run_id is None)
            ) or (
                profile
                in {EbookRenameOperatorJobProfile.EXECUTE, EbookRenameOperatorJobProfile.RECOVER}
                and not (authorization_id is None and run_id is not None)
            ):
                raise ValueError("e-book rename operator job result shape is invalid")
            existing = (
                connection.execute(
                    select(ebook_rename_operator_job_results).where(
                        ebook_rename_operator_job_results.c.job_id == job_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if any(existing[key] != value for key, value in expected.items()):
                    raise ValueError("e-book rename operator job result retry differs")
                return
            connection.execute(insert(ebook_rename_operator_job_results).values(**expected))

    def claim_next_job(self, role: ProcessRole, lease_digest: str) -> ClaimedJob | None:
        now = _now()
        until = now + timedelta(minutes=2)
        with self._engine.begin() as connection:
            clauses = [
                application_jobs.c.worker_role == role.value,
                application_jobs.c.status == JobStatus.WAITING.value,
            ]
            if role is ProcessRole.OPERATOR_WORKER:
                clauses.append(
                    application_jobs.c.command_profile.in_(
                        tuple(profile.value for profile in EbookRenameOperatorJobProfile)
                    )
                )
            elif role is ProcessRole.ANALYSIS_WORKER:
                clauses.append(
                    application_jobs.c.command_profile.in_(
                        tuple(profile.value for profile in EbookFixityAnalysisJobProfile)
                    )
                )
            row = (
                connection.execute(
                    select(application_jobs)
                    .where(and_(*clauses))
                    .order_by(application_jobs.c.created_at)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            epoch = int(row["fence_epoch"]) + 1
            changed = connection.execute(
                update(application_jobs)
                .where(
                    and_(
                        application_jobs.c.id == row["id"],
                        application_jobs.c.status == JobStatus.WAITING.value,
                        application_jobs.c.fence_epoch == row["fence_epoch"],
                    )
                )
                .values(
                    status=JobStatus.ACTIVE.value,
                    lease_digest=lease_digest,
                    lease_expires_at=until,
                    fence_epoch=epoch,
                )
            ).rowcount
            if changed != 1:
                return None
            self._event(
                connection,
                str(row["id"]),
                self._next_sequence(connection, str(row["id"])),
                JobStatus.ACTIVE,
                now,
            )
            return ClaimedJob(str(row["id"]), str(row["actor_id"]), epoch, lease_digest)

    def complete_claimed_job(
        self,
        claim: ClaimedJob,
        *,
        status: JobStatus,
        finding_code: str | None = None,
    ) -> bool:
        """Finish one leased worker job without reopening or changing its envelope."""
        if status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.RECOVERY_REQUIRED}:
            raise ValueError("worker job terminal status is invalid")
        now = _now()
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(application_jobs)
                .where(
                    and_(
                        application_jobs.c.id == claim.id,
                        application_jobs.c.status == JobStatus.ACTIVE.value,
                        application_jobs.c.fence_epoch == claim.fence_epoch,
                        application_jobs.c.lease_digest == claim.lease_token,
                        application_jobs.c.lease_expires_at > now,
                    )
                )
                .values(status=status.value, lease_expires_at=now)
            ).rowcount
            if changed != 1:
                return False
            self._event(
                connection,
                claim.id,
                self._next_sequence(connection, claim.id),
                status,
                now,
                finding_code=finding_code,
            )
            self._audit(
                connection,
                None,
                self._finished_job_audit_type(connection, claim.id),
                status.value,
                job_id=claim.id,
                finding_code=finding_code,
            )
            return True

    def heartbeat_claimed_job(self, claim: ClaimedJob) -> bool:
        """Extend one still-current worker lease without changing its immutable binder."""
        now = _now()
        with self._engine.begin() as connection:
            return (
                connection.execute(
                    update(application_jobs)
                    .where(
                        and_(
                            application_jobs.c.id == claim.id,
                            application_jobs.c.status == JobStatus.ACTIVE.value,
                            application_jobs.c.fence_epoch == claim.fence_epoch,
                            application_jobs.c.lease_digest == claim.lease_token,
                            application_jobs.c.lease_expires_at > now,
                        )
                    )
                    .values(lease_expires_at=now + timedelta(minutes=2))
                ).rowcount
                == 1
            )

    def abandon_claimed_job_for_recovery(self, claim: ClaimedJob, *, finding_code: str) -> bool:
        """Fence a lost lease into a queryable recovery state without reopening its binder."""
        now = _now()
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(application_jobs)
                .where(
                    and_(
                        application_jobs.c.id == claim.id,
                        application_jobs.c.status == JobStatus.ACTIVE.value,
                        application_jobs.c.fence_epoch == claim.fence_epoch,
                        application_jobs.c.lease_digest == claim.lease_token,
                    )
                )
                .values(status=JobStatus.RECOVERY_REQUIRED.value, lease_expires_at=now)
            ).rowcount
            if changed != 1:
                return False
            self._event(
                connection,
                claim.id,
                self._next_sequence(connection, claim.id),
                JobStatus.RECOVERY_REQUIRED,
                now,
                finding_code=finding_code,
            )
            self._audit(
                connection,
                None,
                self._finished_job_audit_type(connection, claim.id),
                JobStatus.RECOVERY_REQUIRED.value,
                job_id=claim.id,
                finding_code=finding_code,
            )
            return True

    def _next_sequence(self, connection: Connection, job_id: str) -> int:
        result = connection.execute(
            select(application_job_events.c.sequence_no)
            .where(application_job_events.c.job_id == job_id)
            .order_by(application_job_events.c.sequence_no.desc())
            .limit(1)
        )
        prior = result.scalar_one_or_none()
        return 1 if prior is None else int(prior) + 1

    @staticmethod
    def _finished_job_audit_type(connection: Connection, job_id: str) -> str:
        profile = connection.execute(
            select(application_jobs.c.command_profile).where(application_jobs.c.id == job_id)
        ).scalar_one_or_none()
        if profile in tuple(item.value for item in EbookFixityAnalysisJobProfile):
            return "EBOOK_FIXITY_JOB_FINISHED"
        if profile in tuple(item.value for item in EbookRenameOperatorJobProfile):
            return "EBOOK_RENAME_JOB_FINISHED"
        return "APPLICATION_JOB_FINISHED"

    @staticmethod
    def _event(
        connection: Connection,
        job_id: str,
        sequence_no: int,
        status: JobStatus,
        occurred_at: datetime,
        finding_code: str | None = None,
    ) -> None:
        connection.execute(
            insert(application_job_events).values(
                id=str(uuid4()),
                job_id=job_id,
                sequence_no=sequence_no,
                status=status.value,
                occurred_at=occurred_at,
                finding_code=finding_code,
            )
        )

    @staticmethod
    def _audit(
        connection: Connection,
        actor_id: str | None,
        event_type: str,
        decision: str,
        *,
        job_id: str | None = None,
        finding_code: str | None = None,
    ) -> None:
        connection.execute(
            insert(surface_audit_events).values(
                id=str(uuid4()),
                actor_id=actor_id,
                event_type=event_type,
                decision=decision,
                correlation_id=None,
                job_id=job_id,
                finding_code=finding_code,
                occurred_at=_now(),
            )
        )
