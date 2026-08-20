"""Read-only, value-free 7-Zip 26.02 format measurement."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

PROFILE = "archive-7zip-format-measurement/v1"
FIXTURE_PROFILE = "archive-7zip-format-fixtures/v1"
COMMAND = ("l", "-slt", "-ba", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0", "-sccUTF-8")
MAX_STDOUT_BYTES, MAX_LINE_BYTES, MAX_RECORDS, MAX_FIELDS, MAX_FIELD_NAME_BYTES = (
    8_388_608,
    8_192,
    10_000,
    32,
    128,
)
FIXTURE_KEYS = frozenset({"id", "path", "sha256", "format_kind", "record_role", "min_records"})
MANIFEST_KEYS = frozenset({"profile", "fixtures"})
EXPECTED_FIXTURES = {
    "zip": ("ZIP", "DIRECT_MEMBER", "direct/zip.zip"),
    "rar4": ("RAR4", "DIRECT_MEMBER", "rar-test-files/build/testfile.rar3.rar"),
    "rar5": ("RAR5", "DIRECT_MEMBER", "rar-test-files/build/testfile.rar5.rar"),
    "seven_z": ("SEVEN_Z", "DIRECT_MEMBER", "direct/seven-z.7z"),
    "tar": ("TAR", "DIRECT_MEMBER", "direct/tar.tar"),
    "tar_gzip": ("TAR_GZIP", "OUTER_STREAM", "outer/tar.tar.gz"),
    "tar_bzip2": ("TAR_BZIP2", "OUTER_STREAM", "outer/tar.tar.bz2"),
    "tar_xz": ("TAR_XZ", "OUTER_STREAM", "outer/tar.tar.xz"),
    "tar_zstd": ("TAR_ZSTD", "OUTER_STREAM", "outer/tar.tar.zst"),
}
PRIVATE_FIELDS = frozenset({"Path", "Comment", "Symbolic Link", "Hard Link", "User", "Group"})
BOOL_FIELDS = frozenset({"Folder", "Encrypted", "Solid", "Alternate Stream", "Anti"})
UINT, CRC32, TIMESTAMP, FIELD_NAME = (
    re.compile(r"(?:0|[1-9][0-9]*)$"),
    re.compile(r"[0-9A-F]{8}$"),
    re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:.-]+$"),
    re.compile(r"[ -~]+$"),
)


class MeasurementError(RuntimeError):
    """Fixed, path-free measurement error."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise MeasurementError("FIXTURE_PATH_REJECTED")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MeasurementError("FIXTURE_PATH_REJECTED")
    return value


def load_fixture_manifest(root: Path) -> list[dict[str, Any]]:
    try:
        manifest = json.loads((root / "fixture-manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != MANIFEST_KEYS
        or manifest.get("profile") != FIXTURE_PROFILE
    ):
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 9:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    seen: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != FIXTURE_KEYS:
            raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
        identifier, digest = fixture.get("id"), fixture.get("sha256")
        if (
            not isinstance(identifier, str)
            or identifier in seen
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
        relative = _reject_path(fixture["path"])
        if EXPECTED_FIXTURES.get(identifier) != (
            fixture.get("format_kind"),
            fixture.get("record_role"),
            relative,
        ):
            raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
        if not isinstance(fixture.get("min_records"), int) or fixture["min_records"] < 1:
            raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
        candidate = root.joinpath(*Path(relative).parts)
        try:
            info = candidate.lstat()
        except OSError as error:
            raise MeasurementError("FIXTURE_FILE_REJECTED") from error
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or info.st_nlink != 1
            or _sha256(candidate) != digest
        ):
            raise MeasurementError("FIXTURE_FILE_REJECTED")
        seen.add(identifier)
    if seen != set(EXPECTED_FIXTURES):
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    return fixtures


def _lock() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).with_name("archive-image.lock.json")).read_text(encoding="utf-8")
    )


