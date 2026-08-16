from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, insert, update

from foliotone.core import (
    EbookCollectionItem,
    EbookCollectionItemStatus,
    EbookCollectionRunStatus,
    EntityId,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import (
    EbookCollectionStoreError,
    SQLiteEbookCollectionStore,
    create_sqlite_engine,
    migrate,
    repository,
    schema,
    w3_schema,
)
from foliotone.tooling import ToolExecution
from foliotone.workflows import (
    EBOOK_ANALYSIS_PROFILE,
    EbookAnalysisOutcome,
    EbookAnalysisStepDisposition,
    EbookAnalysisStepOutcome,
    EbookCollectionInterrupted,
    EbookCollectionService,
    EbookQualityAssessment,
    EbookQualityDimension,
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
)

NOW = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)


def test_collection_plan_is_stable_filtered_and_resumable(tmp_path: Path) -> None:
    engine, root, observations = _environment(
        tmp_path,
        (
            "05/book.pdf",
            "01/book.EPUB",
            "03/book.azw",
            "02/book.mobi",
            "04/book.azw3",
            "ignored/readme.txt",
        ),
    )
    analyzed: list[EntityId] = []

    def analyze(observation: FileObservation, fresh: bool) -> EbookAnalysisOutcome:
        assert not fresh
        analyzed.append(observation.id)
        return _persisted_success_outcome(engine, observation)

    service = EbookCollectionService(
        SQLiteEbookCollectionStore(engine),
        analyze,
        clock=lambda: NOW,
    )
    first = service.start(root.id, worker_count=2, max_items=2)

    assert first.run.status is EbookCollectionRunStatus.INTERRUPTED
    assert first.processed_this_invocation == 2
    assert first.counts.planned == 5
    assert first.counts.succeeded == 2
    assert first.counts.pending == 3

    resumed = service.resume(first.run.id)

    assert resumed.run.status is EbookCollectionRunStatus.COMPLETED
    assert resumed.processed_this_invocation == 3
    assert resumed.counts.succeeded == 5
    assert resumed.counts.pending == 0
    assert len(analyzed) == len(set(analyzed)) == 5
    assert observations["ignored/readme.txt"].id not in analyzed

    items = sorted(
        repository(engine, EbookCollectionItem).list_all(),
        key=lambda item: item.ordinal,
    )
    assert [item.format_name for item in items] == [
        "EPUB",
        "MOBI",
        "AZW",
        "AZW3",
        "PDF",
    ]
    assert all(item.attempt_count == 1 for item in items)


def test_large_plan_uses_one_streamed_select_and_bounded_insert_batches(
    tmp_path: Path,
) -> None:
    engine, root, _observations = _environment(tmp_path, ())
    (scan,) = repository(engine, ScanRun).list_all()
    records: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    timestamp = NOW.isoformat()
    for index in range(1201):
        file_id = str(EntityId.new())
        relative_path = f"bulk/{index:05d}.epub"
        records.append(
            {
                "id": file_id,
                "scan_root_id": str(root.id),
                "relative_path": relative_path,
                "size_bytes": index + 1,
                "modified_at": timestamp,
                "media_type": MediaType.EBOOK.value,
                "presence_state": PresenceState.PRESENT.value,
                "first_seen_at": timestamp,
                "last_seen_at": timestamp,
                "missing_since_at": None,
                "consecutive_missing_scans": 0,
            }
        )
        observations.append(
            {
                "id": str(EntityId.new()),
                "file_id": file_id,
                "scan_run_id": str(scan.id),
                "relative_path": relative_path,
                "size_bytes": index + 1,
                "modified_at": timestamp,
                "observed_at": timestamp,
            }
        )
    with engine.begin() as connection:
        connection.execute(insert(schema.file_records), records)
        connection.execute(insert(schema.file_observations), observations)

    statements: list[tuple[str, int]] = []

    def observe_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        executemany: bool,
    ) -> None:
        batch_size = len(parameters) if executemany and isinstance(parameters, list) else 1
        statements.append((statement, batch_size))

    event.listen(engine, "before_cursor_execute", observe_statement)
    try:
        created = SQLiteEbookCollectionStore(engine).create_run(
            root.id,
            profile="ebook-collection-analysis/v1",
            analysis_profile=EBOOK_ANALYSIS_PROFILE,
            fresh=False,
            worker_count=1,
            started_at=NOW,
            lease_token="streamed-plan",
            lease_expires_at=NOW + timedelta(minutes=30),
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe_statement)

    plan_selects = [
        statement
        for statement, _batch_size in statements
        if "FROM file_observations JOIN file_records" in statement
    ]
    insert_sizes = [
        batch_size
        for statement, batch_size in statements
        if f"INSERT INTO {w3_schema.ebook_collection_items.name}" in statement
    ]
    assert created.planned_count == 1201
    assert len(plan_selects) == 1
    assert insert_sizes == [500, 500, 201]


