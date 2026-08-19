from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from foliotone.core import (
    Agent,
    AgentName,
    AgentNameType,
    AgentType,
    CatalogDesignation,
    ClassificationAssertion,
    Contribution,
    Edition,
    EntityId,
    EntityKind,
    Evidence,
    ExternalIdentifier,
    FileObservation,
    FileRecord,
    Fingerprint,
    MatchStatus,
    MediaType,
    MusicWork,
    MusicWorkRelation,
    MusicWorkRelationType,
    PresenceState,
    Provenance,
    Recording,
    Relation,
    RelationType,
    Release,
    ReleaseGroup,
    ReleaseRecording,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
    Series,
    SeriesMembership,
    ToolCapability,
    ToolExecutionStatus,
    ValueAssertion,
    ValueState,
    Work,
)
from foliotone.persistence import (
    alembic_config,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
    migrate,
    repository,
)
from foliotone.persistence.calibre_library_schema import (
    calibre_library_formats,
    calibre_library_records,
    calibre_library_sidecars,
    calibre_library_snapshots,
    calibre_reconciliation_finding_refs,
    calibre_reconciliation_findings,
)
from foliotone.persistence.consolidation_schema import CONSOLIDATION_TABLES
from foliotone.persistence.relation_candidate_schema import (
    relation_candidate_evidence,
    relation_candidates,
)
from foliotone.persistence.resolution_review_schema import (
    resolution_candidate_evidence,
    resolution_candidates,
    review_decisions,
    review_items,
)
from foliotone.persistence.schema import ALL_TABLES
from foliotone.persistence.w2_schema import (
    file_relocation_candidates,
    file_scan_events,
    tool_artifacts,
)
from foliotone.persistence.w3_schema import (
    ebook_candidate_hash_runs,
    ebook_collection_finding_executions,
    ebook_collection_findings,
    ebook_collection_item_executions,
    ebook_collection_items,
    ebook_collection_runs,
    provider_cache_entries,
)
from foliotone.tooling import ToolExecution, ToolResult

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=1)


def provenance() -> Provenance:
    return Provenance(
        source_kind="test",
        source_name="synthetic",
        source_version="1",
        observed_at=NOW,
    )


@pytest.fixture
def database(head_database: Path) -> Path:
    return head_database


