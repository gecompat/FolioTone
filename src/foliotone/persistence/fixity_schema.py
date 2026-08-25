"""Insert-only SQLite schema for book-only fixity baseline v1."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

_SHA_CHECK = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"

ebook_fixity_baseline_builds = Table(
    "ebook_fixity_baseline_builds",
    metadata,
    Column("manifest_id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("started_at", DATETIME, nullable=False),
    UniqueConstraint(
        "manifest_id",
        "scan_root_id",
        name="uq_ebook_fixity_build_manifest_root",
    ),
    CheckConstraint(
        "profile='ebook-fixity-baseline/v1' AND serializer='canonical-json/v1'",
        name="ck_ebook_fixity_builds_contract",
    ),
)

ebook_fixity_baseline_build_events = Table(
    "ebook_fixity_baseline_build_events",
    metadata,
    Column(
        "manifest_id",
        ID,
        ForeignKey("ebook_fixity_baseline_builds.manifest_id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("event_kind", ENUM, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("failure_code", ENUM),
    CheckConstraint(
        "(ordinal=0 AND event_kind='STARTED' AND failure_code IS NULL) OR "
        "(ordinal=1 AND event_kind='FAILED' AND failure_code IS NOT NULL "
        "AND length(failure_code) BETWEEN 1 AND 64) OR "
        "(ordinal=1 AND event_kind='MANIFEST_READY' AND failure_code IS NULL)",
        name="ck_ebook_fixity_build_events_contract",
    ),
    UniqueConstraint(
        "manifest_id",
        "event_kind",
        name="uq_ebook_fixity_build_events_kind",
    ),
)

ebook_fixity_baseline_entries = Table(
    "ebook_fixity_baseline_entries",
    metadata,
    Column(
        "manifest_id",
        ID,
        ForeignKey("ebook_fixity_baseline_builds.manifest_id"),
        primary_key=True,
    ),
    Column("ordinal", Integer, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("observation_id", ID, ForeignKey("file_observations.id"), nullable=False),
    Column("expected_size_bytes", Integer, nullable=False),
    Column("relative_locator", Text, nullable=False),
    Column("hash_algorithm", Text, nullable=False),
    Column("hash_algorithm_version", Text, nullable=False),
    Column("expected_sha256", Text, nullable=False),
    Column("entry_digest", Text, nullable=False),
    CheckConstraint(
        "ordinal>=0 AND expected_size_bytes>=0",
        name="ck_ebook_fixity_entries_counts",
    ),
    CheckConstraint(
        "length(relative_locator) BETWEEN 1 AND 4096 "
        "AND relative_locator NOT LIKE '/%' "
        "AND relative_locator NOT LIKE '%\\%' "
        "AND relative_locator NOT LIKE '../%' "
        "AND relative_locator NOT LIKE '%/../%' "
        "AND relative_locator NOT LIKE '%/..'",
        name="ck_ebook_fixity_entries_locator",
    ),
    CheckConstraint(
        "hash_algorithm='sha256' AND hash_algorithm_version='1'",
        name="ck_ebook_fixity_entries_hash_profile",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="expected_sha256"),
        name="ck_ebook_fixity_entries_sha256",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="entry_digest"),
        name="ck_ebook_fixity_entries_digest",
    ),
    UniqueConstraint(
        "manifest_id",
        "file_id",
        name="uq_ebook_fixity_entries_file",
    ),
    UniqueConstraint(
        "manifest_id",
        "observation_id",
        name="uq_ebook_fixity_entries_observation",
    ),
)

ebook_fixity_baseline_manifests = Table(
    "ebook_fixity_baseline_manifests",
    metadata,
    Column(
        "manifest_id",
        ID,
        ForeignKey("ebook_fixity_baseline_builds.manifest_id"),
        primary_key=True,
    ),
    Column("prepared_at", DATETIME, nullable=False),
    Column("expires_at", DATETIME, nullable=False),
    Column("item_count", Integer, nullable=False),
    Column("total_size_bytes", Integer, nullable=False),
    Column("entries_digest", Text, nullable=False),
    Column("content_digest", Text, nullable=False),
    CheckConstraint(
        "julianday(prepared_at) IS NOT NULL AND julianday(expires_at) IS NOT NULL "
        "AND julianday(expires_at)>julianday(prepared_at) "
        "AND item_count>=0 AND total_size_bytes>=0 "
        "AND (julianday(expires_at)-julianday(prepared_at))*86400.0<=900.001",
        name="ck_ebook_fixity_manifests_counts",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="entries_digest"),
        name="ck_ebook_fixity_manifests_entries_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="content_digest"),
        name="ck_ebook_fixity_manifests_content_digest",
    ),
)

ebook_fixity_baseline_activations = Table(
    "ebook_fixity_baseline_activations",
    metadata,
    Column("activation_id", ID, primary_key=True),
    Column("manifest_id", ID, nullable=False, unique=True),
    Column("scan_root_id", ID, nullable=False),
    Column("profile", Text, nullable=False),
    Column("activated_at", DATETIME, nullable=False),
    Column("manifest_content_digest", Text, nullable=False),
    Column("confirmation_digest", Text, nullable=False),
    Column("activation_digest", Text, nullable=False),
    ForeignKeyConstraint(
        ("manifest_id", "scan_root_id"),
        (
            "ebook_fixity_baseline_builds.manifest_id",
            "ebook_fixity_baseline_builds.scan_root_id",
        ),
        name="fk_ebook_fixity_activation_manifest_root",
    ),
    UniqueConstraint(
        "profile",
        "scan_root_id",
        name="uq_ebook_fixity_activation_profile_root",
    ),
    CheckConstraint(
        "profile='ebook-fixity-baseline/v1'",
        name="ck_ebook_fixity_activations_profile",
    ),
    CheckConstraint(
        "julianday(activated_at) IS NOT NULL",
        name="ck_ebook_fixity_activations_time",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="manifest_content_digest"),
        name="ck_ebook_fixity_activations_manifest_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="confirmation_digest"),
        name="ck_ebook_fixity_activations_confirmation_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="activation_digest"),
        name="ck_ebook_fixity_activations_digest",
    ),
)

Index(
    "ix_ebook_fixity_builds_root_started",
    ebook_fixity_baseline_builds.c.scan_root_id,
    ebook_fixity_baseline_builds.c.started_at,
    ebook_fixity_baseline_builds.c.manifest_id,
)
Index(
    "ix_ebook_fixity_entries_manifest_ordinal",
    ebook_fixity_baseline_entries.c.manifest_id,
    ebook_fixity_baseline_entries.c.ordinal,
)

EBOOK_FIXITY_BASELINE_TABLES = (
    ebook_fixity_baseline_builds,
    ebook_fixity_baseline_build_events,
    ebook_fixity_baseline_entries,
    ebook_fixity_baseline_manifests,
    ebook_fixity_baseline_activations,
)
