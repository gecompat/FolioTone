"""Insert-only SQLite tables for ADR-0066 e-book rename authority."""
# ruff: noqa: E501

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Text, UniqueConstraint

from foliotone.persistence.collection_state_schema import collection_state_snapshots
from foliotone.persistence.schema import DATETIME, ID, metadata


def _sha(table: str, column: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column})=64 AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=f"ck_{table}_{column}_sha256",
    )


ebook_rename_capability_probes = Table(
    "ebook_rename_capability_probes",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("ebook_rename_capability_id", ID, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("capability_configuration_fingerprint", Text, nullable=False),
    Column("filesystem_type", Text, nullable=False),
    Column("filesystem_identity_fingerprint", Text, nullable=False),
    Column("kernel_release", Text, nullable=False),
    Column("probed_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("openat2_supported", Integer, nullable=False),
    Column("renameat2_noreplace_supported", Integer, nullable=False),
    Column("directory_fsync_supported", Integer, nullable=False),
    Column("root_probe_same_filesystem", Integer, nullable=False),
    Column("platform_profile", Text, nullable=False),
    Column("backend_profile", Text, nullable=False),
    Column("capability_profile", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-file-rename-capability-probe/v1' AND platform_profile='linux-x86_64-glibc/v1' AND backend_profile='ebook-file-rename-linux-renameat2-noreplace/v1' AND capability_profile='ebook-file-rename-capability/v1'",
        name="ck_ebook_rename_capability_probes_profiles",
    ),
    CheckConstraint(
        "filesystem_type IN ('ext4','btrfs','xfs','tmpfs') AND openat2_supported=1 AND renameat2_noreplace_supported=1 AND directory_fsync_supported=1 AND root_probe_same_filesystem=1",
        name="ck_ebook_rename_capability_probes_success",
    ),
    CheckConstraint(
        "length(kernel_release) BETWEEN 1 AND 256",
        name="ck_ebook_rename_capability_probes_kernel",
    ),
    _sha("ebook_rename_capability_probes", "capability_configuration_fingerprint"),
    _sha("ebook_rename_capability_probes", "filesystem_identity_fingerprint"),
    _sha("ebook_rename_capability_probes", "content_hash"),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_ebook_rename_capability_probes_content",
    ),
)


ebook_rename_preparations = Table(
    "ebook_rename_preparations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("preparation_owner_id", ID, nullable=False),
    Column("preparation_fence_epoch", Integer, nullable=False),
    Column("plan_id", ID, ForeignKey("ebook_operation_recipe_plans.id"), nullable=False),
    Column("plan_content_hash", Text, nullable=False),
    Column("candidate_id", ID, ForeignKey("ebook_operation_recipe_candidates.id"), nullable=False),
    Column("candidate_content_hash", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("source_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("source_observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("source_locator_digest", Text, nullable=False),
    Column("target_locator_digest", Text, nullable=False),
    Column("source_format_label", Text, nullable=False),
    Column("source_full_sha256", Text, nullable=False),
    Column("source_size_bytes", Integer, nullable=False),
    Column("source_modified_at", DATETIME, nullable=False),
    Column("source_device", Integer, nullable=False),
    Column("source_inode", Integer, nullable=False),
    Column("source_mode", Integer, nullable=False),
    Column("source_uid", Integer, nullable=False),
    Column("source_gid", Integer, nullable=False),
    Column("source_link_count", Integer, nullable=False),
    Column("source_mtime_ns", Integer, nullable=False),
    Column("source_xattr_fingerprint", Text, nullable=False),
    Column("target_state_fingerprint", Text, nullable=False),
    Column("target_absence_fingerprint", Text, nullable=False),
    Column("dependency_scope_id", ID, nullable=False),
    Column("dependency_scope_material_fingerprint", Text, nullable=False),
    Column("dependencies_fingerprint", Text, nullable=False),
    Column("review_item_id", ID, ForeignKey("review_items.id"), nullable=False),
    Column("review_decision_id", ID, ForeignKey("review_decisions.id"), nullable=False),
    Column("review_decision_sequence_no", Integer, nullable=False),
    Column("review_evidence_fingerprint", Text, nullable=False),
    Column("review_candidate_set_fingerprint", Text, nullable=False),
    Column("ebook_rename_capability_id", ID, nullable=False),
    Column("capability_configuration_fingerprint", Text, nullable=False),
    Column("probe_id", ID, ForeignKey("ebook_rename_capability_probes.id"), nullable=False),
    Column("probe_content_hash", Text, nullable=False),
    Column("authorized_at", DATETIME, nullable=False),
    Column("prepared_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("backend_profile", Text, nullable=False),
    Column("probe_profile", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-file-rename-preparation/v1' AND backend_profile='ebook-file-rename-linux-renameat2-noreplace/v1' AND probe_profile='ebook-file-rename-capability-probe/v1'",
        name="ck_ebook_rename_preparations_profiles",
    ),
    CheckConstraint(
        "preparation_fence_epoch>0 AND review_decision_sequence_no>0 AND source_device>0 AND source_inode>0 AND source_mode>0 AND source_uid>=0 AND source_gid>=0 AND source_link_count=1 AND source_size_bytes>=0",
        name="ck_ebook_rename_preparations_shape",
    ),
    CheckConstraint(
        "source_format_label IN ('EPUB','MOBI','AZW','AZW3','PDF') AND authorized_at<=prepared_at",
        name="ck_ebook_rename_preparations_format_time",
    ),
    *(
        _sha("ebook_rename_preparations", column)
        for column in (
            "plan_content_hash",
            "candidate_content_hash",
            "source_locator_digest",
            "target_locator_digest",
            "source_full_sha256",
            "source_xattr_fingerprint",
            "target_state_fingerprint",
            "target_absence_fingerprint",
            "dependency_scope_material_fingerprint",
            "dependencies_fingerprint",
            "review_evidence_fingerprint",
            "review_candidate_set_fingerprint",
            "capability_configuration_fingerprint",
            "probe_content_hash",
            "content_hash",
        )
    ),
    UniqueConstraint("profile", "content_hash", name="uq_ebook_rename_preparations_content"),
)


ebook_rename_authorizations = Table(
    "ebook_rename_authorizations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("preparation_id", ID, ForeignKey("ebook_rename_preparations.id"), nullable=False, unique=True),
    Column("preparation_content_hash", Text, nullable=False),
    Column("plan_id", ID, ForeignKey("ebook_operation_recipe_plans.id"), nullable=False),
    Column("plan_content_hash", Text, nullable=False),
    Column("candidate_id", ID, ForeignKey("ebook_operation_recipe_candidates.id"), nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("ebook_rename_capability_id", ID, nullable=False),
    Column("capability_configuration_fingerprint", Text, nullable=False),
    Column("probe_id", ID, ForeignKey("ebook_rename_capability_probes.id"), nullable=False),
    Column("probe_content_hash", Text, nullable=False),
    Column("authorized_at", DATETIME, nullable=False),
    Column("prepared_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("backend_profile", Text, nullable=False),
    Column("probe_profile", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-file-rename-authorization/v1' AND backend_profile='ebook-file-rename-linux-renameat2-noreplace/v1' AND probe_profile='ebook-file-rename-capability-probe/v1'",
        name="ck_ebook_rename_authorizations_profiles",
    ),
    CheckConstraint(
        "authorized_at<=prepared_at AND prepared_at<expires_at AND julianday(authorized_at) IS NOT NULL AND julianday(prepared_at) IS NOT NULL AND julianday(expires_at) IS NOT NULL AND (julianday(expires_at)-julianday(authorized_at))*86400.0<=900.001",
        name="ck_ebook_rename_authorizations_window",
    ),
    *(
        _sha("ebook_rename_authorizations", column)
        for column in (
            "preparation_content_hash",
            "plan_content_hash",
            "capability_configuration_fingerprint",
            "probe_content_hash",
            "content_hash",
        )
    ),
    UniqueConstraint("profile", "content_hash", name="uq_ebook_rename_authorizations_content"),
)


ebook_rename_runs = Table(
    "ebook_rename_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("authorization_id", ID, ForeignKey("ebook_rename_authorizations.id"), nullable=False, unique=True),
    Column("authorization_content_hash", Text, nullable=False),
    Column("plan_id", ID, ForeignKey("ebook_operation_recipe_plans.id"), nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("ebook_rename_capability_id", ID, nullable=False),
    Column("probe_id", ID, ForeignKey("ebook_rename_capability_probes.id"), nullable=False),
    Column("initial_fence_epoch", Integer, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("backend_profile", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-file-rename-run/v1' AND backend_profile='ebook-file-rename-linux-renameat2-noreplace/v1' AND initial_fence_epoch>0",
        name="ck_ebook_rename_runs_contract",
    ),
    _sha("ebook_rename_runs", "authorization_content_hash"),
)


ebook_rename_backend_bindings = Table(
    "ebook_rename_backend_bindings",
    metadata,
    Column("run_id", ID, ForeignKey("ebook_rename_runs.id"), primary_key=True),
    Column("ebook_rename_capability_id", ID, nullable=False),
    Column("capability_configuration_fingerprint", Text, nullable=False),
    Column("probe_id", ID, ForeignKey("ebook_rename_capability_probes.id"), nullable=False),
    Column("probe_content_hash", Text, nullable=False),
    Column("bound_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("backend_profile", Text, nullable=False),
    Column("probe_profile", Text, nullable=False),
    CheckConstraint(
        "backend_profile='ebook-file-rename-linux-renameat2-noreplace/v1' AND probe_profile='ebook-file-rename-capability-probe/v1'",
        name="ck_ebook_rename_backend_bindings_profiles",
    ),
    _sha("ebook_rename_backend_bindings", "capability_configuration_fingerprint"),
    _sha("ebook_rename_backend_bindings", "probe_content_hash"),
    _sha("ebook_rename_backend_bindings", "content_hash"),
)


ebook_rename_events = Table(
    "ebook_rename_events",
    metadata,
    Column("run_id", ID, ForeignKey("ebook_rename_runs.id"), primary_key=True),
    Column("sequence_no", Integer, primary_key=True),
    Column("status", Text, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("fence_epoch", Integer, nullable=False),
    Column("finding_code", Text),
    Column("confirmation_digest", Text),
    CheckConstraint(
        "sequence_no BETWEEN 1 AND 16 AND fence_epoch>0",
        name="ck_ebook_rename_events_sequence_fence",
    ),
    CheckConstraint(
        "status IN ('PREPARED','RELOCATED','IMMEDIATE_VERIFIED','RECOVERY_RELOCATED','RECOVERY_VERIFIED','SCAN_HANDOFF','VERIFIED','CANCELLED','RECOVERED','MANUAL_RECOVERY_REQUIRED')",
        name="ck_ebook_rename_events_status",
    ),
    CheckConstraint(
        "(sequence_no=1 AND status='PREPARED' AND confirmation_digest IS NOT NULL) OR (sequence_no>1 AND status<>'PREPARED' AND confirmation_digest IS NULL)",
        name="ck_ebook_rename_events_prepared_confirmation",
    ),
    CheckConstraint(
        "finding_code IS NULL OR (length(finding_code) BETWEEN 1 AND 64 AND substr(finding_code,1,1) GLOB '[A-Z]' AND finding_code NOT GLOB '*[^A-Z0-9_]*')",
        name="ck_ebook_rename_events_finding",
    ),
    CheckConstraint(
        "confirmation_digest IS NULL OR (length(confirmation_digest)=64 AND confirmation_digest NOT GLOB '*[^0-9a-f]*')",
        name="ck_ebook_rename_events_confirmation",
    ),
)


ebook_rename_reconciliations = Table(
    "ebook_rename_reconciliations",
    metadata,
    Column(
        "run_id",
        ID,
        ForeignKey("ebook_rename_runs.id"),
        primary_key=True,
    ),
    Column("profile", Text, nullable=False),
    Column(
        "authorization_id",
        ID,
        ForeignKey("ebook_rename_authorizations.id"),
        nullable=False,
    ),
    Column("authorization_content_hash", Text, nullable=False),
    Column(
        "preparation_id",
        ID,
        ForeignKey("ebook_rename_preparations.id"),
        nullable=False,
    ),
    Column("preparation_content_hash", Text, nullable=False),
    Column("outcome_status", Text, nullable=False),
    Column("scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("source_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column(
        "source_before_observation_id",
        ID,
        ForeignKey("file_observations.id"),
        nullable=False,
    ),
    Column(
        "source_scan_event_id",
        ID,
        ForeignKey("file_scan_events.id"),
        nullable=False,
    ),
    Column("source_observation_id", ID, ForeignKey("file_observations.id")),
    Column("target_file_id", ID, ForeignKey("file_records.id")),
    Column("target_observation_id", ID, ForeignKey("file_observations.id")),
    Column("target_scan_event_id", ID, ForeignKey("file_scan_events.id")),
    Column(
        "collection_state_snapshot_id",
        ID,
        ForeignKey(f"{collection_state_snapshots.name}.id"),
        nullable=False,
    ),
    Column("collection_state_content_digest", Text, nullable=False),
    Column("expected_full_sha256", Text, nullable=False),
    Column("expected_size_bytes", Integer, nullable=False),
    Column("target_absence_fingerprint", Text, nullable=False),
    Column("physical_confirmation_digest", Text, nullable=False),
    Column("reconciled_at", DATETIME, nullable=False),
    Column("content_hash", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-file-rename-reconciliation/v1' "
        "AND outcome_status IN ('VERIFIED','RECOVERED') "
        "AND expected_size_bytes>=0",
        name="ck_ebook_rename_reconciliations_contract",
    ),
    CheckConstraint(
        "(outcome_status='VERIFIED' AND source_observation_id IS NULL "
        "AND target_file_id IS NOT NULL AND target_observation_id IS NOT NULL "
        "AND target_scan_event_id IS NOT NULL) OR "
        "(outcome_status='RECOVERED' AND source_observation_id IS NOT NULL "
        "AND target_file_id IS NULL AND target_observation_id IS NULL "
        "AND target_scan_event_id IS NULL)",
        name="ck_ebook_rename_reconciliations_outcome_shape",
    ),
    CheckConstraint(
        "target_file_id IS NULL OR target_file_id<>source_file_id",
        name="ck_ebook_rename_reconciliations_distinct_files",
    ),
    *(
        _sha("ebook_rename_reconciliations", column)
        for column in (
            "authorization_content_hash",
            "preparation_content_hash",
            "collection_state_content_digest",
            "expected_full_sha256",
            "target_absence_fingerprint",
            "physical_confirmation_digest",
            "content_hash",
        )
    ),
    UniqueConstraint(
        "profile",
        "content_hash",
        name="uq_ebook_rename_reconciliations_content",
    ),
    UniqueConstraint(
        "scan_run_id",
        name="uq_ebook_rename_reconciliations_scan_run",
    ),
    UniqueConstraint(
        "collection_state_snapshot_id",
        name="uq_ebook_rename_reconciliations_collection_state",
    ),
)


EBOOK_RENAME_TABLES = (
    ebook_rename_capability_probes,
    ebook_rename_preparations,
    ebook_rename_authorizations,
    ebook_rename_runs,
    ebook_rename_backend_bindings,
    ebook_rename_events,
)

EBOOK_RENAME_RECONCILIATION_TABLES = (ebook_rename_reconciliations,)


__all__ = [
    "EBOOK_RENAME_TABLES",
    "EBOOK_RENAME_RECONCILIATION_TABLES",
    "ebook_rename_authorizations",
    "ebook_rename_backend_bindings",
    "ebook_rename_capability_probes",
    "ebook_rename_events",
    "ebook_rename_preparations",
    "ebook_rename_reconciliations",
    "ebook_rename_runs",
]
