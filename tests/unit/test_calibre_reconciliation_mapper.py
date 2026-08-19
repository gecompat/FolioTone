from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId, EntityKind, FileObservation, Fingerprint
from foliotone.workflows.calibre_reconciliation import (
    CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySnapshot,
    CalibreLibrarySnapshotStatus,
    CalibreReconciliationFindingCode,
)
from foliotone.workflows.calibre_reconciliation_mapper import (
    CalibreReconciliationMapper,
)

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _snapshot() -> CalibreLibrarySnapshot:
    return CalibreLibrarySnapshot(
        EntityId.new(),
        EntityId.new(),
        EntityId.new(),
        CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
        "calibredb-library/1",
        "9.13.0",
        "calibre-library-parser/1",
        DIGEST,
        DIGEST,
        DIGEST,
        CalibreLibrarySnapshotStatus.COMPLETED,
        NOW,
        NOW + timedelta(minutes=1),
    )


def _observation(path: str, scan_run_id: EntityId) -> FileObservation:
    return FileObservation(
        EntityId.new(),
        EntityId.new(),
        scan_run_id,
        path,
        10,
        NOW,
        NOW,
    )


def _record(snapshot: CalibreLibrarySnapshot, number: int) -> CalibreLibraryRecordSnapshot:
    return CalibreLibraryRecordSnapshot(
        EntityId.new(),
        snapshot.id,
        number,
        DIGEST,
    )


def _format(
    record: CalibreLibraryRecordSnapshot,
    label: str,
    observation: FileObservation,
) -> CalibreLibraryFormatSnapshot:
    return CalibreLibraryFormatSnapshot(
        EntityId.new(),
        record.id,
        label,
        observation.relative_path,
        10,
        observation.id,
    )


def _fingerprint(observation: FileObservation, value: str) -> Fingerprint:
    return Fingerprint(
        EntityId.new(),
        EntityKind.FILE_OBSERVATION,
        observation.id,
        "FILE_SHA256",
        "sha256",
        "1",
        value,
        NOW,
    )


def test_cases_a_through_d_and_multi_format_boundary() -> None:
    snapshot = _snapshot()
    record_b = _record(snapshot, 102)
    record_c1 = _record(snapshot, 103)
    record_c2 = _record(snapshot, 104)
    record_d = _record(snapshot, 105)
    observation_a = _observation("Loose/Only.epub", snapshot.source_scan_run_id)
    observation_c1 = _observation("A/Twin.epub", snapshot.source_scan_run_id)
    observation_c2 = _observation("B/Twin.epub", snapshot.source_scan_run_id)
    observation_d1 = _observation("D/Book.epub", snapshot.source_scan_run_id)
    observation_d2 = _observation("D/Book.pdf", snapshot.source_scan_run_id)
    formats = (
        _format(record_c1, "EPUB", observation_c1),
        _format(record_c2, "EPUB", observation_c2),
        _format(record_d, "EPUB", observation_d1),
        _format(record_d, "PDF", observation_d2),
    )
    result = CalibreReconciliationMapper().map(
        snapshot,
        (record_d, record_c2, record_b, record_c1),
        formats,
        (observation_d2, observation_a, observation_c2, observation_d1, observation_c1),
        (
            _fingerprint(observation_c1, DIGEST),
            _fingerprint(observation_c2, DIGEST),
            _fingerprint(observation_d1, "c" * 64),
            _fingerprint(observation_d2, "b" * 64),
        ),
        created_at=NOW,
    )

    codes = [finding.code for finding in result.findings]
    assert codes.count(CalibreReconciliationFindingCode.FILESYSTEM_ONLY) == 1
    assert codes.count(CalibreReconciliationFindingCode.CALIBRE_RECORD_WITHOUT_FILE) == 1
    assert codes.count(CalibreReconciliationFindingCode.CALIBRE_DUPLICATE_RECORD_CANDIDATE) == 1
    assert codes.count(CalibreReconciliationFindingCode.CALIBRE_MULTI_FORMAT_RECORD) == 1
    assert not any(
        finding.code is CalibreReconciliationFindingCode.CALIBRE_DUPLICATE_RECORD_CANDIDATE
        and any(ref.ref_id == record_d.id for ref in result.refs_for(finding))
        for finding in result.findings
    )


