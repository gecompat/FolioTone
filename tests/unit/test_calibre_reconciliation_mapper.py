from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ResolutionCandidate,
    ResolutionDisposition,
    ReviewCandidateKind,
    ReviewItem,
    ReviewItemState,
    ReviewType,
)
from foliotone.tooling import ToolResult
from foliotone.workflows.calibre_reconciliation import (
    CALIBRE_LIBRARY_SNAPSHOT_PROFILE,
    CalibreLibraryFormatSnapshot,
    CalibreLibraryRecordSnapshot,
    CalibreLibrarySidecarKind,
    CalibreLibrarySidecarSnapshot,
    CalibreLibrarySnapshot,
    CalibreLibrarySnapshotStatus,
    CalibreReconciliationFindingCode,
)
from foliotone.workflows.calibre_reconciliation_mapper import (
    CalibreAuthorityConflict,
    CalibreMetadataConflict,
    CalibreReconciliationMapper,
    CalibreSidecarDependency,
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


def _tool_result(observation: FileObservation, key: str, value: str) -> ToolResult:
    return ToolResult(
        EntityId.new(),
        EntityId.new(),
        "ebook_metadata_candidate",
        EntityKind.FILE_OBSERVATION,
        observation.id,
        key,
        value,
    )


def _candidate(subject_id: EntityId) -> ResolutionCandidate:
    return ResolutionCandidate(
        EntityId.new(),
        EntityKind.FILE_OBSERVATION,
        subject_id,
        EntityKind.AGENT,
        EntityId.new(),
        "offline-book-resolution",
        "1",
        "authority-decision/v1",
        DIGEST,
        "b" * 64,
        0.5,
        ResolutionDisposition.REVIEW_REQUIRED,
        NOW,
    )


def _review(candidate: ResolutionCandidate) -> ReviewItem:
    return ReviewItem(
        EntityId.new(),
        ReviewType.AUTHORITY_RESOLUTION,
        candidate.subject_kind,
        candidate.subject_id,
        ReviewCandidateKind.RESOLUTION_CANDIDATE,
        candidate.id,
        candidate.resolver_name,
        candidate.resolver_version,
        candidate.decision_compatibility_version,
        candidate.evidence_fingerprint,
        candidate.candidate_set_fingerprint,
        ReviewItemState.PENDING,
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


def test_cases_e_through_g_link_only_existing_evidence_and_require_review() -> None:
    snapshot = _snapshot()
    metadata_record = _record(snapshot, 106)
    authority_record = _record(snapshot, 107)
    sidecar_record = _record(snapshot, 108)
    authority_observation = _observation(
        "Zora Zeta/Authority Conflict (107)/Book.epub", snapshot.source_scan_run_id
    )
    metadata_observation = _observation(
        "Meta/Metadata Conflict (106)/Book.epub", snapshot.source_scan_run_id
    )
    sidecar_observation = _observation(
        "Eli Eta/Sidecar Owner (108)/metadata.opf", snapshot.source_scan_run_id
    )
    extra_observation = _observation(
        "Eli Eta/Sidecar Owner (108)/data/notes.txt", snapshot.source_scan_run_id
    )
    format_observation = _observation(
        "Eli Eta/Sidecar Owner (108)/Book.epub", snapshot.source_scan_run_id
    )
    sidecar_format = _format(sidecar_record, "EPUB", format_observation)
    candidate = _candidate(authority_observation.id)
    review = _review(candidate)
    sidecar = CalibreLibrarySidecarSnapshot(
        EntityId.new(),
        sidecar_record.id,
        CalibreLibrarySidecarKind.METADATA_OPF,
        sidecar_observation.relative_path,
        sidecar_observation.id,
    )
    metadata_conflict = CalibreMetadataConflict(
        metadata_record.id,
        "title",
        _tool_result(metadata_observation, "title", "Calibre Heading"),
        _tool_result(metadata_observation, "title", "Embedded Heading"),
    )
    authority_conflict = CalibreAuthorityConflict(
        authority_record.id,
        "Zora Zeta",
        _tool_result(authority_observation, "author", "Zora Zeta"),
        candidate,
        review,
    )

    result = CalibreReconciliationMapper().map(
        snapshot,
        (metadata_record, authority_record, sidecar_record),
        (sidecar_format,),
        (
            metadata_observation,
            authority_observation,
            sidecar_observation,
            extra_observation,
            format_observation,
        ),
        created_at=NOW,
        metadata_conflicts=(metadata_conflict,),
        authority_conflicts=(authority_conflict,),
        sidecar_dependencies=(
            CalibreSidecarDependency(
                sidecar_record.id,
                sidecar,
                sidecar_observation.id,
                (sidecar_format.id,),
                (extra_observation.id,),
                True,
            ),
        ),
    )

    by_code = {finding.code: finding for finding in result.findings}
    for code in (
        CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT,
        CalibreReconciliationFindingCode.CALIBRE_AUTHORITY_CONFLICT,
        CalibreReconciliationFindingCode.CALIBRE_SIDECAR_DEPENDENCY,
    ):
        assert by_code[code].review_required is True
    authority_refs = result.refs_for(
        by_code[CalibreReconciliationFindingCode.CALIBRE_AUTHORITY_CONFLICT]
    )
    assert {ref.ref_id for ref in authority_refs} >= {candidate.id, review.id}
    assert [ref.ordinal for ref in authority_refs] == list(range(len(authority_refs)))
    assert "Calibre Heading" not in repr(result)
    assert "Embedded Heading" not in repr(result)
    assert "Calibre Heading" not in repr(metadata_conflict)
    assert "Embedded Heading" not in repr(metadata_conflict)
    assert "Zora Zeta" not in repr(authority_conflict)


def test_cases_e_to_g_fail_closed_for_invalid_evidence_or_ownership() -> None:
    snapshot = _snapshot()
    record = _record(snapshot, 1)
    observation = _observation("Author/Book.epub", snapshot.source_scan_run_id)
    candidate = _candidate(observation.id)
    review = _review(candidate)
    foreign_record = _record(snapshot, 2)
    foreign_sidecar = CalibreLibrarySidecarSnapshot(
        EntityId.new(),
        foreign_record.id,
        CalibreLibrarySidecarKind.COVER,
        "Other/cover.jpg",
    )

    with pytest.raises(ValueError, match="same exact field"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record,),
            (),
            (observation,),
            created_at=NOW,
            metadata_conflicts=(
                CalibreMetadataConflict(
                    record.id,
                    "title",
                    _tool_result(observation, "author", "Calibre"),
                    _tool_result(observation, "title", "Embedded"),
                ),
            ),
        )
    with pytest.raises(ValueError, match="must belong"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record, foreign_record),
            (),
            (observation,),
            created_at=NOW,
            sidecar_dependencies=(CalibreSidecarDependency(record.id, foreign_sidecar),),
        )
    mapped_format = _format(record, "EPUB", observation)
    nested_sidecar = CalibreLibrarySidecarSnapshot(
        EntityId.new(),
        record.id,
        CalibreLibrarySidecarKind.METADATA_OPF,
        "Author/nested/metadata.opf",
    )
    with pytest.raises(ValueError, match="record directory"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record,),
            (mapped_format,),
            (observation,),
            created_at=NOW,
            sidecar_dependencies=(
                CalibreSidecarDependency(
                    record.id, nested_sidecar, format_ids=(mapped_format.id,)
                ),
            ),
        )
    direct_sidecar = CalibreLibrarySidecarSnapshot(
        EntityId.new(), record.id, CalibreLibrarySidecarKind.COVER, "Author/cover.jpg"
    )
    with pytest.raises(ValueError, match="exact current observation"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record,),
            (mapped_format,),
            (),
            created_at=NOW,
            sidecar_dependencies=(
                CalibreSidecarDependency(
                    record.id, direct_sidecar, format_ids=(mapped_format.id,)
                ),
            ),
        )
    with pytest.raises(ValueError, match="must not use a decided"):
        CalibreReconciliationMapper().map(
            snapshot,
            (record,),
            (),
            (observation,),
            created_at=NOW,
            authority_conflicts=(
                CalibreAuthorityConflict(
                    record.id,
                    "Author",
                    _tool_result(observation, "author", "Author"),
                    candidate,
                    ReviewItem(
                        review.id,
                        review.review_type,
                        review.subject_kind,
                        review.subject_id,
                        review.candidate_kind,
                        review.candidate_id,
                        review.producer_name,
                        review.producer_version,
                        review.decision_compatibility_version,
                        review.evidence_fingerprint,
                        review.candidate_set_fingerprint,
                        ReviewItemState.DECIDED,
                        review.created_at,
                    ),
                ),
            ),
        )


