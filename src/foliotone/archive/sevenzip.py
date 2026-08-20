"""Fixed, read-only 7-Zip command and runtime-identity contracts.

This module deliberately does not start a process.  The later container runner
may use only these command shapes after its separate staging and sandbox
preflight has succeeded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from foliotone.core.enums import ToolCapability

ARCHIVE_7ZIP_PROVIDER_ID: Final = "archive-7zip"
ARCHIVE_7ZIP_ADAPTER_VERSION: Final = "archive-7zip-cli/1"
ARCHIVE_7ZIP_TOOL_VERSION: Final = "26.02"
ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE: Final = "archive-linux-container-runner/v1"
ARCHIVE_IMAGE_LOCK_PROFILE: Final = "archive-image-lock/v1"
ARCHIVE_IMAGE_REFERENCE: Final = "ghcr.io/gecompat/foliotone-archive-7zip"
ARCHIVE_LISTING_PROFILE: Final = "archive-listing/v1"
ARCHIVE_INTEGRITY_PROFILE: Final = "archive-integrity/v1"
ARCHIVE_EXTRACTION_PROFILE: Final = "archive-extraction/v1"
MAX_INFORMATION_OUTPUT_BYTES: Final = 1_048_576
MAX_INFORMATION_LINE_BYTES: Final = 4_096
_CONTAINER_7ZZS: Final = "/usr/local/bin/7zzs"
_CONTAINER_ARCHIVE: Final = "/workspace/input/archive"
_CONTAINER_OUTPUT: Final = "/workspace/output"
_DIGEST_RE: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LOCK_FIXED_VALUES: Final = {
    "profile": ARCHIVE_IMAGE_LOCK_PROFILE,
    "recipe_profile": "archive-7zip-image/v1",
    "version": "26.02",
    "platform": "linux/amd64",
    "base_kind": "SCRATCH",
    "base_reference": "scratch",
    "base_digest": "NONE",
    "upstream_url": "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-linux-x64.tar.xz",
    "upstream_size_bytes": 1_571_416,
    "upstream_sha256": "41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e",
    "release_tag_commit": "f9d78aff31a5f2521ae7ddbdc97c4a8855808959",
    "signature_status": "UNSIGNED_UPSTREAM_RELEASE",
    "executable_member_name": "7zzs",
    "executable_member_size_bytes": 3_763_320,
    "executable_member_sha256": "20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453",
    "executable_image_path": "/usr/local/bin/7zzs",
    "binary_tar_license_member_name": "License.txt",
    "binary_tar_license_size_bytes": 6_029,
    "binary_tar_license_sha256": "1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1",
    "binary_tar_readme_member_name": "readme.txt",
    "binary_tar_readme_size_bytes": 3_863,
    "binary_tar_readme_sha256": "c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0",
    "source_tar_url": "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-src.tar.xz",
    "source_tar_size_bytes": 1_543_480,
    "source_tar_sha256": "cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd",
    "source_copying_url": "https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/copying.txt",
    "source_copying_sha256": "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
    "source_unrar_license_url": (
        "https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/unRarLicense.txt"
    ),
    "source_unrar_license_sha256": (
        "17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976"
    ),
    "image_user": "65532:65532",
    "image_uid": 65_532,
    "image_gid": 65_532,
    "source_date_epoch": 1_782_345_600,
    "build_profile": "archive-image-build/v1",
    "build_platform": "linux/amd64",
    "build_network": "none",
    "build_no_cache": True,
    "buildx_version": "v0.36.1",
    "buildx_linux_amd64_asset_url": (
        "https://github.com/docker/buildx/releases/download/v0.36.1/"
        "buildx-v0.36.1.linux-amd64"
    ),
    "buildx_linux_amd64_asset_size_bytes": 65_302_690,
    "buildx_linux_amd64_asset_sha256": (
        "48af8a397ebd60178778bf63611dbcebe5f5e7a9be90eb9147b24b9587455778"
    ),
    "buildkit_version": "v0.32.2",
    "buildkit_image_index_digest": (
        "sha256:28a898719c18a33f4e8000685287fa36fd0dd9560c6440227d3a732d79bb41d8"
    ),
    "buildkit_linux_amd64_manifest_digest": (
        "sha256:040d34121c27906c4ff9ac152a30d52bf2c5d328d3bb748916bb3d2743c02528"
    ),
}
_LOCK_BUILD_OUTPUT: Final = {
    "oci_mediatypes": True,
    "compression": "gzip",
    "force_compression": True,
    "rewrite_timestamp": True,
    "provenance": False,
    "sbom": False,
}
_LOCK_CONTENT_HASHES: Final = {
    "dockerfile_sha256": "9ab4f5c5895db715366e2d15b7301abef525bc74ab62884424860ff0231bfe9a",
    "rootfs_tar_sha256": "a817c489a8458dae30df188380b3c0d4e59baad77bfa1a7bd385c4ec016538fc",
    "sbom_sha256": "ce32dada7227c05e147280404b3d0ce0304eba5e6e085c644f7ac4cb0ddf5a9f",
}
_LOCK_DYNAMIC_FIELDS: Final = {
    "state",
    "runtime_platform_manifest_digest",
    "runtime_platform_manifest_size_bytes",
    "runtime_config_digest",
    "runtime_config_size_bytes",
    "runtime_rootfs_layer_digest",
    "runtime_rootfs_layer_size_bytes",
    "runtime_rootfs_diff_id",
    "runtime_workdir_layer_digest",
    "runtime_workdir_layer_size_bytes",
    "runtime_workdir_diff_id",
}
_LOCK_STAGE1_IDENTITY: Final = {
    "runtime_platform_manifest_digest": (
        "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
    ),
    "runtime_platform_manifest_size_bytes": 838,
    "runtime_config_digest": (
        "sha256:6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f"
    ),
    "runtime_config_size_bytes": 1_185,
    "runtime_rootfs_layer_digest": (
        "sha256:ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f"
    ),
    "runtime_rootfs_layer_size_bytes": 3_298_569,
    "runtime_rootfs_diff_id": (
        "sha256:b2af5e745f24985c459fd49b2191807b36364540d53d472db3620e0b4cfc024e"
    ),
    "runtime_workdir_layer_digest": (
        "sha256:4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1"
    ),
    "runtime_workdir_layer_size_bytes": 32,
    "runtime_workdir_diff_id": (
        "sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef"
    ),
}


class ArchiveImageLockState(StrEnum):
    BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
    BOOTSTRAP_LOCKED = "BOOTSTRAP_LOCKED"


@dataclass(frozen=True, slots=True)
class ArchiveImageBootstrapPendingLock:
    state: ArchiveImageLockState = ArchiveImageLockState.BOOTSTRAP_PENDING


@dataclass(frozen=True, slots=True)
class ArchiveImageBootstrapLockedLock:
    runtime_platform_manifest_digest: str
    runtime_platform_manifest_size_bytes: int
    runtime_config_digest: str
    runtime_config_size_bytes: int
    runtime_rootfs_layer_digest: str
    runtime_rootfs_layer_size_bytes: int
    runtime_rootfs_diff_id: str
    runtime_workdir_layer_digest: str
    runtime_workdir_layer_size_bytes: int
    runtime_workdir_diff_id: str
    state: ArchiveImageLockState = ArchiveImageLockState.BOOTSTRAP_LOCKED

    def __post_init__(self) -> None:
        if not all(
            _DIGEST_RE.fullmatch(value) is not None
            for value in (
                self.runtime_platform_manifest_digest,
                self.runtime_config_digest,
                self.runtime_rootfs_layer_digest,
                self.runtime_rootfs_diff_id,
                self.runtime_workdir_layer_digest,
                self.runtime_workdir_diff_id,
            )
        ):
            raise ValueError("locked OCI identities must be sha256 digests")
        if any(
            type(value) is not int or value <= 0
            for value in (
                self.runtime_platform_manifest_size_bytes,
                self.runtime_config_size_bytes,
                self.runtime_rootfs_layer_size_bytes,
                self.runtime_workdir_layer_size_bytes,
            )
        ):
            raise ValueError("locked OCI descriptor sizes must be positive integers")
        if any(
            getattr(self, field) != expected
            for field, expected in _LOCK_STAGE1_IDENTITY.items()
        ):
            raise ValueError("locked OCI identity must match the measured Stage-1 result")


type ArchiveImageLock = ArchiveImageBootstrapPendingLock | ArchiveImageBootstrapLockedLock


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipRuntimeAvailability:
    """Path-free, fail-closed runtime availability result."""

    profile: str
    available: bool
    reason: str
    image_reference: str | None = None

    def __post_init__(self) -> None:
        if self.profile != ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE:
            raise ValueError("profile must be archive-linux-container-runner/v1")
        if not isinstance(self.available, bool):
            raise ValueError("available must be bool")
        if self.reason not in {"AVAILABLE", "TOOL_UNAVAILABLE"}:
            raise ValueError("reason must be fixed")
        if self.available != (self.reason == "AVAILABLE"):
            raise ValueError("availability and reason disagree")
        if self.available != (self.image_reference is not None):
            raise ValueError("available status requires exactly one pinned image reference")
        if self.image_reference is not None and not _is_digest_reference(self.image_reference):
            raise ValueError("image_reference must be a pinned image digest")


@dataclass(frozen=True, slots=True)
class ArchiveSevenZipToolManifest:
    provider_id: str
    adapter_version: str
    tool_version: str
    listing_profile: str
    integrity_profile: str
    extraction_profile: str
    accepted_exit_codes: frozenset[int]
    network_enabled: bool
    capabilities: frozenset[ToolCapability]

    def __post_init__(self) -> None:
        expected = (
            ARCHIVE_7ZIP_PROVIDER_ID,
            ARCHIVE_7ZIP_ADAPTER_VERSION,
            ARCHIVE_7ZIP_TOOL_VERSION,
            ARCHIVE_LISTING_PROFILE,
            ARCHIVE_INTEGRITY_PROFILE,
            ARCHIVE_EXTRACTION_PROFILE,
            frozenset({0}),
            False,
            archive_7zip_capabilities(),
        )
        if tuple(getattr(self, field) for field in self.__dataclass_fields__) != expected:
            raise ValueError("archive 7zzs tool manifest must match the fixed v1 contract")


def archive_7zip_capabilities() -> frozenset[ToolCapability]:
    """Return only the separated, read-only archive capabilities."""

    return frozenset(
        {
            ToolCapability.ARCHIVE_LISTING,
            ToolCapability.ARCHIVE_INTEGRITY,
            ToolCapability.ARCHIVE_EXTRACTION,
        }
    )


ARCHIVE_7ZIP_TOOL_MANIFEST: Final = ArchiveSevenZipToolManifest(
    ARCHIVE_7ZIP_PROVIDER_ID,
    ARCHIVE_7ZIP_ADAPTER_VERSION,
    ARCHIVE_7ZIP_TOOL_VERSION,
    ARCHIVE_LISTING_PROFILE,
    ARCHIVE_INTEGRITY_PROFILE,
    ARCHIVE_EXTRACTION_PROFILE,
    frozenset({0}),
    False,
    archive_7zip_capabilities(),
)


def parse_7zzs_information_output(chunks: Iterable[bytes]) -> bool:
    """Recognize only the bounded, exact 7zzs 26.02 information banner."""

    payload = bytearray()
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes) or len(chunk) > 262_144:
                return False
            if len(payload) + len(chunk) > MAX_INFORMATION_OUTPUT_BYTES:
                return False
            payload.extend(chunk)
        text = bytes(payload).decode("utf-8", errors="strict")
    except (TypeError, UnicodeDecodeError):
        return False
    if not text.endswith(("\n", "\r\n")) or "\r" in text.replace("\r\n", ""):
        return False
    lines = text.replace("\r\n", "\n").splitlines()
    if any(
        len(line.encode("utf-8")) > MAX_INFORMATION_LINE_BYTES
        or any(ord(character) < 0x20 and character != "\t" for character in line)
        for line in lines
    ):
        return False
    nonempty = [line for line in lines if line]
    return bool(
        nonempty
        and nonempty[0]
        == "7-Zip (z) 26.02 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-06-25"
        and "Formats:" in nonempty
    )


def build_7zzs_information_command() -> tuple[str, ...]:
    """Return the sole allowed information command shape."""

    return (_CONTAINER_7ZZS, "i")


def build_7zzs_listing_command() -> tuple[str, ...]:
    """Return the sole allowed bounded SLT listing command shape."""

    return (
        _CONTAINER_7ZZS,
        "l",
        "-slt",
        "-ba",
        "-bd",
        "-bb0",
        "-bso1",
        "-bse2",
        "-bsp0",
        "-sccUTF-8",
        "--",
        _CONTAINER_ARCHIVE,
    )


def build_7zzs_integrity_command() -> tuple[str, ...]:
    """Return the sole allowed single-threaded integrity command shape."""

    return (
        _CONTAINER_7ZZS,
        "t",
        "-bd",
        "-bb0",
        "-bso1",
        "-bse2",
        "-bsp0",
        "-sccUTF-8",
        "-mmt=1",
        "--",
        _CONTAINER_ARCHIVE,
    )


def build_7zzs_extraction_command() -> tuple[str, ...]:
    """Return the reserved, fixed private-workspace extraction command shape."""

    return (
        _CONTAINER_7ZZS,
        "x",
        "-y",
        "-bd",
        "-bb0",
        "-bso1",
        "-bse2",
        "-bsp0",
        "-sccUTF-8",
        "-mmt=1",
        f"-o{_CONTAINER_OUTPUT}",
        "--",
        _CONTAINER_ARCHIVE,
    )


def archive_7zip_runtime_availability(lock_path: Path) -> ArchiveSevenZipRuntimeAvailability:
    """Remain unavailable until live, cryptographic post-publish verification exists.

    A repository JSON file cannot prove registry visibility, source association,
    anonymous retrieval, or GitHub artifact attestations.  S-EBAR-03 therefore
    validates bootstrap identity but never converts repository booleans into
    runtime authority.  The later runtime preflight must verify those external
    facts directly before constructing an available descriptor.
    """

    load_archive_image_lock(lock_path)
    return _unavailable()


def load_archive_image_lock(lock_path: Path) -> ArchiveImageLock | None:
    """Parse the closed-schema bootstrap lock as an explicit state sum type."""

    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    expected_fields = (
        set(_LOCK_FIXED_VALUES)
        | set(_LOCK_CONTENT_HASHES)
        | _LOCK_DYNAMIC_FIELDS
        | {"build_output"}
    )
    if set(raw) != expected_fields:
        return None
    if any(raw.get(field) != expected for field, expected in _LOCK_FIXED_VALUES.items()):
        return None
    if any(raw.get(field) != expected for field, expected in _LOCK_CONTENT_HASHES.items()):
        return None
    if raw.get("build_output") != _LOCK_BUILD_OUTPUT:
        return None
    raw_state = raw.get("state")
    if not isinstance(raw_state, str):
        return None
    try:
        state = ArchiveImageLockState(raw_state)
    except (TypeError, ValueError):
        return None
    if state is ArchiveImageLockState.BOOTSTRAP_PENDING:
        if (
            any(
                raw.get(field) != "UNVERIFIED"
                for field in (
                    "runtime_platform_manifest_digest",
                    "runtime_config_digest",
                    "runtime_rootfs_layer_digest",
                    "runtime_rootfs_diff_id",
                    "runtime_workdir_layer_digest",
                    "runtime_workdir_diff_id",
                )
            )
            or any(
                raw.get(field) != 0
                for field in (
                    "runtime_platform_manifest_size_bytes",
                    "runtime_config_size_bytes",
                    "runtime_rootfs_layer_size_bytes",
                    "runtime_workdir_layer_size_bytes",
                )
            )
        ):
            return None
        return ArchiveImageBootstrapPendingLock()
    try:
        return ArchiveImageBootstrapLockedLock(
            runtime_platform_manifest_digest=raw["runtime_platform_manifest_digest"],
            runtime_platform_manifest_size_bytes=raw[
                "runtime_platform_manifest_size_bytes"
            ],
            runtime_config_digest=raw["runtime_config_digest"],
            runtime_config_size_bytes=raw["runtime_config_size_bytes"],
            runtime_rootfs_layer_digest=raw["runtime_rootfs_layer_digest"],
            runtime_rootfs_layer_size_bytes=raw["runtime_rootfs_layer_size_bytes"],
            runtime_rootfs_diff_id=raw["runtime_rootfs_diff_id"],
            runtime_workdir_layer_digest=raw["runtime_workdir_layer_digest"],
            runtime_workdir_layer_size_bytes=raw["runtime_workdir_layer_size_bytes"],
            runtime_workdir_diff_id=raw["runtime_workdir_diff_id"],
        )
    except (TypeError, ValueError):
        return None


def _is_digest_reference(value: str) -> bool:
    repository, separator, digest = value.partition("@")
    return (
        repository == ARCHIVE_IMAGE_REFERENCE
        and separator == "@"
        and _DIGEST_RE.fullmatch(digest) is not None
    )


def _unavailable() -> ArchiveSevenZipRuntimeAvailability:
    return ArchiveSevenZipRuntimeAvailability(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE, False, "TOOL_UNAVAILABLE"
    )
