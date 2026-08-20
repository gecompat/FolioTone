#!/usr/bin/env python3
"""Prepare the exact offline context for ``archive-7zip-image/v1``."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tarfile
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE_DATE_EPOCH = 1_782_345_600
RELEASE_TAG_API_URL = "https://api.github.com/repos/ip7z/7zip/git/ref/tags/26.02"
RELEASE_TAG_COMMIT = "f9d78aff31a5f2521ae7ddbdc97c4a8855808959"
MAX_RELEASE_TAG_RESPONSE_BYTES = 65_536
UPSTREAM_URL = "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-linux-x64.tar.xz"
UPSTREAM_SIZE = 1_571_416
UPSTREAM_SHA256 = "41aaba7b1235304ab5aa0624530c67ae829496cd29e875925271efdccc28c03e"
SOURCE_URL = "https://github.com/ip7z/7zip/releases/download/26.02/7z2602-src.tar.xz"
SOURCE_SIZE = 1_543_480
SOURCE_SHA256 = "cf967c98bca02a4b8b16375f441825a8e141362f14be1969bbec8e1ca0bff9dd"
BUILDX_URL = (
    "https://github.com/docker/buildx/releases/download/v0.36.1/"
    "buildx-v0.36.1.linux-amd64"
)
BUILDX_SIZE = 65_302_690
BUILDX_SHA256 = "48af8a397ebd60178778bf63611dbcebe5f5e7a9be90eb9147b24b9587455778"
EXECUTABLE_MEMBER_NAME = "7zzs"
EXECUTABLE_MEMBER_SIZE = 3_763_320
EXECUTABLE_MEMBER_SHA256 = "20df89e993594c1bb7686f125dabe1acc56c109fb1d9b40435ea5fcbc1ca3453"
BINARY_TAR_MEMBERS = {
    "License.txt": (6_029, "1790374e5352329cedb46ee3808930a88e9ca2f08b82b10fcf5cf605d2c301b1"),
    "readme.txt": (3_863, "c3ecf1b8f38631d6ef8a35048e80da77b31cf292a42b3e8793afd44bf4f001b0"),
}
SOURCE_LICENSES = {
    "copying.txt": (
        "https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/copying.txt",
        26_530,
        "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
    ),
    "unRarLicense.txt": (
        "https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/unRarLicense.txt",
        1_921,
        "17bd9fa4399092c777536fff045b41df76ec9d2ac4c9b8e7345d3b8b6ccc7976",
    ),
}


class VerificationError(RuntimeError):
    """An immutable supply-chain input or filesystem invariant failed."""


@dataclass(frozen=True, slots=True)
class PreparedInputs:
    executable_sha256: str
    rootfs_sha256: str
    dockerfile_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, expected_size: int, expected_sha256: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != expected_size:
        raise VerificationError("fixed input size/type verification failed")
    if sha256_file(path) != expected_sha256:
        raise VerificationError("fixed input SHA-256 verification failed")


def acquire(cache: Path, filename: str, url: str, size: int, digest: str) -> Path:
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = cache / filename
    if target.exists():
        verify_file(target, size, digest)
        return target
    temporary = cache / f".{filename}.partial"
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "FolioTone archive-image/v1"})
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            temporary.open("xb") as output,
        ):
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != size:
                raise VerificationError("fixed input Content-Length verification failed")
            observed = 0
            while block := response.read(min(1024 * 1024, size + 1 - observed)):
                observed += len(block)
                if observed > size:
                    raise VerificationError("fixed input exceeded expected size")
                output.write(block)
        verify_file(temporary, size, digest)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def verify_release_tag_commit() -> None:
    request = urllib.request.Request(
        RELEASE_TAG_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FolioTone archive-image/v1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > MAX_RELEASE_TAG_RESPONSE_BYTES:
            raise VerificationError("release-tag response Content-Length exceeds bound")
        payload = response.read(MAX_RELEASE_TAG_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RELEASE_TAG_RESPONSE_BYTES:
        raise VerificationError("release-tag response exceeds bound")
    try:
        result = json.loads(payload)
        target = result["object"]
    except (KeyError, TypeError, ValueError) as error:
        raise VerificationError("release-tag response schema invalid") from error
    if not isinstance(target, dict):
        raise VerificationError("release-tag response target invalid")
    if target.get("sha") != RELEASE_TAG_COMMIT or target.get("type") != "commit":
        raise VerificationError("release tag is not the exact lightweight commit")


def _safe_member_name(name: str) -> None:
    candidate = PurePosixPath(name)
    if not name or candidate.is_absolute() or ".." in candidate.parts or str(candidate) != name:
        raise VerificationError("unsafe tar member name")


def extract_binary_members(upstream_tar: Path, destination: Path) -> dict[str, Path]:
    """Extract only the three exact regular binary-distribution members."""

    expected = {
        EXECUTABLE_MEMBER_NAME: (EXECUTABLE_MEMBER_SIZE, EXECUTABLE_MEMBER_SHA256),
        **BINARY_TAR_MEMBERS,
    }
    selected: dict[str, tarfile.TarInfo] = {}
    outputs: dict[str, Path] = {}
    normalized_names: set[str] = set()
    with tarfile.open(upstream_tar, "r:xz") as archive:
        for member in archive.getmembers():
            _safe_member_name(member.name)
            normalized = unicodedata.normalize("NFC", member.name)
            if normalized in normalized_names:
                raise VerificationError("duplicate normalized tar member")
            normalized_names.add(normalized)
            if member.name in expected:
                if member.name in selected:
                    raise VerificationError("duplicate selected tar member")
                selected[member.name] = member
        if selected.keys() != expected.keys():
            raise VerificationError("required binary-distribution member missing")
        for name in sorted(expected):
            member = selected[name]
            size, digest = expected[name]
            if not member.isreg() or member.linkname or member.size != size:
                raise VerificationError("selected tar member type/size verification failed")
            source = archive.extractfile(member)
            if source is None:
                raise VerificationError("selected tar member extraction failed")
            target = destination / "binary-members" / name
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            with source, target.open("xb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
            verify_file(target, size, digest)
            outputs[name] = target
    return outputs


def verify_static_linux_amd64_elf(path: Path) -> None:
    """Require little-endian ELF64 ET_EXEC without dynamic runtime metadata."""

    data = path.read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4:6] != b"\x02\x01":
        raise VerificationError("7zzs is not little-endian ELF64")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if header[1] != 2 or header[2] != 62:  # ET_EXEC / EM_X86_64
        raise VerificationError("7zzs is not linux-x86-64 ET_EXEC")
    program_offset, program_size, program_count = header[5], header[9], header[10]
    if program_size < 56 or program_offset + program_size * program_count > len(data):
        raise VerificationError("ELF program header bounds invalid")
    for index in range(program_count):
        program_type = struct.unpack_from("<I", data, program_offset + index * program_size)[0]
        if program_type == 3:
            raise VerificationError("7zzs contains PT_INTERP")
        if program_type == 2:
            raise VerificationError("7zzs contains PT_DYNAMIC")
    section_offset, section_size, section_count = header[6], header[11], header[12]
    if section_offset:
        if section_size < 64 or section_offset + section_size * section_count > len(data):
            raise VerificationError("ELF section header bounds invalid")
        for index in range(section_count):
            offset = section_offset + index * section_size
            if struct.unpack_from("<I", data, offset + 4)[0] == 6:
                raise VerificationError("7zzs contains SHT_DYNAMIC/DT_NEEDED")


def _tar_info(name: str, *, directory: bool, size: int = 0, mode: int = 0o555) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.size = size
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = SOURCE_DATE_EPOCH
    return info


def build_rootfs(package_dir: Path, cache: Path, output: Path) -> PreparedInputs:
    """Create the sole Docker-build input as deterministic USTAR."""

    verify_release_tag_commit()
    upstream = acquire(
        cache,
        "7z2602-linux-x64.tar.xz",
        UPSTREAM_URL,
        UPSTREAM_SIZE,
        UPSTREAM_SHA256,
    )
    source_tar = acquire(cache, "7z2602-src.tar.xz", SOURCE_URL, SOURCE_SIZE, SOURCE_SHA256)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = output.parent / "rootfs-staging"
    if staging.exists() or output.exists():
        raise VerificationError("output must be a fresh private workspace")
    staging.mkdir(mode=0o700)
    binary = extract_binary_members(upstream, staging)
    executable = binary[EXECUTABLE_MEMBER_NAME]
    verify_static_linux_amd64_elf(executable)
    source_license_inputs: dict[str, Path] = {}
    for name, (url, size, digest) in SOURCE_LICENSES.items():
        upstream_text = acquire(cache, name, url, size, digest)
        mirror = package_dir / "licenses" / name
        verify_file(mirror, size, digest)
        if mirror.read_bytes() != upstream_text.read_bytes():
            raise VerificationError("source-license mirror hash verification failed")
        source_license_inputs[name] = mirror
    for name, (size, digest) in BINARY_TAR_MEMBERS.items():
        mirror = package_dir / "licenses" / name
        verify_file(mirror, size, digest)
        if mirror.read_bytes() != binary[name].read_bytes():
            raise VerificationError("binary-tar text mirror is not byte-identical")
    files = {
        "usr/local/bin/7zzs": executable,
        "usr/share/licenses/7zip/License.txt": binary["License.txt"],
        "usr/share/licenses/7zip/copying.txt": source_license_inputs["copying.txt"],
        "usr/share/licenses/7zip/unRarLicense.txt": source_license_inputs["unRarLicense.txt"],
        "usr/share/doc/7zip/readme.txt": binary["readme.txt"],
        "usr/share/src/7zip/7z2602-src.tar.xz": source_tar,
    }
    directories = {"workspace", "workspace/input", "workspace/output"}
    for file_name in files:
        parent = PurePosixPath(file_name).parent
        while str(parent) != ".":
            directories.add(str(parent))
            parent = parent.parent
    entries = {name: (True, None) for name in directories}
    entries.update({name: (False, source) for name, source in files.items()})
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(entries, key=lambda value: value.encode("utf-8")):
            directory, source = entries[name]
            mode = 0o555 if directory or name.endswith("/7zzs") else 0o444
            size = 0 if source is None else source.stat().st_size
            info = _tar_info(name, directory=directory, size=size, mode=mode)
            if source is None:
                archive.addfile(info)
            else:
                with source.open("rb") as handle:
                    archive.addfile(info, handle)
    return PreparedInputs(
        sha256_file(executable),
        sha256_file(output),
        sha256_file(package_dir / "Dockerfile"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acquire-buildx", action="store_true")
    arguments = parser.parse_args()
    prepared = build_rootfs(
        Path(__file__).resolve().parent,
        arguments.cache.resolve(),
        arguments.output.resolve(),
    )
    if arguments.acquire_buildx:
        acquire(
            arguments.cache.resolve(),
            "buildx-v0.36.1.linux-amd64",
            BUILDX_URL,
            BUILDX_SIZE,
            BUILDX_SHA256,
        )
    print(f"7zzs_sha256={prepared.executable_sha256}")
    print(f"rootfs_sha256={prepared.rootfs_sha256}")
    print(f"dockerfile_sha256={prepared.dockerfile_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
