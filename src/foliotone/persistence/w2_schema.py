"""W2 schema extensions for incremental scans and tool runtime artifacts."""

from sqlalchemy import Column, ForeignKey, Index, Integer, Table, Text, UniqueConstraint

from foliotone.persistence.schema import DATETIME, ENUM, ID, metadata

file_scan_events = Table(
    "file_scan_events",
    metadata,
    Column("id", ID, primary_key=True),
    Column("file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("change_state", ENUM, nullable=False),
    Column("recorded_at", DATETIME, nullable=False),
    Column("previous_relative_path", Text),
    Column("current_relative_path", Text),
)

file_relocation_candidates = Table(
    "file_relocation_candidates",
    metadata,
    Column("id", ID, primary_key=True),
    Column("scan_run_id", ID, ForeignKey("scan_runs.id"), nullable=False),
    Column("source_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("target_file_id", ID, ForeignKey("file_records.id"), nullable=False),
    Column("kind", ENUM, nullable=False),
    Column("source_relative_path", Text, nullable=False),
    Column("target_relative_path", Text, nullable=False),
    Column("source_fingerprint_id", ID, ForeignKey("fingerprints.id"), nullable=False),
    Column("target_fingerprint_id", ID, ForeignKey("fingerprints.id"), nullable=False),
    Column("fingerprint_kind", Text, nullable=False),
    Column("fingerprint_algorithm", Text, nullable=False),
    Column("fingerprint_algorithm_version", Text, nullable=False),
    Column("created_at", DATETIME, nullable=False),
    UniqueConstraint(
        "scan_run_id",
        "source_file_id",
        "target_file_id",
        name="uq_relocation_candidate_run_pair",
    ),
)

tool_artifacts = Table(
    "tool_artifacts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("execution_id", ID, ForeignKey("tool_executions.id"), nullable=False),
    Column("artifact_type", Text, nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
)

Index("uq_scan_roots_name", metadata.tables["scan_roots"].c.name, unique=True)
Index(
    "ix_scan_runs_resumed_from_run_id",
    metadata.tables["scan_runs"].c.resumed_from_run_id,
)
Index(
    "ix_file_scan_events_run_state",
    file_scan_events.c.scan_run_id,
    file_scan_events.c.change_state,
)
Index(
    "ix_file_observations_run_file",
    metadata.tables["file_observations"].c.scan_run_id,
    metadata.tables["file_observations"].c.file_id,
)
Index(
    "ix_file_relocation_candidates_run",
    file_relocation_candidates.c.scan_run_id,
)
Index(
    "ix_file_relocation_candidates_source_target",
    file_relocation_candidates.c.source_file_id,
    file_relocation_candidates.c.target_file_id,
)
Index("ix_tool_artifacts_execution", tool_artifacts.c.execution_id)