def test_migration_creates_current_schema_and_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "migration-head.db"
    migrate(database)
    migrate(database)
    engine = create_sqlite_engine(database)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    expected = {table.name for table in ALL_TABLES} | {
        table.name for table in CONSOLIDATION_TABLES
    } | {
        "alembic_version",
        file_scan_events.name,
        file_relocation_candidates.name,
        tool_artifacts.name,
        ebook_collection_runs.name,
        ebook_collection_items.name,
        ebook_collection_item_executions.name,
        ebook_collection_findings.name,
        ebook_collection_finding_executions.name,
        ebook_candidate_hash_runs.name,
        provider_cache_entries.name,
        resolution_candidates.name,
        resolution_candidate_evidence.name,
        review_items.name,
        review_decisions.name,
        relation_candidates.name,
        relation_candidate_evidence.name,
        calibre_library_snapshots.name,
        calibre_library_records.name,
        calibre_library_formats.name,
        calibre_library_sidecars.name,
        calibre_reconciliation_findings.name,
        calibre_reconciliation_finding_refs.name,
    }
    assert table_names == expected
    file_columns = {column["name"] for column in inspector.get_columns("file_records")}
    assert {"missing_since_at", "consecutive_missing_scans"} <= file_columns
    scan_columns = {column["name"] for column in inspector.get_columns("scan_runs")}
    assert {"resumed_from_run_id", "lease_token", "lease_expires_at"} <= scan_columns
    expected_indexes = {
        "scan_runs": {
            "ix_scan_runs_root_status_lease",
            "uq_scan_runs_active_root",
        },
        "tool_executions": {"ix_tool_executions_input_capability_provider_started"},
        "tool_results": {"ix_tool_results_target_execution"},
        "fingerprints": {
            "ix_fingerprints_target_kind_execution",
            "ix_fingerprints_kind_algorithm_version_value_target",
            "ix_fingerprints_target_profile_id_value",
        },
        "ebook_collection_runs": {"ix_ebook_collection_runs_root_status"},
        "ebook_collection_items": {"ix_ebook_collection_items_run_status_ordinal"},
        "ebook_collection_item_executions": {"ix_ebook_collection_item_executions_execution_item"},
        "ebook_collection_findings": {"ix_ebook_collection_findings_code_item"},
        "ebook_collection_finding_executions": {
            "ix_ebook_collection_finding_executions_execution_finding"
        },
        "ebook_candidate_hash_runs": {
            "uq_ebook_candidate_hash_runs_active_root",
            "ix_ebook_candidate_hash_runs_root_started",
        },
        "resolution_candidates": {
            "ix_resolution_candidates_subject_created",
            "ix_resolution_candidates_reuse",
        },
        "resolution_candidate_evidence": {
            "ix_resolution_candidate_evidence_source",
        },
        "review_items": {
            "ix_review_items_queue",
            "ix_review_items_subject_history",
        },
        "review_decisions": {"ix_review_decisions_item_sequence"},
        "relation_candidates": {
            "ix_relation_candidates_pair_created",
            "ix_relation_candidates_reuse",
        },
        "relation_candidate_evidence": {"ix_relation_candidate_evidence_source"},
        "calibre_library_snapshots": {"ix_calibre_library_snapshots_root_scan_created"},
        "calibre_library_formats": {"ix_calibre_library_formats_observation"},
        "calibre_library_sidecars": {"ix_calibre_library_sidecars_observation"},
        "calibre_reconciliation_findings": {"ix_calibre_reconciliation_findings_snapshot_created"},
        "calibre_reconciliation_finding_refs": {"ix_calibre_reconciliation_finding_refs_reference"},
        "provider_cache_entries": {
            "ix_provider_cache_entries_generation",
            "ix_provider_cache_entries_provider_query",
            "ix_provider_cache_entries_status_expires",
            "ix_provider_cache_entries_retention_until_source_cache_key",
        },
        "consolidation_plans": {"ix_consolidation_plans_root_scan"},
        "consolidation_quality_evidence": {"ix_consolidation_quality_observation"},
    }
    for table_name, names in expected_indexes.items():
        assert names <= {str(index["name"]) for index in inspector.get_indexes(table_name)}
    provider_cache_index_names = {
        str(index["name"])
        for index in inspector.get_indexes("provider_cache_entries")
    }
    assert (
        {
            "ix_provider_cache_entries_generation",
            "ix_provider_cache_entries_provider_query",
            "ix_provider_cache_entries_status_expires",
            "ix_provider_cache_entries_retention_until_source_cache_key",
        }
        <= provider_cache_index_names
    )
    provider_cache_columns = {
        column["name"] for column in inspector.get_columns("provider_cache_entries")
    }
    assert {
        "source_cache_key",
        "provider_id",
        "provider_adapter_version",
        "query_fingerprint",
        "provider_source_version",
        "content_status",
        "payload_kind",
        "payload_codec",
        "payload_bytes",
        "payload_bytes_sha256",
        "content_http_status",
        "content_fetched_at",
        "content_fresh_until_at",
        "content_expires_at",
        "failure_status",
        "failure_http_status",
        "failure_at",
        "failure_retry_after_at",
        "failure_expires_at",
        "generation",
        "content_hash",
        "retention_until_at",
    } <= provider_cache_columns
    assert {
        "ck_provider_cache_entries_source_cache_key",
        "ck_provider_cache_entries_provider_id",
        "ck_provider_cache_entries_provider_adapter_version",
        "ck_provider_cache_entries_provider_source_version",
        "ck_provider_cache_entries_query_fingerprint",
        "ck_provider_cache_entries_content_status",
        "ck_provider_cache_entries_payload_kind",
        "ck_provider_cache_entries_failure_status",
        "ck_provider_cache_entries_at_least_one_slot",
        "ck_provider_cache_entries_content_slot_complete",
        "ck_provider_cache_entries_content_timeline_order",
        "ck_provider_cache_entries_success_payload_kind",
        "ck_provider_cache_entries_content_http_status",
        "ck_provider_cache_entries_payload_kind_shape",
        "ck_provider_cache_entries_payload_shape",
        "ck_provider_cache_entries_payload_digest",
        "ck_provider_cache_entries_failure_http_status",
        "ck_provider_cache_entries_failure_slot_complete",
        "ck_provider_cache_entries_failure_retry",
        "ck_provider_cache_entries_generation",
        "ck_provider_cache_entries_content_hash",
    } <= {
        constraint["name"]
        for constraint in inspector.get_check_constraints("provider_cache_entries")
    }
    assert inspector.get_foreign_keys("provider_cache_entries") == []

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        query_plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT value FROM fingerprints "
                "WHERE target_kind = :target_kind AND kind = :kind "
                "AND algorithm = :algorithm AND algorithm_version = :version "
                "AND target_id = :target_id"
            ),
            {
                "target_kind": "FILE_OBSERVATION",
                "kind": "QUICK_FILE",
                "algorithm": "sha256-head-tail",
                "version": "1",
                "target_id": "00000000-0000-0000-0000-000000000001",
            },
        ).all()
    assert revision == "0017_provider_cache_schema"
    assert any("ix_fingerprints_target_profile_id_value" in str(row[-1]) for row in query_plan)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, content_status, payload_kind, "
                "content_fetched_at, content_fresh_until_at, content_expires_at, "
                "generation, content_hash"
                ") VALUES ("
                ":source_cache_key, :provider_id, :provider_adapter_version, "
                ":query_fingerprint, :provider_source_version, :content_status, "
                ":payload_kind, :content_fetched_at, :content_fresh_until_at, "
                ":content_expires_at, :generation, :content_hash"
                ")"
            ),
            {
                "source_cache_key": "a" * 64,
                "provider_id": "provider",
                "provider_adapter_version": "v1",
                "query_fingerprint": "b" * 64,
                "provider_source_version": "v1",
                "content_status": "not_found",
                "payload_kind": "none",
                "content_fetched_at": NOW.isoformat(),
                "content_fresh_until_at": NOW.isoformat(),
                "content_expires_at": (NOW + timedelta(days=1)).isoformat(),
                "generation": 1,
                "content_hash": "c" * 64,
            },
        )
        retention_query_plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT source_cache_key "
                "FROM provider_cache_entries "
                "WHERE retention_until_at <= :retention_until "
                "ORDER BY retention_until_at, source_cache_key"
            ),
            {"retention_until": (NOW + timedelta(days=1)).isoformat()},
        ).all()
    assert any(
        "ix_provider_cache_entries_retention_until_source_cache_key"
        in str(row[-1])
        for row in retention_query_plan
    )


