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
