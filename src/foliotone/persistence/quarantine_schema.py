"""Immutable, path-free persistence tables for ADR-0056 quarantine runs."""
# ruff: noqa: E501

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ID, metadata


def _sha(name: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_quarantine_{name}_sha256",
    )


quarantine_authorizations = Table(
    "quarantine_authorizations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("plan_id", ID, ForeignKey("consolidation_plans.id"), nullable=False),
    Column("plan_content_hash", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("keeper_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("candidate_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("keeper_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("candidate_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("keeper_full_sha256", Text, nullable=False),
    Column("candidate_full_sha256", Text, nullable=False),
    Column("quarantine_capability_id", ID, nullable=False),
    Column("review_fingerprint", Text, nullable=False),
    Column("authorized_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    CheckConstraint(
        "profile='quarantine-authorization/v1' AND keeper_file_id<>candidate_file_id AND keeper_observation_id<>candidate_observation_id",
        name="ck_quarantine_authorizations_contract",
    ),
    CheckConstraint("authorized_at < expires_at", name="ck_quarantine_authorizations_window"),
    _sha("plan_content_hash"),
    _sha("keeper_full_sha256"),
    _sha("candidate_full_sha256"),
    _sha("review_fingerprint"),
    _sha("content_hash"),
    UniqueConstraint("profile", "content_hash", name="uq_quarantine_authorizations_content"),
)

quarantine_execution_runs = Table(
    "quarantine_execution_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column(
        "authorization_id",
        ID,
        ForeignKey("quarantine_authorizations.id"),
        nullable=False,
        unique=True,
    ),
    Column("plan_id", ID, ForeignKey("consolidation_plans.id"), nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("keeper_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("candidate_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("target_token", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile='quarantine-execution/v1' AND keeper_file_id<>candidate_file_id",
        name="ck_quarantine_execution_runs_contract",
    ),
    CheckConstraint(
        "length(target_token)=64 AND target_token NOT GLOB '*[^0-9a-f]*'",
        name="ck_quarantine_execution_runs_target",
    ),
)

quarantine_execution_events = Table(
    "quarantine_execution_events",
    metadata,
    Column("run_id", ID, ForeignKey("quarantine_execution_runs.id"), primary_key=True),
    Column("sequence_no", Integer, primary_key=True),
    Column("status", Text, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("fence_epoch", Integer),
    Column("finding_code", Text),
    Column("confirmation_digest", Text),
    CheckConstraint("sequence_no>=1", name="ck_quarantine_execution_events_sequence"),
    CheckConstraint(
        "status IN ('PREPARED','MOVED','VERIFIED','COMPLETED','STALE','TOOL_UNAVAILABLE','VALIDATION_FAILED','FENCED_OUT','MANUAL_REVIEW','CANCELLED')",
        name="ck_quarantine_execution_events_status",
    ),
    CheckConstraint(
        "fence_epoch IS NULL OR fence_epoch>0", name="ck_quarantine_execution_events_fence"
    ),
    CheckConstraint(
        "finding_code IS NULL OR (length(finding_code) BETWEEN 1 AND 64 AND finding_code NOT GLOB '*[^A-Z0-9_]*')",
        name="ck_quarantine_execution_events_finding",
    ),
    CheckConstraint(
        "confirmation_digest IS NULL OR (length(confirmation_digest)=64 AND confirmation_digest NOT GLOB '*[^0-9a-f]*')",
        name="ck_quarantine_execution_events_confirmation",
    ),
)

QUARANTINE_TABLES = (
    quarantine_authorizations,
    quarantine_execution_runs,
    quarantine_execution_events,
)