def test_collection_plan_per_format_is_bounded_and_deterministic(
    tmp_path: Path,
) -> None:
    engine, root, observations = _environment(
        tmp_path,
        (
            "epub/z.epub",
            "epub/a.epub",
            "pdf/z.pdf",
            "pdf/a.pdf",
            "kindle/book.azw3",
            "legacy/z.mobi",
            "legacy/a.mobi",
            "ignored/readme.txt",
        ),
    )

    created = SQLiteEbookCollectionStore(engine).create_run(
        root.id,
        profile="ebook-collection-analysis/v1",
        analysis_profile=EBOOK_ANALYSIS_PROFILE,
        fresh=False,
        worker_count=1,
        started_at=NOW,
        lease_token="format-plan",
        lease_expires_at=NOW + timedelta(minutes=30),
        plan_per_format=1,
    )

    items = sorted(
        repository(engine, EbookCollectionItem).list_all(),
        key=lambda item: item.ordinal,
    )
    assert created.planned_count == 4
    assert [item.format_name for item in items] == ["AZW3", "EPUB", "MOBI", "PDF"]
    assert [item.observation_id for item in items] == [
        observations["kindle/book.azw3"].id,
        observations["epub/a.epub"].id,
        observations["legacy/a.mobi"].id,
        observations["pdf/a.pdf"].id,
    ]


def test_collection_format_counts_are_fixed_path_free_and_read_only(
    tmp_path: Path,
) -> None:
    engine, root, _observations = _environment(
        tmp_path,
        (
            "private/one.epub",
            "private/two.EPUB",
            "private/legacy.mobi",
            "private/kindle.azw3",
            "private/manual.pdf",
            "private/ignored.txt",
        ),
    )
    store = SQLiteEbookCollectionStore(engine)
    created = store.create_run(
        root.id,
        profile="ebook-collection-analysis/v1",
        analysis_profile=EBOOK_ANALYSIS_PROFILE,
        fresh=False,
        worker_count=1,
        started_at=NOW,
        lease_token="format-counts",
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    statements: list[str] = []

    def observe_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lstrip().upper())

    event.listen(engine, "before_cursor_execute", observe_statement)
    try:
        counts = store.format_counts(created.run.id)
    finally:
        event.remove(engine, "before_cursor_execute", observe_statement)

    assert counts == (
        ("EPUB", 2),
        ("MOBI", 1),
        ("AZW", 0),
        ("AZW3", 1),
        ("PDF", 1),
    )
    assert len(statements) == 2
    assert all(statement.startswith("SELECT") for statement in statements)
    assert all("PRIVATE/" not in statement for statement in statements)


def test_collection_format_counts_reject_unknown_persisted_labels(
    tmp_path: Path,
) -> None:
    engine, root, _observations = _environment(tmp_path, ("book.epub",))
    store = SQLiteEbookCollectionStore(engine)
    created = store.create_run(
        root.id,
        profile="ebook-collection-analysis/v1",
        analysis_profile=EBOOK_ANALYSIS_PROFILE,
        fresh=False,
        worker_count=1,
        started_at=NOW,
        lease_token="unknown-format-count",
        lease_expires_at=NOW + timedelta(minutes=30),
    )
    with engine.begin() as connection:
        connection.execute(
            update(w3_schema.ebook_collection_items)
            .where(w3_schema.ebook_collection_items.c.run_id == str(created.run.id))
            .values(format_name="CBZ")
        )

    with pytest.raises(EbookCollectionStoreError, match="unknown format"):
        store.format_counts(created.run.id)


def test_collection_format_counts_require_an_existing_run(tmp_path: Path) -> None:
    engine, _root, _observations = _environment(tmp_path, ())

    with pytest.raises(EbookCollectionStoreError, match="run does not exist"):
        SQLiteEbookCollectionStore(engine).format_counts(EntityId.new())