def test_case_e_fingerprints_are_stable_across_input_order() -> None:
    snapshot = _snapshot()
    record = _record(snapshot, 1)
    observation = _observation("Author/Book.epub", snapshot.source_scan_run_id)
    conflicts = tuple(
        CalibreMetadataConflict(
            record.id,
            field_name,
            _tool_result(observation, field_name, calibre_value),
            _tool_result(observation, field_name, embedded_value),
        )
        for field_name, calibre_value, embedded_value in (
            ("title", "Calibre title", "Embedded title"),
            ("language", "de", "en"),
        )
    )
    mapper = CalibreReconciliationMapper()
    first = mapper.map(
        snapshot,
        (record,),
        (),
        (observation,),
        created_at=NOW,
        metadata_conflicts=conflicts,
    )
    second = mapper.map(
        snapshot,
        (record,),
        (),
        (observation,),
        created_at=NOW,
        metadata_conflicts=reversed(conflicts),
    )
    assert [item.finding_fingerprint for item in first.findings] == [
        item.finding_fingerprint for item in second.findings
    ]
    same_material_new_rows = CalibreMetadataConflict(
        record.id,
        "title",
        _tool_result(observation, "title", "Calibre title"),
        _tool_result(observation, "title", "Embedded title"),
    )
    retry = mapper.map(
        snapshot,
        (record,),
        (),
        (observation,),
        created_at=NOW,
        metadata_conflicts=(same_material_new_rows,),
    )
    retry_fingerprint = next(
        item.finding_fingerprint
        for item in retry.findings
        if item.code is CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT
    )
    assert retry_fingerprint in {
        item.finding_fingerprint
        for item in first.findings
        if item.code is CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT
    }

    other_observation = _observation("Other/Book.epub", snapshot.source_scan_run_id)
    other_target = mapper.map(
        snapshot,
        (record,),
        (),
        (observation, other_observation),
        created_at=NOW,
        metadata_conflicts=(
            CalibreMetadataConflict(
                record.id,
                "title",
                _tool_result(other_observation, "title", "Calibre title"),
                _tool_result(other_observation, "title", "Embedded title"),
            ),
        ),
    )
    other_fingerprint = next(
        item.finding_fingerprint
        for item in other_target.findings
        if item.code is CalibreReconciliationFindingCode.CALIBRE_METADATA_CONFLICT
    )
    assert other_fingerprint != retry_fingerprint
