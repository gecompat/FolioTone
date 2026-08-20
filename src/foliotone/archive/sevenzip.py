"""Fixed, read-only 7-Zip command and runtime-identity contracts.

This module never executes archive operations.  Its bounded helper processes
only verify the reviewed runtime identity before the later container runner may
use these command shapes after a separate staging and sandbox preflight.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from foliotone.core.enums import ToolCapability

ARCHIVE_7ZIP_PROVIDER_ID: Final = "archive-7zip"
ARCHIVE_7ZIP_ADAPTER_VERSION: Final = "archive-7zip-cli/1"
ARCHIVE_7ZIP_TOOL_VERSION: Final = "26.02"
ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE: Final = "archive-linux-container-runner/v1"
ARCHIVE_IMAGE_LOCK_PROFILE: Final = "archive-image-lock/v1"
ARCHIVE_RUNTIME_RELEASE_PROFILE: Final = "archive-runtime-release/v1"
ARCHIVE_RUNTIME_REVOCATIONS_PROFILE: Final = "archive-runtime-revocations/v1"
ARCHIVE_RUNTIME_LOCAL_STATE_PROFILE: Final = "archive-runtime-local-state/v1"
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
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}\Z")
_UTC_RE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_RELEASE_DOMAIN: Final = b"archive-runtime-release/v1\x00"
_MAX_RELEASE_BYTES: Final = 65_536
_MAX_REVOCATIONS_BYTES: Final = 1_048_576
_MAX_STATE_BYTES: Final = 16_384
_MAX_BUNDLE_BYTES: Final = 4_194_304
_MAX_TRUSTED_ROOT_BYTES: Final = 1_048_576
_CLOCK_ROLLBACK_TOLERANCE: Final = timedelta(seconds=300)
_MAX_OFFLINE_WINDOW: Final = timedelta(days=90)
_TRUSTED_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_TRUSTED_PACKAGE_DIRECTORY: Final = (
    _TRUSTED_REPOSITORY_ROOT / "packaging" / "archive" / "7zip-26.02"
)
_EXPECTED_IMAGE_REFERENCE: Final = (
    "ghcr.io/gecompat/foliotone-archive-7zip@"
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
)
_ACTION_IDENTITIES: Final = {
    "actions/attest": "daf44fb950173508f38bd2406030372c1d1162b1",
    "actions/attest-sbom": "4651f806c01d8637787e274ac3bdf724ef169f34",
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
}
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
_RELEASE_FIELDS: Final = {
    "accepted_at",
    "action_identities",
    "archive_image_lock_sha256",
    "archive_image_spdx_sha256",
    "custom_slsa_bundle_sha256",
    "custom_slsa_certificate_sha256",
    "custom_slsa_predicate_sha256",
    "custom_slsa_predicate_type",
    "custom_slsa_statement_sha256",
    "custom_slsa_verified_timestamp",
    "deny_self_hosted_runners",
    "generation",
    "image_repository",
    "minimum_revocation_generation",
    "offline_not_after",
    "oidc_issuer",
    "platform",
    "profile",
    "release_id",
    "repository",
    "repository_commit",
    "repository_id",
    "repository_owner_id",
    "revocation_policy_profile",
    "runner_environment",
    "runtime_config_digest",
    "runtime_config_size_bytes",
    "runtime_platform_manifest_digest",
    "runtime_platform_manifest_size_bytes",
    "runtime_rootfs_diff_id",
    "runtime_rootfs_layer_digest",
    "runtime_rootfs_layer_size_bytes",
    "runtime_workdir_diff_id",
    "runtime_workdir_layer_digest",
    "runtime_workdir_layer_size_bytes",
    "signer_digest",
    "signer_workflow",
    "source_ref",
    "spdx_bundle_sha256",
    "spdx_certificate_sha256",
    "spdx_predicate_type",
    "spdx_statement_sha256",
    "spdx_verified_timestamp",
    "state",
    "trusted_root_snapshot_sha256",
    "workflow_invocation_id",
    "workflow_path",
    "workflow_ref",
}
_RELEASE_FIXED_VALUES: Final = {
    "profile": ARCHIVE_RUNTIME_RELEASE_PROFILE,
    "state": "RELEASE_ACCEPTED",
    "repository": "gecompat/FolioTone",
    "repository_id": 1_328_118_830,
    "repository_owner_id": 48_807_214,
    "source_ref": "refs/heads/main",
    "workflow_path": ".github/workflows/archive-image.yml",
    "workflow_ref": "refs/heads/main",
    "runner_environment": "github-hosted",
    "oidc_issuer": "https://token.actions.githubusercontent.com",
    "signer_workflow": "gecompat/FolioTone/.github/workflows/archive-image.yml",
    "deny_self_hosted_runners": True,
    "action_identities": _ACTION_IDENTITIES,
    "image_repository": ARCHIVE_IMAGE_REFERENCE,
    "platform": "linux/amd64",
    "runtime_platform_manifest_digest": _LOCK_STAGE1_IDENTITY[
        "runtime_platform_manifest_digest"
    ],
    "runtime_platform_manifest_size_bytes": _LOCK_STAGE1_IDENTITY[
        "runtime_platform_manifest_size_bytes"
    ],
    "runtime_config_digest": _LOCK_STAGE1_IDENTITY["runtime_config_digest"],
    "runtime_config_size_bytes": _LOCK_STAGE1_IDENTITY["runtime_config_size_bytes"],
    "runtime_rootfs_layer_digest": _LOCK_STAGE1_IDENTITY[
        "runtime_rootfs_layer_digest"
    ],
    "runtime_rootfs_layer_size_bytes": _LOCK_STAGE1_IDENTITY[
        "runtime_rootfs_layer_size_bytes"
    ],
    "runtime_rootfs_diff_id": _LOCK_STAGE1_IDENTITY["runtime_rootfs_diff_id"],
    "runtime_workdir_layer_digest": _LOCK_STAGE1_IDENTITY[
        "runtime_workdir_layer_digest"
    ],
    "runtime_workdir_layer_size_bytes": _LOCK_STAGE1_IDENTITY[
        "runtime_workdir_layer_size_bytes"
    ],
    "runtime_workdir_diff_id": _LOCK_STAGE1_IDENTITY["runtime_workdir_diff_id"],
    "archive_image_lock_sha256": "6fe5a1bc5f2f247d00ee47b75f3d8405a0aa99567ebc2e1a9b556fc7c3782db1",
    "archive_image_spdx_sha256": "ce32dada7227c05e147280404b3d0ce0304eba5e6e085c644f7ac4cb0ddf5a9f",
    "custom_slsa_predicate_type": "https://slsa.dev/provenance/v1",
    "spdx_predicate_type": "https://spdx.dev/Document/v2.3",
    "revocation_policy_profile": ARCHIVE_RUNTIME_REVOCATIONS_PROFILE,
}
_REVOCATION_FIELDS: Final = {
    "bundle_sha256_values",
    "generation",
    "profile",
    "release_ids",
    "repository_commits",
    "runtime_platform_manifest_digests",
}
_STATE_FIELDS: Final = {
    "highest_observed_utc",
    "highest_revocation_generation",
    "ordered_rootfs_diff_ids",
    "profile",
    "provisioned_at",
    "release_generation",
    "release_id",
    "release_record_sha256",
    "runtime_config_digest",
    "runtime_platform_manifest_digest",
}


class ArchiveImageLockState(StrEnum):
    BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
    BOOTSTRAP_LOCKED = "BOOTSTRAP_LOCKED"


class ArchiveRuntimeDiagnosticCode(StrEnum):
    RELEASE_NOT_ACCEPTED = "RELEASE_NOT_ACCEPTED"
    RELEASE_EXPIRED = "RELEASE_EXPIRED"
    LOCAL_STATE_MISSING = "LOCAL_STATE_MISSING"
    LOCAL_STATE_INVALID = "LOCAL_STATE_INVALID"
    GENERATION_ROLLBACK = "GENERATION_ROLLBACK"
    CLOCK_ROLLBACK = "CLOCK_ROLLBACK"
    REVOKED = "REVOKED"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    OCI_LAYOUT_MISMATCH = "OCI_LAYOUT_MISMATCH"
    IMAGE_NOT_PRESENT = "IMAGE_NOT_PRESENT"
    IMAGE_INSPECT_MISMATCH = "IMAGE_INSPECT_MISMATCH"
    STATE_UPDATE_FAILED = "STATE_UPDATE_FAILED"


class _ArchiveRuntimeFailure(RuntimeError):
    def __init__(self, code: ArchiveRuntimeDiagnosticCode) -> None:
        super().__init__(code.value)
        self.code = code


class _OciIdentity(Protocol):
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
    diagnostic_code: ArchiveRuntimeDiagnosticCode | None = None

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
        if self.available != (self.diagnostic_code is None):
            raise ValueError("only unavailable results carry a diagnostic code")


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


def archive_7zip_runtime_availability(
    lock_path: Path,
    *,
    release_path: Path | None = None,
    revocations_path: Path | None = None,
    evidence_directory: Path | None = None,
    local_state_root: Path | None = None,
    private_state_parent: Path | None = None,
    scan_roots: Iterable[Path] | None = None,
    oci_layout_path: Path | None = None,
    now: datetime | None = None,
) -> ArchiveSevenZipRuntimeAvailability:
    """Revalidate the accepted release, local state, OCI layout, and image offline."""

    if not isinstance(load_archive_image_lock(lock_path), ArchiveImageBootstrapLockedLock):
        return _unavailable(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    required = (
        release_path,
        revocations_path,
        evidence_directory,
        local_state_root,
        private_state_parent,
        oci_layout_path,
    )
    if any(value is None for value in required):
        return _unavailable(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING)
    assert release_path is not None
    assert revocations_path is not None
    assert evidence_directory is not None
    assert local_state_root is not None
    assert private_state_parent is not None
    assert oci_layout_path is not None
    instant = _normalize_now(now)
    try:
        _require_private_state_location(
            local_state_root, private_state_parent, scan_roots
        )
        with _state_lock(local_state_root, private_state_parent):
            _verify_state_security(private_state_parent, local_state_root)
            release, release_bytes = _load_release(release_path)
            _verify_package_hashes(_TRUSTED_PACKAGE_DIRECTORY, release)
            revocations = _load_revocations(revocations_path)
            _verify_evidence(evidence_directory, release)
            state = _load_state(local_state_root)
            _verify_time_and_generations(release, revocations, state, instant)
            _verify_not_revoked(release, revocations)
            _verify_state_bindings(state, release, release_bytes)
            _verify_oci_layout(oci_layout_path, release)
            _verify_docker_inspect(
                _docker_image_inspect(_EXPECTED_IMAGE_REFERENCE), release
            )
            updated = dict(state)
            updated["highest_observed_utc"] = _format_utc(
                max(instant, _parse_utc(state["highest_observed_utc"]))
            )
            updated["highest_revocation_generation"] = max(
                state["highest_revocation_generation"], revocations["generation"]
            )
            _replace_state_file(local_state_root, updated)
    except _ArchiveRuntimeFailure as failure:
        return _unavailable(failure.code)
    except Exception:
        return _unavailable(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    return ArchiveSevenZipRuntimeAvailability(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        True,
        "AVAILABLE",
        _EXPECTED_IMAGE_REFERENCE,
    )


def provision_archive_7zip_runtime(
    *,
    local_state_root: Path,
    private_state_parent: Path,
    scan_roots: Iterable[Path],
    oci_layout_path: Path,
    attestation_artifact_path: Path,
    now: datetime | None = None,
    refresh: bool = False,
) -> None:
    """Run every distribution gate and atomically create or refresh private state."""

    instant = _normalize_now(now)
    _require_private_state_location(local_state_root, private_state_parent, scan_roots)
    _verify_online_distribution()
    release_path = _TRUSTED_PACKAGE_DIRECTORY / "archive-runtime-release.json"
    revocations_path = _TRUSTED_PACKAGE_DIRECTORY / "archive-runtime-revocations.json"
    evidence_directory = _TRUSTED_PACKAGE_DIRECTORY / "archive-runtime-evidence"
    with _state_lock(local_state_root, private_state_parent):
        _verify_state_security(private_state_parent, local_state_root, allow_missing_root=True)
        release, release_bytes = _load_release(release_path)
        _verify_package_hashes(_TRUSTED_PACKAGE_DIRECTORY, release)
        revocations = _load_revocations(revocations_path)
        _verify_evidence(evidence_directory, release)
        _verify_not_revoked(release, revocations)
        if revocations["generation"] < release["minimum_revocation_generation"]:
            raise _ArchiveRuntimeFailure(
                ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK
            )
        accepted = _parse_utc(
            release["accepted_at"], ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
        )
        if instant < accepted:
            raise _ArchiveRuntimeFailure(
                ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
            )
        if instant > _parse_utc(release["offline_not_after"]):
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_EXPIRED)
        _verify_offline_attestations(
            attestation_artifact_path,
            _supporting_gh_executable(),
            evidence_directory,
            release,
        )
        _verify_oci_layout(oci_layout_path, release)
        _verify_docker_inspect(_docker_image_inspect(_EXPECTED_IMAGE_REFERENCE), release)
        old_state: dict[str, Any] | None = None
        if refresh:
            old_state = _load_state(local_state_root)
            _verify_time_and_generations(release, revocations, old_state, instant)
            _verify_refresh_release_transition(release, release_bytes, old_state)
        elif local_state_root.exists():
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
        state = {
            "highest_observed_utc": _format_utc(
                max(
                    instant,
                    _parse_utc(old_state["highest_observed_utc"])
                    if old_state is not None
                    else instant,
                )
            ),
            "highest_revocation_generation": revocations["generation"],
            "ordered_rootfs_diff_ids": [
                release["runtime_rootfs_diff_id"],
                release["runtime_workdir_diff_id"],
            ],
            "profile": ARCHIVE_RUNTIME_LOCAL_STATE_PROFILE,
            "provisioned_at": _format_utc(instant),
            "release_generation": release["generation"],
            "release_id": release["release_id"],
            "release_record_sha256": hashlib.sha256(release_bytes).hexdigest(),
            "runtime_config_digest": release["runtime_config_digest"],
            "runtime_platform_manifest_digest": release[
                "runtime_platform_manifest_digest"
            ],
        }
        if refresh:
            _replace_state_file(local_state_root, state)
        else:
            _create_state_root(local_state_root, state)
        _verify_state_security(private_state_parent, local_state_root)


def load_archive_runtime_release(release_path: Path) -> dict[str, Any] | None:
    """Return a validated closed release record without exposing raw evidence."""

    try:
        release, _ = _load_release(release_path)
        return release
    except _ArchiveRuntimeFailure:
        return None


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


def _load_release(path: Path) -> tuple[dict[str, Any], bytes]:
    value, raw = _load_canonical_object(
        path, _MAX_RELEASE_BYTES, ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
    )
    if set(value) != _RELEASE_FIELDS:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    if any(value.get(name) != expected for name, expected in _RELEASE_FIXED_VALUES.items()):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    for name in (
        "generation",
        "minimum_revocation_generation",
        "runtime_platform_manifest_size_bytes",
        "runtime_config_size_bytes",
        "runtime_rootfs_layer_size_bytes",
        "runtime_workdir_layer_size_bytes",
    ):
        if type(value.get(name)) is not int or value[name] <= 0:
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    for name in (
        "archive_image_lock_sha256",
        "archive_image_spdx_sha256",
        "custom_slsa_bundle_sha256",
        "custom_slsa_statement_sha256",
        "custom_slsa_predicate_sha256",
        "custom_slsa_certificate_sha256",
        "spdx_bundle_sha256",
        "spdx_statement_sha256",
        "spdx_certificate_sha256",
        "trusted_root_snapshot_sha256",
    ):
        if not isinstance(value.get(name), str) or _SHA256_RE.fullmatch(value[name]) is None:
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    for name in (
        "runtime_platform_manifest_digest",
        "runtime_config_digest",
        "runtime_rootfs_layer_digest",
        "runtime_rootfs_diff_id",
        "runtime_workdir_layer_digest",
        "runtime_workdir_diff_id",
    ):
        if not isinstance(value.get(name), str) or _DIGEST_RE.fullmatch(value[name]) is None:
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    commit = value.get("repository_commit")
    if not isinstance(commit, str) or _COMMIT_RE.fullmatch(commit) is None:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    if value.get("signer_digest") != commit:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    expected_invocation = (
        "https://github.com/gecompat/FolioTone/actions/runs/32345177882/attempts/1"
    )
    if value.get("workflow_invocation_id") != expected_invocation:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    release_error = ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
    accepted = _parse_utc(value.get("accepted_at"), release_error)
    expires = _parse_utc(value.get("offline_not_after"), release_error)
    custom_verified = _parse_utc(
        value.get("custom_slsa_verified_timestamp"), release_error
    )
    spdx_verified = _parse_utc(value.get("spdx_verified_timestamp"), release_error)
    if not (
        custom_verified <= accepted
        and spdx_verified <= accepted
        and accepted < expires <= accepted + _MAX_OFFLINE_WINDOW
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    release_id = value.get("release_id")
    if not isinstance(release_id, str) or _SHA256_RE.fullmatch(release_id) is None:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    material = dict(value)
    del material["release_id"]
    expected_id = hashlib.sha256(
        _RELEASE_DOMAIN + _canonical_json_bytes(material)
    ).hexdigest()
    if release_id != expected_id:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED)
    return value, raw


def _load_revocations(path: Path) -> dict[str, Any]:
    value, _ = _load_canonical_object(
        path, _MAX_REVOCATIONS_BYTES, ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
    )
    if set(value) != _REVOCATION_FIELDS or value.get("profile") != (
        ARCHIVE_RUNTIME_REVOCATIONS_PROFILE
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if type(value.get("generation")) is not int or value["generation"] <= 0:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    validators = {
        "bundle_sha256_values": _SHA256_RE,
        "release_ids": _SHA256_RE,
        "repository_commits": _COMMIT_RE,
        "runtime_platform_manifest_digests": _DIGEST_RE,
    }
    for name, pattern in validators.items():
        entries = value.get(name)
        if (
            not isinstance(entries, list)
            or entries != sorted(entries)
            or len(entries) != len(set(entries))
            or any(
                not isinstance(entry, str) or pattern.fullmatch(entry) is None
                for entry in entries
            )
        ):
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    return value


def _verify_evidence(
    evidence_directory: Path,
    release: dict[str, Any],
) -> None:
    custom = _load_bundle(
        evidence_directory / "custom-slsa.jsonl",
        release["custom_slsa_bundle_sha256"],
        release["custom_slsa_statement_sha256"],
        release["custom_slsa_certificate_sha256"],
        release["custom_slsa_predicate_type"],
        release.get("custom_slsa_predicate_sha256"),
    )
    spdx = _load_bundle(
        evidence_directory / "spdx.jsonl",
        release["spdx_bundle_sha256"],
        release["spdx_statement_sha256"],
        release["spdx_certificate_sha256"],
        release["spdx_predicate_type"],
        None,
    )
    trusted_root = _read_bounded_file(
        evidence_directory / "trusted_root.jsonl",
        _MAX_TRUSTED_ROOT_BYTES,
        ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
    )
    if (
        hashlib.sha256(trusted_root).hexdigest()
        != release["trusted_root_snapshot_sha256"]
        or not trusted_root.endswith(b"\n")
        or len(trusted_root.splitlines()) != 2
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    expected_custom = _expected_custom_predicate(release)
    _verify_statement(
        custom, release, custom_slsa=True, expected_custom=expected_custom
    )
    _verify_statement(spdx, release, custom_slsa=False, expected_custom=None)
    expected_spdx = _load_json_value(
        _read_bounded_file(
            _TRUSTED_PACKAGE_DIRECTORY / "archive-image.spdx.json",
            1_048_576,
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
        ),
        ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
    )
    if spdx.get("predicate") != expected_spdx:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)


def _load_bundle(
    path: Path,
    bundle_sha256: str,
    statement_sha256: str,
    certificate_sha256: str,
    predicate_type: str,
    predicate_sha256: str | None,
) -> dict[str, Any]:
    raw = _read_bounded_file(
        path, _MAX_BUNDLE_BYTES, ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
    )
    if (
        hashlib.sha256(raw).hexdigest() != bundle_sha256
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    bundle = _load_json_value(raw, ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if not isinstance(bundle, dict) or set(bundle) != {
        "mediaType",
        "verificationMaterial",
        "dsseEnvelope",
    }:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if bundle.get("mediaType") != "application/vnd.dev.sigstore.bundle.v0.3+json":
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    envelope = bundle.get("dsseEnvelope")
    verification = bundle.get("verificationMaterial")
    if not isinstance(envelope, dict) or not isinstance(verification, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if set(envelope) != {"payload", "payloadType", "signatures"} or envelope.get(
        "payloadType"
    ) != "application/vnd.in-toto+json":
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    signatures = envelope.get("signatures")
    if (
        not isinstance(signatures, list)
        or len(signatures) != 1
        or not isinstance(signatures[0], dict)
        or set(signatures[0]) != {"sig"}
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    try:
        statement_bytes = base64.b64decode(envelope["payload"], validate=True)
        certificate = verification["certificate"]
        certificate_bytes = base64.b64decode(certificate["rawBytes"], validate=True)
    except (KeyError, TypeError, ValueError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
        ) from None
    if (
        not isinstance(certificate, dict)
        or set(certificate) != {"rawBytes"}
        or hashlib.sha256(statement_bytes).hexdigest() != statement_sha256
        or hashlib.sha256(certificate_bytes).hexdigest() != certificate_sha256
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    statement = _load_json_value(
        statement_bytes, ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
    )
    if not isinstance(statement, dict) or statement.get("predicateType") != predicate_type:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if predicate_sha256 is not None:
        predicate_bytes = _extract_json_object_member(statement_bytes, "predicate")
        if hashlib.sha256(predicate_bytes).hexdigest() != predicate_sha256:
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    return statement


def _verify_statement(
    statement: dict[str, Any],
    release: dict[str, Any],
    *,
    custom_slsa: bool,
    expected_custom: dict[str, Any] | None,
) -> None:
    expected_subject = [
        {
            "digest": {
                "sha256": release["runtime_platform_manifest_digest"].removeprefix(
                    "sha256:"
                )
            },
            "name": release["image_repository"],
        }
    ]
    if set(statement) != {"_type", "predicate", "predicateType", "subject"} or (
        statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("subject") != expected_subject
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    if not custom_slsa:
        return
    if expected_custom is None or predicate != expected_custom:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)


def _expected_custom_predicate(release: dict[str, Any]) -> dict[str, Any]:
    """Build the complete predicate through fixed trusted FolioTone source."""

    try:
        module = _trusted_supply_chain_module()
        expected = module.build_provenance_predicate(
            release["repository_commit"], release["workflow_invocation_id"]
        )
    except Exception:
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
        ) from None
    if not isinstance(expected, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    return expected


def _trusted_supply_chain_module() -> Any:
    script = _TRUSTED_PACKAGE_DIRECTORY / "supply_chain_evidence.py"
    spec = importlib.util.spec_from_file_location(
        "foliotone_archive_runtime_supply_chain", script
    )
    if spec is None or spec.loader is None:
        raise ValueError("trusted supply-chain verifier unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_online_distribution() -> None:
    """Run exact public-manifest and source-association gates from trusted source."""

    try:
        module = _trusted_supply_chain_module()
        opener = _provisioning_opener(module)
        module.verify_public_manifest(opener)
        module.verify_public_source_association(opener)
    except Exception:
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
        ) from None


def _provisioning_opener(module: Any) -> Any:
    """Private raw HTTP transport seam; verifier semantics remain fixed above it."""

    return module.urllib.request.build_opener(module._NoRedirect())


def _extract_json_object_member(payload: bytes, name: str) -> bytes:
    marker = json.dumps(name).encode("ascii")
    position = payload.find(marker)
    if position < 0 or payload.find(marker, position + len(marker)) >= 0:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    position += len(marker)
    while position < len(payload) and payload[position] in b" \t\r\n":
        position += 1
    if position >= len(payload) or payload[position] != ord(":"):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    position += 1
    while position < len(payload) and payload[position] in b" \t\r\n":
        position += 1
    start = position
    if position >= len(payload) or payload[position] != ord("{"):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    depth = 0
    in_string = False
    escaped = False
    for index in range(position, len(payload)):
        byte = payload[index]
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
        elif byte == ord('"'):
            in_string = True
        elif byte == ord("{"):
            depth += 1
        elif byte == ord("}"):
            depth -= 1
            if depth == 0:
                return payload[start : index + 1]
    raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)


def _load_state(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING)
    value, _ = _load_canonical_object(
        root / "state.json", _MAX_STATE_BYTES, ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
    )
    if set(value) != _STATE_FIELDS or value.get("profile") != (
        ARCHIVE_RUNTIME_LOCAL_STATE_PROFILE
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    if (
        type(value.get("release_generation")) is not int
        or value["release_generation"] <= 0
        or type(value.get("highest_revocation_generation")) is not int
        or value["highest_revocation_generation"] <= 0
        or not isinstance(value.get("release_id"), str)
        or _SHA256_RE.fullmatch(value["release_id"]) is None
        or not isinstance(value.get("release_record_sha256"), str)
        or _SHA256_RE.fullmatch(value["release_record_sha256"]) is None
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    _parse_utc(value.get("provisioned_at"))
    _parse_utc(value.get("highest_observed_utc"))
    ordered = value.get("ordered_rootfs_diff_ids")
    if (
        not isinstance(ordered, list)
        or len(ordered) != 2
        or any(not isinstance(item, str) or _DIGEST_RE.fullmatch(item) is None for item in ordered)
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    return value


def _verify_time_and_generations(
    release: dict[str, Any],
    revocations: dict[str, Any],
    state: dict[str, Any],
    now: datetime,
) -> None:
    if now < _parse_utc(
        release["accepted_at"], ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
    ):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
        )
    if now > _parse_utc(release["offline_not_after"]):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.RELEASE_EXPIRED)
    if release["generation"] < state["release_generation"] or (
        revocations["generation"] < state["highest_revocation_generation"]
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK)
    if revocations["generation"] < release["minimum_revocation_generation"]:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK)
    if now + _CLOCK_ROLLBACK_TOLERANCE < _parse_utc(state["highest_observed_utc"]):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.CLOCK_ROLLBACK)


def _verify_refresh_release_transition(
    release: dict[str, Any], release_bytes: bytes, state: dict[str, Any]
) -> None:
    """Require exact record identity when a refresh reuses a generation."""

    if release["generation"] == state["release_generation"] and (
        release["release_id"] != state["release_id"]
        or hashlib.sha256(release_bytes).hexdigest()
        != state["release_record_sha256"]
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK)


def _verify_not_revoked(
    release: dict[str, Any], revocations: dict[str, Any]
) -> None:
    if (
        release["release_id"] in revocations["release_ids"]
        or release["runtime_platform_manifest_digest"]
        in revocations["runtime_platform_manifest_digests"]
        or release["repository_commit"] in revocations["repository_commits"]
        or release["custom_slsa_bundle_sha256"]
        in revocations["bundle_sha256_values"]
        or release["spdx_bundle_sha256"] in revocations["bundle_sha256_values"]
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.REVOKED)


def _verify_state_bindings(
    state: dict[str, Any], release: dict[str, Any], release_bytes: bytes
) -> None:
    expected = {
        "release_id": release["release_id"],
        "release_generation": release["generation"],
        "release_record_sha256": hashlib.sha256(release_bytes).hexdigest(),
        "runtime_platform_manifest_digest": release["runtime_platform_manifest_digest"],
        "runtime_config_digest": release["runtime_config_digest"],
        "ordered_rootfs_diff_ids": [
            release["runtime_rootfs_diff_id"],
            release["runtime_workdir_diff_id"],
        ],
    }
    if any(state.get(name) != value for name, value in expected.items()):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)


def _verify_package_hashes(package_directory: Path, release: dict[str, Any]) -> None:
    expected = {
        "archive-image.lock.json": release["archive_image_lock_sha256"],
        "archive-image.spdx.json": release["archive_image_spdx_sha256"],
    }
    for name, digest in expected.items():
        payload = _read_bounded_file(
            package_directory / name,
            1_048_576,
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
        )
        if hashlib.sha256(payload).hexdigest() != digest:
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)


def _verify_oci_layout(
    oci_layout_path: Path,
    release: dict[str, Any],
) -> None:
    try:
        identity = _inspect_oci_layout_identity(oci_layout_path)
        actual = {
            "runtime_platform_manifest_digest": identity.runtime_platform_manifest_digest,
            "runtime_platform_manifest_size_bytes": identity.runtime_platform_manifest_size_bytes,
            "runtime_config_digest": identity.runtime_config_digest,
            "runtime_config_size_bytes": identity.runtime_config_size_bytes,
            "runtime_rootfs_layer_digest": identity.runtime_rootfs_layer_digest,
            "runtime_rootfs_layer_size_bytes": identity.runtime_rootfs_layer_size_bytes,
            "runtime_rootfs_diff_id": identity.runtime_rootfs_diff_id,
            "runtime_workdir_layer_digest": identity.runtime_workdir_layer_digest,
            "runtime_workdir_layer_size_bytes": identity.runtime_workdir_layer_size_bytes,
            "runtime_workdir_diff_id": identity.runtime_workdir_diff_id,
        }
    except Exception:
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.OCI_LAYOUT_MISMATCH
        ) from None
    if any(actual[name] != release[name] for name in actual):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.OCI_LAYOUT_MISMATCH)


def _inspect_oci_layout_identity(oci_layout_path: Path) -> _OciIdentity:
    """Return raw inspector identity using only the fixed installed implementation."""

    script = _TRUSTED_PACKAGE_DIRECTORY / "inspect_oci_layout.py"
    if not script.is_file() or not oci_layout_path.is_file():
        raise ValueError("trusted OCI inspector input unavailable")
    spec = importlib.util.spec_from_file_location(
        "foliotone_archive_runtime_oci_inspector", script
    )
    if spec is None or spec.loader is None:
        raise ValueError("trusted OCI inspector unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.inspect_oci_layout(oci_layout_path)  # type: ignore[no-any-return]


def _docker_image_inspect(image_reference: str) -> object:
    environment = {"PATH": os.environ.get("PATH", "")}
    try:
        returncode, stdout = _run_bounded_process(
            ["docker", "image", "inspect", image_reference],
            env=environment,
            timeout=30,
            maximum_stdout=1_048_576,
        )
    except (OSError, RuntimeError, TimeoutError):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.IMAGE_NOT_PRESENT) from None
    if returncode != 0:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.IMAGE_NOT_PRESENT)
    try:
        return json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH
        ) from None


def _verify_offline_attestations(
    artifact_path: Path,
    gh_executable: Path,
    evidence_directory: Path,
    release: dict[str, Any],
) -> None:
    """Cryptographically verify both reviewed bundles through a bounded offline CLI."""

    artifact = _read_bounded_file(
        artifact_path,
        release["runtime_platform_manifest_size_bytes"],
        ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
    )
    if (
        len(artifact) != release["runtime_platform_manifest_size_bytes"]
        or "sha256:" + hashlib.sha256(artifact).hexdigest()
        != release["runtime_platform_manifest_digest"]
        or not gh_executable.is_file()
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    expected_custom = _expected_custom_predicate(release)
    expected_spdx = _load_json_value(
        _read_bounded_file(
            _TRUSTED_PACKAGE_DIRECTORY / "archive-image.spdx.json",
            1_048_576,
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
        ),
        ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH,
    )
    common = [
        str(gh_executable),
        "attestation",
        "verify",
        str(artifact_path),
        "--repo",
        release["repository"],
        "--signer-workflow",
        release["signer_workflow"],
        "--signer-digest",
        release["signer_digest"],
        "--source-digest",
        release["repository_commit"],
        "--source-ref",
        release["source_ref"],
        "--cert-oidc-issuer",
        release["oidc_issuer"],
        "--deny-self-hosted-runners",
        "--custom-trusted-root",
        str(evidence_directory / "trusted_root.jsonl"),
        "--format",
        "json",
    ]
    with tempfile.TemporaryDirectory(prefix="foliotone-offline-verifier-") as home:
        environment = {
            "PATH": str(gh_executable.parent),
            "HOME": home,
            "GH_CONFIG_DIR": str(Path(home) / "gh"),
            "XDG_CONFIG_HOME": str(Path(home) / "xdg"),
            "XDG_STATE_HOME": str(Path(home) / "state"),
            "LOCALAPPDATA": str(Path(home) / "local"),
            "APPDATA": str(Path(home) / "roaming"),
            "USERPROFILE": home,
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
        }
        for predicate_type, bundle_name, expected in (
            (
                release["custom_slsa_predicate_type"],
                "custom-slsa.jsonl",
                expected_custom,
            ),
            (release["spdx_predicate_type"], "spdx.jsonl", expected_spdx),
        ):
            try:
                returncode, stdout = _run_bounded_process(
                    common
                    + [
                        "--predicate-type",
                        predicate_type,
                        "--bundle",
                        str(evidence_directory / bundle_name),
                    ],
                    env=environment,
                    timeout=30,
                    maximum_stdout=4_194_304,
                )
            except (OSError, RuntimeError, TimeoutError):
                raise _ArchiveRuntimeFailure(
                    ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
                ) from None
            if returncode != 0:
                raise _ArchiveRuntimeFailure(
                    ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
                )
            _verify_gh_attestation_output(stdout, predicate_type, expected, release)


def _supporting_gh_executable() -> Path:
    executable = Path(shutil.which("gh") or "")
    if not executable.is_file():
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    return executable


def _verify_gh_attestation_output(
    raw: bytes,
    predicate_type: str,
    expected_predicate: object,
    release: dict[str, Any],
) -> None:
    try:
        results = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
        ) from None
    if not isinstance(results, list) or len(results) != 1:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)
    result = results[0]
    verification = result.get("verificationResult") if isinstance(result, dict) else None
    statement = verification.get("statement") if isinstance(verification, dict) else None
    expected_subject = [
        {
            "name": release["image_repository"],
            "digest": {
                "sha256": release["runtime_platform_manifest_digest"].removeprefix(
                    "sha256:"
                )
            },
        }
    ]
    if (
        not isinstance(statement, dict)
        or set(statement) != {"_type", "predicate", "predicateType", "subject"}
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != predicate_type
        or statement.get("subject") != expected_subject
        or statement.get("predicate") != expected_predicate
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH)


def _run_bounded_process(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    maximum_stdout: int,
) -> tuple[int, bytes]:
    """Stream bounded stdout, discard stderr, and kill the whole tree on failure."""

    if not command or maximum_stdout <= 0 or timeout <= 0:
        raise ValueError("invalid bounded process contract")
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        shell=False,
        start_new_session=os.name != "nt",
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if os.name == "nt"
            else 0
        ),
    )
    if process.stdout is None:
        _terminate_process_tree(process)
        raise RuntimeError("bounded process stdout unavailable")
    stdout = process.stdout
    payload = bytearray()
    overflow = threading.Event()

    def read_stdout() -> None:
        while True:
            chunk = stdout.read(65_536)
            if not chunk:
                return
            remaining = maximum_stdout + 1 - len(payload)
            if remaining > 0:
                payload.extend(chunk[:remaining])
            if len(payload) > maximum_stdout:
                overflow.set()
                return

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    while reader.is_alive() and not overflow.is_set() and time.monotonic() < deadline:
        reader.join(0.05)
    if overflow.is_set() or reader.is_alive():
        _terminate_process_tree(process)
        reader.join(5)
        if overflow.is_set():
            raise RuntimeError("bounded process output exceeded limit")
        raise TimeoutError("bounded process timed out")
    try:
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        raise TimeoutError("bounded process timed out") from None
    return returncode, bytes(payload)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        killer = subprocess.Popen(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        try:
            killer.wait(timeout=5)
        except subprocess.TimeoutExpired:
            killer.kill()
    else:
        try:
            getattr(os, "killpg")(process.pid, 9)  # noqa: B009
        except OSError:
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _verify_docker_inspect(value: object, release: dict[str, Any]) -> None:
    if isinstance(value, list):
        if len(value) != 1:
            raise _ArchiveRuntimeFailure(
                ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH
            )
        value = value[0]
    if not isinstance(value, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH)
    config = value.get("Config")
    rootfs = value.get("RootFS")
    if not isinstance(config, dict) or not isinstance(rootfs, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH)
    expected = {
        "Id": release["runtime_config_digest"],
        "Architecture": "amd64",
        "Os": "linux",
    }
    if (
        any(value.get(name) != expected_value for name, expected_value in expected.items())
        or value.get("RepoDigests") is None
        or not isinstance(value["RepoDigests"], list)
        or _EXPECTED_IMAGE_REFERENCE not in value["RepoDigests"]
        or config.get("User") != "65532:65532"
        or config.get("Entrypoint") != ["/usr/local/bin/7zzs"]
        or config.get("WorkingDir") != "/workspace"
        or config.get("Env")
        != ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        or config.get("Labels")
        != {"org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"}
        or config.get("Cmd") is not None
        or rootfs.get("Type") != "layers"
        or rootfs.get("Layers")
        != [release["runtime_rootfs_diff_id"], release["runtime_workdir_diff_id"]]
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH)


def _create_state_root(
    root: Path,
    state: dict[str, Any],
) -> None:
    parent = root.parent
    _verify_secure_path(parent, directory=True)
    if _path_exists_no_follow(root):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=parent))
    try:
        if os.name != "nt":
            temporary.chmod(0o700)
        _write_state_payload(temporary / "state.json", state)
        _call_failure_hook("before_state_directory_fsync")
        _fsync_directory(temporary)
        _call_failure_hook("before_state_replace")
        _atomic_replace(temporary, root)
        _call_failure_hook("before_parent_directory_fsync")
        _fsync_directory(parent)
    except Exception as error:
        if temporary.exists():
            try:
                (temporary / "state.json").unlink(missing_ok=True)
                temporary.rmdir()
            except OSError:
                pass
        if isinstance(error, _ArchiveRuntimeFailure):
            raise
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.STATE_UPDATE_FAILED) from None


def _replace_state_file(
    root: Path,
    state: dict[str, Any],
) -> None:
    _verify_secure_path(root, directory=True)
    _verify_secure_path(root / "state.json", directory=False)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        _write_state_payload(temporary, state)
        _call_failure_hook("before_state_replace")
        _atomic_replace(temporary, root / "state.json")
        _call_failure_hook("before_parent_directory_fsync")
        _fsync_directory(root)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, _ArchiveRuntimeFailure):
            raise
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.STATE_UPDATE_FAILED) from None


def _write_state_payload(
    path: Path,
    state: dict[str, Any],
) -> None:
    payload = _canonical_json_bytes(state)
    if len(payload) > _MAX_STATE_BYTES:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.STATE_UPDATE_FAILED)
    with path.open("xb") as handle:
        if os.name != "nt":
            os.chmod(path, 0o600)
        handle.write(payload)
        handle.flush()
        _call_failure_hook("before_state_file_fsync")
        os.fsync(handle.fileno())


def _call_failure_hook(stage: str) -> None:
    """Private fault-injection seam; production deliberately performs no action."""

    del stage


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        # Windows replacements use MOVEFILE_WRITE_THROUGH in _atomic_replace.
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(source: Path, destination: Path) -> None:
    if os.name != "nt":
        os.replace(source, destination)
        return
    windows_ctypes: Any = ctypes
    move_file = windows_ctypes.windll.kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    move_file.restype = ctypes.c_int
    movefile_replace_existing = 0x1
    movefile_write_through = 0x8
    if not move_file(
        str(source),
        str(destination),
        movefile_replace_existing | movefile_write_through,
    ):
        raise OSError("atomic write-through replacement failed")


@contextmanager
def _state_lock(root: Path, private_parent: Path) -> Iterator[None]:
    parent = root.parent
    if parent != private_parent:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    lock_path = parent / f".{root.name}.lock"
    try:
        if _path_exists_no_follow(lock_path):
            _verify_secure_path(lock_path, directory=False)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            if os.name != "nt":
                getattr(os, "fchmod")(descriptor, 0o600)  # noqa: B009
            opened = os.fstat(descriptor)
            observed = lock_path.lstat()
            if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
                raise _ArchiveRuntimeFailure(
                    ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
                )
            _verify_secure_path(lock_path, directory=False)
        except Exception:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "a+b") as handle:
            if os.name == "nt":
                msvcrt = importlib.import_module("msvcrt")

                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except _ArchiveRuntimeFailure:
        raise
    except (OSError, RuntimeError):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.STATE_UPDATE_FAILED) from None


def _require_private_state_location(
    root: Path,
    private_parent: Path,
    scan_roots: Iterable[Path] | None,
) -> None:
    roots = tuple(scan_roots or ())
    if not roots or not private_parent.is_absolute() or not root.is_absolute():
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    if root.parent != private_parent:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    try:
        resolved_parent = private_parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
        ) from None
    try:
        if root.parent.resolve(strict=True) != resolved_parent:
            raise _ArchiveRuntimeFailure(
                ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
            )
    except (OSError, RuntimeError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
        ) from None
    resolved = resolved_parent / root.name
    for scan_root in roots:
        try:
            candidate = scan_root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise _ArchiveRuntimeFailure(
                ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
            ) from None
        if resolved == candidate or resolved.is_relative_to(candidate):
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    _verify_secure_path(private_parent, directory=True)


def _verify_state_security(
    private_parent: Path,
    root: Path,
    *,
    allow_missing_root: bool = False,
) -> None:
    _verify_secure_path(private_parent, directory=True)
    if not _path_exists_no_follow(root):
        if allow_missing_root:
            return
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING)
    _verify_secure_path(root, directory=True)
    state_path = root / "state.json"
    if not _path_exists_no_follow(state_path):
        if allow_missing_root:
            return
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING)
    _verify_secure_path(state_path, directory=False)


def _path_exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
        ) from None
    return True


def _verify_secure_path(path: Path, *, directory: bool) -> None:
    try:
        details = path.lstat()
    except OSError:
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
        ) from None
    expected_kind = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(
        details.st_mode
    )
    reparse = bool(getattr(details, "st_file_attributes", 0) & 0x400)
    if not expected_kind or stat.S_ISLNK(details.st_mode) or reparse:
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    if os.name == "nt":
        _verify_windows_private_acl(path)
        return
    expected_mode = 0o700 if directory else 0o600
    if details.st_uid != getattr(os, "geteuid")() or (  # noqa: B009
        stat.S_IMODE(details.st_mode) != expected_mode
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)


def _verify_windows_private_acl(path: Path) -> None:
    script = (
        "$ErrorActionPreference='Stop';"
        "$m=Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\Modules\\"
        "Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1';"
        "Import-Module -Name $m -Force -ErrorAction Stop;"
        "$a=Get-Acl -LiteralPath $env:FOLIOTONE_STATE_ACL_PATH;"
        "$owner=([System.Security.Principal.NTAccount]::new($a.Owner)).Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value;"
        "$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        "$access=@($a.Access|ForEach-Object { [pscustomobject]@{"
        "sid=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value;"
        "type=$_.AccessControlType.ToString()} });"
        "[pscustomobject]@{owner=$owner;current=$current;access=$access}|"
        "ConvertTo-Json -Compress -Depth 4"
    )
    try:
        returncode, raw = _run_bounded_process(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            env={
                "PATH": os.environ.get("PATH", ""),
                "SystemRoot": os.environ.get("SystemRoot", "C:\\Windows"),
                "FOLIOTONE_STATE_ACL_PATH": str(path),
            },
            timeout=10,
            maximum_stdout=65_536,
        )
        value = json.loads(raw)
    except (OSError, RuntimeError, TimeoutError, UnicodeError, json.JSONDecodeError):
        raise _ArchiveRuntimeFailure(
            ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
        ) from None
    if returncode != 0 or not isinstance(value, dict):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    owner = value.get("owner")
    current = value.get("current")
    access = value.get("access")
    allowed = {current, "S-1-5-18", "S-1-5-32-544"}
    if (
        not isinstance(current, str)
        or owner not in {current, "S-1-5-32-544"}
        or not isinstance(access, list)
        or not access
    ):
        raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)
    for rule in access:
        if (
            not isinstance(rule, dict)
            or rule.get("type") not in {"Allow", "Deny"}
            or (rule.get("type") == "Allow" and rule.get("sid") not in allowed)
        ):
            raise _ArchiveRuntimeFailure(ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID)


def _load_canonical_object(
    path: Path,
    maximum: int,
    code: ArchiveRuntimeDiagnosticCode,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_bounded_file(path, maximum, code)
    value = _load_json_value(raw, code)
    if not isinstance(value, dict) or raw != _canonical_json_bytes(value):
        raise _ArchiveRuntimeFailure(code)
    return value, raw


def _load_json_value(raw: bytes, code: ArchiveRuntimeDiagnosticCode) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise ValueError
            result[name] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _ArchiveRuntimeFailure(code) from None


def _read_bounded_file(
    path: Path, maximum: int, code: ArchiveRuntimeDiagnosticCode
) -> bytes:
    try:
        observed = path.lstat()
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or bool(getattr(observed, "st_file_attributes", 0) & 0x400)
            or observed.st_size > maximum
        ):
            raise _ArchiveRuntimeFailure(code)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
                raise _ArchiveRuntimeFailure(code)
        except Exception:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "rb") as handle:
            payload = handle.read(maximum + 1)
    except _ArchiveRuntimeFailure:
        raise
    except OSError:
        raise _ArchiveRuntimeFailure(code) from None
    if len(payload) > maximum:
        raise _ArchiveRuntimeFailure(code)
    return payload


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _normalize_now(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return instant.astimezone(UTC).replace(microsecond=0)


def _parse_utc(
    value: object,
    code: ArchiveRuntimeDiagnosticCode = ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID,
) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise _ArchiveRuntimeFailure(code)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise _ArchiveRuntimeFailure(code) from None


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_digest_reference(value: str) -> bool:
    repository, separator, digest = value.partition("@")
    return (
        repository == ARCHIVE_IMAGE_REFERENCE
        and separator == "@"
        and _DIGEST_RE.fullmatch(digest) is not None
    )


def _unavailable(
    code: ArchiveRuntimeDiagnosticCode,
) -> ArchiveSevenZipRuntimeAvailability:
    return ArchiveSevenZipRuntimeAvailability(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        False,
        "TOOL_UNAVAILABLE",
        diagnostic_code=code,
    )
