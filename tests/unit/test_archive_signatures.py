"""Synthetic tests for the pure ADR-0038 signature observer."""

from __future__ import annotations

import json
from itertools import repeat
from pathlib import Path
from typing import Any

import pytest

from foliotone.archive import (
    ArchiveContainerClass,
    ArchiveFormatKind,
    ArchiveListingStatus,
    ArchiveRecognitionStatus,
    group_archive_volume_names,
    observe_archive_signature,
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
