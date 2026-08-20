from __future__ import annotations

import json
from pathlib import Path

import pytest

from foliotone.archive.sevenzip import (
    ARCHIVE_7ZIP_TOOL_MANIFEST,
    ARCHIVE_IMAGE_REFERENCE,
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    ArchiveImageBootstrapLockedLock,
    ArchiveImageBootstrapPendingLock,
    ArchiveSevenZipRuntimeAvailability,
    archive_7zip_capabilities,
    archive_7zip_runtime_availability,
    build_7zzs_extraction_command,
    build_7zzs_information_command,
    build_7zzs_integrity_command,
    build_7zzs_listing_command,
    load_archive_image_lock,
    parse_7zzs_information_output,
)
from foliotone.core.enums import ToolCapability


def test_only_fixed_read_only_argv_shapes_and_archive_capabilities_are_exposed() -> None:
    assert archive_7zip_capabilities() == frozenset(
        {
            ToolCapability.ARCHIVE_LISTING,
            ToolCapability.ARCHIVE_INTEGRITY,
            ToolCapability.ARCHIVE_EXTRACTION,
        }
    )
    assert build_7zzs_information_command() == ("/usr/local/bin/7zzs", "i")
    assert build_7zzs_listing_command() == (
        "/usr/local/bin/7zzs", "l", "-slt", "-ba", "-bd", "-bb0", "-bso1", "-bse2",
        "-bsp0", "-sccUTF-8", "--", "/workspace/input/archive",
    )
    assert build_7zzs_integrity_command() == (
        "/usr/local/bin/7zzs", "t", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0",
        "-sccUTF-8", "-mmt=1", "--", "/workspace/input/archive",
    )
    assert build_7zzs_extraction_command() == (
        "/usr/local/bin/7zzs", "x", "-y", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0",
        "-sccUTF-8", "-mmt=1", "-o/workspace/output", "--", "/workspace/input/archive",
    )
    commands = (
        build_7zzs_listing_command(),
        build_7zzs_integrity_command(),
        build_7zzs_extraction_command(),
    )
    for command in commands:
        assert "-p" not in command
        assert not any(argument.startswith("-p") for argument in command)
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.accepted_exit_codes == frozenset({0})
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.network_enabled is False
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.listing_profile == "archive-listing/v1"
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.integrity_profile == "archive-integrity/v1"
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.extraction_profile == "archive-extraction/v1"


def test_information_parser_accepts_only_bounded_exact_7zzs_2602_output() -> None:
    valid = (
        b"\n7-Zip (z) 26.02 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-06-25\n"
        b"\nFormats:\n  C   F         7z       7z            7 z BC AF ' 1C\n"
    )
    assert parse_7zzs_information_output([valid[:17], valid[17:]]) is True
    assert parse_7zzs_information_output([valid.replace(b"26.02", b"26.01")]) is False
    assert parse_7zzs_information_output([b"x" * 262_145]) is False


def test_runtime_stays_fail_closed_until_all_post_merge_evidence_is_verified(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "lock.json"
    template_path = (
        Path(__file__).parents[2]
        / "packaging"
        / "archive"
        / "7zip-26.02"
        / "archive-image.lock.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    lock.write_text(json.dumps(template), encoding="utf-8")
    assert isinstance(load_archive_image_lock(lock), ArchiveImageBootstrapLockedLock)
    unavailable = archive_7zip_runtime_availability(lock)
    assert (unavailable.profile, unavailable.available, unavailable.reason) == (
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE, False, "TOOL_UNAVAILABLE",
    )
    digest = template["runtime_platform_manifest_digest"]
    pending = dict(template)
    pending["state"] = "BOOTSTRAP_PENDING"
    for field in (
        "runtime_platform_manifest_digest",
        "runtime_config_digest",
        "runtime_rootfs_layer_digest",
        "runtime_rootfs_diff_id",
        "runtime_workdir_layer_digest",
        "runtime_workdir_diff_id",
    ):
        pending[field] = "UNVERIFIED"
    for field in (
        "runtime_platform_manifest_size_bytes",
        "runtime_config_size_bytes",
        "runtime_rootfs_layer_size_bytes",
        "runtime_workdir_layer_size_bytes",
    ):
        pending[field] = 0
    lock.write_text(json.dumps(pending), encoding="utf-8")
    assert isinstance(load_archive_image_lock(lock), ArchiveImageBootstrapPendingLock)
    still_unavailable = archive_7zip_runtime_availability(lock)
    assert still_unavailable.available is False
    pending["published_public_source_associated"] = True
    lock.write_text(json.dumps(pending), encoding="utf-8")
    assert load_archive_image_lock(lock) is None
    with pytest.raises(ValueError):
        ArchiveSevenZipRuntimeAvailability(
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE, True, "AVAILABLE", None
        )
    available = ArchiveSevenZipRuntimeAvailability(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        True,
        "AVAILABLE",
        f"{ARCHIVE_IMAGE_REFERENCE}@{digest}",
    )
    assert available.image_reference is not None