def test_provider_cache_retention_until_at_uses_slot_maximum(
    head_database: Path,
) -> None:
    db_path = head_database
    content_only_key = "a" * 64
    failure_only_key = "b" * 64
    both_slots_key = "c" * 64
    content_only_expires = NOW + timedelta(days=1)
    failure_only_expires = NOW + timedelta(days=2)
    both_content_expires = NOW + timedelta(days=1)
    both_failure_expires = NOW + timedelta(days=3)
    with create_sqlite_engine(db_path).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, content_status, payload_kind, "
                "content_fetched_at, content_fresh_until_at, content_expires_at, "
                "generation, content_hash"
                ") VALUES ("
                ":source_cache_key, :provider_id, :provider_adapter_version, "
                ":query_fingerprint, :provider_source_version, :content_status, "
                ":payload_kind, :content_fetched_at, :content_fresh_until_at, "
                ":content_expires_at, :generation, :content_hash)"
            ),
            {
                "source_cache_key": content_only_key,
                "provider_id": "provider",
                "provider_adapter_version": "v1",
                "query_fingerprint": "a" * 64,
                "provider_source_version": "v1",
                "content_status": "not_found",
                "payload_kind": "none",
                "content_fetched_at": NOW.isoformat(),
                "content_fresh_until_at": NOW.isoformat(),
                "content_expires_at": content_only_expires.isoformat(),
                "generation": 1,
                "content_hash": "c" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, payload_kind, "
                "failure_status, "
                "failure_http_status, failure_at, failure_retry_after_at, "
                "failure_expires_at, generation, content_hash"
                ") VALUES ("
                ":source_cache_key, :provider_id, :provider_adapter_version, :query_fingerprint, "
                ":provider_source_version, :payload_kind, :failure_status, "
                ":failure_http_status, :failure_at, :failure_retry_after_at, "
                ":failure_expires_at, :generation, :content_hash)"
            ),
            {
                "source_cache_key": failure_only_key,
                "provider_id": "provider",
                "provider_adapter_version": "v1",
                "query_fingerprint": "b" * 64,
                "provider_source_version": "v1",
                "payload_kind": "none",
                "failure_status": "rate_limited",
                "failure_http_status": 429,
                "failure_at": NOW.isoformat(),
                "failure_retry_after_at": NOW.isoformat(),
                "failure_expires_at": failure_only_expires.isoformat(),
                "generation": 1,
                "content_hash": "d" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, content_status, payload_kind, "
                "content_fetched_at, content_fresh_until_at, content_expires_at, "
                "failure_status, failure_http_status, failure_at, failure_retry_after_at, "
                "failure_expires_at, generation, content_hash"
                ") VALUES ("
                ":source_cache_key, :provider_id, :provider_adapter_version, "
                ":query_fingerprint, :provider_source_version, :content_status, "
                ":payload_kind, :content_fetched_at, :content_fresh_until_at, "
                ":content_expires_at, :failure_status, :failure_http_status, :failure_at, "
                ":failure_retry_after_at, :failure_expires_at, :generation, :content_hash)"
            ),
            {
                "source_cache_key": both_slots_key,
                "provider_id": "provider",
                "provider_adapter_version": "v1",
                "query_fingerprint": "c" * 64,
                "provider_source_version": "v1",
                "content_status": "not_found",
                "payload_kind": "none",
                "content_fetched_at": NOW.isoformat(),
                "content_fresh_until_at": NOW.isoformat(),
                "content_expires_at": both_content_expires.isoformat(),
                "failure_status": "temporary_failure",
                "failure_http_status": 503,
                "failure_at": NOW.isoformat(),
                "failure_retry_after_at": None,
                "failure_expires_at": both_failure_expires.isoformat(),
                "generation": 1,
                "content_hash": "e" * 64,
            },
        )

        retention_rows = connection.execute(
            text(
                "SELECT source_cache_key, retention_until_at "
                "FROM provider_cache_entries "
                "WHERE retention_until_at <= :retention_until "
                "ORDER BY retention_until_at, source_cache_key"
            ),
            {"retention_until": (NOW + timedelta(days=4)).isoformat()},
        ).all()
        retention_query_plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT source_cache_key "
                "FROM provider_cache_entries "
                "WHERE retention_until_at <= :retention_until "
                "ORDER BY retention_until_at, source_cache_key"
            ),
            {"retention_until": (NOW + timedelta(days=4)).isoformat()},
        ).all()

    def _as_utc(value: datetime | str) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    assert [row.source_cache_key for row in retention_rows] == [
        content_only_key,
        failure_only_key,
        both_slots_key,
    ]
    assert [_as_utc(row.retention_until_at) for row in retention_rows] == [
        content_only_expires,
        failure_only_expires,
        both_failure_expires,
    ]
    assert any(
        "ix_provider_cache_entries_retention_until_source_cache_key"
        in str(row[-1])
        for row in retention_query_plan
    )


