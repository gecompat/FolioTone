"""Insert-only SQLite schema for book-only fixity verification v1."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

_SHA_CHECK = "length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*'"
_RELATIVE_LOCATOR_CHECK = (
    "length({name}) BETWEEN 1 AND 4096 "
    "AND {name} NOT LIKE '/%' "
    "AND {name} NOT LIKE '%\\%' "
    "AND {name} NOT LIKE '../%' "
    "AND {name} NOT LIKE '%/../%' "
    "AND {name} NOT LIKE '%/..'"
)


ebook_fixity_verification_runs = Table(
    "ebook_fixity_verification_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column(
        "baseline_activation_id",
        ID,
        ForeignKey("ebook_fixity_baseline_activations.activation_id"),
        nullable=False,
    ),
    Column("expectation_revision_no", Integer, nullable=False),
    Column("expectation_revision_digest", Text, nullable=False),
    Column("source_scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("started_at", DATETIME, nullable=False),
    Column("expected_result_count", Integer, nullable=False),
    Column("input_digest", Text, nullable=False),
    CheckConstraint(
        "profile='ebook-fixity-verification/v1' AND serializer='canonical-json/v1'",
        name="ck_ebook_fixity_verification_runs_contract",
    ),
    CheckConstraint(
        "expectation_revision_no>=0 AND expected_result_count>=0",
        name="ck_ebook_fixity_verification_runs_counts",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="expectation_revision_digest"),
        name="ck_ebook_fixity_verification_runs_revision_digest",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="input_digest"),
        name="ck_ebook_fixity_verification_runs_input_digest",
    ),
)


ebook_fixity_verification_events = Table(
    "ebook_fixity_verification_events",
    metadata,
    Column(
        "run_id",
        ID,
        ForeignKey("ebook_fixity_verification_runs.id"),
        primary_key=True,
    ),
    Column("sequence_no", Integer, primary_key=True),
    Column("status", ENUM, nullable=False),
    Column("occurred_at", DATETIME, nullable=False),
    Column("failure_code", ENUM),
    Column("content_digest", Text),
    CheckConstraint(
        "(sequence_no=0 AND status='RUNNING' AND failure_code IS NULL "
        "AND content_digest IS NULL) OR "
        "(sequence_no=1 AND status='COMPLETED' AND failure_code IS NULL "
        "AND content_digest IS NOT NULL) OR "
        "(sequence_no=1 AND status='FAILED' AND failure_code IS NOT NULL "
        "AND length(failure_code) BETWEEN 1 AND 64 "
        "AND failure_code NOT GLOB '*[^A-Z0-9_]*' AND content_digest IS NULL)",
        name="ck_ebook_fixity_verification_events_contract",
    ),
    CheckConstraint(
        "content_digest IS NULL OR (" + _SHA_CHECK.format(name="content_digest") + ")",
        name="ck_ebook_fixity_verification_events_content_digest",
    ),
)


ebook_fixity_verification_results = Table(
    "ebook_fixity_verification_results",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("run_id", ID, ForeignKey("ebook_fixity_verification_runs.id"), nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("result_type", ENUM, nullable=False),
    Column("expected_observation_id", ID, ForeignKey("file_observations.id")),
    Column("expected_size_bytes", Integer),
    Column("expected_sha256", Text),
    Column("expected_relative_locator", Text),
    Column("current_observation_id", ID, ForeignKey("file_observations.id")),
    Column("current_size_bytes", Integer),
    Column("current_sha256", Text),
    Column("current_relative_locator", Text),
    Column("failure_code", ENUM),
    Column("content_digest", Text, nullable=False),
    Column("recorded_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile='ebook-fixity-result/v1'",
        name="ck_ebook_fixity_verification_results_profile",
    ),
    CheckConstraint(
        "result_type IN ('VERIFIED','UNEXPECTED_BYTE_CHANGE','MISSING',"
        "'UNBASELINED','UNREADABLE','SOURCE_CHANGED_DURING_RUN')",
        name="ck_ebook_fixity_verification_results_type",
    ),
    CheckConstraint(
        "(expected_size_bytes IS NULL OR expected_size_bytes>=0) "
        "AND (current_size_bytes IS NULL OR current_size_bytes>=0)",
        name="ck_ebook_fixity_verification_results_sizes",
    ),
    CheckConstraint(
        "expected_sha256 IS NULL OR (" + _SHA_CHECK.format(name="expected_sha256") + ")",
        name="ck_ebook_fixity_verification_results_expected_sha256",
    ),
    CheckConstraint(
        "current_sha256 IS NULL OR (" + _SHA_CHECK.format(name="current_sha256") + ")",
        name="ck_ebook_fixity_verification_results_current_sha256",
    ),
    CheckConstraint(
        "expected_relative_locator IS NULL OR ("
        + _RELATIVE_LOCATOR_CHECK.format(name="expected_relative_locator")
        + ")",
        name="ck_ebook_fixity_verification_results_expected_locator",
    ),
    CheckConstraint(
        "current_relative_locator IS NULL OR ("
        + _RELATIVE_LOCATOR_CHECK.format(name="current_relative_locator")
        + ")",
        name="ck_ebook_fixity_verification_results_current_locator",
    ),
    CheckConstraint(
        "failure_code IS NULL OR (length(failure_code) BETWEEN 1 AND 64 "
        "AND failure_code NOT GLOB '*[^A-Z0-9_]*')",
        name="ck_ebook_fixity_verification_results_failure_code",
    ),
    CheckConstraint(
        "((expected_observation_id IS NULL AND expected_size_bytes IS NULL "
        "AND expected_sha256 IS NULL AND expected_relative_locator IS NULL) OR "
        "(expected_observation_id IS NOT NULL AND expected_size_bytes IS NOT NULL "
        "AND expected_sha256 IS NOT NULL AND expected_relative_locator IS NOT NULL)) "
        "AND ((result_type='VERIFIED' AND expected_observation_id IS NOT NULL "
        "AND current_observation_id IS NOT NULL AND current_size_bytes IS NOT NULL "
        "AND current_sha256 IS NOT NULL AND current_relative_locator IS NOT NULL "
        "AND expected_size_bytes=current_size_bytes AND expected_sha256=current_sha256 "
        "AND failure_code IS NULL) OR (result_type='UNEXPECTED_BYTE_CHANGE' "
        "AND expected_observation_id IS NOT NULL AND current_observation_id IS NOT NULL "
        "AND current_size_bytes IS NOT NULL AND current_sha256 IS NOT NULL "
        "AND current_relative_locator IS NOT NULL "
        "AND (expected_size_bytes<>current_size_bytes OR expected_sha256<>current_sha256) "
        "AND failure_code IS NULL) OR (result_type='MISSING' "
        "AND expected_observation_id IS NOT NULL AND current_observation_id IS NULL "
        "AND current_size_bytes IS NULL AND current_sha256 IS NULL "
        "AND current_relative_locator IS NULL AND failure_code IS NULL) OR "
        "(result_type='UNBASELINED' AND expected_observation_id IS NULL "
        "AND current_observation_id IS NOT NULL AND current_size_bytes IS NOT NULL "
        "AND current_sha256 IS NOT NULL AND current_relative_locator IS NOT NULL "
        "AND failure_code IS NULL) OR (result_type IN "
        "('UNREADABLE','SOURCE_CHANGED_DURING_RUN') "
        "AND current_observation_id IS NOT NULL AND current_size_bytes IS NOT NULL "
        "AND current_sha256 IS NULL AND current_relative_locator IS NOT NULL "
        "AND ((result_type='UNREADABLE' AND failure_code='SOURCE_UNREADABLE') OR "
        "(result_type='SOURCE_CHANGED_DURING_RUN' AND failure_code='SOURCE_CHANGED'))))",
        name="ck_ebook_fixity_verification_results_shape",
    ),
    CheckConstraint(
        _SHA_CHECK.format(name="content_digest"),
        name="ck_ebook_fixity_verification_results_content_digest",
    ),
    UniqueConstraint(
        "run_id",
        "file_id",
        name="uq_ebook_fixity_verification_results_run_file",
    ),
)


ebook_fixity_expectation_revisions = Table(
    "ebook_fixity_expectation_revisions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("profile", Text, nullable=False),
    Column("serializer", Text, nullable=False),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column(
        "baseline_activation_id",
        ID,
        ForeignKey("ebook_fixity_baseline_activations.activation_id"),
        nullable=False,
    ),
    Column("revision_no", Integer, nullable=False),
    Column("previous_revision_digest", Text, nullable=False),
    Column("revision_digest", Text, nullable=False),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("action", ENUM, nullable=False),
    Column(
        "source_result_id",
        ID,
        ForeignKey("ebook_fixity_verification_results.id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "review_decision_id",
        ID,
        ForeignKey("review_decisions.id"),
        nullable=False,
        unique=True,
    ),
    Column("expected_observation_id", ID, ForeignKey("file_observations.id")),
    Column("expected_size_bytes", Integer),
    Column("expected_sha256", Text),
    Column("expected_relative_locator", Text),
    Column("evidence_fingerprint", Text, nullable=False),
    Column("candidate_set_fingerprint", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    CheckConstraint(
        "profile='ebook-fixity-decision/v1' AND serializer='canonical-json/v1'",
        name="ck_ebook_fixity_expectation_revisions_contract",
    ),
    CheckConstraint(
        "revision_no>=1",
        name="ck_ebook_fixity_expectation_revisions_number",
    ),
    CheckConstraint(
        "action IN ('ACCEPT_CURRENT','RETIRE_MISSING')",
        name="ck_ebook_fixity_expectation_revisions_action",
    ),
    CheckConstraint(
        "(action='ACCEPT_CURRENT' AND expected_observation_id IS NOT NULL "
        "AND expected_size_bytes>=0 AND expected_sha256 IS NOT NULL "
        "AND expected_relative_locator IS NOT NULL) OR "
        "(action='RETIRE_MISSING' AND expected_observation_id IS NULL "
        "AND expected_size_bytes IS NULL AND expected_sha256 IS NULL "
        "AND expected_relative_locator IS NULL)",
        name="ck_ebook_fixity_expectation_revisions_shape",
    ),
    CheckConstraint(
        "expected_sha256 IS NULL OR (" + _SHA_CHECK.format(name="expected_sha256") + ")",
        name="ck_ebook_fixity_expectation_revisions_sha256",
    ),
    CheckConstraint(
        "expected_relative_locator IS NULL OR ("
        + _RELATIVE_LOCATOR_CHECK.format(name="expected_relative_locator")
        + ")",
        name="ck_ebook_fixity_expectation_revisions_locator",
    ),
    *(
        CheckConstraint(
            _SHA_CHECK.format(name=name),
            name=f"ck_ebook_fixity_expectation_revisions_{name}",
        )
        for name in (
            "previous_revision_digest",
            "revision_digest",
            "evidence_fingerprint",
            "candidate_set_fingerprint",
        )
    ),
    UniqueConstraint(
        "scan_root_id",
        "revision_no",
        name="uq_ebook_fixity_expectation_revisions_root_no",
    ),
    UniqueConstraint(
        "scan_root_id",
        "revision_digest",
        name="uq_ebook_fixity_expectation_revisions_root_digest",
    ),
)


Index(
    "ix_ebook_fixity_verification_runs_root_started",
    ebook_fixity_verification_runs.c.scan_root_id,
    ebook_fixity_verification_runs.c.started_at,
    ebook_fixity_verification_runs.c.id,
)
Index(
    "ix_ebook_fixity_verification_results_run_id",
    ebook_fixity_verification_results.c.run_id,
    ebook_fixity_verification_results.c.id,
)
Index(
    "ix_ebook_fixity_expectation_revisions_root_file",
    ebook_fixity_expectation_revisions.c.scan_root_id,
    ebook_fixity_expectation_revisions.c.file_id,
    ebook_fixity_expectation_revisions.c.revision_no,
)


EBOOK_FIXITY_VERIFICATION_TABLES = (
    ebook_fixity_verification_runs,
    ebook_fixity_verification_events,
    ebook_fixity_verification_results,
    ebook_fixity_expectation_revisions,
)


__all__ = [
    "EBOOK_FIXITY_VERIFICATION_TABLES",
    "ebook_fixity_expectation_revisions",
    "ebook_fixity_verification_events",
    "ebook_fixity_verification_results",
    "ebook_fixity_verification_runs",
]