def test_finding_fingerprints_ignore_input_order_and_internal_row_ids() -> None:
    first_snapshot = _snapshot()
    first_record_a = _record(first_snapshot, 1)
    first_record_b = _record(first_snapshot, 2)
    first_observation_a = _observation("A/Book.epub", first_snapshot.source_scan_run_id)
    first_observation_b = _observation("B/Book.epub", first_snapshot.source_scan_run_id)
    first_formats = (
        _format(first_record_a, "EPUB", first_observation_a),
        _format(first_record_b, "EPUB", first_observation_b),
    )
    first = CalibreReconciliationMapper().map(
        first_snapshot,
        (first_record_a, first_record_b),
        first_formats,
        (first_observation_a, first_observation_b),
        (
            _fingerprint(first_observation_a, DIGEST),
            _fingerprint(first_observation_b, DIGEST),
        ),
        created_at=NOW,
    )

    second_snapshot = _snapshot()
    second_record_a = _record(second_snapshot, 1)
    second_record_b = _record(second_snapshot, 2)
    second_observation_a = _observation("A/Book.epub", second_snapshot.source_scan_run_id)
    second_observation_b = _observation("B/Book.epub", second_snapshot.source_scan_run_id)
    second = CalibreReconciliationMapper().map(
        second_snapshot,
        (second_record_b, second_record_a),
        (
            _format(second_record_b, "EPUB", second_observation_b),
            _format(second_record_a, "EPUB", second_observation_a),
        ),
        (second_observation_b, second_observation_a),
        (
            _fingerprint(second_observation_b, DIGEST),
            _fingerprint(second_observation_a, DIGEST),
        ),
        created_at=NOW,
    )

    assert [item.finding_fingerprint for item in first.findings] == [
        item.finding_fingerprint for item in second.findings
    ]


def test_inconsistent_full_hash_evidence_does_not_create_duplicate_candidate() -> None:
    snapshot = _snapshot()
    record_a = _record(snapshot, 1)
    record_b = _record(snapshot, 2)
    observation_a = _observation("A/Book.epub", snapshot.source_scan_run_id)
    observation_b = _observation("B/Book.epub", snapshot.source_scan_run_id)
    result = CalibreReconciliationMapper().map(
        snapshot,
        (record_a, record_b),
        (_format(record_a, "EPUB", observation_a), _format(record_b, "EPUB", observation_b)),
        (observation_a, observation_b),
        (
            _fingerprint(observation_a, DIGEST),
            _fingerprint(observation_a, "b" * 64),
            _fingerprint(observation_b, DIGEST),
        ),
        created_at=NOW,
    )
    assert not any(
        item.code is CalibreReconciliationFindingCode.CALIBRE_DUPLICATE_RECORD_CANDIDATE
        for item in result.findings
    )


def test_mapper_rejects_observations_from_another_scan() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="another source scan"):
        CalibreReconciliationMapper().map(
            snapshot,
            (),
            (),
            (_observation("Loose/Book.epub", EntityId.new()),),
            created_at=NOW,
        )


def test_mapper_rejects_format_locator_that_differs_from_observation() -> None:
    snapshot = _snapshot()
    record = _record(snapshot, 1)
    observation = _observation("Author/Book.epub", snapshot.source_scan_run_id)
    format_item = CalibreLibraryFormatSnapshot(
        EntityId.new(), record.id, "EPUB", "Elsewhere/Book.epub", 10, observation.id
    )
    with pytest.raises(ValueError, match="locator"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record,),
            (format_item,),
            (observation,),
            created_at=NOW,
        )


def test_duplicate_finding_fails_closed_above_reference_limit() -> None:
    snapshot = _snapshot()
    records = tuple(_record(snapshot, number) for number in range(86))
    observations = tuple(
        _observation(f"Author{number}/Book.epub", snapshot.source_scan_run_id)
        for number in range(86)
    )
    formats = tuple(
        _format(record, "EPUB", observation)
        for record, observation in zip(records, observations, strict=True)
    )
    fingerprints = tuple(_fingerprint(observation, DIGEST) for observation in observations)

    with pytest.raises(ValueError, match="reference limit"):
        CalibreReconciliationMapper().map(
            snapshot,
            records,
            formats,
            observations,
            fingerprints,
            created_at=NOW,
        )
