"""Synthetic migration and persistence coverage for ADR-0052."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from foliotone.archive.container_sandbox import (
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
    ArchiveContainerRequest,
    ArchiveContainerRunResult,
    ArchiveContainerRunStatus,
    ArchiveVolumeSource,
    ArchiveWrapperContainerRunResult,
)
from foliotone.archive.provider import (
    ARCHIVE_PROVIDER_PROFILE,
    _inspect,
    build_archive_volume_group_fingerprint,
)
from foliotone.archive.sevenzip import build_7zzs_listing_command
from foliotone.archive.sevenzip_slt import ArchiveSevenZipSltParseStatus
from foliotone.archive.signatures import observe_archive_signature_v2
from foliotone.core import EntityId
from foliotone.persistence import alembic_config, create_sqlite_engine, migrate
from foliotone.persistence import archive_schema as archive
from foliotone.persistence.archive import (
    ArchiveEvidenceCompatibility,
    ArchiveEvidenceSnapshot,
    ArchiveEvidenceSource,
    ArchiveEvidenceStoreError,
    SQLiteArchiveEvidenceStore,
)
from foliotone.persistence.scan_root_lease import (
    ScanRootWriteOwnerKind,
    SQLiteScanRootWriteLeaseStore,
)

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
ROOT_ID = "00000000-0000-0000-0000-000000000201"
RUN_ID = "00000000-0000-0000-0000-000000000202"
OBSERVATION_ID = "00000000-0000-0000-0000-000000000203"
FILE_ID = "00000000-0000-0000-0000-000000000205"
FILE_OBSERVATION_ID = "00000000-0000-0000-0000-000000000206"
FORMAT_LOCK = (
    Path(__file__).parents[2]
    / "packaging"
    / "archive"
    / "7zip-26.02"
    / "archive-format.lock.json"
)


def _source_lineage(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id, name, media_type, enabled) "
                "VALUES (:id, 'synthetic-root', 'EBOOK', 1)"
            ),
            {"id": ROOT_ID},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs (id, scan_root_id, started_at, status, completed_at) "
                "VALUES (:id, :root_id, :started_at, 'COMPLETED', :completed_at)"
            ),
            {
                "id": RUN_ID,
                "root_id": ROOT_ID,
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
            },
        )


def _observation_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": OBSERVATION_ID,
        "profile": "archive-observation/v1",
        "content_hash": "a" * 64,
        "scan_root_id": ROOT_ID,
        "source_scan_run_id": RUN_ID,
        "observed_at": NOW,
        "archive_full_sha256": "b" * 64,
        "archive_content_fingerprint": "c" * 64,
        "volume_group_fingerprint": "d" * 64,
        "signature_profile": "archive-signature-observer/v2",
        "compatibility_profile": "archive-publication-storage-compatibility/v1",
        "container_class": "GENERIC_ARCHIVE",
        "suffix_kind": "ZIP",
        "publication_kind": "NONE",
        "storage_family": "ZIP",
        "outer_compression_kind": "NONE",
        "recognition_status": "MATCHED",
        "inspected_bytes": 8,
        "structural_confirmation_required": False,
        "provider_profile": "archive-7zip-provider/v1",
        "runner_profile": "archive-linux-container-runner/v1",
        "parser_profile": "archive-7zip-slt-parser/v3",
        "parser_status": "PARSED",
        "format_case_kind": "PLAINTEXT_REGULAR",
        "format_lock_profile": "archive-7zip-format-lock/v1",
        "format_lock_sha256": (
            "4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061"
        ),
        "listing_profile": "archive-listing/v1",
        "integrity_profile": "archive-integrity/v1",
        "extraction_profile": "archive-extraction/v1",
        "safety_profile": "archive-safety-policy/v1",
        "secret_version": "NONE",
        "listing_status": "LISTED",
        "encryption_status": "NONE",
        "integrity_status": "PASSED",
        "extraction_status": "NOT_ATTEMPTED",
        "password_attempt_status": "NOT_ATTEMPTED",
        "extraction_policy_status": "ACCEPTED",
        "member_count": 0,
        "writer_owner_kind": "EBOOK_ANALYSIS",
        "writer_owner_run_id": "00000000-0000-0000-0000-000000000204",
        "writer_fence_epoch": 1,
    }
    row.update(changes)
    return row


def test_migration_0019_upgrades_0018_and_has_exact_schema(tmp_path: Path) -> None:
    path = tmp_path / "archive-upgrade.db"
    migrate(path, "0018_book_classification_projection")
    previous = create_sqlite_engine(path)
    assert archive.archive_observations.name not in inspect(previous).get_table_names()
    previous.dispose()

    migrate(path)
    engine = create_sqlite_engine(path)
    inspector = inspect(engine)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "0019_archive_evidence"
    assert {table.name for table in archive.ARCHIVE_EVIDENCE_TABLES} <= set(
        inspector.get_table_names()
    )
    assert {
        "ix_archive_observations_scan_run_observed",
        "ix_archive_observations_listing_reuse",
        "ix_archive_observations_member_reuse",
    } == {str(item["name"]) for item in inspector.get_indexes("archive_observations")}
    assert {"scan_roots", "scan_runs"} == {
        str(item["referred_table"])
        for item in inspector.get_foreign_keys("archive_observations")
    }
    engine.dispose()


def test_migration_0019_rejects_invalid_parent_shapes(head_database: Path) -> None:
    invalid = (
        ("profile", "archive-observation/v2"),
        ("content_hash", "A" * 64),
        ("format_lock_sha256", "e" * 64),
        ("provider_profile", "foreign-provider/v1"),
        ("parser_status", "FOREIGN"),
        ("format_case_kind", None),
        ("extraction_status", "EXTRACTED"),
        ("member_count", 10_001),
        ("writer_fence_epoch", 0),
    )
    engine = create_sqlite_engine(head_database)
    _source_lineage(engine)
    for change, value in invalid:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    archive.archive_observations.insert().values(
                        **_observation_row(**{change: value})
                    )
                )
    engine.dispose()


def test_migration_0019_empty_downgrade_is_safe(head_database: Path) -> None:
    command.downgrade(
        alembic_config(head_database), "0018_book_classification_projection"
    )
    engine = create_sqlite_engine(head_database)
    assert not (
        {table.name for table in archive.ARCHIVE_EVIDENCE_TABLES}
        & set(inspect(engine).get_table_names())
    )
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0018_book_classification_projection"
        )
    engine.dispose()


def test_migration_0019_accepts_unattempted_parser_and_empty_wrapper_material(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    _source_lineage(engine)
    with engine.begin() as connection:
        connection.execute(
            archive.archive_observations.insert().values(
                **_observation_row(
                    parser_status=None,
                    format_case_kind=None,
                    listing_status="NOT_ATTEMPTED",
                    encryption_status="UNKNOWN",
                    integrity_status="NOT_TESTED",
                    extraction_policy_status="POLICY_REJECTED",
                )
            )
        )
        wrapper_id = "00000000-0000-0000-0000-000000000209"
        connection.execute(
            archive.archive_observations.insert().values(
                **_observation_row(
                    id=wrapper_id,
                    content_hash="9" * 64,
                    container_class="GENERIC_ARCHIVE",
                    suffix_kind="TAR_GZIP",
                    storage_family="UNKNOWN",
                    outer_compression_kind="GZIP",
                    recognition_status="OUTER_COMPRESSION_ONLY",
                    structural_confirmation_required=True,
                    provider_profile="archive-7zip-wrapper-provider/v1",
                    runner_profile="archive-wrapper-container-runner/v1",
                    parser_status=None,
                    format_case_kind=None,
                    listing_status="NOT_ATTEMPTED",
                    encryption_status="UNKNOWN",
                    integrity_status="NOT_TESTED",
                    extraction_policy_status="POLICY_REJECTED",
                )
            )
        )
        connection.execute(
            archive.archive_wrapper_lineage.insert().values(
                archive_observation_id=wrapper_id,
                profile="archive-7zip-wrapper-provider/v1",
                inner_storage_family="TAR",
                inner_stream_size_bytes=None,
                inner_stream_sha256=None,
                frame_profile="archive-tar-stream-frame/v1",
                wrapper_runner_profile="archive-wrapper-container-runner/v1",
                image_reference=(
                    "ghcr.io/gecompat/foliotone-archive-7zip@sha256:"
                    "26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
                ),
                wrapper_command_identity="1" * 64,
                listing_command_identity="2" * 64,
                integrity_command_identity="3" * 64,
            )
        )
        connection.execute(
            archive.archive_observations.insert().values(
                **_observation_row(
                    id="00000000-0000-0000-0000-000000000211",
                    content_hash="8" * 64,
                    container_class="UNSUPPORTED_CONTAINER",
                    suffix_kind="UNSUPPORTED",
                    storage_family="UNKNOWN",
                    outer_compression_kind="GZIP",
                    recognition_status="UNSUPPORTED_FORMAT",
                    structural_confirmation_required=True,
                    parser_status=None,
                    format_case_kind=None,
                    listing_status="NOT_ATTEMPTED",
                    encryption_status="UNKNOWN",
                    integrity_status="NOT_TESTED",
                    extraction_policy_status="POLICY_REJECTED",
                )
            )
        )
    engine.dispose()


def test_migration_0019_populated_downgrade_is_guarded(head_database: Path) -> None:
    engine = create_sqlite_engine(head_database)
    _source_lineage(engine)
    with engine.begin() as connection:
        connection.execute(archive.archive_observations.insert().values(**_observation_row()))
    engine.dispose()

    with pytest.raises(RuntimeError, match="archive evidence prevents migration downgrade"):
        command.downgrade(
            alembic_config(head_database), "0018_book_classification_projection"
        )


class _Runner:
    def __init__(self, listing: bytes) -> None:
        self._steps = [(listing,), ()]

    def run(self, request: ArchiveContainerRequest, **kwargs: Any) -> ArchiveContainerRunResult:
        del request
        chunks = self._steps.pop(0)
        for chunk in chunks:
            assert kwargs["stdout_consumer"](chunk)
        return ArchiveContainerRunResult(
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
            ArchiveContainerRunStatus.COMPLETED,
            0,
        )


class _WrapperRunner:
    def __init__(self) -> None:
        self._steps = [(_locked_listing("TAR"),), ()]

    def run(self, request: ArchiveContainerRequest, **kwargs: Any) -> ArchiveContainerRunResult:
        del request, kwargs
        raise AssertionError("wrapper archive must not use direct execution")

    def run_wrapper_pipeline(self, request: Any, **kwargs: Any) -> ArchiveWrapperContainerRunResult:
        del request
        chunks = self._steps.pop(0)
        for chunk in chunks:
            assert kwargs["stdout_consumer"](chunk)
        return ArchiveWrapperContainerRunResult(
            ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
            ArchiveContainerRunStatus.COMPLETED,
            0,
            0,
            sum(len(chunk) for chunk in chunks),
            0,
            2_048,
            "e" * 64,
        )


class _UnavailableWrapperRunner:
    def run(self, request: ArchiveContainerRequest, **kwargs: Any) -> ArchiveContainerRunResult:
        del request, kwargs
        raise AssertionError("wrapper archive must not use direct execution")

    def run_wrapper_pipeline(self, request: Any, **kwargs: Any) -> ArchiveWrapperContainerRunResult:
        del request, kwargs
        return ArchiveWrapperContainerRunResult(
            ARCHIVE_WRAPPER_CONTAINER_RUNNER_PROFILE,
            ArchiveContainerRunStatus.TOOL_UNAVAILABLE,
        )


def _locked_listing(storage_family: str = "ZIP") -> bytes:
    lock = json.loads(FORMAT_LOCK.read_text(encoding="utf-8"))
    capability = next(
        item
        for item in lock["capabilities"]
        if item["storage_family"] == storage_family
        and item["case_kind"] == "PLAINTEXT_REGULAR"
    )
    values = {
        "EMPTY": "",
        "BOOL_PLUS": "+",
        "BOOL_MINUS": "-",
        "CANONICAL_UINT": "1",
        "CRC32": "ABCDEF12",
        "TIMESTAMP": "2026-08-21 09:00:00",
        "PRIVATE_LOCATOR_DISCARDED": "member.bin",
        "PRIVATE_NONEMPTY_DISCARDED": "private",
        "TECHNICAL_NONEMPTY_DISCARDED": "technical",
    }
    return (
        "".join(
            f"{field['name']} = {values[field['value_class']]}\n"
            for field in capability["record_profiles"][0]["fields"]
        )
        + "\n"
    ).encode()


def _seed_archive_authorities(engine: Engine, outcome: Any) -> None:
    _source_lineage(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO file_records (id, scan_root_id, relative_path, size_bytes, "
                "modified_at, media_type, presence_state, first_seen_at, last_seen_at, "
                "consecutive_missing_scans) VALUES (:id, :root, 'synthetic.zip', 1, :now, "
                "'EBOOK', 'PRESENT', :now, :now, 0)"
            ),
            {"id": FILE_ID, "root": ROOT_ID, "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO file_observations (id, file_id, scan_run_id, relative_path, "
                "size_bytes, modified_at, observed_at) VALUES (:id, :file, :run, "
                "'synthetic.zip', 1, :now, :now)"
            ),
            {
                "id": FILE_OBSERVATION_ID,
                "file": FILE_ID,
                "run": RUN_ID,
                "now": NOW.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO fingerprints (id, target_kind, target_id, kind, algorithm, "
                "algorithm_version, value, created_at) VALUES (:id, 'FILE_OBSERVATION', "
                ":target, 'FILE_SHA256', 'sha256', '1', :value, :now)"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000207",
                "target": FILE_OBSERVATION_ID,
                "value": "b" * 64,
                "now": NOW.isoformat(),
            },
        )
        _insert_tool_executions(connection, outcome)


def _insert_tool_executions(connection: Any, outcome: Any) -> None:
    for execution in outcome.executions:
        connection.execute(
            text(
                "INSERT INTO tool_executions (id, provider_id, tool_version, "
                "adapter_version, capability, input_identity, config_identity, "
                "started_at, finished_at, status, exit_code, error_summary) VALUES "
                "(:id, :provider, "
                ":tool, :adapter, :capability, :input, :config, :started, :finished, "
                ":status, :exit_code, :error_summary)"
            ),
            {
                "id": str(execution.id),
                "provider": execution.provider_id,
                "tool": execution.tool_version,
                "adapter": execution.adapter_version,
                "capability": execution.capability.value,
                "input": execution.input_identity,
                "config": execution.config_identity,
                "started": execution.started_at.isoformat(),
                "finished": execution.finished_at.isoformat(),
                "status": execution.status.value,
                "exit_code": execution.exit_code,
                "error_summary": execution.error_summary,
            },
        )


def test_archive_store_direct_roundtrip_exact_retry_and_fence(
    tmp_path: Path, head_database: Path
) -> None:
    engine = create_sqlite_engine(head_database)
    source_path = tmp_path / "source.zip"
    request = ArchiveContainerRequest(
        (ArchiveVolumeSource(source_path, 1, "b" * 64, "archive"),),
        build_7zzs_listing_command(),
        (tmp_path,),
    )
    observation_id = EntityId.parse(OBSERVATION_ID)
    signature = observe_archive_signature_v2("synthetic.zip", b"PK\x03\x04")
    moments = iter(NOW + timedelta(seconds=value) for value in range(8))
    outcome = _inspect(
        _Runner(_locked_listing()),
        request,
        signature=signature,
        archive_observation_id=str(observation_id),
        archive_full_sha256="b" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
        cancellation=None,
        now=lambda: next(moments),
    )
    _seed_archive_authorities(engine, outcome)
    owner = EntityId.parse("00000000-0000-0000-0000-000000000208")
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        EntityId.parse(ROOT_ID),
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
        owner,
        lease_token="synthetic-secret-token",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    snapshot = ArchiveEvidenceSnapshot(
        observation_id,
        EntityId.parse(ROOT_ID),
        EntityId.parse(RUN_ID),
        NOW,
        signature,
        outcome,
        (
            ArchiveEvidenceSource(
                EntityId.parse(FILE_OBSERVATION_ID), "b" * 64, 1, "archive"
            ),
        ),
    )
    store = SQLiteArchiveEvidenceStore(engine)
    created = store.create_or_get(snapshot, lease, NOW + timedelta(seconds=1))
    assert not hasattr(created, "members")
    assert "member.bin" not in repr(created)
    assert store.create_or_get(snapshot, lease, NOW + timedelta(seconds=2)) == created
    assert store.get_by_id(observation_id) == created
    assert store.list_for_source_observation(EntityId.parse(FILE_OBSERVATION_ID), 1) == (
        created,
    )
    assert outcome.result is not None
    assert store.find_listing_reuse(
        outcome.result.reuse_key,
        ArchiveEvidenceCompatibility(
            signature,
            ARCHIVE_PROVIDER_PROFILE,
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
            ArchiveSevenZipSltParseStatus.PARSED,
            "PLAINTEXT_REGULAR",
        ),
    ) == created
    with pytest.raises(ArchiveEvidenceStoreError, match="identity"):
        store.create_or_get(
            replace(snapshot, observed_at=NOW + timedelta(seconds=3)),
            lease,
            NOW + timedelta(seconds=3),
        )
    foreign_source = replace(
        snapshot.sources[0],
        file_observation_id=EntityId.parse(
            "00000000-0000-0000-0000-000000000299"
        ),
    )
    with pytest.raises(ArchiveEvidenceStoreError, match="source lineage"):
        store.create_or_get(
            replace(snapshot, sources=(foreign_source,)),
            lease,
            NOW + timedelta(seconds=3),
        )
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM archive_observations")).scalar_one()
            == 1
        )
        assert connection.execute(
            text("SELECT COUNT(*) FROM archive_member_observations")
        ).scalar_one() == 1
    unavailable_id = EntityId.parse("00000000-0000-0000-0000-000000000210")
    unavailable_signature = observe_archive_signature_v2("synthetic.rar", b"PK\x03\x04")
    unavailable = _inspect(
        _Runner(b""),
        request,
        signature=unavailable_signature,
        archive_observation_id=str(unavailable_id),
        archive_full_sha256="b" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
        cancellation=None,
        now=lambda: NOW,
    )
    assert unavailable.executions == ()
    unavailable_stored = store.create_or_get(
        ArchiveEvidenceSnapshot(
            unavailable_id,
            EntityId.parse(ROOT_ID),
            EntityId.parse(RUN_ID),
            NOW + timedelta(seconds=4),
            unavailable_signature,
            unavailable,
            snapshot.sources,
        ),
        lease,
        NOW + timedelta(seconds=4),
    )
    assert unavailable_stored.listing_status == "NOT_ATTEMPTED"
    assert unavailable_stored.execution_count == 0
    SQLiteScanRootWriteLeaseStore(engine).release(
        lease, released_at=NOW + timedelta(seconds=5)
    )
    with pytest.raises(ArchiveEvidenceStoreError, match="write failed"):
        store.create_or_get(snapshot, lease, NOW + timedelta(seconds=6))
    engine.dispose()


def test_archive_store_wrapper_roundtrip_keeps_inner_lineage(
    tmp_path: Path, head_database: Path
) -> None:
    engine = create_sqlite_engine(head_database)
    request = ArchiveContainerRequest(
        (ArchiveVolumeSource(tmp_path / "source.gz", 1, "b" * 64, "archive"),),
        build_7zzs_listing_command(),
        (tmp_path,),
    )
    observation_id = EntityId.parse(OBSERVATION_ID)
    signature = observe_archive_signature_v2("synthetic.tar.gz", b"\x1f\x8b")
    moments = iter(NOW + timedelta(seconds=value) for value in range(8))
    outcome = _inspect(
        _WrapperRunner(),
        request,
        signature=signature,
        archive_observation_id=str(observation_id),
        archive_full_sha256="b" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
        cancellation=None,
        now=lambda: next(moments),
    )
    _seed_archive_authorities(engine, outcome)
    lease = SQLiteScanRootWriteLeaseStore(engine).acquire(
        EntityId.parse(ROOT_ID),
        ScanRootWriteOwnerKind.EBOOK_ANALYSIS,
        EntityId.parse("00000000-0000-0000-0000-000000000208"),
        lease_token="synthetic-secret-token",
        acquired_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    snapshot = ArchiveEvidenceSnapshot(
        observation_id,
        EntityId.parse(ROOT_ID),
        EntityId.parse(RUN_ID),
        NOW,
        signature,
        outcome,
        (
            ArchiveEvidenceSource(
                EntityId.parse(FILE_OBSERVATION_ID), "b" * 64, 1, "archive"
            ),
        ),
    )
    store = SQLiteArchiveEvidenceStore(engine)
    stored = store.create_or_get(
        snapshot, lease, NOW + timedelta(seconds=1)
    )
    assert stored.has_wrapper_lineage is True
    assert stored.member_count == 1
    with engine.connect() as connection:
        wrapper = connection.execute(
            text(
                "SELECT inner_storage_family, inner_stream_size_bytes, "
                "inner_stream_sha256 FROM archive_wrapper_lineage"
            )
        ).mappings().one()
    assert wrapper["inner_storage_family"] == "TAR"
    assert wrapper["inner_stream_size_bytes"] == 2_048
    assert wrapper["inner_stream_sha256"] == "e" * 64

    failed_id = EntityId.parse("00000000-0000-0000-0000-000000000212")
    failed = _inspect(
        _UnavailableWrapperRunner(),
        request,
        signature=signature,
        archive_observation_id=str(failed_id),
        archive_full_sha256="b" * 64,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
        cancellation=None,
        now=lambda: NOW,
    )
    with engine.begin() as connection:
        _insert_tool_executions(connection, failed)
    failed_stored = store.create_or_get(
        ArchiveEvidenceSnapshot(
            failed_id,
            EntityId.parse(ROOT_ID),
            EntityId.parse(RUN_ID),
            NOW + timedelta(seconds=2),
            signature,
            failed,
            snapshot.sources,
        ),
        lease,
        NOW + timedelta(seconds=2),
    )
    assert failed_stored.listing_status == "TOOL_UNAVAILABLE"
    assert failed_stored.has_wrapper_lineage is True
    with engine.connect() as connection:
        failed_inner = connection.execute(
            text(
                "SELECT inner_stream_size_bytes, inner_stream_sha256 "
                "FROM archive_wrapper_lineage WHERE archive_observation_id = :id"
            ),
            {"id": str(failed_id)},
        ).mappings().one()
    assert failed_inner == {
        "inner_stream_size_bytes": None,
        "inner_stream_sha256": None,
    }
    engine.dispose()