def test_provider_cache_failure_only_requires_payload_kind_none(
    head_database: Path,
) -> None:
    path = head_database
    source = "f" * 64
    now = NOW.isoformat()
    later = LATER.isoformat()
    with create_sqlite_engine(path).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, payload_kind, "
                "failure_status, failure_http_status, failure_at, "
                "failure_retry_after_at, failure_expires_at, generation, content_hash"
                ") VALUES ("
                ":source_cache_key, :provider_id, :provider_adapter_version, "
                ":query_fingerprint, :provider_source_version, :payload_kind, "
                ":failure_status, :failure_http_status, :failure_at, "
                ":failure_retry_after_at, :failure_expires_at, :generation, :content_hash)"
            ),
            {
                "source_cache_key": source,
                "provider_id": "provider",
                "provider_adapter_version": "v1",
                "query_fingerprint": "f" * 64,
                "provider_source_version": "v1",
                "payload_kind": "none",
                "failure_status": "rate_limited",
                "failure_http_status": 429,
                "failure_at": now,
                "failure_retry_after_at": now,
                "failure_expires_at": later,
                "generation": 1,
                "content_hash": "f" * 64,
            },
        )
    with create_sqlite_engine(path).connect() as connection:
        with pytest.raises(
            IntegrityError,
            match="NOT NULL constraint failed|not-?null|payload_kind",
        ):
            with connection.begin():
                connection.execute(
                    text(
                        "INSERT INTO provider_cache_entries ("
                        "source_cache_key, provider_id, provider_adapter_version, "
                        "query_fingerprint, provider_source_version, payload_kind, "
                        "failure_status, failure_http_status, failure_at, "
                        "failure_retry_after_at, failure_expires_at, generation, "
                        "content_hash"
                        ") VALUES ("
                        ":source_cache_key, :provider_id, :provider_adapter_version, "
                        ":query_fingerprint, :provider_source_version, :payload_kind, "
                        ":failure_status, :failure_http_status, :failure_at, "
                        ":failure_retry_after_at, :failure_expires_at, :generation, "
                        ":content_hash)"
                    ),
                    {
                        "source_cache_key": source.replace("f", "e"),
                        "provider_id": "provider",
                        "provider_adapter_version": "v1",
                        "query_fingerprint": "e" * 64,
                        "provider_source_version": "v1",
                        "payload_kind": None,
                        "failure_status": "rate_limited",
                        "failure_http_status": 429,
                        "failure_at": now,
                        "failure_retry_after_at": now,
                        "failure_expires_at": later,
                        "generation": 1,
                        "content_hash": "e" * 64,
                    },
                )


