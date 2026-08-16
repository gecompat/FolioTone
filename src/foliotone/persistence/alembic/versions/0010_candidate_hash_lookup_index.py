"""Add the measured duplicate-candidate hash lookup index.

Revision ID: 0010_candidate_hash_lookup_index
Revises: 0009_scan_run_leases
Created: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_candidate_hash_lookup_index"
down_revision: str | None = "0009_scan_run_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_fingerprints_target_profile_id_value",
        "fingerprints",
        [
            "target_kind",
            "kind",
            "algorithm",
            "algorithm_version",
            "target_id",
            "value",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fingerprints_target_profile_id_value",
        table_name="fingerprints",
    )
