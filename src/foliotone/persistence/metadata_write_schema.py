"""Insert-only SQLite tables for ADR-0063 metadata-write operations."""
# ruff: noqa: E501

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from foliotone.persistence.schema import DATETIME, ID, metadata


def _sha(table: str, column: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{table}_{column}_sha256",
    )


metadata_write_authorizations = Table(
    "metadata_write_authorizations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("preparation_id", ID, nullable=False),
    Column("preparation_content_hash", Text, nullable=False),
    Column("preparation_owner_id", ID, nullable=False),
    Column("preparation_fence_epoch", Integer, nullable=False),
    Column("plan_id", ID, ForeignKey("metadata_correction_plans.id"), nullable=False),
    Column("plan_content_hash", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("source_sha256", Text, nullable=False),
    Column("source_size_bytes", Integer, nullable=False),
    Column("expected_output_sha256", Text, nullable=False),
    Column("expected_output_size_bytes", Integer, nullable=False),
    Column("metadata_write_capability_id", ID, nullable=False),
    Column("dcterms_modified", Text, nullable=False),
    Column("authorized_at", DATETIME, nullable=False),
    Column("prepared_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("metadata_tool_version", Text, nullable=False),
    Column("epubcheck_tool_version", Text, nullable=False),
    Column("text_tool_version", Text, nullable=False),
    Column("cover_tool_version", Text, nullable=False),
    Column("validator_set_fingerprint", Text, nullable=False),
    Column("writer_profile", Text, nullable=False),
    Column("patcher_version", Text, nullable=False),
    Column("staging_profile", Text, nullable=False),
    Column("validation_profile", Text, nullable=False),
    Column("validator_set", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    CheckConstraint(
        "profile='metadata-write-authorization/v1' AND writer_profile='ebook-source-metadata-write/epub3-title-replace/v1' AND patcher_version='epub3-title-lexical-patch/1' AND staging_profile='epub3-title-private-staging/v1' AND validation_profile='epub3-title-staged-validation/v1' AND validator_set='ebook-meta-opf/2+epubcheck-json/1+ebook-convert-text/2+calibre-debug-cover/1'",
        name="ck_metadata_write_authorizations_profiles",
    ),
    CheckConstraint(
        "preparation_fence_epoch>0 AND source_size_bytes BETWEEN 1 AND 268435456 AND expected_output_size_bytes BETWEEN 1 AND 268435456 AND source_sha256<>expected_output_sha256",
        name="ck_metadata_write_authorizations_shape",
    ),
    CheckConstraint(
        "authorized_at<=prepared_at AND prepared_at<expires_at",
        name="ck_metadata_write_authorizations_window",
    ),
    CheckConstraint(
        "julianday(authorized_at) IS NOT NULL AND julianday(prepared_at) IS NOT NULL AND julianday(expires_at) IS NOT NULL AND (julianday(expires_at)-julianday(authorized_at))*86400.0<=900.001",
        name="ck_metadata_write_authorizations_max_window",
    ),
    CheckConstraint(
        "length(dcterms_modified)=20 AND substr(dcterms_modified,11,1)='T' AND substr(dcterms_modified,20,1)='Z'",
        name="ck_metadata_write_authorizations_modified",
    ),
    CheckConstraint(
        "length(metadata_tool_version) BETWEEN 1 AND 256 AND length(epubcheck_tool_version) BETWEEN 1 AND 256 AND length(text_tool_version) BETWEEN 1 AND 256 AND length(cover_tool_version) BETWEEN 1 AND 256",
        name="ck_metadata_write_authorizations_versions",
    ),
    _sha("metadata_write_authorizations", "preparation_content_hash"),
    _sha("metadata_write_authorizations", "plan_content_hash"),
    _sha("metadata_write_authorizations", "source_sha256"),
    _sha("metadata_write_authorizations", "expected_output_sha256"),
    _sha("metadata_write_authorizations", "validator_set_fingerprint"),
    _sha("metadata_write_authorizations", "content_hash"),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_metadata_write_authorizations_content",
    ),
    UniqueConstraint(
        "preparation_id",
        name="uq_metadata_write_authorizations_preparation",
    ),
)


metadata_write_runs = Table(
    "metadata_write_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column(
        "authorization_id",
        ID,
        ForeignKey("metadata_write_authorizations.id"),
        nullable=False,
        unique=True,
    ),
    Column("authorization_content_hash", Text, nullable=False),
    Column("plan_id", ID, ForeignKey("metadata_correction_plans.id"), nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("metadata_write_capability_id", ID, nullable=False),
    Column("initial_fence_epoch", Integer, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("writer_profile", Text, nullable=False),
    CheckConstraint(
        "profile='metadata-write-run/v1' AND writer_profile='ebook-source-metadata-write/epub3-title-replace/v1' AND initial_fence_epoch>0",
        name="ck_metadata_write_runs_contract",
    ),
    _sha("metadata_write_runs", "authorization_content_hash"),
)


metadata_write_events = Table(
    "metadata_write_events",
    metadata,
    Column("run_id", ID, ForeignKey("metadata_write_runs.id"), primary_key=True),
    Column("sequence_no", Integer, primary_key=True),
    Column("status", Text, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("fence_epoch", Integer, nullable=False),
    Column("finding_code", Text),
    Column("confirmation_digest", Text),
    CheckConstraint(
        "sequence_no BETWEEN 1 AND 16 AND fence_epoch>0",
        name="ck_metadata_write_events_sequence_fence",
    ),
    CheckConstraint(
        "status IN ('CREATED','PREPARED','EXCHANGED','ORIGINAL_PRESERVED','VERIFIED','RECOVERED','MANUAL_RECOVERY_REQUIRED','STALE','TOOL_UNAVAILABLE','VALIDATION_FAILED','FENCED_OUT','CANCELLED')",
        name="ck_metadata_write_events_status",
    ),
    CheckConstraint(
        "finding_code IS NULL OR (length(finding_code) BETWEEN 1 AND 64 AND substr(finding_code,1,1) GLOB '[A-Z]' AND finding_code NOT GLOB '*[^A-Z0-9_]*')",
        name="ck_metadata_write_events_finding",
    ),
    CheckConstraint(
        "confirmation_digest IS NULL OR (length(confirmation_digest)=64 AND confirmation_digest NOT GLOB '*[^0-9a-f]*')",
        name="ck_metadata_write_events_confirmation",
    ),
)


metadata_write_backend_bindings = Table(
    "metadata_write_backend_bindings",
    metadata,
    Column(
        "run_id",
        ID,
        ForeignKey("metadata_write_runs.id"),
        primary_key=True,
    ),
    Column("backend_profile", Text, nullable=False),
    Column("conformance_profile", Text, nullable=False),
    Column("bound_at", DATETIME, nullable=False),
    CheckConstraint(
        "backend_profile='epub-source-replace-linux-renameat2/v1' "
        "AND conformance_profile='renameat2-capability-probe/v1'",
        name="ck_metadata_write_backend_bindings_profiles",
    ),
)


METADATA_WRITE_TABLES = (
    metadata_write_authorizations,
    metadata_write_runs,
    metadata_write_events,
)

METADATA_WRITE_BACKEND_TABLES = (metadata_write_backend_bindings,)


__all__ = [
    "METADATA_WRITE_TABLES",
    "METADATA_WRITE_BACKEND_TABLES",
    "metadata_write_authorizations",
    "metadata_write_backend_bindings",
    "metadata_write_events",
    "metadata_write_runs",
]
