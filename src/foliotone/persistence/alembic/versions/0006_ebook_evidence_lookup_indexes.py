"""Add measured e-book Evidence lookup indexes.

Revision ID: 0006_ebook_evidence_lookup_indexes
Revises: 0005_scan_resume_lineage
Created: 2026-08-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_ebook_evidence_lookup_indexes"
down_revision: str | None = "0005_scan_resume_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_tool_executions_input_capability_provider_started",
        "tool_executions",
        ["input_identity", "capability", "provider_id", "started_at"],
    )
    op.create_index(
        "ix_tool_results_target_execution",
        "tool_results",
        ["target_kind", "target_id", "execution_id"],
    )
    op.create_index(
        "ix_fingerprints_target_kind_execution",
        "fingerprints",
        ["target_kind", "target_id", "kind", "tool_execution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fingerprints_target_kind_execution",
        table_name="fingerprints",
    )
    op.drop_index(
        "ix_tool_results_target_execution",
        table_name="tool_results",
    )
    op.drop_index(
        "ix_tool_executions_input_capability_provider_started",
        table_name="tool_executions",
    )
