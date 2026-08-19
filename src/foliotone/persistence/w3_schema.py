"""W3 schema extensions for resumable e-book collection analysis."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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

provider_cache_entries = Table(
    "provider_cache_entries",
    metadata,
    Column("source_cache_key", Text, primary_key=True),
    Column("provider_id", Text, nullable=False),
    Column("provider_adapter_version", Text, nullable=False),
    Column("query_fingerprint", Text, nullable=False),
    Column("provider_source_version", Text, nullable=False),
    Column("content_status", ENUM),
    Column("payload_kind", ENUM, nullable=False),
    Column("payload_codec", Text),
    Column("payload_bytes", LargeBinary),
    Column("payload_bytes_sha256", Text),
    Column("content_http_status", Integer),
    Column("content_fetched_at", DATETIME),
    Column("content_fresh_until_at", DATETIME),
    Column("content_expires_at", DATETIME),
    Column("failure_status", ENUM),
    Column("failure_http_status", Integer),
    Column("failure_at", DATETIME),
    Column("failure_retry_after_at", DATETIME),
    Column("failure_expires_at", DATETIME),
    Column("generation", Integer, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column(
        "retention_until_at",
        DATETIME,
        Computed(
            "CASE "
            "WHEN content_expires_at IS NULL THEN failure_expires_at "
            "WHEN failure_expires_at IS NULL THEN content_expires_at "
            "WHEN content_expires_at >= failure_expires_at THEN content_expires_at "
            "ELSE failure_expires_at "
            "END",
            persisted=True,
        ),
        nullable=False,
    ),
    CheckConstraint(
        "length(source_cache_key)=64 "
        "AND source_cache_key NOT GLOB '*[^0-9a-f]*'",
        name="ck_provider_cache_entries_source_cache_key",
    ),
    CheckConstraint(
        "length(provider_id) BETWEEN 1 AND 128 "
        "AND provider_id GLOB '[a-z0-9._-]*' "
        "AND provider_id NOT GLOB '*[^a-z0-9._-]*'",
        name="ck_provider_cache_entries_provider_id",
    ),
    CheckConstraint(
        "length(provider_adapter_version) BETWEEN 1 AND 128 "
        "AND provider_adapter_version NOT GLOB '*[^a-z0-9._/-]*' "
        "AND provider_adapter_version NOT LIKE '/%' "
        "AND provider_adapter_version NOT LIKE '%/' "
        "AND provider_adapter_version NOT LIKE '%//' "
        "AND instr(provider_adapter_version, '\\\\') = 0 "
        "AND instr(provider_adapter_version, ':') = 0",
        name="ck_provider_cache_entries_provider_adapter_version",
    ),
    CheckConstraint(
        "length(provider_source_version) BETWEEN 1 AND 128 "
        "AND provider_source_version NOT GLOB '*[^a-z0-9._/-]*' "
        "AND provider_source_version NOT LIKE '/%' "
        "AND provider_source_version NOT LIKE '%/' "
        "AND provider_source_version NOT LIKE '%//' "
        "AND instr(provider_source_version, '\\\\') = 0 "
        "AND instr(provider_source_version, ':') = 0",
        name="ck_provider_cache_entries_provider_source_version",
    ),
    CheckConstraint(
        "length(query_fingerprint)=64 "
        "AND query_fingerprint NOT GLOB '*[^0-9a-f]*'",
        name="ck_provider_cache_entries_query_fingerprint",
    ),
    CheckConstraint(
        "content_status IS NULL OR content_status IN ('success', 'not_found')",
        name="ck_provider_cache_entries_content_status",
    ),
    CheckConstraint(
        "payload_kind IN "
        "('none', 'raw_response', 'normalized_source_dto')",
        name="ck_provider_cache_entries_payload_kind",
    ),
    CheckConstraint(
        "failure_status IS NULL OR failure_status IN ("
        "'rate_limited', 'temporary_failure', 'permanent_failure', "
        "'invalid_response')",
        name="ck_provider_cache_entries_failure_status",
    ),
    CheckConstraint(
        "content_status IS NOT NULL OR failure_status IS NOT NULL",
        name="ck_provider_cache_entries_at_least_one_slot",
    ),
    CheckConstraint(
        "(content_status IS NULL AND content_http_status IS NULL "
        "AND content_fetched_at IS NULL AND content_fresh_until_at IS NULL "
        "AND content_expires_at IS NULL AND payload_kind = 'none' "
        "AND payload_codec IS NULL AND payload_bytes IS NULL "
        "AND payload_bytes_sha256 IS NULL) "
        "OR (content_status IN ('success', 'not_found') "
        "AND payload_kind IN ('raw_response', 'normalized_source_dto', 'none') "
        "AND content_fetched_at IS NOT NULL "
        "AND content_fresh_until_at IS NOT NULL AND content_expires_at IS NOT NULL)",
        name="ck_provider_cache_entries_content_slot_complete",
    ),
    CheckConstraint(
        "content_status IS NULL OR (content_fetched_at <= content_fresh_until_at "
        "AND content_fresh_until_at <= content_expires_at)",
        name="ck_provider_cache_entries_content_timeline_order",
    ),
    CheckConstraint(
        "content_status <> 'success' OR payload_kind <> 'none'",
        name="ck_provider_cache_entries_success_payload_kind",
    ),
    CheckConstraint(
        "(content_status IS NULL AND content_http_status IS NULL) "
        "OR (content_http_status BETWEEN 100 AND 599)",
        name="ck_provider_cache_entries_content_http_status",
    ),
    CheckConstraint(
        "(payload_kind = 'none' AND payload_codec IS NULL AND payload_bytes IS NULL "
        "AND payload_bytes_sha256 IS NULL) "
        "OR (payload_kind IN ('raw_response', 'normalized_source_dto') "
        "AND payload_codec IS NOT NULL AND payload_bytes IS NOT NULL "
        "AND payload_bytes_sha256 IS NOT NULL)",
        name="ck_provider_cache_entries_payload_kind_shape",
    ),
    CheckConstraint(
        "(payload_kind='none' AND payload_codec IS NULL "
        "AND payload_bytes IS NULL AND payload_bytes_sha256 IS NULL) "
        "OR (payload_kind IN ('raw_response', 'normalized_source_dto') "
        "AND length(payload_codec) BETWEEN 1 AND 48 "
        "AND payload_codec GLOB '[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*' "
        "AND payload_bytes IS NOT NULL AND length(payload_bytes) > 0 "
        "AND payload_bytes_sha256 IS NOT NULL)",
        name="ck_provider_cache_entries_payload_shape",
    ),
    CheckConstraint(
        "(payload_bytes IS NULL AND payload_bytes_sha256 IS NULL) "
        "OR (payload_bytes IS NOT NULL AND payload_bytes_sha256 IS NOT NULL "
        "AND length(payload_bytes_sha256)=64 "
        "AND payload_bytes_sha256 NOT GLOB '*[^0-9a-f]*')",
        name="ck_provider_cache_entries_payload_digest",
    ),
    CheckConstraint(
        "failure_status IS NULL OR failure_http_status IS NULL OR "
        "failure_http_status BETWEEN 100 AND 599",
        name="ck_provider_cache_entries_failure_http_status",
    ),
    CheckConstraint(
        "(failure_status IS NULL AND failure_http_status IS NULL "
        "AND failure_at IS NULL AND failure_retry_after_at IS NULL "
        "AND failure_expires_at IS NULL) "
        "OR (failure_status IS NOT NULL AND failure_at IS NOT NULL "
        "AND failure_expires_at IS NOT NULL AND failure_at <= failure_expires_at)",
        name="ck_provider_cache_entries_failure_slot_complete",
    ),
    CheckConstraint(
        "failure_retry_after_at IS NULL OR "
        "(failure_status = 'rate_limited' AND failure_at IS NOT NULL "
        "AND failure_expires_at IS NOT NULL "
        "AND failure_retry_after_at >= failure_at "
        "AND failure_retry_after_at <= failure_expires_at)",
        name="ck_provider_cache_entries_failure_retry",
    ),
    CheckConstraint("generation > 0", name="ck_provider_cache_entries_generation"),
    CheckConstraint(
        "length(content_hash)=64 AND content_hash NOT GLOB '*[^0-9a-f]*'",
        name="ck_provider_cache_entries_content_hash",
    ),
)

Index(
    "ix_provider_cache_entries_generation",
    provider_cache_entries.c.provider_id,
    provider_cache_entries.c.generation,
)
Index(
    "ix_provider_cache_entries_provider_query",
    provider_cache_entries.c.provider_id,
    provider_cache_entries.c.query_fingerprint,
)
Index(
    "ix_provider_cache_entries_status_expires",
    provider_cache_entries.c.content_status,
    provider_cache_entries.c.content_expires_at,
)
Index(
    "ix_provider_cache_entries_retention_until_source_cache_key",
    provider_cache_entries.c.retention_until_at,
    provider_cache_entries.c.source_cache_key,
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
