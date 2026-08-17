"""Add root-wide write leases with monotonic fencing.

Revision ID: 0012_scan_root_write_leases
Revises: 0011_candidate_hash_run_leases
Created: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.schema import DATETIME, ENUM, ID

revision: str = "0012_scan_root_write_leases"
down_revision: str | None = "0011_candidate_hash_run_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    active = connection.execute(
        sa.text(
            "SELECT 1 FROM scan_runs WHERE status = 'RUNNING' "
            "UNION ALL SELECT 1 FROM ebook_candidate_hash_runs "
            "WHERE status = 'RUNNING' "
            "UNION ALL SELECT 1 FROM ebook_collection_runs "
            "WHERE status = 'RUNNING' LIMIT 1"
        )
    ).first()
    if active is not None:
        raise RuntimeError("all root writers must be quiescent before migration")
    op.create_table(
        "scan_root_write_leases",
        sa.Column(
            "scan_root_id",
            ID,
            sa.ForeignKey("scan_roots.id"),
            primary_key=True,
        ),
        sa.Column("owner_kind", ENUM),
        sa.Column("owner_run_id", ID),
        sa.Column("lease_token", sa.Text()),
        sa.Column("fence_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", DATETIME),
        sa.Column("heartbeat_at", DATETIME),
        sa.Column("acquired_at", DATETIME),
        sa.UniqueConstraint(
            "owner_kind",
            "owner_run_id",
            name="uq_scan_root_write_leases_owner",
        ),
        sa.CheckConstraint(
            "fence_epoch >= 0",
            name="ck_scan_root_write_leases_epoch",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL "
            "AND lease_expires_at IS NULL AND heartbeat_at IS NULL "
            "AND acquired_at IS NULL) OR (lease_token IS NOT NULL "
            "AND lease_token <> '' AND owner_kind IN ('SCAN_RUN', "
            "'EBOOK_CANDIDATE_HASH_RUN', 'EBOOK_COLLECTION_RUN', "
            "'EBOOK_ANALYSIS') "
            "AND owner_run_id IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND acquired_at IS NOT NULL "
            "AND fence_epoch >= 1 AND acquired_at <= heartbeat_at "
            "AND heartbeat_at < lease_expires_at)",
            name="ck_scan_root_write_leases_state",
        ),
    )
    op.create_index(
        "uq_scan_runs_active_root",
        "scan_runs",
        ["scan_root_id"],
        unique=True,
        sqlite_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    active = connection.execute(
        sa.text(
            "SELECT 1 FROM scan_root_write_leases WHERE lease_token IS NOT NULL LIMIT 1"
        )
    ).first()
    if active is not None:
        raise RuntimeError("active root writers prevent migration downgrade")
    op.drop_index("uq_scan_runs_active_root", table_name="scan_runs")
    op.drop_table("scan_root_write_leases")
