"""Synthetic tests for the pure ADR-0038 signature observer."""

from __future__ import annotations

import json
from itertools import repeat
from pathlib import Path
from typing import Any

import pytest

from foliotone.archive import (
    ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY,
    ARCHIVE_SIGNATURE_PROFILE_V2,
    ArchiveContainerClass,
    ArchiveFormatKind,
    ArchiveListingStatus,
    ArchiveOuterCompressionKind,
    ArchivePublicationKind,
    ArchiveRecognitionStatus,
    ArchiveSignatureObservationV2,
    ArchiveStorageFamily,
    ArchiveSuffixKind,
    group_archive_volume_names,
    observe_archive_signature,
    observe_archive_signature_v2,
)
from foliotone.archive.signatures import (
    ArchiveVolumePartitionFinding,
    partition_archive_volume_names,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "archive" / "v1" / "archive_cases.json"


@pytest.fixture(scope="module")
def cases() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_signature_fixture_cases_are_observed_without_io(cases: dict[str, Any]) -> None:
    signatures = {case["name"]: case for case in cases["signatures"]}
    for name, case in signatures.items():
        header_hex = case["header_hex"] + case.get("tail_padding_hex", "")
        observed = observe_archive_signature(
            f"synthetic{case['suffix']}", bytes.fromhex(header_hex)
        )
        if "expected_format" in case:
            assert observed.format_kind.value == case["expected_format"], name
        if "expected_status" in case:
            assert observed.recognition_status.value == case["expected_status"], name

    assert signatures["epub-basis"]["expected_format"] == "EPUB"
    epub = observe_archive_signature("synthetic.epub", b"PK\x03\x04")
    assert epub.container_class is ArchiveContainerClass.PUBLICATION_CONTAINER
    assert epub.structural_confirmation_required is True
    cbz = observe_archive_signature("synthetic.cbz", b"PK\x03\x04")
    assert cbz.format_kind is ArchiveFormatKind.CBZ
    cbr = observe_archive_signature("synthetic.cbr", b"Rar!\x1a\x07\x00")
    assert cbr.format_kind is ArchiveFormatKind.CBR


@pytest.mark.parametrize(
    ("name", "header", "kind"),
    [
        ("synthetic.tar.gz", b"\x1f\x8b", ArchiveFormatKind.TAR_GZIP),
        ("synthetic.tar.bz2", b"BZh", ArchiveFormatKind.TAR_BZIP2),
        ("synthetic.tar.xz", b"\xfd7zXZ\x00", ArchiveFormatKind.TAR_XZ),
        ("synthetic.tar.zst", b"(\xb5/\xfd", ArchiveFormatKind.TAR_ZSTD),
    ],
)
def test_outer_compression_never_claims_inner_tar(
    name: str, header: bytes, kind: ArchiveFormatKind
) -> None:
    observed = observe_archive_signature(name, header)
    assert observed.format_kind is kind
    assert observed.recognition_status is ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY
    assert observed.structural_confirmation_required is True


def test_unknown_unsupported_mismatch_and_bounds_fail_closed() -> None:
    mismatch = observe_archive_signature("synthetic.zip", b"Rar!\x1a\x07\x00")
    assert mismatch.recognition_status is ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
    unsupported = observe_archive_signature("synthetic.gz", b"\x1f\x8b")
    assert unsupported.recognition_status is ArchiveRecognitionStatus.UNSUPPORTED_FORMAT
    unknown = observe_archive_signature("synthetic.arc", b"\xde\xad\xbe\xef")
    assert unknown.recognition_status is ArchiveRecognitionStatus.UNKNOWN_SIGNATURE
    with pytest.raises(ValueError, match="512"):
        observe_archive_signature("synthetic.zip", b"x" * 513)
    with pytest.raises(ValueError, match="path"):
        observe_archive_signature("private/synthetic.zip", b"PK\x03\x04")


def test_volume_fixture_cases_are_numeric_bounded_and_deterministic(
    cases: dict[str, Any],
) -> None:
    groups = cases["volume_groups"]
    for case in groups:
        observed = group_archive_volume_names(reversed(case["members"]))
        assert observed.status.value == case["expected_status"], case["name"]

    rar = group_archive_volume_names(("book.part02.rar", "book.part01.rar"))
    assert rar.status is ArchiveListingStatus.LISTED
    assert rar.entry_name == "book.part01.rar"
    assert rar.members == ("book.part01.rar", "book.part02.rar")
    split = group_archive_volume_names(("book.zip", "book.z02", "book.z01"))
    assert split.status is ArchiveListingStatus.UNSUPPORTED_FORMAT
    assert split.members == ("book.z01", "book.z02", "book.zip")


@pytest.mark.parametrize(
    "names",
    [
        ("Book.part01.rar", "book.part02.rar"),
        ("book.part1.rar", "book.part02.rar"),
        ("book.7z.001", "book.7z.001"),
        ("book.rar", "book.r00", "other.r01"),
    ],
)
def test_ambiguous_or_inconsistent_volume_names_are_policy_rejected(
    names: tuple[str, ...],
) -> None:
    assert group_archive_volume_names(names).status is ArchiveListingStatus.POLICY_REJECTED


def test_volume_input_is_consumed_only_to_the_documented_bound() -> None:
    observed = group_archive_volume_names(repeat("book.part001.rar"))
    assert observed.status is ArchiveListingStatus.POLICY_REJECTED


def test_volume_partition_is_disjoint_ordered_and_keeps_split_zip_unsupported() -> None:
    observed = partition_archive_volume_names(
        (
            "other.tar",
            "book.part02.rar",
            "split.zip",
            "book.part01.rar",
            "split.z01",
            "single.cbz",
        )
    )
    assert observed.findings == ()
    assert tuple(group.entry_name for group in observed.groups) == (
        "book.part01.rar",
        "other.tar",
        "single.cbz",
        "split.zip",
    )
    split = observed.groups[-1]
    assert split.status is ArchiveListingStatus.UNSUPPORTED_FORMAT
    assert split.members == ("split.z01", "split.zip")


def test_volume_partition_counts_gap_orphan_collision_and_ambiguity() -> None:
    observed = partition_archive_volume_names(
        (
            "gap.7z.001",
            "gap.7z.003",
            "orphan.r00",
            "Case.zip",
            "case.ZIP",
            "mixed.part01.rar",
            "mixed.rar",
        )
    )
    assert observed.groups == ()
    assert observed.findings == (
        ArchiveVolumePartitionFinding.AMBIGUOUS_VOLUME,
        ArchiveVolumePartitionFinding.MISSING_VOLUME,
        ArchiveVolumePartitionFinding.NAME_COLLISION,
        ArchiveVolumePartitionFinding.ORPHAN_VOLUME,
    )


@pytest.mark.parametrize(
    ("name", "header", "publication", "storage", "suffix"),
    [
        (
            "book.epub",
            b"PK\x03\x04",
            ArchivePublicationKind.EPUB,
            ArchiveStorageFamily.ZIP,
            ArchiveSuffixKind.EPUB,
        ),
        (
            "BOOK.CBZ",
            b"PK\x05\x06",
            ArchivePublicationKind.CBZ,
            ArchiveStorageFamily.ZIP,
            ArchiveSuffixKind.CBZ,
        ),
        (
            "book.cbr",
            b"Rar!\x1a\x07\x00",
            ArchivePublicationKind.CBR,
            ArchiveStorageFamily.RAR4,
            ArchiveSuffixKind.CBR,
        ),
        (
            "book.cbr",
            b"Rar!\x1a\x07\x01\x00",
            ArchivePublicationKind.CBR,
            ArchiveStorageFamily.RAR5,
            ArchiveSuffixKind.CBR,
        ),
        (
            "book.zip",
            b"PK\x03\x04",
            ArchivePublicationKind.NONE,
            ArchiveStorageFamily.ZIP,
            ArchiveSuffixKind.ZIP,
        ),
        (
            "book.rar",
            b"Rar!\x1a\x07\x01\x00",
            ArchivePublicationKind.NONE,
            ArchiveStorageFamily.RAR5,
            ArchiveSuffixKind.RAR,
        ),
        (
            "book.7z",
            b"7z\xbc\xaf'\x1c",
            ArchivePublicationKind.NONE,
            ArchiveStorageFamily.SEVEN_Z,
            ArchiveSuffixKind.SEVEN_Z,
        ),
    ],
)
def test_v2_routes_publication_and_storage_as_orthogonal_axes(
    name: str,
    header: bytes,
    publication: ArchivePublicationKind,
    storage: ArchiveStorageFamily,
    suffix: ArchiveSuffixKind,
) -> None:
    observed = observe_archive_signature_v2(name, header)
    assert observed.profile == ARCHIVE_SIGNATURE_PROFILE_V2
    assert observed.compatibility == ARCHIVE_PUBLICATION_STORAGE_COMPATIBILITY
    assert observed.publication_kind is publication
    assert observed.storage_family is storage
    assert observed.suffix_kind is suffix
    assert observed.outer_compression_kind is ArchiveOuterCompressionKind.NONE
    assert observed.recognition_status is ArchiveRecognitionStatus.MATCHED


def test_v2_routes_tar_wrappers_and_mismatches_without_guessing(
    cases: dict[str, Any],
) -> None:
    tar_case = next(
        case for case in cases["signatures"] if case["name"] == "tar-header-only"
    )
    tar_header = bytes.fromhex(tar_case["header_hex"] + tar_case["tail_padding_hex"])
    tar = observe_archive_signature_v2("book.tar", tar_header)
    assert tar.storage_family is ArchiveStorageFamily.TAR
    assert tar.recognition_status is ArchiveRecognitionStatus.MATCHED

    gzip = observe_archive_signature_v2("book.tar.gz", b"\x1f\x8b")
    assert gzip.storage_family is ArchiveStorageFamily.UNKNOWN
    assert gzip.outer_compression_kind is ArchiveOuterCompressionKind.GZIP
    assert gzip.recognition_status is ArchiveRecognitionStatus.OUTER_COMPRESSION_ONLY

    mismatch = observe_archive_signature_v2("book.gz", b"PK\x03\x04")
    assert mismatch.storage_family is ArchiveStorageFamily.ZIP
    assert mismatch.suffix_kind is ArchiveSuffixKind.UNSUPPORTED
    assert mismatch.recognition_status is ArchiveRecognitionStatus.SIGNATURE_SUFFIX_MISMATCH
    unsupported = observe_archive_signature_v2("book.exe", b"\x1f\x8b")
    assert unsupported.recognition_status is ArchiveRecognitionStatus.UNSUPPORTED_FORMAT
    assert unsupported.container_class is ArchiveContainerClass.UNSUPPORTED_CONTAINER
    unsupported_gzip = observe_archive_signature_v2("book.gz", b"\x1f\x8b")
    assert unsupported_gzip.container_class is ArchiveContainerClass.UNSUPPORTED_CONTAINER
    unknown = observe_archive_signature_v2("book.bin", b"unknown")
    assert unknown.recognition_status is ArchiveRecognitionStatus.UNKNOWN_SIGNATURE


def test_v2_constructor_rejects_cross_axis_inventions() -> None:
    valid = observe_archive_signature_v2("book.epub", b"PK\x03\x04")
    assert "book.epub" not in repr(valid)
    with pytest.raises(ValueError):
        ArchiveSignatureObservationV2(
            profile=valid.profile,
            compatibility=valid.compatibility,
            container_class=valid.container_class,
            suffix_kind=valid.suffix_kind,
            publication_kind=valid.publication_kind,
            storage_family=ArchiveStorageFamily.RAR5,
            outer_compression_kind=valid.outer_compression_kind,
            recognition_status=valid.recognition_status,
            inspected_bytes=valid.inspected_bytes,
            structural_confirmation_required=valid.structural_confirmation_required,
        )