def test_read_only_engine_cannot_write_or_create_storage(
    database: Path,
    tmp_path: Path,
) -> None:
    before = database.read_bytes()
    before_entries = {path.name for path in database.parent.iterdir()}
    engine = create_sqlite_read_only_engine(database)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA query_only")).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        with pytest.raises(OperationalError, match="readonly|read-only|query_only"):
            connection.execute(
                text(
                    "INSERT INTO scan_roots (id, name, media_type, enabled) "
                    "VALUES ('00000000-0000-0000-0000-000000000099', "
                    "'must-not-write', 'EBOOK', 1)"
                )
            )
    engine.dispose()
    assert database.read_bytes() == before
    assert {path.name for path in database.parent.iterdir()} == before_entries

    missing = tmp_path / "missing-parent" / "missing.db"
    with pytest.raises(FileNotFoundError):
        create_sqlite_read_only_engine(missing)
    assert not missing.parent.exists()


def test_migration_upgrades_0002_absence_state_conservatively(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    migrate(path, "0002_incremental_index")
    engine = create_sqlite_engine(path)
    root_id = "00000000-0000-0000-0000-000000000001"
    file_id = "00000000-0000-0000-0000-000000000002"
    timestamp = NOW.isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id, name, media_type, enabled) "
                "VALUES (:id, :name, :media_type, :enabled)"
            ),
            {"id": root_id, "name": "legacy", "media_type": "EBOOK", "enabled": True},
        )
        connection.execute(
            text(
                "INSERT INTO file_records "
                "(id, scan_root_id, relative_path, size_bytes, modified_at, media_type, "
                "presence_state, first_seen_at, last_seen_at) "
                "VALUES (:id, :root, :path, :size, :modified, :media_type, :presence, "
                ":first_seen, :last_seen)"
            ),
            {
                "id": file_id,
                "root": root_id,
                "path": "legacy.epub",
                "size": 1,
                "modified": timestamp,
                "media_type": "EBOOK",
                "presence": "MISSING",
                "first_seen": timestamp,
                "last_seen": timestamp,
            },
        )
    engine.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    with upgraded.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT missing_since_at, consecutive_missing_scans "
                    "FROM file_records WHERE id = :id"
                ),
                {"id": file_id},
            )
            .mappings()
            .one()
        )
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert row["missing_since_at"] is None
    assert row["consecutive_missing_scans"] == 0
    assert revision == "0017_provider_cache_schema"


