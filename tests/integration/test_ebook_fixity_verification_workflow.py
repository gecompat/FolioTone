from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from foliotone.core import EntityId
from foliotone.fixity import (
    EbookFixityBaselineEntry,
    EbookFixityBaselineSourceEntry,
    EbookFixityHashError,
    EbookFixityHashErrorCode,
    EbookFixityVerificationResult,
    expected_fixity_baseline_confirmation,
)
from foliotone.persistence import (
    SQLiteEbookFixityBaselineProjection,
    SQLiteEbookFixityBaselineStore,
    create_sqlite_engine,
    create_sqlite_read_only_engine,
)
from foliotone.persistence.fixity_verification import (
    EbookFixityVerificationWorkItem,
    SQLiteEbookFixityVerificationStore,
)
from foliotone.workflows import fixity_verification as workflow

NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
BASELINE_BYTES = {
    "changed.epub": b"before",
    "missing.epub": b"missing",
    "steady.epub": b"steady",
}
CURRENT_BYTES = {
    "changed.epub": b"after!!",
    "new.epub": b"new",
    "steady.epub": b"steady",
}


class _SyntheticReader:
    def __init__(
        self,
        values: dict[str, bytes | EbookFixityHashErrorCode],
        *,
        enter_error: EbookFixityHashErrorCode | None = None,
    ) -> None:
        self._values = values
        self._enter_error = enter_error

    def __enter__(self) -> _SyntheticReader:
        if self._enter_error is not None:
            raise EbookFixityHashError(self._enter_error)
        return self

    def __exit__(self, *_exception: object) -> None:
        return None

    def hash(
        self,
        source: EbookFixityBaselineSourceEntry,
        *,
        cancelled: object = None,
    ) -> str:
        if callable(cancelled) and cancelled():
            raise EbookFixityHashError(EbookFixityHashErrorCode.CANCELLED)
        value = self._values[source.relative_locator]
        if isinstance(value, EbookFixityHashErrorCode):
            raise EbookFixityHashError(value)
        return hashlib.sha256(value).hexdigest()

    def check_root(self) -> None:
        return None


def _seed_initial_scan(database: Path) -> tuple[EntityId, dict[str, EntityId]]:
    root_id = EntityId.new()
    scan_id = EntityId.new()
    file_ids = {locator: EntityId.new() for locator in BASELINE_BYTES}
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_roots (id,name,media_type,enabled) "
                "VALUES (:id,'books','EBOOK',1)"
            ),
            {"id": str(root_id)},
        )
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'COMPLETED',:completed)"
            ),
            {
                "id": str(scan_id),
                "root": str(root_id),
                "started": (NOW - timedelta(minutes=2)).isoformat(),
                "completed": (NOW - timedelta(minutes=1)).isoformat(),
            },
        )
        for locator, content in BASELINE_BYTES.items():
            file_id = file_ids[locator]
            observation_id = EntityId.new()
            connection.execute(
                text(
                    "INSERT INTO file_records "
                    "(id,scan_root_id,relative_path,size_bytes,modified_at,media_type,"
                    "presence_state,first_seen_at,last_seen_at,missing_since_at,"
                    "consecutive_missing_scans) VALUES "
                    "(:id,:root,:path,:size,:modified,'EBOOK','PRESENT',:seen,:seen,NULL,0)"
                ),
                {
                    "id": str(file_id),
                    "root": str(root_id),
                    "path": locator,
                    "size": len(content),
                    "modified": NOW.isoformat(),
                    "seen": NOW.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO file_observations "
                    "(id,file_id,scan_run_id,relative_path,size_bytes,modified_at,observed_at) "
                    "VALUES (:id,:file,:scan,:path,:size,:modified,:observed)"
                ),
                {
                    "id": str(observation_id),
                    "file": str(file_id),
                    "scan": str(scan_id),
                    "path": locator,
                    "size": len(content),
                    "modified": NOW.isoformat(),
                    "observed": NOW.isoformat(),
                },
            )
    engine.dispose()
    return root_id, file_ids


