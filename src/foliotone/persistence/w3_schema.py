"""W3 schema extensions for resumable e-book collection analysis."""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

ebook_collection_runs = Table(
    "ebook_collection_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("profile", Text, nullable=False),
    Column("analysis_profile", Text, nullable=False),
    Column("fresh", Boolean, nullable=False),
    Column("worker_count", Integer, nullable=False),
    Column("started_at", DATETIME, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("completed_at", DATETIME),
    Column("lease_token", Text),
    Column("lease_expires_at", DATETIME),
)

ebook_collection_items = Table(
    "ebook_collection_items",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "run_id",
        ID,
        ForeignKey("ebook_collection_runs.id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        ID,
        ForeignKey("file_observations.id"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("format_name", Text, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("started_at", DATETIME),
    Column("completed_at", DATETIME),
    Column("quality_status", Text),
    Column("reused_step_count", Integer, nullable=False),
    Column("executed_step_count", Integer, nullable=False),
    Column("finding_count", Integer, nullable=False),
    Column("error_code", Text),
    UniqueConstraint(
        "run_id",
        "observation_id",
        name="uq_ebook_collection_items_run_observation",
    ),
    UniqueConstraint(
        "run_id",
        "ordinal",
        name="uq_ebook_collection_items_run_ordinal",
    ),
)

ebook_collection_item_executions = Table(
    "ebook_collection_item_executions",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "item_id",
        ID,
        ForeignKey("ebook_collection_items.id"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("step_name", Text, nullable=False),
    Column("disposition", ENUM, nullable=False),
    Column(
        "execution_id",
        ID,
        ForeignKey("tool_executions.id"),
        nullable=False,
    ),
    UniqueConstraint(
        "item_id",
        "ordinal",
        name="uq_ebook_collection_item_executions_item_ordinal",
    ),
    UniqueConstraint(
        "item_id",
        "execution_id",
        name="uq_ebook_collection_item_executions_item_execution",
    ),
)

ebook_collection_findings = Table(
    "ebook_collection_findings",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "item_id",
        ID,
        ForeignKey("ebook_collection_items.id"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("code", Text, nullable=False),
    Column("dimension", ENUM, nullable=False),
    Column("severity", ENUM, nullable=False),
    UniqueConstraint(
        "item_id",
        "ordinal",
        name="uq_ebook_collection_findings_item_ordinal",
    ),
    UniqueConstraint(
        "item_id",
        "code",
        name="uq_ebook_collection_findings_item_code",
    ),
)

ebook_collection_finding_executions = Table(
    "ebook_collection_finding_executions",
    metadata,
    Column("id", ID, primary_key=True),
    Column(
        "finding_id",
        ID,
        ForeignKey("ebook_collection_findings.id"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column(
        "execution_id",
        ID,
        ForeignKey("tool_executions.id"),
        nullable=False,
    ),
    UniqueConstraint(
        "finding_id",
        "ordinal",
        name="uq_ebook_collection_finding_executions_finding_ordinal",
    ),
    UniqueConstraint(
        "finding_id",
        "execution_id",
        name="uq_ebook_collection_finding_executions_finding_execution",
    ),
)

ebook_candidate_hash_runs = Table(
    "ebook_candidate_hash_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column(
        "source_scan_run_id",
        ID,
        ForeignKey("scan_runs.id"),
        nullable=False,
    ),
    Column("profile", Text, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("phase", ENUM, nullable=False),
    Column("started_at", DATETIME, nullable=False),
    Column("heartbeat_at", DATETIME, nullable=False),
    Column("finished_at", DATETIME),
    Column("lease_token", Text),
    Column("lease_expires_at", DATETIME),
    Column("candidate_groups", Integer),
    Column("candidate_observations", Integer),
    Column("already_hashed", Integer),
    Column("processed_count", Integer, nullable=False),
    Column("hashed_count", Integer, nullable=False),
    Column("failure_count", Integer, nullable=False),
    Column("remaining_count", Integer),
)

Index(
    "ix_ebook_collection_runs_root_status",
    ebook_collection_runs.c.scan_root_id,
    ebook_collection_runs.c.status,
)
Index(
    "ix_ebook_collection_items_run_status_ordinal",
    ebook_collection_items.c.run_id,
    ebook_collection_items.c.status,
    ebook_collection_items.c.ordinal,
)
Index(
    "ix_ebook_collection_item_executions_execution_item",
    ebook_collection_item_executions.c.execution_id,
    ebook_collection_item_executions.c.item_id,
)
Index(
    "ix_ebook_collection_findings_code_item",
    ebook_collection_findings.c.code,
    ebook_collection_findings.c.item_id,
)
Index(
    "ix_ebook_collection_finding_executions_execution_finding",
    ebook_collection_finding_executions.c.execution_id,
    ebook_collection_finding_executions.c.finding_id,
)
Index(
    "uq_ebook_candidate_hash_runs_active_root",
    ebook_candidate_hash_runs.c.scan_root_id,
    unique=True,
    sqlite_where=ebook_candidate_hash_runs.c.status == "RUNNING",
)
Index(
    "ix_ebook_candidate_hash_runs_root_started",
    ebook_candidate_hash_runs.c.scan_root_id,
    ebook_candidate_hash_runs.c.started_at,
    ebook_candidate_hash_runs.c.id,
)