def test_migration_adds_candidate_hash_lookup_index_to_0009_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidate-index-upgrade.db"
    migrate(path, "0009_scan_run_leases")
    legacy = create_sqlite_engine(path)
    assert "ix_fingerprints_target_profile_id_value" not in {
        str(index["name"]) for index in inspect(legacy).get_indexes("fingerprints")
    }
    legacy.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    indexes = {str(index["name"]) for index in inspect(upgraded).get_indexes("fingerprints")}
    with upgraded.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert "ix_fingerprints_target_profile_id_value" in indexes
    assert revision == "0017_provider_cache_schema"


def test_migration_adds_candidate_hash_runs_without_fingerprint_uniqueness(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidate-run-upgrade.db"
    migrate(path, "0010_candidate_hash_lookup_index")
    legacy = create_sqlite_engine(path)
    duplicate_profile = {
        "target_kind": "FILE_OBSERVATION",
        "target_id": "00000000-0000-0000-0000-000000000001",
        "kind": "FILE_SHA256",
        "algorithm": "sha256",
        "algorithm_version": "1",
        "value": "same-value",
        "created_at": NOW.isoformat(),
        "tool_execution_id": None,
    }
    with legacy.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fingerprints "
                "(id, target_kind, target_id, kind, algorithm, algorithm_version, "
                "value, created_at, tool_execution_id) VALUES "
                "(:id, :target_kind, :target_id, :kind, :algorithm, "
                ":algorithm_version, :value, :created_at, :tool_execution_id)"
            ),
            [
                {"id": "00000000-0000-0000-0000-000000000010", **duplicate_profile},
                {"id": "00000000-0000-0000-0000-000000000011", **duplicate_profile},
            ],
        )
    assert ebook_candidate_hash_runs.name not in inspect(legacy).get_table_names()
    legacy.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    inspector = inspect(upgraded)
    with upgraded.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        duplicate_count = connection.execute(
            text("SELECT count(*) FROM fingerprints WHERE value = 'same-value'")
        ).scalar_one()

    assert ebook_candidate_hash_runs.name in inspector.get_table_names()
    assert {
        "uq_ebook_candidate_hash_runs_active_root",
        "ix_ebook_candidate_hash_runs_root_started",
    } <= {str(index["name"]) for index in inspector.get_indexes(ebook_candidate_hash_runs.name)}
    assert duplicate_count == 2
    assert revision == "0017_provider_cache_schema"


def test_migration_from_previous_head_adds_provider_cache_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "provider-cache-upgrade.db"
    migrate(path, "0016_consolidation_plans")
    legacy = create_sqlite_engine(path)
    assert provider_cache_entries.name not in inspect(legacy).get_table_names()
    legacy.dispose()

    migrate(path)
    upgraded = create_sqlite_engine(path)
    assert provider_cache_entries.name in inspect(upgraded).get_table_names()
    with upgraded.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "0017_provider_cache_schema"

    migrate(path)
    second = create_sqlite_engine(path)
    with second.connect() as connection:
        second_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert second_revision == "0017_provider_cache_schema"


def test_migration_0017_downgrade_guard(tmp_path: Path) -> None:
    path = tmp_path / "provider-cache-downgrade.db"
    migrate(path, "0016_consolidation_plans")
    migrate(path)

    command.downgrade(alembic_config(path), "0016_consolidation_plans")
    downgraded = create_sqlite_engine(path)
    assert provider_cache_entries.name not in inspect(downgraded).get_table_names()
    with downgraded.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0016_consolidation_plans"
        )
    downgraded.dispose()

    migrate(path)
    now = NOW.isoformat()
    later = LATER.isoformat()
    engine = create_sqlite_engine(path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_cache_entries ("
                "source_cache_key, provider_id, provider_adapter_version, "
                "query_fingerprint, provider_source_version, payload_kind, "
                "failure_status, "
                "failure_http_status, failure_at, failure_retry_after_at, "
                "failure_expires_at, generation, content_hash) "
                "VALUES (:source_cache_key, :provider_id, :provider_adapter_version, "
                ":query_fingerprint, :provider_source_version, :payload_kind, "
                ":failure_status, "
                ":failure_http_status, :failure_at, :failure_retry_after_at, "
                ":failure_expires_at, :generation, :content_hash)"
            ),
            {
                "source_cache_key": "0" * 64,
                "provider_id": "openlibrary",
                "provider_adapter_version": "v1",
                "query_fingerprint": "1" * 64,
                "provider_source_version": "1",
                "payload_kind": "none",
                "failure_status": "rate_limited",
                "failure_http_status": 429,
                "failure_at": now,
                "failure_retry_after_at": now,
                "failure_expires_at": later,
                "generation": 1,
                "content_hash": "2" * 64,
            },
        )
    with pytest.raises(RuntimeError, match="prevents migration downgrade"):
        command.downgrade(alembic_config(path), "0016_consolidation_plans")


