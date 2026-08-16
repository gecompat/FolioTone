from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pytest import CaptureFixture
from sqlalchemy import event

from foliotone.cli.main import main
from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint, MediaType
from foliotone.index import (
    DuplicateHashCandidateService,
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import create_sqlite_engine, migrate, repository

NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)


def test_candidate_hash_cli_is_selective_path_free_and_restartable(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "private-media"
    media.mkdir()
    sources = {
        media / "a.epub": b"same e-book bytes",
        media / "b.epub": b"same e-book bytes",
        media / "unique.pdf": b"different bytes",
    }
    for path, content in sources.items():
        path.write_bytes(content)
    database = tmp_path / "foliotone.db"

    assert main(
        [
            "scan",
            "--name",
            "candidate-hash-cli",
            "--path",
            str(media),
            "--media-type",
            "ebook",
            "--database",
            str(database),
            "--hash",
            "quick",
            "--suffix",
            "epub",
            "--suffix",
            "pdf",
        ]
    ) == 0
    capsys.readouterr()
    base_args = [
        "ebook-hash-candidates",
        "--root",
        str(media),
        "--scan-root",
        "candidate-hash-cli",
        "--database",
        str(database),
        "--workers",
        "2",
        "--batch-size",
        "1",
    ]

    assert main([*base_args, "--max-items", "1"]) == 3
    first_output = capsys.readouterr().out
    assert "Candidate hashing progress: candidate selection started." in first_output
    assert "Candidate hashing progress: candidate selection completed:" in first_output
    assert "Candidate hashing progress: full hashing:" in first_output
    assert "Quick candidate groups: 1" in first_output
    assert "Quick candidate observations: 2" in first_output
    assert "Full-hashed this invocation: 1" in first_output
    assert "Remaining candidates: 1" in first_output
    assert "Status: INTERRUPTED" in first_output
    assert str(media) not in first_output

    assert main(base_args) == 0
    resumed_output = capsys.readouterr().out
    assert "Already full-hashed: 1" in resumed_output
    assert "Full-hashed this invocation: 1" in resumed_output
    assert "Remaining candidates: 0" in resumed_output
    assert "Status: COMPLETED" in resumed_output
    assert str(media) not in resumed_output

    engine = create_sqlite_engine(database)
    observations = repository(engine, FileObservation).list_all()
    duplicate_ids = {
        observation.id
        for observation in observations
        if observation.relative_path in {"a.epub", "b.epub"}
    }
    full_hashes = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]
    assert {fingerprint.target_id for fingerprint in full_hashes} == duplicate_ids
    assert len({fingerprint.value for fingerprint in full_hashes}) == 1
    assert all(path.read_bytes() == content for path, content in sources.items())


def test_candidate_hash_materializes_only_the_current_snapshot_once(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    for name, content in {
        "a.epub": b"same",
        "b.epub": b"same",
        "unique.pdf": b"unique",
    }.items():
        (media / name).write_bytes(content)
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("snapshot-once", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    for _ in range(3):
        scanner.scan(root, ScanRootBinding(media))

    materializations: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if (
            "INSERT INTO" in statement.upper()
            and "_foliotone_duplicate_hash_candidates" in statement
            and "current_quick_observations" in statement
        ):
            materializations.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        summary = DuplicateHashCandidateService(engine).enrich(
            root,
            media,
            batch_size=1,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 2
    assert summary.remaining == 0
    assert len(materializations) == 1
    quick_hashes = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "QUICK_FILE"
    ]
    assert len(quick_hashes) == 9


def test_candidate_hash_excludes_inconsistent_current_quick_evidence(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    for name in ("a.epub", "b.epub", "conflicting.epub"):
        (media / name).write_bytes(b"same")
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("conflicting-quick", MediaType.EBOOK)
    IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    ).scan(root, ScanRootBinding(media))
    conflicting = next(
        observation
        for observation in repository(engine, FileObservation).list_all()
        if observation.relative_path == "conflicting.epub"
    )
    repository(engine, Fingerprint).save(
        Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=conflicting.id,
            kind="QUICK_FILE",
            algorithm="sha256-head-tail",
            algorithm_version="1",
            value="0" * 64,
            created_at=NOW,
        )
    )

    summary = DuplicateHashCandidateService(engine).enrich(root, media)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 2
    full_hash_targets = {
        fingerprint.target_id
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    }
    assert conflicting.id not in full_hash_targets


def test_candidate_hash_isolates_a_source_changed_after_scan(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first = media / "a.epub"
    second = media / "b.epub"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    store = SQLiteIndexStore(engine)
    root = store.get_or_create_root("changed-candidate", MediaType.EBOOK)
    scanner = IncrementalScanner(
        store,
        hash_mode=HashMode.QUICK,
        fingerprint_writer=FingerprintWriter(engine),
        clock=lambda: NOW,
    )
    scanner.scan(root, ScanRootBinding(media))
    first.write_bytes(b"changed after scan")

    summary = DuplicateHashCandidateService(
        engine,
        clock=lambda: NOW + timedelta(minutes=1),
    ).enrich(root, media, worker_count=2)

    assert summary.candidate_groups == 1
    assert summary.candidate_observations == 2
    assert summary.hashed_this_invocation == 1
    assert summary.hash_failures == 1
    assert summary.remaining == 1
    (full_hash,) = [
        fingerprint
        for fingerprint in repository(engine, Fingerprint).list_all()
        if fingerprint.kind == "FILE_SHA256"
    ]
    observations = repository(engine, FileObservation).list_all()
    second_observation = next(
        observation
        for observation in observations
        if observation.relative_path == "b.epub"
    )
    assert full_hash.target_id == second_observation.id