def _verify_image(image: str, lock: dict[str, Any]) -> None:
    expected_manifest = lock["runtime_platform_manifest_digest"]
    expected_config = lock["runtime_config_digest"]
    if image != expected_config:
        raise MeasurementError("IMAGE_REFERENCE_REJECTED")
    inspected = subprocess.run(
        ["docker", "image", "inspect", image],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        value = json.loads(inspected.stdout)
        detail = value[0]
        config = detail["Config"]
        rootfs = detail["RootFS"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise MeasurementError("IMAGE_INSPECT_REJECTED") from error
    descriptor = detail.get("Descriptor")
    if inspected.returncode or detail.get("Id") != expected_config:
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if descriptor is not None and (
        not isinstance(descriptor, dict) or descriptor.get("digest") != expected_manifest
    ):
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if detail.get("Architecture") != "amd64" or detail.get("Os") != "linux":
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if config.get("User") != lock["image_user"] or config.get("Entrypoint") != [
        "/usr/local/bin/7zzs"
    ]:
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if config.get("WorkingDir") != "/workspace" or config.get("Env") != [
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    ]:
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if config.get("Labels") != {
        "org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"
    }:
        raise MeasurementError("IMAGE_INSPECT_REJECTED")
    if rootfs.get("Layers") != [lock["runtime_rootfs_diff_id"], lock["runtime_workdir_diff_id"]]:
        raise MeasurementError("IMAGE_INSPECT_REJECTED")


def docker_argv(image: str, fixture_root: Path, relative_path: str) -> list[str]:
    return [
        "docker",
        "run",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--rm",
        "--user",
        "65532:65532",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "256m",
        "--cpus",
        "1",
        "--mount",
        f"type=bind,src={fixture_root},dst=/fixtures,readonly",
        image,
        *COMMAND,
        "--",
        f"/fixtures/{relative_path}",
    ]


def _classify(field: str, value: str) -> str:
    if not value:
        return "EMPTY"
    if field == "Path":
        return "PRIVATE_LOCATOR_DISCARDED"
    if field in PRIVATE_FIELDS:
        return "PRIVATE_NONEMPTY_DISCARDED"
    if field in BOOL_FIELDS and value == "+":
        return "BOOL_PLUS"
    if field in BOOL_FIELDS and value == "-":
        return "BOOL_MINUS"
    if UINT.fullmatch(value):
        return "CANONICAL_UINT"
    if CRC32.fullmatch(value):
        return "CRC32"
    if TIMESTAMP.fullmatch(value):
        return "TIMESTAMP"
    return "TECHNICAL_NONEMPTY_DISCARDED"


def _lines(stream: Any) -> Iterator[bytes]:
    buffered, total = b"", 0
    while chunk := stream.read1(65_536):
        total += len(chunk)
        if total > MAX_STDOUT_BYTES:
            raise MeasurementError("OUTPUT_LIMIT_EXCEEDED")
        buffered += chunk
        while b"\n" in buffered:
            line, buffered = buffered.split(b"\n", 1)
            if len(line) > MAX_LINE_BYTES:
                raise MeasurementError("OUTPUT_LIMIT_EXCEEDED")
            yield line[:-1] if line.endswith(b"\r") else line
    if buffered:
        raise MeasurementError("OUTPUT_GRAMMAR_REJECTED")


def project_stream(stream: Any, fixture: dict[str, Any]) -> list[dict[str, object]]:
    records, fields, names = [], [], set()
    for raw in _lines(stream):
        if not raw:
            if not fields or len(records) >= MAX_RECORDS:
                raise MeasurementError("OUTPUT_GRAMMAR_REJECTED")
            records.append(
                {
                    "fixture_id": fixture["id"],
                    "fixture_sha256": fixture["sha256"],
                    "format_kind": fixture["format_kind"],
                    "record_role": fixture["record_role"],
                    "exit_code": 0,
                    "record_ordinal": len(records) + 1,
                    "fields": fields,
                }
            )
            fields, names = [], set()
            continue
        if b" = " not in raw:
            raise MeasurementError("OUTPUT_GRAMMAR_REJECTED")
        name_raw, value_raw = raw.split(b" = ", 1)
        if len(name_raw) > MAX_FIELD_NAME_BYTES:
            raise MeasurementError("OUTPUT_LIMIT_EXCEEDED")
        try:
            name, value = name_raw.decode("ascii"), value_raw.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise MeasurementError("OUTPUT_ENCODING_REJECTED") from error
        if not FIELD_NAME.fullmatch(name) or name in names or len(fields) >= MAX_FIELDS:
            raise MeasurementError("OUTPUT_GRAMMAR_REJECTED")
        names.add(name)
        fields.append({"name": name, "value_class": _classify(name, value)})
    if fields or len(records) < fixture["min_records"]:
        raise MeasurementError("RECORD_COUNT_REJECTED")
    return records


def measure(image: str, fixture_root: Path) -> dict[str, object]:
    lock = _lock()
    _verify_image(image, lock)
    try:
        fixture_root = fixture_root.resolve(strict=True)
    except OSError as error:
        raise MeasurementError("FIXTURE_ROOT_REJECTED") from error
    if not fixture_root.is_dir() or fixture_root.is_symlink():
        raise MeasurementError("FIXTURE_ROOT_REJECTED")
    records: list[dict[str, object]] = []
    for fixture in load_fixture_manifest(fixture_root):
        process = subprocess.Popen(
            docker_argv(image, fixture_root, fixture["path"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdout is not None
        try:
            current = project_stream(process.stdout, fixture)
            if process.wait() != 0:
                raise MeasurementError("LISTING_EXIT_REJECTED")
            records.extend(current)
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    return {
        "profile": PROFILE,
        "image_manifest_digest": lock["runtime_platform_manifest_digest"],
        "tool_version": lock["version"],
        "command_profile": "archive-listing/v1",
        "command_sha256": hashlib.sha256("\0".join(COMMAND).encode()).hexdigest(),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--image", required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        args.output.write_bytes(_canonical(measure(args.image, args.fixtures)))
    except MeasurementError as error:
        print(f"measurement_error={error}", file=sys.stderr)
        return 2
    except Exception:
        print("measurement_error=INTERNAL_ERROR", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