def test_round_trip_complete_w1_graph(database: Path) -> None:
    engine = create_sqlite_engine(database)

    root = ScanRoot(id=EntityId.new(), name="ebooks", media_type=MediaType.EBOOK)
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=LATER,
        status=ScanRunStatus.COMPLETED,
    )
    file_a = FileRecord(
        id=EntityId.new(),
        scan_root_id=root.id,
        relative_path="Author/Book.epub",
        size_bytes=100,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    file_b = FileRecord(
        id=EntityId.new(),
        scan_root_id=root.id,
        relative_path="Incoming/Book.epub",
        size_bytes=100,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    observation = FileObservation(
        id=EntityId.new(),
        file_id=file_a.id,
        scan_run_id=scan.id,
        relative_path=file_a.relative_path,
        size_bytes=file_a.size_bytes,
        modified_at=file_a.modified_at,
        observed_at=NOW,
    )

    agent = Agent(id=EntityId.new(), agent_type=AgentType.PERSON)
    agent_name = AgentName(
        id=EntityId.new(),
        agent_id=agent.id,
        name_type=AgentNameType.CREDITED_AS,
        value="Asimov, Isaac",
        normalized_value="isaac asimov",
        provenance=provenance(),
    )
    work = Work(id=EntityId.new(), canonical_title="Synthetic Work")
    edition = Edition(
        id=EntityId.new(),
        work_id=work.id,
        canonical_title="Synthetic Edition",
        language="en",
    )
    series = Series(id=EntityId.new(), canonical_name="Synthetic Series")
    membership = SeriesMembership(
        id=EntityId.new(),
        series_id=series.id,
        target_kind=EntityKind.WORK,
        target_id=work.id,
        position="1.5",
    )
    identifier = ExternalIdentifier(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        namespace="example",
        value="work-1",
        provenance=provenance(),
    )
    contribution = Contribution(
        id=EntityId.new(),
        agent_id=agent.id,
        target_kind=EntityKind.WORK,
        target_id=work.id,
        role="AUTHOR",
        credited_as="I. Asimov",
        provenance=provenance(),
    )
    assertion = ValueAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        field_name="title",
        value="Synthetic Work",
        state=ValueState.CANONICAL,
        provenance=provenance(),
        confidence=0.99,
    )

    parent_work = MusicWork(id=EntityId.new(), canonical_title="Synthetic Symphony")
    child_work = MusicWork(id=EntityId.new(), canonical_title="Movement I")
    work_relation = MusicWorkRelation(
        id=EntityId.new(),
        source_work_id=child_work.id,
        target_work_id=parent_work.id,
        relation_type=MusicWorkRelationType.PART_OF,
    )
    catalog = CatalogDesignation(
        id=EntityId.new(),
        music_work_id=parent_work.id,
        system="TEST",
        value="1",
    )
    recording = Recording(
        id=EntityId.new(),
        canonical_title="Synthetic Recording",
        duration_ms=123000,
    )
    release_group = ReleaseGroup(id=EntityId.new(), canonical_title="Synthetic Album")
    release = Release(
        id=EntityId.new(),
        release_group_id=release_group.id,
        canonical_title="Synthetic Album",
        release_date="2026",
    )
    release_recording = ReleaseRecording(
        id=EntityId.new(),
        release_id=release.id,
        recording_id=recording.id,
        disc_number=1,
        track_number=1,
        observed_title="Synthetic Track",
    )

    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="ffprobe",
        tool_version="8.0",
        adapter_version="1",
        capability=ToolCapability.TECHNICAL_METADATA,
        input_identity=f"file:{file_a.id}",
        config_identity="default-v1",
        started_at=NOW,
        finished_at=LATER,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    tool_result = ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type="technical_metadata",
        target_kind=EntityKind.FILE,
        target_id=file_a.id,
        key="codec_name",
        value="epub",
        confidence=1.0,
    )
    classification = ClassificationAssertion(
        id=EntityId.new(),
        target_kind=EntityKind.WORK,
        target_id=work.id,
        dimension="genre",
        value="science fiction",
        taxonomy="synthetic",
        confidence=0.8,
        provenance=provenance(),
    )
    fingerprint = Fingerprint(
        id=EntityId.new(),
        target_kind=EntityKind.FILE,
        target_id=file_a.id,
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="1",
        value="0" * 64,
        created_at=NOW,
        tool_execution_id=execution.id,
    )
    relation = Relation(
        id=EntityId.new(),
        left_kind=EntityKind.FILE,
        left_id=file_a.id,
        right_kind=EntityKind.FILE,
        right_id=file_b.id,
        relation_type=RelationType.EXACT_DUPLICATE,
        confidence=1.0,
        status=MatchStatus.CONFIRMED,
        created_at=NOW,
    )
    evidence = Evidence(
        id=EntityId.new(),
        relation_id=relation.id,
        evidence_type="sha256",
        summary="Synthetic hashes match",
        strength=1.0,
        tool_execution_id=execution.id,
        provenance=provenance(),
    )

    values = [
        root,
        scan,
        file_a,
        file_b,
        observation,
        agent,
        agent_name,
        work,
        edition,
        series,
        membership,
        identifier,
        contribution,
        assertion,
        parent_work,
        child_work,
        work_relation,
        catalog,
        recording,
        release_group,
        release,
        release_recording,
        execution,
        tool_result,
        classification,
        fingerprint,
        relation,
        evidence,
    ]

    for value in values:
        repo = repository(engine, type(value))
        repo.save(value)
        assert repo.get(value.id) == value


