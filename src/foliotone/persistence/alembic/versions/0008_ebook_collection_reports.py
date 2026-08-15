"""Add collection report projections and fingerprint grouping index.

Revision ID: 0008_ebook_collection_reports
Revises: 0007_ebook_collection_batches
Created: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_ebook_collection_reports"
down_revision: str | None = "0007_ebook_collection_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(36)
ENUM = sa.String(48)


def upgrade() -> None:
    op.create_table(
        "ebook_collection_item_executions",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "item_id",
            ID,
            sa.ForeignKey("ebook_collection_items.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("disposition", ENUM, nullable=False),
        sa.Column(
            "execution_id",
            ID,
            sa.ForeignKey("tool_executions.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "item_id",
            "ordinal",
            name="uq_ebook_collection_item_executions_item_ordinal",
        ),
        sa.UniqueConstraint(
            "item_id",
            "execution_id",
            name="uq_ebook_collection_item_executions_item_execution",
        ),
    )
    op.create_table(
        "ebook_collection_findings",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "item_id",
            ID,
            sa.ForeignKey("ebook_collection_items.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("dimension", ENUM, nullable=False),
        sa.Column("severity", ENUM, nullable=False),
        sa.UniqueConstraint(
            "item_id",
            "ordinal",
            name="uq_ebook_collection_findings_item_ordinal",
        ),
        sa.UniqueConstraint(
            "item_id",
            "code",
            name="uq_ebook_collection_findings_item_code",
        ),
    )
    op.create_table(
        "ebook_collection_finding_executions",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "finding_id",
            ID,
            sa.ForeignKey("ebook_collection_findings.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "execution_id",
            ID,
            sa.ForeignKey("tool_executions.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "finding_id",
            "ordinal",
            name="uq_ebook_collection_finding_executions_finding_ordinal",
        ),
        sa.UniqueConstraint(
            "finding_id",
            "execution_id",
            name="uq_ebook_collection_finding_executions_finding_execution",
        ),
    )
    op.create_index(
        "ix_ebook_collection_item_executions_execution_item",
        "ebook_collection_item_executions",
        ["execution_id", "item_id"],
    )
    op.create_index(
        "ix_ebook_collection_findings_code_item",
        "ebook_collection_findings",
        ["code", "item_id"],
    )
    op.create_index(
        "ix_ebook_collection_finding_executions_execution_finding",
        "ebook_collection_finding_executions",
        ["execution_id", "finding_id"],
    )
    op.create_index(
        "ix_fingerprints_kind_algorithm_version_value_target",
        "fingerprints",
        [
            "kind",
            "algorithm",
            "algorithm_version",
            "value",
            "target_kind",
            "target_id",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fingerprints_kind_algorithm_version_value_target",
        table_name="fingerprints",
    )
    op.drop_index(
        "ix_ebook_collection_findings_code_item",
        table_name="ebook_collection_findings",
    )
    op.drop_index(
        "ix_ebook_collection_finding_executions_execution_finding",
        table_name="ebook_collection_finding_executions",
    )
    op.drop_index(
        "ix_ebook_collection_item_executions_execution_item",
        table_name="ebook_collection_item_executions",
    )
    op.drop_table("ebook_collection_finding_executions")
    op.drop_table("ebook_collection_findings")
    op.drop_table("ebook_collection_item_executions")