def test_collection_plan_limits_are_mutually_exclusive(tmp_path: Path) -> None:
    engine, root, _observations = _environment(tmp_path, ("book.epub",))

    with pytest.raises(ValueError, match="mutually exclusive"):
        SQLiteEbookCollectionStore(engine).create_run(
            root.id,
            profile="ebook-collection-analysis/v1",
            analysis_profile=EBOOK_ANALYSIS_PROFILE,
            fresh=False,
            worker_count=1,
            started_at=NOW,
            lease_token="invalid-plan",
            lease_expires_at=NOW + timedelta(minutes=30),
            plan_limit=1,
            plan_per_format=1,
        )


def test_collection_continues_after_private_per_file_exception(tmp_path: Path) -> None:
    engine, root, observations = _environment(
        tmp_path,
        ("a.epub", "b.epub", "c.epub"),
    )
    rejected = observations["b.epub"].id

    def analyze(observation: FileObservation, _fresh: bool) -> EbookAnalysisOutcome:
        if observation.id == rejected:
            raise RuntimeError(r"private failure at Q:\synthetic-library\b.epub")
        return _persisted_success_outcome(engine, observation)

    outcome = EbookCollectionService(
        SQLiteEbookCollectionStore(engine),
        analyze,
        clock=lambda: NOW,
    ).start(root.id, worker_count=2)

    assert outcome.run.status is EbookCollectionRunStatus.COMPLETED_WITH_FAILURES
    assert outcome.counts.succeeded == 2
    assert outcome.counts.error == 1
    items = repository(engine, EbookCollectionItem).list_all()
    errored = [item for item in items if item.status is EbookCollectionItemStatus.ERROR]
    assert len(errored) == 1
    assert errored[0].error_code == "UNEXPECTED_ANALYSIS_ERROR"
    assert "NAS" not in repr(items)


def test_collection_worker_concurrency_is_bounded(tmp_path: Path) -> None:
    engine, root, _observations = _environment(
        tmp_path,
        tuple(f"books/{index:02d}.epub" for index in range(8)),
    )
    lock = threading.Lock()
    active = 0
    peak = 0

    def analyze(observation: FileObservation, _fresh: bool) -> EbookAnalysisOutcome:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return _persisted_success_outcome(engine, observation)

    outcome = EbookCollectionService(
        SQLiteEbookCollectionStore(engine),
        analyze,
        clock=lambda: NOW,
    ).start(root.id, worker_count=3)

    assert outcome.run.status is EbookCollectionRunStatus.COMPLETED
    assert outcome.counts.succeeded == 8
    assert 2 <= peak <= 3


def test_active_lease_blocks_resume_and_stale_claim_is_retried(tmp_path: Path) -> None:
    engine, root, _observations = _environment(tmp_path, ("book.epub",))
    store = SQLiteEbookCollectionStore(engine)
    created = store.create_run(
        root.id,
        profile="ebook-collection-analysis/v1",
        analysis_profile=EBOOK_ANALYSIS_PROFILE,
        fresh=False,
        worker_count=1,
        started_at=NOW,
        lease_token="first-lease",
        lease_expires_at=NOW + timedelta(minutes=30),
    )

    with pytest.raises(EbookCollectionStoreError, match="active lease"):
        store.acquire_resume(
            created.run.id,
            lease_token="second-lease",
            now=NOW + timedelta(minutes=1),
            lease_expires_at=NOW + timedelta(minutes=31),
        )

    (claimed,) = store.claim_pending(
        created.run.id,
        "first-lease",
        limit=1,
        started_at=NOW + timedelta(minutes=1),
    )
    assert claimed.item.attempt_count == 1

    with pytest.raises(EbookCollectionStoreError, match="expired"):
        store.heartbeat(
            created.run.id,
            "first-lease",
            NOW + timedelta(minutes=31),
            NOW + timedelta(minutes=61),
        )

    store.acquire_resume(
        created.run.id,
        lease_token="second-lease",
        now=NOW + timedelta(minutes=31),
        lease_expires_at=NOW + timedelta(minutes=61),
    )
    (retried,) = store.claim_pending(
        created.run.id,
        "second-lease",
        limit=1,
        started_at=NOW + timedelta(minutes=32),
    )

    assert retried.item.id == claimed.item.id
    assert retried.item.attempt_count == 2


