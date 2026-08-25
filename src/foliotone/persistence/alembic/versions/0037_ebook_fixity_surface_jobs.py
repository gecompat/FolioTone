"""Add immutable path-free binders for manually queued e-book fixity jobs.

Revision ID: 0037_ebook_fixity_surface_jobs
Revises: 0036_ebook_fixity_verification
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foliotone.persistence.surface_schema import (
    ebook_fixity_analysis_job_binders,
    ebook_fixity_analysis_job_results,
)

revision: str = "0037_ebook_fixity_surface_jobs"
down_revision: str | None = "0036_ebook_fixity_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (ebook_fixity_analysis_job_binders, ebook_fixity_analysis_job_results):
        table.create(bind)
        for action in ("UPDATE", "DELETE"):
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {table.name}_no_{action.lower()} "
                    f"BEFORE {action} ON {table.name} "
                    "BEGIN SELECT RAISE(ABORT, 'immutable fixity surface job record'); END"
                )
            )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_analysis_job_binder_job BEFORE INSERT ON "
            "ebook_fixity_analysis_job_binders WHEN NOT EXISTS (SELECT 1 FROM "
            "application_jobs AS job WHERE job.id=NEW.job_id AND "
            "job.worker_role='analysis-worker' AND job.command_profile=NEW.profile) "
            "BEGIN SELECT RAISE(ABORT, 'fixity job binder does not match application job'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_analysis_job_result_profile BEFORE INSERT ON "
            "ebook_fixity_analysis_job_results WHEN NOT EXISTS (SELECT 1 FROM "
            "ebook_fixity_analysis_job_binders AS binder WHERE binder.job_id=NEW.job_id "
            "AND ((binder.profile='ebook-fixity-baseline-build/v1' AND NEW.manifest_id IS NOT NULL "
            "AND NEW.verification_run_id IS NULL) OR "
            "(binder.profile='ebook-fixity-verification/v1' "
            "AND NEW.manifest_id IS NULL AND NEW.verification_run_id IS NOT NULL))) "
            "BEGIN SELECT RAISE(ABORT, 'fixity job result does not match binder profile'); END"
        )
    )
    bind.execute(
        sa.text(
            "CREATE TRIGGER ebook_fixity_analysis_job_identity_no_update "
            "BEFORE UPDATE OF actor_id,command_profile,input_digest,idempotency_digest,"
            "created_at,worker_role ON application_jobs "
            "WHEN EXISTS (SELECT 1 FROM ebook_fixity_analysis_job_binders AS binder "
            "WHERE binder.job_id=OLD.id) AND (NEW.actor_id<>OLD.actor_id "
            "OR NEW.command_profile<>OLD.command_profile "
            "OR NEW.input_digest<>OLD.input_digest "
            "OR NEW.idempotency_digest<>OLD.idempotency_digest "
            "OR NEW.created_at<>OLD.created_at OR NEW.worker_role<>OLD.worker_role) "
            "BEGIN SELECT RAISE(ABORT, 'immutable fixity application job identity'); END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = (ebook_fixity_analysis_job_binders, ebook_fixity_analysis_job_results)
    union = " UNION ALL ".join(f"SELECT 1 FROM {table.name}" for table in tables)
    if bind.execute(sa.text(f"{union} LIMIT 1")).first() is not None:
        raise RuntimeError("fixity surface jobs prevent migration downgrade")
    for trigger in (
        "ebook_fixity_analysis_job_identity_no_update",
        "ebook_fixity_analysis_job_result_profile",
        "ebook_fixity_analysis_job_binder_job",
    ):
        bind.execute(sa.text(f"DROP TRIGGER {trigger}"))
    for table in reversed(tables):
        for action in ("UPDATE", "DELETE"):
            bind.execute(sa.text(f"DROP TRIGGER {table.name}_no_{action.lower()}"))
        table.drop(bind)
