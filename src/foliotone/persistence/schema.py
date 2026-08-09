"""SQLAlchemy Core schema for provider-independent FolioTone persistence."""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

ID = String(36)
ENUM = String(48)
DATETIME = String(40)

scan_roots = Table(
    "scan_roots",
    metadata,
    Column("id", ID, primary_key=True),
    Column("name", Text, nullable=False),
    Column("media_type", ENUM, nullable=False),
    Column("enabled", Boolean, nullable=False),
)

scan_runs = Table(
    "scan_runs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("started_at", DATETIME, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("completed_at", DATETIME),
    Column("resumed_from_run_id", ID, ForeignKey("scan_runs.id")),
)

file_records = Table(
    "file_records",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_root_id", ID, ForeignKey("scan_roots.id"), nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("modified_at", DATETIME, nullable=False),
    Column("media_type", ENUM, nullable=False),
    Column("presence_state", ENUM, nullable=False),
    Column("first_seen_at", DATETIME, nullable=False),
    Column("last_seen_at", DATETIME, nullable=False),
    Column("missing_since_at", DATETIME),
    Column("consecutive_missing_scans", Integer, nullable=False, default=0),
    UniqueConstraint("scan_root_id", "relative_path", name="uq_file_root_path"),
)

file_observations = Table(
    "file_observations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("modified_at", DATETIME, nullable=False),
    Column("observed_at", DATETIME, nullable=False),
)

value_assertions = Table(
    "value_assertions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("field_name", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("state", ENUM, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
    Column("confidence", Float),
    Column("explanation", Text),
)

agents = Table(
    "agents",
    metadata,
    Column("id", ID, primary_key=True),
    Column("agent_type", ENUM, nullable=False),
)

agent_names = Table(
    "agent_names",
    metadata,
    Column("id", ID, primary_key=True),
    Column("agent_id", ID, ForeignKey("agents.id"), nullable=False),
    Column("name_type", ENUM, nullable=False),
    Column("value", Text, nullable=False),
    Column("normalized_value", Text),
    Column("language", String(32)),
    Column("script", String(32)),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
)

external_identifiers = Table(
    "external_identifiers",
    metadata,
    Column("id", ID, primary_key=True),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("namespace", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
    UniqueConstraint(
        "target_kind",
        "target_id",
        "namespace",
        "value",
        name="uq_external_identifier",
    ),
)

contributions = Table(
    "contributions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("agent_id", ID, ForeignKey("agents.id"), nullable=False),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("role", Text, nullable=False),
    Column("credited_as", Text),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
)

works = Table(
    "works",
    metadata,
    Column("id", ID, primary_key=True),
    Column("canonical_title", Text),
)

editions = Table(
    "editions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("work_id", ID, ForeignKey("works.id"), nullable=False),
    Column("canonical_title", Text),
    Column("language", String(32)),
)

series = Table(
    "series",
    metadata,
    Column("id", ID, primary_key=True),
    Column("canonical_name", Text),
)

series_memberships = Table(
    "series_memberships",
    metadata,
    Column("id", ID, primary_key=True),
    Column("series_id", ID, ForeignKey("series.id"), nullable=False),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("position", Text),
)

music_works = Table(
    "music_works",
    metadata,
    Column("id", ID, primary_key=True),
    Column("canonical_title", Text),
)

music_work_relations = Table(
    "music_work_relations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("source_work_id", ID, ForeignKey("music_works.id"), nullable=False),
    Column("target_work_id", ID, ForeignKey("music_works.id"), nullable=False),
    Column("relation_type", ENUM, nullable=False),
)

catalog_designations = Table(
    "catalog_designations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("music_work_id", ID, ForeignKey("music_works.id"), nullable=False),
    Column("system", Text, nullable=False),
    Column("value", Text, nullable=False),
    UniqueConstraint("music_work_id", "system", "value", name="uq_catalog_designation"),
)

recordings = Table(
    "recordings",
    metadata,
    Column("id", ID, primary_key=True),
    Column("canonical_title", Text),
    Column("duration_ms", Integer),
)

release_groups = Table(
    "release_groups",
    metadata,
    Column("id", ID, primary_key=True),
    Column("canonical_title", Text),
)

releases = Table(
    "releases",
    metadata,
    Column("id", ID, primary_key=True),
    Column("release_group_id", ID, ForeignKey("release_groups.id")),
    Column("canonical_title", Text),
    Column("release_date", Text),
)

release_recordings = Table(
    "release_recordings",
    metadata,
    Column("id", ID, primary_key=True),
    Column("release_id", ID, ForeignKey("releases.id"), nullable=False),
    Column("recording_id", ID, ForeignKey("recordings.id"), nullable=False),
    Column("disc_number", Integer),
    Column("track_number", Integer),
    Column("observed_title", Text),
)

classification_assertions = Table(
    "classification_assertions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("dimension", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("taxonomy", Text),
    Column("confidence", Float),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
)

fingerprints = Table(
    "fingerprints",
    metadata,
    Column("id", ID, primary_key=True),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("kind", Text, nullable=False),
    Column("algorithm", Text, nullable=False),
    Column("algorithm_version", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    Column("tool_execution_id", ID, ForeignKey("tool_executions.id")),
)

tool_executions = Table(
    "tool_executions",
    metadata,
    Column("id", ID, primary_key=True),
    Column("provider_id", Text, nullable=False),
    Column("tool_version", Text, nullable=False),
    Column("adapter_version", Text, nullable=False),
    Column("capability", ENUM, nullable=False),
    Column("input_identity", Text, nullable=False),
    Column("config_identity", Text),
    Column("started_at", DATETIME, nullable=False),
    Column("finished_at", DATETIME),
    Column("status", ENUM, nullable=False),
    Column("exit_code", Integer),
    Column("error_summary", Text),
)

tool_results = Table(
    "tool_results",
    metadata,
    Column("id", ID, primary_key=True),
    Column("execution_id", ID, ForeignKey("tool_executions.id"), nullable=False),
    Column("result_type", Text, nullable=False),
    Column("target_kind", ENUM, nullable=False),
    Column("target_id", ID, nullable=False),
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("confidence", Float),
    Column("explanation", Text),
)

relations = Table(
    "relations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("left_kind", ENUM, nullable=False),
    Column("left_id", ID, nullable=False),
    Column("right_kind", ENUM, nullable=False),
    Column("right_id", ID, nullable=False),
    Column("relation_type", ENUM, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("status", ENUM, nullable=False),
    Column("created_at", DATETIME, nullable=False),
)

evidence = Table(
    "evidence",
    metadata,
    Column("id", ID, primary_key=True),
    Column("relation_id", ID, ForeignKey("relations.id"), nullable=False),
    Column("evidence_type", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("strength", Float),
    Column("tool_execution_id", ID, ForeignKey("tool_executions.id")),
    Column("source_kind", Text, nullable=False),
    Column("source_name", Text, nullable=False),
    Column("source_version", Text),
    Column("observed_at", DATETIME, nullable=False),
)

ALL_TABLES = (
    scan_roots,
    scan_runs,
    file_records,
    file_observations,
    value_assertions,
    agents,
    agent_names,
    external_identifiers,
    contributions,
    works,
    editions,
    series,
    series_memberships,
    music_works,
    music_work_relations,
    catalog_designations,
    recordings,
    release_groups,
    releases,
    release_recordings,
    tool_executions,
    tool_results,
    classification_assertions,
    fingerprints,
    relations,
    evidence,
)