def test_keyboard_interrupt_releases_run_for_exact_resume(tmp_path: Path) -> None:
    engine, root, _observations = _environment(tmp_path, ("book.epub",))
    store = SQLiteEbookCollectionStore(engine)

    def interrupt(
        _observation: FileObservation,
        _fresh: bool,
    ) -> EbookAnalysisOutcome:
        raise KeyboardInterrupt

    with pytest.raises(EbookCollectionInterrupted) as caught:
        EbookCollectionService(store, interrupt, clock=lambda: NOW).start(root.id)

    assert caught.value.run_id is not None
    interrupted = store.get_run(caught.value.run_id)
    assert interrupted is not None
    assert interrupted.status is EbookCollectionRunStatus.INTERRUPTED

    resumed = EbookCollectionService(
        store,
        lambda observation, _fresh: _persisted_success_outcome(engine, observation),
        clock=lambda: NOW,
    ).resume(interrupted.id)

    assert resumed.run.status is EbookCollectionRunStatus.COMPLETED
    (item,) = repository(engine, EbookCollectionItem).list_all()
    assert item.status is EbookCollectionItemStatus.SUCCEEDED
    assert item.attempt_count == 2


def test_latest_scan_must_be_completed_before_planning(tmp_path: Path) -> None:
    engine, root, _observations = _environment(tmp_path, ("book.epub",))
    repository(engine, ScanRun).save(
        ScanRun(
            id=EntityId.new(),
            scan_root_id=root.id,
            started_at=NOW + timedelta(minutes=1),
            completed_at=NOW + timedelta(minutes=1),
            status=ScanRunStatus.INTERRUPTED,
        )
    )

    with pytest.raises(EbookCollectionStoreError, match="latest ScanRun"):
        EbookCollectionService(
            SQLiteEbookCollectionStore(engine),
            lambda observation, _fresh: _persisted_success_outcome(
                engine, observation
            ),
            clock=lambda: NOW + timedelta(minutes=2),
        ).start(root.id)


def _environment(
    tmp_path: Path,
    paths: tuple[str, ...],
) -> tuple[Engine, ScanRoot, dict[str, FileObservation]]:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name="synthetic-ebooks", media_type=MediaType.EBOOK)
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    observations: dict[str, FileObservation] = {}
    for index, relative_path in enumerate(paths, start=1):
        record = FileRecord(
            id=EntityId.new(),
            scan_root_id=root.id,
            relative_path=relative_path,
            size_bytes=index,
            modified_at=NOW,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        observation = FileObservation(
            id=EntityId.new(),
            file_id=record.id,
            scan_run_id=scan.id,
            relative_path=relative_path,
            size_bytes=index,
            modified_at=NOW,
            observed_at=NOW,
        )
        repository(engine, FileRecord).save(record)
        repository(engine, FileObservation).save(observation)
        observations[relative_path] = observation
    return engine, root, observations


def _success_outcome(
    observation: FileObservation,
    *,
    disposition: EbookAnalysisStepDisposition = EbookAnalysisStepDisposition.EXECUTED,
) -> EbookAnalysisOutcome:
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="synthetic-collection",
        tool_version="1",
        adapter_version="1",
        capability=ToolCapability.READ_METADATA,
        input_identity=f"file-observation:{observation.id}",
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    format_name = observation.relative_path.rsplit(".", 1)[-1].upper()
    quality = EbookQualityAssessment(
        observation_id=observation.id,
        format_name=format_name,
        dimensions=tuple(
            EbookQualityDimension(name, EbookQualityDimensionStatus.OK)
            for name in EbookQualityDimensionName
        ),
        findings=(),
        source_execution_ids=(execution.id,),
    )
    return EbookAnalysisOutcome(
        observation_id=observation.id,
        format_name=format_name,
        steps=(
            EbookAnalysisStepOutcome(
                name="synthetic",
                executions=(execution,),
                disposition=disposition,
            ),
        ),
        quality=quality,
    )


def _persisted_success_outcome(
    engine: Engine,
    observation: FileObservation,
) -> EbookAnalysisOutcome:
    outcome = _success_outcome(observation)
    for step in outcome.steps:
        for execution in step.executions:
            repository(engine, ToolExecution).save(execution)
    return outcome
