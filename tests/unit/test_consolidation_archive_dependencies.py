from __future__ import annotations

from dataclasses import replace

import pytest

from foliotone.archive.signatures import (
    ArchiveContainerClass,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveStorageFamily,
)
from foliotone.consolidation import (
    ARCHIVE_OBSERVATION_PROFILE,
    ARCHIVE_OBSERVATION_SNAPSHOT_KIND,
    MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS,
    ArchiveDependencyProjectionInputs,
    ArchiveSourceDependencyBinding,
    ConsolidationDependencyKind,
    ConsolidationDependencyState,
    ConsolidationFileRole,
    build_archive_dependency,
)
from foliotone.core import EntityId


def _id(value: int) -> EntityId:
    return EntityId.parse(f"00000000-0000-4000-8000-{value:012d}")


def _binding(
    *,
    observation: int = 10,
    ordinal: int = 0,
    publication: ArchivePublicationKind = ArchivePublicationKind.NONE,
    container: ArchiveContainerClass = ArchiveContainerClass.GENERIC_ARCHIVE,
    storage: ArchiveStorageFamily = ArchiveStorageFamily.ZIP,
    outer: ArchiveOuterCompressionKind = ArchiveOuterCompressionKind.NONE,
    recognition: ArchiveRecognitionStatus = ArchiveRecognitionStatus.MATCHED,
    content_hash: str = "a" * 64,
) -> ArchiveSourceDependencyBinding:
    return ArchiveSourceDependencyBinding(
        archive_observation_id=_id(observation),
        file_observation_id=_id(1),
        scan_root_id=_id(2),
        source_scan_run_id=_id(3),
        source_ordinal=ordinal,
        container_class=container,
        publication_kind=publication,
        storage_family=storage,
        outer_compression_kind=outer,
        recognition_status=recognition,
        archive_content_hash=content_hash,
    )


def _inputs(
    bindings: tuple[ArchiveSourceDependencyBinding, ...] = (),
) -> ArchiveDependencyProjectionInputs:
    return ArchiveDependencyProjectionInputs(
        file_role=ConsolidationFileRole.CANDIDATE,
        file_observation_id=_id(1),
        scan_root_id=_id(2),
        source_scan_run_id=_id(3),
        bindings=bindings,
    )


def test_empty_evidence_projects_unknown_without_snapshot() -> None:
    dependency = build_archive_dependency(_inputs())

    assert dependency.kind is ConsolidationDependencyKind.ARCHIVE
    assert dependency.state is ConsolidationDependencyState.UNKNOWN
    assert dependency.snapshot_kind is None
    assert dependency.snapshot_id is None


@pytest.mark.parametrize(
    ("binding", "expected_id"),
    [
        (_binding(), _id(10)),
        (
            _binding(
                storage=ArchiveStorageFamily.UNKNOWN,
                outer=ArchiveOuterCompressionKind.GZIP,
                recognition=ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY,
            ),
            _id(10),
        ),
        (
            _binding(recognition=ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH),
            _id(10),
        ),
    ],
)
def test_generic_direct_and_wrapper_sources_project_known_present(
    binding: ArchiveSourceDependencyBinding, expected_id: EntityId
) -> None:
    dependency = build_archive_dependency(_inputs((binding,)))

    assert dependency.state is ConsolidationDependencyState.KNOWN_PRESENT
    assert dependency.snapshot_kind == ARCHIVE_OBSERVATION_SNAPSHOT_KIND
    assert dependency.snapshot_id == expected_id


def test_publication_container_remains_unknown() -> None:
    publication = _binding(
        publication=ArchivePublicationKind.EPUB,
        container=ArchiveContainerClass.PUBLICATION_CONTAINER,
    )

    dependency = build_archive_dependency(_inputs((publication,)))

    assert dependency.state is ConsolidationDependencyState.UNKNOWN
    assert dependency.snapshot_id is None


def test_unsupported_and_unknown_shapes_remain_unknown() -> None:
    unsupported = _binding(
        container=ArchiveContainerClass.UNSUPPORTED_CONTAINER,
        storage=ArchiveStorageFamily.UNKNOWN,
        recognition=ArchiveRecognitionStatus.UNSUPPORTED_FORMAT,
    )
    unknown = _binding(
        observation=11,
        container=ArchiveContainerClass.UNKNOWN_CONTAINER,
        storage=ArchiveStorageFamily.UNKNOWN,
        recognition=ArchiveRecognitionStatus.UNKNOWN_SIGNATURE,
        content_hash="b" * 64,
    )

    dependency = build_archive_dependency(_inputs((unsupported, unknown)))

    assert dependency.state is ConsolidationDependencyState.UNKNOWN
    assert dependency.snapshot_id is None


def test_unknown_fingerprint_is_independent_of_ignored_publication_evidence() -> None:
    publication = _binding(
        publication=ArchivePublicationKind.CBZ,
        container=ArchiveContainerClass.PUBLICATION_CONTAINER,
    )

    assert build_archive_dependency(_inputs()).material_fingerprint == (
        build_archive_dependency(_inputs((publication,))).material_fingerprint
    )


def test_material_fingerprint_is_bound_to_role_and_archive_content() -> None:
    first = build_archive_dependency(_inputs((_binding(),)))
    changed_hash = build_archive_dependency(
        _inputs((_binding(content_hash="b" * 64),))
    )
    keeper = build_archive_dependency(
        replace(_inputs((_binding(),)), file_role=ConsolidationFileRole.KEEPER)
    )

    assert first.material_fingerprint != changed_hash.material_fingerprint
    assert first.material_fingerprint != keeper.material_fingerprint
    assert (
        first.material_fingerprint
        == "87911a19c189210d30b796126e94c7e715571a1362da4747382962f194d772a8"
    )


def test_ambiguous_and_conflicting_evidence_fails_closed() -> None:
    publication = _binding(
        observation=11,
        publication=ArchivePublicationKind.CBR,
        container=ArchiveContainerClass.PUBLICATION_CONTAINER,
        storage=ArchiveStorageFamily.RAR4,
        content_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="ambiguous"):
        build_archive_dependency(_inputs((_binding(), _binding(observation=11))))
    with pytest.raises(ValueError, match="conflict"):
        build_archive_dependency(_inputs((_binding(), publication)))


def test_inputs_reject_foreign_lineage_duplicates_and_excess() -> None:
    binding = _binding()
    with pytest.raises(ValueError, match="lineage"):
        _inputs((replace(binding, scan_root_id=_id(99)),))
    with pytest.raises(ValueError, match="unique"):
        _inputs((binding, binding))
    with pytest.raises(ValueError, match="bound"):
        _inputs(
            tuple(
                _binding(observation=100 + value, content_hash=f"{value + 1:064x}")
                for value in range(MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS + 1)
            )
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_ordinal": True},
        {"archive_content_hash": "A" * 64},
        {"archive_profile": "archive-observation/v2"},
        {"container_class": ArchiveContainerClass.PUBLICATION_CONTAINER},
    ],
)
def test_binding_rejects_invalid_contract_shapes(mutation: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_binding(), **mutation)


def test_repr_does_not_expose_archive_content_hash_or_binding_tuple() -> None:
    binding = _binding(content_hash="c" * 64)

    assert "c" * 64 not in repr(binding)
    assert "ArchiveSourceDependencyBinding" not in repr(_inputs((binding,)))
    assert binding.archive_profile == ARCHIVE_OBSERVATION_PROFILE