def _activate_baseline(database: Path, root_id: EntityId) -> None:
    engine = create_sqlite_engine(database)
    read_only = create_sqlite_read_only_engine(database)
    projection = SQLiteEbookFixityBaselineProjection(read_only, batch_size=2)
    store = SQLiteEbookFixityBaselineStore(engine)
    manifest_id = EntityId.new()
    lease = store.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=NOW,
        lease_duration=timedelta(minutes=5),
    )
    with projection.open_latest(root_id) as source:
        store.start_build(
            manifest_id,
            source.source_scan_run_id,
            started_at=NOW,
            lease=lease,
        )
        entries: list[EbookFixityBaselineEntry] = []
        for batch in source.iter_batches():
            for item in batch:
                entries.append(
                    EbookFixityBaselineEntry(
                        ordinal=len(entries),
                        file_id=item.file_id,
                        observation_id=item.observation_id,
                        expected_size_bytes=item.expected_size_bytes,
                        relative_locator=item.relative_locator,
                        expected_sha256=hashlib.sha256(
                            BASELINE_BYTES[item.relative_locator]
                        ).hexdigest(),
                    )
                )
        store.append_entries(
            manifest_id,
            tuple(entries),
            lease=lease,
            committed_at=NOW + timedelta(seconds=1),
        )
    store.finalize_manifest(
        manifest_id,
        prepared_at=NOW + timedelta(seconds=2),
        expires_at=NOW + timedelta(minutes=15),
        lease=lease,
    )
    store.release(lease, released_at=NOW + timedelta(seconds=3))
    store.activate(
        manifest_id,
        expected_fixity_baseline_confirmation(manifest_id),
        activated_at=NOW + timedelta(seconds=4),
    )
    read_only.dispose()
    engine.dispose()


def _seed_current_scan(
    database: Path,
    root_id: EntityId,
    file_ids: dict[str, EntityId],
) -> None:
    scan_id = EntityId.new()
    observed_at = NOW + timedelta(minutes=5)
    file_ids["new.epub"] = EntityId.new()
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scan_runs "
                "(id,scan_root_id,started_at,status,completed_at) "
                "VALUES (:id,:root,:started,'COMPLETED',:completed)"
            ),
            {
                "id": str(scan_id),
                "root": str(root_id),
                "started": (observed_at - timedelta(minutes=1)).isoformat(),
                "completed": observed_at.isoformat(),
            },
        )
        connection.execute(
            text(
                "UPDATE file_records SET presence_state='MISSING',"
                "missing_since_at=:missing,consecutive_missing_scans=1 "
                "WHERE id=:id"
            ),
            {"missing": observed_at.isoformat(), "id": str(file_ids["missing.epub"])},
        )
        for locator in ("changed.epub", "steady.epub"):
            content = CURRENT_BYTES[locator]
            connection.execute(
                text(
                    "UPDATE file_records SET size_bytes=:size,modified_at=:modified,"
                    "last_seen_at=:seen WHERE id=:id"
                ),
                {
                    "size": len(content),
                    "modified": observed_at.isoformat(),
                    "seen": observed_at.isoformat(),
                    "id": str(file_ids[locator]),
                },
            )
            _insert_observation(
                connection,
                file_ids[locator],
                scan_id,
                locator,
                content,
                observed_at,
            )
        connection.execute(
            text(
                "INSERT INTO file_records "
                "(id,scan_root_id,relative_path,size_bytes,modified_at,media_type,"
                "presence_state,first_seen_at,last_seen_at,missing_since_at,"
                "consecutive_missing_scans) VALUES "
                "(:id,:root,'new.epub',:size,:modified,'EBOOK','PRESENT',"
                ":seen,:seen,NULL,0)"
            ),
            {
                "id": str(file_ids["new.epub"]),
                "root": str(root_id),
                "size": len(CURRENT_BYTES["new.epub"]),
                "modified": observed_at.isoformat(),
                "seen": observed_at.isoformat(),
            },
        )
        _insert_observation(
            connection,
            file_ids["new.epub"],
            scan_id,
            "new.epub",
            CURRENT_BYTES["new.epub"],
            observed_at,
        )
    engine.dispose()


def _insert_observation(
    connection: object,
    file_id: EntityId,
    scan_id: EntityId,
    locator: str,
    content: bytes,
    observed_at: datetime,
) -> None:
    connection.execute(
        text(
            "INSERT INTO file_observations "
            "(id,file_id,scan_run_id,relative_path,size_bytes,modified_at,observed_at) "
            "VALUES (:id,:file,:scan,:path,:size,:modified,:observed)"
        ),
        {
            "id": str(EntityId.new()),
            "file": str(file_id),
            "scan": str(scan_id),
            "path": locator,
            "size": len(content),
            "modified": observed_at.isoformat(),
            "observed": observed_at.isoformat(),
        },
    )