def test_save_updates_existing_immutable_record(database: Path) -> None:
    engine = create_sqlite_engine(database)
    work_id = EntityId.new()
    repo = repository(engine, Work)
    repo.save(Work(id=work_id, canonical_title="Old"))
    repo.save(Work(id=work_id, canonical_title="New"))
    assert repo.get(work_id) == Work(id=work_id, canonical_title="New")


def test_foreign_keys_are_enforced(database: Path) -> None:
    engine = create_sqlite_engine(database)
    edition = Edition(
        id=EntityId.new(),
        work_id=EntityId.new(),
        canonical_title="Orphan",
    )
    with pytest.raises(IntegrityError):
        repository(engine, Edition).save(edition)


def test_unique_file_root_path_constraint(database: Path) -> None:
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name="ebooks", media_type=MediaType.EBOOK)
    repository(engine, ScanRoot).save(root)
    common = dict(
        scan_root_id=root.id,
        relative_path="same/book.epub",
        size_bytes=1,
        modified_at=NOW,
        media_type=MediaType.EBOOK,
        presence_state=PresenceState.PRESENT,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    repository(engine, FileRecord).save(FileRecord(id=EntityId.new(), **common))
    with pytest.raises(IntegrityError):
        repository(engine, FileRecord).save(FileRecord(id=EntityId.new(), **common))


def test_list_all_is_deterministic(database: Path) -> None:
    engine = create_sqlite_engine(database)
    repo = repository(engine, Work)
    items = [
        Work(id=EntityId.parse("00000000-0000-0000-0000-000000000002"), canonical_title="B"),
        Work(id=EntityId.parse("00000000-0000-0000-0000-000000000001"), canonical_title="A"),
    ]
    for item in items:
        repo.save(item)
    assert [str(item.id) for item in repo.list_all()] == sorted(str(item.id) for item in items)
