"""Acquire and safely unpack the locked Linux/amd64 e-book toolchain."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

CHUNK_BYTES = 1024 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class Component(TypedDict):
    id: str
    version: str
    archive: str
    url: str
    sha256: str
    size_bytes: int
    format: str
    strip_components: int
    license: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    components = _load_lock(args.lock)
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    for component in components:
        archive = args.cache / component["archive"]
        _acquire(component, archive)
        destination = args.output / component["id"]
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        _extract(component, archive, destination)
    return 0


def _load_lock(path: Path) -> tuple[Component, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("profile") != "ebook-toolchain-linux-amd64/v1":
        raise ValueError("unexpected toolchain profile")
    if data.get("platform") != "linux/amd64":
        raise ValueError("unexpected toolchain platform")
    raw_components = data.get("components")
    if not isinstance(raw_components, list):
        raise ValueError("components must be a list")
    components = tuple(cast(Component, item) for item in raw_components)
    if tuple(item["id"] for item in components) != (
        "calibre",
        "poppler",
        "temurin-jre",
        "epubcheck",
    ):
        raise ValueError("toolchain components or ordering are unexpected")
    for item in components:
        if not item["url"].startswith("https://"):
            raise ValueError("component URL must use HTTPS")
        if SHA256_PATTERN.fullmatch(item["sha256"]) is None:
            raise ValueError("component SHA-256 is invalid")
        if item["size_bytes"] <= 0:
            raise ValueError("component size must be positive")
        if item["format"] not in {"tar.xz", "tar.gz", "zip"}:
            raise ValueError("component archive format is unsupported")
        if item["strip_components"] not in {0, 1}:
            raise ValueError("component strip_components is unsupported")
    return components


def _acquire(component: Component, destination: Path) -> None:
    if destination.is_file() and _matches_lock(destination, component):
        return
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(  # noqa: S310 - URL is validated against the lock
        component["url"],
        headers={"User-Agent": "FolioTone-ebook-toolchain/1"},
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,  # noqa: S310
            temporary.open("xb") as out,
        ):
            if not response.geturl().startswith("https://"):
                raise ValueError(f'{component["id"]} download redirected away from HTTPS')
            while chunk := response.read(CHUNK_BYTES):
                size += len(chunk)
                if size > component["size_bytes"]:
                    raise ValueError(f'{component["id"]} download exceeds locked size')
                digest.update(chunk)
                out.write(chunk)
        if size != component["size_bytes"]:
            raise ValueError(f'{component["id"]} download size differs from lock')
        if digest.hexdigest() != component["sha256"]:
            raise ValueError(f'{component["id"]} download SHA-256 differs from lock')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _matches_lock(path: Path, component: Component) -> bool:
    if path.stat().st_size != component["size_bytes"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest() == component["sha256"]


def _extract(component: Component, archive: Path, destination: Path) -> None:
    if component["format"] == "zip":
        _extract_zip(archive, destination, component["strip_components"])
        return
    mode = "r:xz" if component["format"] == "tar.xz" else "r:gz"
    with tarfile.open(archive, mode) as bundle:
        members = tuple(
            _stripped_tar_member(member, component["strip_components"])
            for member in bundle.getmembers()
        )
        bundle.extractall(  # noqa: S202 - every member is normalized and confined below
            destination,
            members=(member for member in members if member is not None),
            filter="data",
        )


def _stripped_tar_member(member: tarfile.TarInfo, strip: int) -> tarfile.TarInfo | None:
    relative = _stripped_path(member.name, strip)
    if relative is None:
        return None
    result = copy.copy(member)
    result.name = relative.as_posix()
    if result.issym() or result.islnk():
        _validate_link_target(relative, result.linkname)
    return result


def _extract_zip(archive: Path, destination: Path, strip: int) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            relative = _stripped_path(info.filename, strip)
            if relative is None:
                continue
            target = destination.joinpath(*relative.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_BYTES)


def _stripped_path(value: str, strip: int) -> PurePosixPath | None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("archive member escapes destination")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if len(parts) <= strip:
        return None
    relative = PurePosixPath(*parts[strip:])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("archive member escapes destination")
    return relative


def _validate_link_target(member: PurePosixPath, target: str) -> None:
    link = PurePosixPath(target)
    if link.is_absolute():
        raise ValueError("archive link target must be relative")
    combined = member.parent.joinpath(link)
    depth = 0
    for part in combined.parts:
        depth += -1 if part == ".." else 1
        if depth < 0:
            raise ValueError("archive link target escapes destination")


if __name__ == "__main__":
    raise SystemExit(main())
