"""SQLite stores for authentication, audit records, and fenced application jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.engine import Connection

from foliotone.persistence.surface_schema import (
    application_job_events,
    application_jobs,
    surface_audit_events,
    surface_auth_attempts,
    surface_bootstrap_tokens,
    surface_grants,
    surface_sessions,
    surface_users,
)
from foliotone.surface.contracts import JobStatus, ProcessRole, Scope


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


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
    fence_epoch: int
    lease_token: str


class SQLiteSurfaceStore:
    """Explicit SQLAlchemy Core persistence with append-only audit and job events."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        with self._engine.begin() as connection:
            connection.execute(
                update(surface_sessions)
                .where(surface_sessions.c.id == session_id)
                .values(revoked_at=_now())
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
                .where(surface_grants.c.revoked_at.is_(None))
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

    def create_grant(self, session_id: str, scope: Scope) -> None:
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(surface_grants).values(
                    id=str(uuid4()),
                    session_id=session_id,
                    scope=scope.value,
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                    revoked_at=None,
                )
            )
            self._audit(connection, None, "OPERATOR_GRANT", "ACCEPTED")

    def enqueue_job(
        self,
        *,
        actor_id: str,
        command_profile: str,
        input_digest: str,
        idempotency_digest: str,
        worker_role: ProcessRole,
    ) -> str:
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

    def claim_next_job(self, role: ProcessRole, lease_digest: str) -> ClaimedJob | None:
        if role is ProcessRole.OPERATOR_WORKER:
            return None
        now = _now()
        until = now + timedelta(minutes=2)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(application_jobs)
                    .where(
                        and_(
                            application_jobs.c.worker_role == role.value,
                            application_jobs.c.status == JobStatus.WAITING.value,
                        )
                    )
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
            return ClaimedJob(str(row["id"]), epoch, lease_digest)

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
    def _event(
        connection: Connection,
        job_id: str,
        sequence_no: int,
        status: JobStatus,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            insert(application_job_events).values(
                id=str(uuid4()),
                job_id=job_id,
                sequence_no=sequence_no,
                status=status.value,
                occurred_at=occurred_at,
                finding_code=None,
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
    ) -> None:
        connection.execute(
            insert(surface_audit_events).values(
                id=str(uuid4()),
                actor_id=actor_id,
                event_type=event_type,
                decision=decision,
                correlation_id=None,
                job_id=job_id,
                finding_code=None,
                occurred_at=_now(),
            )
        )