def test_verifier_completes_exact_changed_new_missing_and_verified_workset(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_id, file_ids = _seed_initial_scan(head_database)
    _activate_baseline(head_database, root_id)
    _seed_current_scan(head_database, root_id, file_ids)
    engine = create_sqlite_engine(head_database)
    read_only = create_sqlite_read_only_engine(head_database)
    projection = SQLiteEbookFixityBaselineProjection(read_only)
    store = SQLiteEbookFixityVerificationStore(engine)
    monkeypatch.setattr(
        workflow,
        "EbookFixityRootReader",
        lambda _root: _SyntheticReader(CURRENT_BYTES),
    )
    verifier = workflow.EbookFixityVerifier(
        projection,
        store,
        clock=lambda: NOW + timedelta(minutes=6),
        lease_duration=timedelta(minutes=2),
        batch_size=2,
    )

    run = verifier.verify(Path("C:/synthetic/ebooks"), worker_count=2)

    assert run.status.value == "COMPLETED"
    assert run.result_count == 4
    assert run.content_digest is not None
    with engine.connect() as connection:
        result_types = connection.execute(
            text(
                "SELECT result_type FROM ebook_fixity_verification_results "
                "WHERE run_id=:run ORDER BY result_type"
            ),
            {"run": str(run.run_id)},
        ).scalars()
        assert set(result_types) == {
            "MISSING",
            "UNBASELINED",
            "UNEXPECTED_BYTE_CHANGE",
            "VERIFIED",
        }
    status = store.read_status(run.run_id)
    assert status is not None
    assert "changed.epub" not in repr(status)
    assert hashlib.sha256(CURRENT_BYTES["changed.epub"]).hexdigest() not in repr(status)
    read_only.dispose()
    engine.dispose()


def test_verifier_persists_root_failure_without_false_missing_results(
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_id, file_ids = _seed_initial_scan(head_database)
    _activate_baseline(head_database, root_id)
    _seed_current_scan(head_database, root_id, file_ids)
    engine = create_sqlite_engine(head_database)
    read_only = create_sqlite_read_only_engine(head_database)
    store = SQLiteEbookFixityVerificationStore(engine)
    monkeypatch.setattr(
        workflow,
        "EbookFixityRootReader",
        lambda _root: _SyntheticReader(
            CURRENT_BYTES,
            enter_error=EbookFixityHashErrorCode.ROOT_UNAVAILABLE,
        ),
    )
    verifier = workflow.EbookFixityVerifier(
        SQLiteEbookFixityBaselineProjection(read_only),
        store,
        clock=lambda: NOW + timedelta(minutes=6),
        lease_duration=timedelta(minutes=2),
    )

    with pytest.raises(workflow.EbookFixityVerificationError):
        verifier.verify(Path("C:/synthetic/ebooks"))

    with engine.connect() as connection:
        failed_run_id = EntityId.parse(
            str(
                connection.execute(
                    text(
                        "SELECT id FROM ebook_fixity_verification_runs "
                        "ORDER BY started_at DESC,id DESC LIMIT 1"
                    )
                ).scalar_one()
            )
        )
        result_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM ebook_fixity_verification_results WHERE run_id=:run"
            ),
            {"run": str(failed_run_id)},
        ).scalar_one()
    status = store.read_status(failed_run_id)
    assert status is not None
    assert status.status.value == "FAILED"
    assert status.failure_code == "ROOT_UNAVAILABLE"
    assert result_count == 0
    read_only.dispose()
    engine.dispose()


@pytest.mark.parametrize(
    ("error_code", "expected_result"),
    (
        (EbookFixityHashErrorCode.SOURCE_UNREADABLE, EbookFixityVerificationResult.UNREADABLE),
        (
            EbookFixityHashErrorCode.SOURCE_CHANGED,
            EbookFixityVerificationResult.SOURCE_CHANGED_DURING_RUN,
        ),
    ),
)
def test_verifier_preserves_safe_per_file_read_failures(
    error_code: EbookFixityHashErrorCode,
    expected_result: EbookFixityVerificationResult,
) -> None:
    run_id = EntityId.new()
    item = EbookFixityVerificationWorkItem(
        file_id=EntityId.new(),
        expected_observation_id=EntityId.new(),
        expected_size_bytes=6,
        expected_sha256=hashlib.sha256(b"before").hexdigest(),
        expected_relative_locator="changed.epub",
        current_observation_id=EntityId.new(),
        current_size_bytes=7,
        current_modified_at=NOW,
        current_relative_locator="changed.epub",
    )

    result = workflow._verify_one(
        _SyntheticReader({"changed.epub": error_code}),
        run_id,
        item,
        cancelled=lambda: False,
    )

    assert result.result is expected_result
    assert result.failure_code == error_code.value
    assert result.current_size_bytes == 7
    assert result.current_sha256 is None
