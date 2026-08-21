"""Add restartable archive collection runs.

Revision ID: 0020_archive_collection_runs
Revises: 0019_archive_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.archive_collection_schema import ARCHIVE_COLLECTION_TABLES

revision: str = "0020_archive_collection_runs"
down_revision: str | None = "0019_archive_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OWNER_CHECK = (
    "(lease_token IS NULL AND owner_kind IS NULL AND owner_run_id IS NULL "
    "AND lease_expires_at IS NULL AND heartbeat_at IS NULL AND acquired_at IS NULL) "
    "OR (lease_token IS NOT NULL AND lease_token <> '' "
    "AND owner_kind IN ('SCAN_RUN', 'EBOOK_CANDIDATE_HASH_RUN', "
    "'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS') AND owner_run_id IS NOT NULL "
    "AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL "
    "AND acquired_at IS NOT NULL AND fence_epoch >= 1 "
    "AND acquired_at <= heartbeat_at AND heartbeat_at < lease_expires_at)"
)
_NEW_OWNER_CHECK = _OLD_OWNER_CHECK.replace(
    "'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS'",
    "'EBOOK_COLLECTION_RUN', 'EBOOK_ANALYSIS', 'ARCHIVE_COLLECTION_RUN'",
)
_OLD_ARCHIVE_WRITER_CHECK = (
    "writer_owner_kind IN ('EBOOK_ANALYSIS','EBOOK_COLLECTION_RUN') "
    "AND writer_fence_epoch > 0"
)
_NEW_ARCHIVE_WRITER_CHECK = (
    "writer_owner_kind IN "
    "('EBOOK_ANALYSIS','EBOOK_COLLECTION_RUN','ARCHIVE_COLLECTION_RUN') "
    "AND writer_fence_epoch > 0"
)


def upgrade() -> None:
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _NEW_OWNER_CHECK)
    with op.batch_alter_table("archive_observations") as batch:
        batch.drop_constraint("ck_archive_observations_writer", type_="check")
        batch.create_check_constraint(
            "ck_archive_observations_writer", _NEW_ARCHIVE_WRITER_CHECK
        )
    bind = op.get_bind()
    for table in ARCHIVE_COLLECTION_TABLES:
        table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    union = " UNION ALL ".join(f"SELECT 1 FROM {table.name}" for table in ARCHIVE_COLLECTION_TABLES)
    occupied = bind.execute(sa.text(f"{union} LIMIT 1")).first()
    archive_owner = bind.execute(
        sa.text(
            "SELECT 1 FROM scan_root_write_leases "
            "WHERE owner_kind = 'ARCHIVE_COLLECTION_RUN' "
            "UNION ALL SELECT 1 FROM archive_observations "
            "WHERE writer_owner_kind = 'ARCHIVE_COLLECTION_RUN' LIMIT 1"
        )
    ).first()
    if occupied is not None or archive_owner is not None:
        raise RuntimeError("archive collection state prevents migration downgrade")
    for table in reversed(ARCHIVE_COLLECTION_TABLES):
        table.drop(bind)
    with op.batch_alter_table("archive_observations") as batch:
        batch.drop_constraint("ck_archive_observations_writer", type_="check")
        batch.create_check_constraint(
            "ck_archive_observations_writer", _OLD_ARCHIVE_WRITER_CHECK
        )
    with op.batch_alter_table("scan_root_write_leases") as batch:
        batch.drop_constraint("ck_scan_root_write_leases_state", type_="check")
        batch.create_check_constraint("ck_scan_root_write_leases_state", _OLD_OWNER_CHECK)
