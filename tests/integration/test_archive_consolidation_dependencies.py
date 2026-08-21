"""Synthetic bounded archive dependency query and store integration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, insert

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
)
from foliotone.consolidation import (
    CONSOLIDATION_PLAN_PROFILE,
    CONSOLIDATION_PLAN_SERIALIZER_VERSION,
    CONSOLIDATION_PLAN_VERSION,
    ArchiveDependencyProjectionInputs,
    ConsolidationBlocker,
    ConsolidationBlockerCode,
    ConsolidationDependency,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationExecutionState,
    ConsolidationFileEndpoint,
    ConsolidationFileRole,
    ConsolidationPlan,
    ConsolidationPlanStatus,
    build_archive_dependency,
    consolidation_candidate_physical_preconditions,
    consolidation_plan_content_hash,
)
from foliotone.core import (
    EntityId,
    FileObservation,
    FileRecord,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
)
from foliotone.persistence import (
    create_sqlite_engine,
    repository,
    schema,
)
from foliotone.persistence._mapping import datetime_to_db
from foliotone.persistence.archive import (
    ARCHIVE_OBSERVATION_PROFILE,
    ArchiveEvidenceSource,
    ArchiveEvidenceStoreError,
    SQLiteArchiveEvidenceStore,
    _archive_content_fingerprint,
    _content_hash_material,
    _insert_graph,
    _PersistedArchiveEvidenceGraph,
    _row_tuple,
    _volume_group_fingerprint,
)
from foliotone.persistence.consolidation import (
    ConsolidationStoreError,
    SQLiteConsolidationStore,
)

NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("00000000-0000-4000-8000-000000000001")
RUN_ID = EntityId.parse("00000000-0000-4000-8000-000000000002")
FULL_SHA256 = "f" * 64
IMAGE_REFERENCE = (
    "ghcr.io/gecompat/foliotone-archive-7zip@sha256:"
    "26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)


def _id(value: int) -> EntityId:
    return EntityId.parse(f"00000000-0000-4000-8000-{value:012d}")


def _lineage(engine: Engine, count: int) -> tuple[tuple[EntityId, EntityId], ...]:
    root = ScanRoot(ROOT_ID, "synthetic-archive-dependency", MediaType.EBOOK)
    run = ScanRun(RUN_ID, ROOT_ID, NOW, ScanRunStatus.COMPLETED, completed_at=NOW)
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(run)
    values: list[tuple[EntityId, EntityId]] = []
    for ordinal in range(count):
        file_id = _id(100 + ordinal)
        observation_id = _id(200 + ordinal)
        relative_path = f"synthetic-{ordinal}.bin"
        repository(engine, FileRecord).save(
            FileRecord(
                file_id,
                ROOT_ID,
                relative_path,
                10,
                NOW,
                MediaType.EBOOK,
                PresenceState.PRESENT,
                NOW,
                NOW,
            )
        )
        repository(engine, FileObservation).save(
            FileObservation(
                observation_id,
                file_id,
                RUN_ID,
                relative_path,
                10,
                NOW,
                NOW,
            )
        )
        with engine.begin() as connection:
            connection.execute(
                insert(schema.fingerprints).values(
                    id=str(_id(300 + ordinal)),
                    target_kind="FILE_OBSERVATION",
                    target_id=str(observation_id),
                    kind="FILE_SHA256",
                    algorithm="sha256",
                    algorithm_version="1",
                    value=FULL_SHA256,
                    created_at=datetime_to_db(NOW),
                )
            )
        values.append((file_id, observation_id))
    return tuple(values)


def _archive_graph(
    engine: Engine,
    observation_id: EntityId,
    sources: tuple[EntityId, ...],
    *,
    container: ArchiveContainerClass = ArchiveContainerClass.GENERIC_ARCHIVE,
    publication: ArchivePublicationKind = ArchivePublicationKind.NONE,
    storage: ArchiveStorageFamily = ArchiveStorageFamily.ZIP,
    outer: ArchiveOuterCompressionKind = ArchiveOuterCompressionKind.NONE,
    recognition: ArchiveRecognitionStatus = ArchiveRecognitionStatus.MATCHED,
) -> None:
    evidence_sources = tuple(
        ArchiveEvidenceSource(
            source_id,
            FULL_SHA256,
            10,
            "archive" if ordinal == 0 else f"archive.{ordinal:03d}",
        )
        for ordinal, source_id in enumerate(sources)
    )
    source_rows = tuple(
        _row_tuple(
            {
                "archive_observation_id": str(observation_id),
                "source_ordinal": ordinal,
                "file_observation_id": str(source.file_observation_id),
                "source_full_sha256": source.full_sha256,
                "source_size_bytes": source.size_bytes,
                "staging_name": source.staging_name,
            }
        )
        for ordinal, source in enumerate(evidence_sources)
    )
    wrapper = None
    if recognition is ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY:
        wrapper = _row_tuple(
            {
                "archive_observation_id": str(observation_id),
                "profile": "archive-7zip-wrapper-provider/v1",
                "inner_storage_family": "TAR",
                "inner_stream_size_bytes": None,
                "inner_stream_sha256": None,
                "frame_profile": "archive-tar-stream-frame/v1",
                "wrapper_runner_profile": "archive-wrapper-container-runner/v1",
                "image_reference": IMAGE_REFERENCE,
                "wrapper_command_identity": "1" * 64,
                "listing_command_identity": "2" * 64,
                "integrity_command_identity": "3" * 64,
            }
        )
    parent: dict[str, object] = {
        "id": str(observation_id),
        "profile": ARCHIVE_OBSERVATION_PROFILE,
        "content_hash": "",
        "scan_root_id": str(ROOT_ID),
        "source_scan_run_id": str(RUN_ID),
        "observed_at": datetime_to_db(NOW),
        "archive_full_sha256": FULL_SHA256,
        "archive_content_fingerprint": _archive_content_fingerprint(evidence_sources),
        "volume_group_fingerprint": _volume_group_fingerprint(evidence_sources),
        "signature_profile": "archive-signature-observer/v2",
        "compatibility_profile": "archive-publication-storage-compatibility/v1",
        "container_class": container.value,
        "suffix_kind": "EPUB" if publication is ArchivePublicationKind.EPUB else "ZIP",
        "publication_kind": publication.value,
        "storage_family": storage.value,
        "outer_compression_kind": outer.value,
        "recognition_status": recognition.value,
        "inspected_bytes": 8,
        "structural_confirmation_required": False,
        "provider_profile": (
            "archive-7zip-wrapper-provider/v1"
            if wrapper is not None
            else "archive-7zip-provider/v1"
        ),
        "runner_profile": (
            "archive-wrapper-container-runner/v1"
            if wrapper is not None
            else "archive-linux-container-runner/v1"
        ),
        "parser_profile": "archive-7zip-slt-parser/v3",
        "parser_status": None,
        "format_case_kind": None,
        "format_lock_profile": "archive-7zip-format-lock/v1",
        "format_lock_sha256": (
            "4270fbf6ba7782c3b2fb1025137581ce07a1bc271664e19692dce388a617e061"
        ),
        "listing_profile": "archive-listing/v1",
        "integrity_profile": "archive-integrity/v1",
        "extraction_profile": "archive-extraction/v1",
        "safety_profile": "archive-safety-policy/v1",
        "secret_version": "NONE",
        "listing_status": "NOT_ATTEMPTED",
        "encryption_status": "UNKNOWN",
        "integrity_status": "NOT_TESTED",
        "extraction_status": "NOT_ATTEMPTED",
        "password_attempt_status": "NOT_ATTEMPTED",
        "extraction_policy_status": "POLICY_REJECTED",
        "member_count": 0,
        "writer_owner_kind": "EBOOK_ANALYSIS",
        "writer_owner_run_id": str(_id(900)),
        "writer_fence_epoch": 1,
    }
    parent["content_hash"] = _content_hash_material(
        parent, source_rows, (), (), wrapper
    )
    graph = _PersistedArchiveEvidenceGraph(
        _row_tuple(parent), source_rows, (), (), wrapper
    )
    with engine.begin() as connection:
        _insert_graph(connection, graph)


def _endpoint(
    role: ConsolidationFileRole, file_id: EntityId, observation_id: EntityId
) -> ConsolidationFileEndpoint:
    return ConsolidationFileEndpoint(
        role,
        file_id,
        observation_id,
        ROOT_ID,
        RUN_ID,
        PresenceState.PRESENT,
        FULL_SHA256,
        10,
        NOW,
        NOW,
        "EPUB",
    )


def test_query_projects_direct_volume_wrapper_and_publication_evidence(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    lineage = _lineage(engine, 5)
    cases = (
        ({}, (lineage[0][1],), True),
        (
            {"storage": ArchiveStorageFamily.RAR4},
            (lineage[1][1], lineage[2][1]),
            True,
        ),
        (
            {
                "storage": ArchiveStorageFamily.UNKNOWN,
                "outer": ArchiveOuterCompressionKind.GZIP,
                "recognition": ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY,
            },
            (lineage[3][1],),
            True,
        ),
        (
            {
                "container": ArchiveContainerClass.PUBLICATION_CONTAINER,
                "publication": ArchivePublicationKind.EPUB,
            },
            (lineage[4][1],),
            False,
        ),
    )
    for ordinal, (changes, sources, expected_present) in enumerate(cases):
        _archive_graph(engine, _id(500 + ordinal), sources, **changes)
        bindings = SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
            (sources[0],), ROOT_ID, RUN_ID
        )
        dependency = build_archive_dependency(
            ArchiveDependencyProjectionInputs(
                ConsolidationFileRole.CANDIDATE,
                sources[0],
                ROOT_ID,
                RUN_ID,
                bindings,
            )
        )
        assert (
            dependency.snapshot_id is not None
        ) is expected_present
    with pytest.raises(ValueError, match="scope"):
        SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
            (lineage[0][1], lineage[1][1], lineage[2][1]), ROOT_ID, RUN_ID
        )
    with engine.begin() as connection:
        connection.execute(
            delete(schema.fingerprints).where(
                schema.fingerprints.c.target_id == str(lineage[0][1])
            )
        )
    with pytest.raises(ArchiveEvidenceStoreError, match="lineage"):
        SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
            (lineage[0][1],), ROOT_ID, RUN_ID
        )
    with pytest.raises(ArchiveEvidenceStoreError, match="endpoint lineage"):
        SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
            (_id(999),), ROOT_ID, RUN_ID
        )
    engine.dispose()


def test_consolidation_store_revalidates_archive_dependency_material(
    head_database: Path,
) -> None:
    engine = create_sqlite_engine(head_database)
    keeper, candidate = _lineage(engine, 2)
    _archive_graph(engine, _id(599), (keeper[1],))
    _archive_graph(engine, _id(600), (candidate[1],))
    bindings = SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
        (candidate[1],), ROOT_ID, RUN_ID
    )
    dependency = build_archive_dependency(
        ArchiveDependencyProjectionInputs(
            ConsolidationFileRole.CANDIDATE,
            candidate[1],
            ROOT_ID,
            RUN_ID,
            bindings,
        )
    )
    keeper_archive = build_archive_dependency(
        ArchiveDependencyProjectionInputs(
            ConsolidationFileRole.KEEPER,
            keeper[1],
            ROOT_ID,
            RUN_ID,
            SQLiteArchiveEvidenceStore(engine).list_source_dependency_bindings(
                (keeper[1],), ROOT_ID, RUN_ID
            ),
        )
    )
    dependencies = (
        ConsolidationDependency(
            ConsolidationFileRole.KEEPER,
            ConsolidationDependencyKind.CALIBRE,
            ConsolidationDependencyState.KNOWN_NONE,
            "1" * 64,
        ),
        ConsolidationDependency(
            ConsolidationFileRole.KEEPER,
            ConsolidationDependencyKind.SIDECAR,
            ConsolidationDependencyState.KNOWN_NONE,
            "2" * 64,
        ),
        keeper_archive,
        ConsolidationDependency(
            ConsolidationFileRole.CANDIDATE,
            ConsolidationDependencyKind.CALIBRE,
            ConsolidationDependencyState.KNOWN_NONE,
            "3" * 64,
        ),
        ConsolidationDependency(
            ConsolidationFileRole.CANDIDATE,
            ConsolidationDependencyKind.SIDECAR,
            ConsolidationDependencyState.KNOWN_NONE,
            "4" * 64,
        ),
        dependency,
    )
    keeper_endpoint = _endpoint(ConsolidationFileRole.KEEPER, *keeper)
    candidate_endpoint = _endpoint(ConsolidationFileRole.CANDIDATE, *candidate)
    preconditions = consolidation_candidate_physical_preconditions(
        (keeper_endpoint, candidate_endpoint), dependencies
    )
    plan = ConsolidationPlan(
        id=_id(700),
        profile=CONSOLIDATION_PLAN_PROFILE,
        plan_version=CONSOLIDATION_PLAN_VERSION,
        serializer_version=CONSOLIDATION_PLAN_SERIALIZER_VERSION,
        scan_root_id=ROOT_ID,
        source_scan_run_id=RUN_ID,
        identity=None,
        keeper=keeper_endpoint,
        candidate=candidate_endpoint,
        keep_preference=None,
        consolidation_candidate=None,
        dependencies=dependencies,
        quality_evidence=(),
        required_reviews=(),
        preconditions=preconditions,
        future_operation_intents=(),
        blockers=(
            ConsolidationBlocker(ConsolidationBlockerCode.ARCHIVE_MEMBERSHIP_PRESENT),
        ),
        status=ConsolidationPlanStatus.BLOCKED,
        execution_state=ConsolidationExecutionState.NOT_EXECUTABLE,
        content_hash="0" * 64,
        created_at=NOW,
    )
    plan = replace(plan, content_hash=consolidation_plan_content_hash(plan))
    with engine.connect() as connection:
        SQLiteConsolidationStore._validate_plan_lineage(connection, plan)

    corrupted = replace(
        plan,
        id=_id(701),
        dependencies=dependencies[:-1]
        + (replace(dependency, material_fingerprint="e" * 64),),
        content_hash="0" * 64,
    )
    corrupted = replace(
        corrupted, content_hash=consolidation_plan_content_hash(corrupted)
    )
    with pytest.raises(ConsolidationStoreError, match="persisted evidence"):
        with engine.connect() as connection:
            SQLiteConsolidationStore._validate_plan_lineage(connection, corrupted)
    engine.dispose()
