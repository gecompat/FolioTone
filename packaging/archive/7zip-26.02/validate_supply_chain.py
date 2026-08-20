#!/usr/bin/env python3
"""Strict local gate for the archive image lock, SBOM, recipe and mirrors."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
LICENSE_DIR = PACKAGE_DIR / "licenses"
REPOSITORY_ROOT = PACKAGE_DIR.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from foliotone.archive.sevenzip import (  # noqa: E402
    ArchiveImageBootstrapLockedLock,
    ArchiveImageLockState,
    load_archive_image_lock,
)

COMPOUND_LICENSE = (
    "LGPL-2.1-or-later AND BSD-2-Clause AND BSD-3-Clause "
    "AND LicenseRef-unRAR-restriction"
)
FILE_IDENTITIES = {
    "/usr/local/bin/7zzs": "20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453",
    "/usr/share/licenses/7zip/License.txt": (
        "1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1"
    ),
    "/usr/share/licenses/7zip/copying.txt": (
        "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
    ),
    "/usr/share/licenses/7zip/unRarLicense.txt": (
        "17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976"
    ),
    "/usr/share/doc/7zip/readme.txt": (
        "c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0"
    ),
    "/usr/share/src/7zip/7z2602-src.tar.xz": (
        "cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd"
    ),
    "/oci/blobs/sha256/26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287": (
        "26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
    ),
    "/oci/blobs/sha256/6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f": (
        "6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f"
    ),
    "/oci/blobs/sha256/ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f": (
        "ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f"
    ),
    "/oci/blobs/sha256/4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1": (
        "4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1"
    ),
}
LICENSE_MIRRORS = {
    "License.txt": FILE_IDENTITIES["/usr/share/licenses/7zip/License.txt"],
    "copying.txt": FILE_IDENTITIES["/usr/share/licenses/7zip/copying.txt"],
    "unRarLicense.txt": FILE_IDENTITIES["/usr/share/licenses/7zip/unRarLicense.txt"],
    "readme.txt": FILE_IDENTITIES["/usr/share/doc/7zip/readme.txt"],
}
EXPECTED_RELATIONSHIPS = {
    ("SPDXRef-DOCUMENT", "DESCRIBES", "SPDXRef-RuntimeImage"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-7Zip"),
    ("SPDXRef-7Zip", "GENERATED_FROM", "SPDXRef-7ZipSource"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-7zzs"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-License"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-Copying"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-UnRarLicense"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-Readme"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-SourceTar"),
    ("SPDXRef-7ZipSource", "CONTAINS", "SPDXRef-SourceTar"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-OciManifest"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-OciConfig"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-OciRootfsLayer"),
    ("SPDXRef-RuntimeImage", "CONTAINS", "SPDXRef-OciWorkdirLayer"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def validate(rootfs: Path | None) -> None:
    lock_path = PACKAGE_DIR / "archive-image.lock.json"
    lock_raw = _object(lock_path)
    lock = load_archive_image_lock(lock_path)
    if lock is None:
        raise ValueError("archive image lock is not closed-schema valid")
    if _sha256(PACKAGE_DIR / "Dockerfile") != lock_raw["dockerfile_sha256"]:
        raise ValueError("Dockerfile digest does not match lock")
    sbom_path = PACKAGE_DIR / "archive-image.spdx.json"
    if _sha256(sbom_path) != lock_raw["sbom_sha256"]:
        raise ValueError("SBOM digest does not match lock")
    if rootfs is not None and _sha256(rootfs) != lock_raw["rootfs_tar_sha256"]:
        raise ValueError("rootfs digest does not match lock")
    for name, digest in LICENSE_MIRRORS.items():
        if _sha256(PACKAGE_DIR / "licenses" / name) != digest:
            raise ValueError("license mirror digest mismatch")
    sbom = _object(sbom_path)
    if set(sbom) != {
        "spdxVersion",
        "dataLicense",
        "SPDXID",
        "name",
        "documentNamespace",
        "creationInfo",
        "documentDescribes",
        "packages",
        "files",
        "hasExtractedLicensingInfos",
        "relationships",
    }:
        raise ValueError("SPDX document schema is not closed")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("dataLicense") != "CC0-1.0"
        or sbom.get("SPDXID") != "SPDXRef-DOCUMENT"
        or sbom.get("name")
        != (
            "foliotone-archive-7zip-26.02-bootstrap"
            if lock.state is ArchiveImageLockState.BOOTSTRAP_PENDING
            else "foliotone-archive-7zip-26.02-locked"
        )
        or sbom.get("creationInfo")
        != {
            "creators": ["Tool: FolioTone archive-7zip-image/v1"],
            "created": "2026-06-25T00:00:00Z",
        }
        or sbom.get("documentDescribes") != ["SPDXRef-RuntimeImage"]
    ):
        raise ValueError("SPDX document identity invalid")
    namespace_suffix = (
        "bootstrap-pending"
        if lock.state is ArchiveImageLockState.BOOTSTRAP_PENDING
        else lock_raw["runtime_platform_manifest_digest"].replace(":", "-")
    )
    if sbom.get("documentNamespace") != (
        f"https://github.com/gecompat/FolioTone/archive-7zip-image/v1/{namespace_suffix}"
    ):
        raise ValueError("SPDX namespace does not match lock state")
    packages = sbom.get("packages")
    if not isinstance(packages, list) or len(packages) != 3:
        raise ValueError("SPDX package set invalid")
    package_by_id = {item.get("SPDXID"): item for item in packages if isinstance(item, dict)}
    if set(package_by_id) != {"SPDXRef-RuntimeImage", "SPDXRef-7Zip", "SPDXRef-7ZipSource"}:
        raise ValueError("SPDX package identifiers invalid")
    if any(
        package_by_id[identifier].get("licenseDeclared") != COMPOUND_LICENSE
        or package_by_id[identifier].get("licenseConcluded") != COMPOUND_LICENSE
        for identifier in package_by_id
    ):
        raise ValueError("SPDX compound licensing invalid")
    sevenzip = package_by_id["SPDXRef-7Zip"]
    source = package_by_id["SPDXRef-7ZipSource"]
    if (
        sevenzip.get("name") != "7-Zip"
        or sevenzip.get("versionInfo") != "26.02"
        or sevenzip.get("downloadLocation") != lock_raw["upstream_url"]
        or sevenzip.get("checksums")
        != [{"algorithm": "SHA256", "checksumValue": lock_raw["upstream_sha256"]}]
        or source.get("name") != "7-Zip source"
        or source.get("versionInfo") != "26.02"
        or source.get("downloadLocation") != lock_raw["source_tar_url"]
        or source.get("checksums")
        != [{"algorithm": "SHA256", "checksumValue": lock_raw["source_tar_sha256"]}]
    ):
        raise ValueError("SPDX upstream package identity invalid")
    runtime = package_by_id["SPDXRef-RuntimeImage"]
    expected_comment = (
        f"archive-image-lock/v1 state={lock.state.value} "
        f"runtime_platform_manifest_digest={lock_raw['runtime_platform_manifest_digest']}"
    )
    if runtime.get("comment") != expected_comment:
        raise ValueError("SPDX runtime lock identity mismatch")
    if isinstance(lock, ArchiveImageBootstrapLockedLock):
        expected_download = (
            "ghcr.io/gecompat/foliotone-archive-7zip@"
            f"{lock.runtime_platform_manifest_digest}"
        )
        if runtime.get("downloadLocation") != expected_download:
            raise ValueError("locked SPDX runtime reference mismatch")
        if runtime.get("checksums") != [
            {
                "algorithm": "SHA256",
                "checksumValue": lock.runtime_platform_manifest_digest.removeprefix(
                    "sha256:"
                ),
            }
        ]:
            raise ValueError("locked SPDX runtime manifest checksum mismatch")
    elif runtime.get("downloadLocation") != "NOASSERTION":
        raise ValueError("pending SPDX runtime reference must remain unasserted")
    files = sbom.get("files")
    if not isinstance(files, list) or len(files) != len(FILE_IDENTITIES):
        raise ValueError("SPDX file set invalid")
    observed: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("checksums"), list):
            raise ValueError("SPDX file schema invalid")
        if set(item) != {
            "fileName",
            "SPDXID",
            "checksums",
            "licenseConcluded",
            "licenseInfoInFiles",
            "copyrightText",
        }:
            raise ValueError("SPDX file schema is not closed")
        checksums = item["checksums"]
        if len(checksums) != 1 or checksums[0].get("algorithm") != "SHA256":
            raise ValueError("SPDX file checksum schema invalid")
        observed[item.get("fileName")] = checksums[0].get("checksumValue")
    if observed != FILE_IDENTITIES:
        raise ValueError("SPDX file identities invalid")
    extracted = sbom.get("hasExtractedLicensingInfos")
    if (
        not isinstance(extracted, list)
        or len(extracted) != 1
        or extracted[0].get("licenseId") != "LicenseRef-unRAR-restriction"
        or extracted[0].get("extractedText")
        != (LICENSE_DIR / "unRarLicense.txt").read_text(encoding="utf-8")
    ):
        raise ValueError("SPDX extracted LicenseRef invalid")
    relationships = sbom.get("relationships")
    if not isinstance(relationships, list) or len(relationships) != len(EXPECTED_RELATIONSHIPS):
        raise ValueError("SPDX relationship set invalid")
    tuples = {
        (item.get("spdxElementId"), item.get("relationshipType"), item.get("relatedSpdxElement"))
        for item in relationships
        if isinstance(item, dict)
    }
    if tuples != EXPECTED_RELATIONSHIPS:
        raise ValueError("SPDX relationships invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", type=Path)
    arguments = parser.parse_args()
    validate(None if arguments.rootfs is None else arguments.rootfs.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
