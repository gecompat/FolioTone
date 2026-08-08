"""W2 schema extensions for incremental scans and tool runtime artifacts."""

from sqlalchemy import Column, ForeignKey, Index, Integer, Table, Text

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
    "ix_file_scan_events_run_state",
    file_scan_events.c.scan_run_id,
    file_scan_events.c.change_state,
)
Index(
    "ix_file_observations_run_file",
    metadata.tables["file_observations"].c.scan_run_id,
    metadata.tables["file_observations"].c.file_id,
)
Index("ix_tool_artifacts_execution", tool_artifacts.c.execution_id)
