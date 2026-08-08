"""W2 schema extensions for incremental scan bookkeeping."""

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text

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
