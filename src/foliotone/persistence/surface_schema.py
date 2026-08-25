"""Additive SQLAlchemy Core tables for the local product surface."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

surface_users = Table(
    "surface_users",
    metadata,
    Column("id", ID, primary_key=True),
    Column("username", Text, nullable=False),
    Column("username_key", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("password_profile", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("active", Boolean, nullable=False),
    UniqueConstraint("username_key", name="uq_surface_users_username_key"),
)
surface_bootstrap_tokens = Table(
    "surface_bootstrap_tokens",
    metadata,
    Column("id", ID, primary_key=True),
    Column("token_digest", Text, nullable=False, unique=True),
    Column("created_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("consumed_at", DATETIME),
    CheckConstraint("attempt_count >= 0", name="ck_surface_bootstrap_attempt_count"),
)
surface_auth_attempts = Table(
    "surface_auth_attempts",
    metadata,
    Column("principal_digest", Text, primary_key=True),
    Column("attempt_kind", ENUM, primary_key=True),
    Column("attempt_count", Integer, nullable=False),
    Column("next_allowed_at", DATETIME, nullable=False),
    CheckConstraint("attempt_count >= 0", name="ck_surface_auth_attempt_count"),
)
surface_sessions = Table(
    "surface_sessions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("user_id", ID, ForeignKey("surface_users.id"), nullable=False),
    Column("token_digest", Text, nullable=False, unique=True),
    Column("csrf_digest", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("last_seen_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("revoked_at", DATETIME),
)
surface_grants = Table(
    "surface_grants",
    metadata,
    Column("id", ID, primary_key=True),
    Column("session_id", ID, ForeignKey("surface_sessions.id"), nullable=False),
    Column("scope", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("revoked_at", DATETIME),
)
surface_audit_events = Table(
    "surface_audit_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("actor_id", ID, ForeignKey("surface_users.id")),
    Column("event_type", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("correlation_id", Text),
    Column("job_id", ID),
    Column("finding_code", Text),
    Column("occurred_at", DATETIME, nullable=False),
)
application_jobs = Table(
    "application_jobs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("actor_id", ID, ForeignKey("surface_users.id"), nullable=False),
    Column("command_profile", Text, nullable=False),
    Column("input_digest", Text, nullable=False),
    Column("idempotency_digest", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("worker_role", ENUM, nullable=False),
    Column("lease_digest", Text),
    Column("lease_expires_at", DATETIME),
    Column("fence_epoch", Integer, nullable=False, default=0),
    UniqueConstraint(
        "actor_id", "command_profile", "idempotency_digest", name="uq_application_jobs_idempotency"
    ),
)
application_job_events = Table(
    "application_job_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("job_id", ID, ForeignKey("application_jobs.id"), nullable=False),
    Column("sequence_no", Integer, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("finding_code", Text),
    UniqueConstraint("job_id", "sequence_no", name="uq_application_job_events_sequence"),
)
surface_command_receipts = Table(
    "surface_command_receipts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("actor_id", ID, ForeignKey("surface_users.id"), nullable=False),
    Column("command_profile", Text, nullable=False),
    Column("input_digest", Text, nullable=False),
    Column("idempotency_digest", Text, nullable=False),
    Column("response_json", Text),
    Column("status", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    UniqueConstraint(
        "actor_id",
        "command_profile",
        "idempotency_digest",
        name="uq_surface_command_receipts_idempotency",
    ),
)
ebook_rename_operator_job_binders = Table(
    "ebook_rename_operator_job_binders",
    metadata,
    Column("job_id", ID, ForeignKey("application_jobs.id"), primary_key=True),
    Column("profile", Text, nullable=False),
    Column("plan_id", ID),
    Column("plan_content_hash", Text),
    Column("capability_id", ID),
    Column("operate_grant_id", ID, ForeignKey("surface_grants.id"), nullable=False),
    Column("authorization_id", ID),
    Column("run_id", ID),
    Column("confirmation_digest", Text),
    CheckConstraint(
        "(profile = 'ebook-rename-operator-authorize/v1' "
        "AND plan_id IS NOT NULL AND plan_content_hash IS NOT NULL AND capability_id IS NOT NULL "
        "AND authorization_id IS NULL AND run_id IS NULL AND confirmation_digest IS NULL) "
        "OR (profile = 'ebook-rename-operator-execute/v1' "
        "AND plan_id IS NOT NULL AND plan_content_hash IS NOT NULL AND capability_id IS NOT NULL "
        "AND authorization_id IS NOT NULL AND run_id IS NULL AND confirmation_digest IS NOT NULL) "
        "OR (profile = 'ebook-rename-operator-recover/v1' "
        "AND plan_id IS NULL AND plan_content_hash IS NULL AND capability_id IS NULL "
        "AND authorization_id IS NULL AND run_id IS NOT NULL AND confirmation_digest IS NULL)",
        name="ck_ebook_rename_operator_job_binder_shape",
    ),
)
ebook_rename_operator_job_results = Table(
    "ebook_rename_operator_job_results",
    metadata,
    Column("job_id", ID, ForeignKey("application_jobs.id"), primary_key=True),
    Column("outcome", Text, nullable=False),
    Column("authorization_id", ID),
    Column("run_id", ID),
    CheckConstraint(
        "(authorization_id IS NULL) OR (run_id IS NULL)",
        name="ck_ebook_rename_operator_job_result_reference",
    ),
)
Index("ix_surface_sessions_active", surface_sessions.c.token_digest, surface_sessions.c.expires_at)
Index(
    "ix_application_jobs_claim",
    application_jobs.c.status,
    application_jobs.c.worker_role,
    application_jobs.c.lease_expires_at,
)
