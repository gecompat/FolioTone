#!/usr/bin/env python3
"""Strictly inspect the sole FolioTone linux/amd64 OCI runtime manifest."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_GZIP_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
SOURCE_LABEL = "https://github.com/gecompat/FolioTone"
MAX_INDEX_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 16_777_216
MAX_CONFIG_BYTES = 1_048_576
MAX_LAYER_BYTES = 16_777_216
MAX_UNCOMPRESSED_LAYER_BYTES = 32_000_000
SOURCE_DATE_EPOCH = 1_782_345_600
SOURCE_CREATED = "2026-06-25T00:00:00Z"
BUILDKIT_PATH = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
REWRITTEN_TIMESTAMP_ANNOTATION = {"buildkit/rewritten-timestamp": "1782345600"}
ROOTFS_FILES = {
    "usr/local/bin/7zzs": (
        3_763_320,
        "20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453",
        0o555,
    ),
    "usr/share/doc/7zip/readme.txt": (
        3_863,
        "c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0",
        0o444,
    ),
    "usr/share/licenses/7zip/License.txt": (
        6_029,
        "1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1",
        0o444,
    ),
    "usr/share/licenses/7zip/copying.txt": (
        26_530,
        "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
        0o444,
    ),
    "usr/share/licenses/7zip/unRarLicense.txt": (
        1_921,
        "17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976",
        0o444,
    ),
    "usr/share/src/7zip/7z2602-src.tar.xz": (
        1_543_480,
        "cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd",
        0o444,
    ),
}


@dataclass(frozen=True, slots=True)
class OciIdentity:
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


EXPECTED_OCI_IDENTITY = OciIdentity(
    "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287",
    838,
    "sha256:6158a13f41ad2915237fc917abb28a7be373abf060402988898cd85bcd565b9f",
    1_185,
    "sha256:ab909aa86586a73ab10913d9662146ae2442e5ce4b74842b54f0984dd18aad4f",
    3_298_569,
    "sha256:b2af5e745f24985c459fd49b2191807b36364540d53d472db3620e0b4cfc024e",
    "sha256:4f4fb700ef54461cfa02571ae0db9a0dc1e0cdb5577484a6d75e68dc38e8acc1",
    32,
    "sha256:5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef",
)


def _object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _descriptor(
    value: object,
    media_type: str,
    label: str,
    *,
    annotations: dict[str, str] | None = None,
) -> tuple[str, int]:
    expected_fields = {"mediaType", "digest", "size"}
    if annotations is not None:
        expected_fields.add("annotations")
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ValueError(f"{label} descriptor schema invalid")
    digest, size = value.get("digest"), value.get("size")
    if value.get("mediaType") != media_type:
        raise ValueError(f"{label} media type invalid")
    if not isinstance(digest, str) or DIGEST.fullmatch(digest) is None:
        raise ValueError(f"{label} digest invalid")
    if type(size) is not int or size < 0:
        raise ValueError(f"{label} size invalid")
    if annotations is not None and value.get("annotations") != annotations:
        raise ValueError(f"{label} annotations invalid")
    return digest, size


def _read_member(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    name: str,
    maximum: int,
) -> bytes:
    member = members.get(name)
    if member is None or not member.isreg() or member.linkname or member.size > maximum:
        raise ValueError("required OCI blob is missing or invalid")
    handle = archive.extractfile(member)
    if handle is None:
        raise ValueError("required OCI blob cannot be read")
    payload = handle.read(maximum + 1)
    if len(payload) != member.size:
        raise ValueError("OCI member size mismatch")
    return payload


def _blob(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    digest: str,
    size: int,
    maximum: int,
) -> bytes:
    payload = _read_member(
        archive,
        members,
        f"blobs/sha256/{digest.removeprefix('sha256:')}",
        maximum,
    )
    if len(payload) != size or "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("OCI descriptor size/digest mismatch")
    return payload


def _validate_config(config: dict[str, Any]) -> tuple[str, str]:
    if set(config) != {"architecture", "os", "created", "config", "rootfs", "history"}:
        raise ValueError("OCI image config top-level schema invalid")
    if (
        config.get("architecture") != "amd64"
        or config.get("os") != "linux"
        or config.get("created") != SOURCE_CREATED
    ):
        raise ValueError("OCI image config platform mismatch")
    runtime = config.get("config")
    if not isinstance(runtime, dict):
        raise ValueError("OCI runtime config missing")
    if set(runtime) != {"User", "Entrypoint", "WorkingDir", "Env", "Labels"}:
        raise ValueError("OCI runtime config schema invalid")
    if runtime.get("User") != "65532:65532":
        raise ValueError("OCI runtime user mismatch")
    if runtime.get("Entrypoint") != ["/usr/local/bin/7zzs"]:
        raise ValueError("OCI runtime entrypoint mismatch")
    if runtime.get("WorkingDir") != "/workspace":
        raise ValueError("OCI runtime working directory mismatch")
    if runtime.get("Env") != [BUILDKIT_PATH]:
        raise ValueError("OCI runtime singleton BuildKit PATH mismatch")
    if runtime.get("Labels") != {"org.opencontainers.image.source": SOURCE_LABEL}:
        raise ValueError("OCI source label mismatch")
    rootfs = config.get("rootfs")
    if not isinstance(rootfs, dict) or set(rootfs) != {"type", "diff_ids"}:
        raise ValueError("OCI rootfs schema invalid")
    diff_ids = rootfs.get("diff_ids")
    if rootfs.get("type") != "layers" or not isinstance(diff_ids, list) or len(diff_ids) != 2:
        raise ValueError("OCI rootfs must contain exactly two diff ids")
    if any(not isinstance(item, str) or DIGEST.fullmatch(item) is None for item in diff_ids):
        raise ValueError("OCI rootfs diff id invalid")
    expected_history = [
        {
            "created": SOURCE_CREATED,
            "created_by": "ADD rootfs.tar / # buildkit",
            "comment": "buildkit.dockerfile.v0",
        },
        {
            "created": SOURCE_CREATED,
            "created_by": (
                "LABEL org.opencontainers.image.source=https://github.com/gecompat/FolioTone"
            ),
            "comment": "buildkit.dockerfile.v0",
            "empty_layer": True,
        },
        {
            "created": SOURCE_CREATED,
            "created_by": "USER 65532:65532",
            "comment": "buildkit.dockerfile.v0",
            "empty_layer": True,
        },
        {
            "created": SOURCE_CREATED,
            "created_by": "WORKDIR /workspace",
            "comment": "buildkit.dockerfile.v0",
        },
        {
            "created": SOURCE_CREATED,
            "created_by": 'ENTRYPOINT ["/usr/local/bin/7zzs"]',
            "comment": "buildkit.dockerfile.v0",
            "empty_layer": True,
        },
    ]
    if config.get("history") != expected_history:
        raise ValueError("OCI five-entry history mismatch")
    return diff_ids[0], diff_ids[1]


def _validate_rootfs_layer(payload: bytes) -> None:
    expected_directories = {"workspace", "workspace/input", "workspace/output"}
    for file_name in ROOTFS_FILES:
        parent = Path(file_name).parent
        while str(parent) != ".":
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        members = archive.getmembers()
        names = [member.name.rstrip("/") for member in members]
        if len(names) != len(set(names)):
            raise ValueError("rootfs layer contains duplicate members")
        if set(names) != expected_directories | set(ROOTFS_FILES):
            raise ValueError("rootfs layer content set mismatch")
        for member, name in zip(members, names, strict=True):
            if (
                member.uid != 0
                or member.gid != 0
                or member.uname
                or member.gname
                or member.mtime != SOURCE_DATE_EPOCH
                or member.linkname
                or member.pax_headers
            ):
                raise ValueError("rootfs layer metadata mismatch")
            if name in expected_directories:
                if not member.isdir() or member.mode != 0o555:
                    raise ValueError("rootfs directory type/mode mismatch")
                continue
            size, digest, mode = ROOTFS_FILES[name]
            if not member.isreg() or member.size != size or member.mode != mode:
                raise ValueError("rootfs file type/size/mode mismatch")
            handle = archive.extractfile(member)
            if handle is None or hashlib.sha256(handle.read(size + 1)).hexdigest() != digest:
                raise ValueError("rootfs file digest mismatch")


def inspect_oci_layout(oci_tar: Path) -> OciIdentity:
    with tarfile.open(oci_tar, "r:") as archive:
        listed = archive.getmembers()
        names = [member.name.rstrip("/") for member in listed]
        if len(names) != len(set(names)):
            raise ValueError("OCI tar contains duplicate members")
        if any(not (member.isreg() or member.isdir()) for member in listed):
            raise ValueError("OCI tar contains a forbidden member type")
        members = {name: member for name, member in zip(names, listed, strict=True)}
        layout = _object(_read_member(archive, members, "oci-layout", 1_024), "OCI layout")
        if layout != {"imageLayoutVersion": "1.0.0"}:
            raise ValueError("OCI layout version invalid")
        index = _object(
            _read_member(archive, members, "index.json", MAX_INDEX_BYTES),
            "OCI index",
        )
        if set(index) != {"schemaVersion", "mediaType", "manifests"}:
            raise ValueError("OCI index schema invalid")
        manifests = index.get("manifests")
        if (
            index.get("schemaVersion") != 2
            or index.get("mediaType") != OCI_INDEX
            or not isinstance(manifests, list)
            or len(manifests) != 1
        ):
            raise ValueError("OCI index must contain one manifest")
        descriptor = manifests[0]
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "mediaType",
            "digest",
            "size",
            "annotations",
            "platform",
        }:
            raise ValueError("OCI platform descriptor schema invalid")
        if descriptor.get("annotations") != {
            "org.opencontainers.image.created": SOURCE_CREATED
        }:
            raise ValueError("OCI platform created annotation mismatch")
        platform = descriptor.get("platform")
        if platform != {"architecture": "amd64", "os": "linux"}:
            raise ValueError("OCI manifest platform must be exactly linux/amd64")
        manifest_digest = descriptor.get("digest")
        manifest_size = descriptor.get("size")
        if (
            descriptor.get("mediaType") != OCI_MANIFEST
            or not isinstance(manifest_digest, str)
            or DIGEST.fullmatch(manifest_digest) is None
            or type(manifest_size) is not int
            or manifest_size < 0
        ):
            raise ValueError("OCI platform descriptor identity invalid")
        manifest = _object(
            _blob(
                archive,
                members,
                manifest_digest,
                manifest_size,
                MAX_MANIFEST_BYTES,
            ),
            "OCI manifest",
        )
        if set(manifest) != {"schemaVersion", "mediaType", "config", "layers"}:
            raise ValueError("OCI manifest schema invalid")
        layers = manifest.get("layers")
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != OCI_MANIFEST
            or not isinstance(layers, list)
            or len(layers) != 2
        ):
            raise ValueError("OCI manifest must contain the two fixed layers")
        config_digest, config_size = _descriptor(manifest.get("config"), OCI_CONFIG, "config")
        rootfs_layer_digest, rootfs_layer_size = _descriptor(
            layers[0],
            OCI_GZIP_LAYER,
            "rootfs layer",
            annotations=REWRITTEN_TIMESTAMP_ANNOTATION,
        )
        workdir_layer_digest, workdir_layer_size = _descriptor(
            layers[1],
            OCI_GZIP_LAYER,
            "WORKDIR layer",
            annotations=REWRITTEN_TIMESTAMP_ANNOTATION,
        )
        config = _object(
            _blob(archive, members, config_digest, config_size, MAX_CONFIG_BYTES),
            "OCI image config",
        )
        rootfs_diff_id, workdir_diff_id = _validate_config(config)
        compressed_rootfs_layer = _blob(
            archive,
            members,
            rootfs_layer_digest,
            rootfs_layer_size,
            MAX_LAYER_BYTES,
        )
        with gzip.GzipFile(fileobj=io.BytesIO(compressed_rootfs_layer), mode="rb") as stream:
            rootfs_payload = stream.read(MAX_UNCOMPRESSED_LAYER_BYTES + 1)
        if len(rootfs_payload) > MAX_UNCOMPRESSED_LAYER_BYTES:
            raise ValueError("OCI rootfs layer exceeds uncompressed bound")
        if "sha256:" + hashlib.sha256(rootfs_payload).hexdigest() != rootfs_diff_id:
            raise ValueError("OCI rootfs diff id mismatch")
        _validate_rootfs_layer(rootfs_payload)
        compressed_workdir_layer = _blob(
            archive,
            members,
            workdir_layer_digest,
            workdir_layer_size,
            MAX_LAYER_BYTES,
        )
        with gzip.GzipFile(fileobj=io.BytesIO(compressed_workdir_layer), mode="rb") as stream:
            workdir_payload = stream.read(1_025)
        if workdir_payload != bytes(1_024):
            raise ValueError("OCI WORKDIR layer is not the canonical empty tar")
        if "sha256:" + hashlib.sha256(workdir_payload).hexdigest() != workdir_diff_id:
            raise ValueError("OCI WORKDIR layer diff id mismatch")
        expected_regular = {
            "oci-layout",
            "index.json",
            f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}",
            f"blobs/sha256/{config_digest.removeprefix('sha256:')}",
            f"blobs/sha256/{rootfs_layer_digest.removeprefix('sha256:')}",
            f"blobs/sha256/{workdir_layer_digest.removeprefix('sha256:')}",
        }
        if {member.name for member in listed if member.isreg()} != expected_regular:
            raise ValueError("OCI layout contains an unexpected regular artifact")
        directory_names = {name for name, member in members.items() if member.isdir()}
        if not directory_names <= {"blobs", "blobs/sha256"}:
            raise ValueError("OCI layout contains an unexpected directory")
        identity = OciIdentity(
            manifest_digest,
            manifest_size,
            config_digest,
            config_size,
            rootfs_layer_digest,
            rootfs_layer_size,
            rootfs_diff_id,
            workdir_layer_digest,
            workdir_layer_size,
            workdir_diff_id,
        )
        if identity != EXPECTED_OCI_IDENTITY:
            raise ValueError("OCI Stage-1 identity mismatch")
        return identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("oci_tar", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(asdict(inspect_oci_layout(arguments.oci_tar.resolve())), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
