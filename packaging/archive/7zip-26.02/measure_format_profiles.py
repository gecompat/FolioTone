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
PROFILE_V2 = "archive-7zip-format-measurement/v2"
FIXTURE_PROFILE = "archive-7zip-format-fixtures/v1"
FIXTURE_PROFILE_V2 = "archive-7zip-format-fixtures/v2"
COMMAND = ("l", "-slt", "-ba", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0", "-sccUTF-8")
MAX_STDOUT_BYTES, MAX_LINE_BYTES, MAX_RECORDS, MAX_FIELDS, MAX_FIELD_NAME_BYTES = (
    8_388_608,
    8_192,
    10_000,
    32,
    128,
)
FIXTURE_KEYS = frozenset({"id", "path", "sha256", "format_kind", "record_role", "min_records"})
FIXTURE_KEYS_V2 = FIXTURE_KEYS | frozenset({"case_kind", "provenance_ref"})
MANIFEST_KEYS = frozenset({"profile", "fixtures"})
MANIFEST_KEYS_V2 = frozenset({"profile", "fixtures", "matrix"})
MATRIX_KEYS = frozenset({"format_kind", "case_kind", "disposition", "evidence_ref"})
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
DIRECT_FORMATS = frozenset({"ZIP", "RAR4", "RAR5", "SEVEN_Z", "TAR"})
CASE_KINDS = frozenset(
    {
        "PLAINTEXT_REGULAR",
        "DIRECTORY",
        "ALL_ENCRYPTED",
        "MIXED",
        "ENCRYPTED_DIRECTORY",
        "SYMBOLIC_LINK",
        "HARD_LINK",
        "COPY_LINK",
    }
)
DISPOSITIONS = frozenset({"MEASURED", "FORMAT_UNSUPPORTED", "EVIDENCE_UNAVAILABLE"})
V2_FIXTURE_IDS = frozenset(
    {
        "zip_plaintext",
        "rar4_plaintext",
        "rar5_plaintext",
        "seven_z_plaintext",
        "tar_plaintext",
        "zip_directory",
        "seven_z_directory",
        "tar_directory",
        "zip_all_encrypted",
        "seven_z_all_encrypted",
        "zip_mixed",
        "seven_z_mixed",
        "tar_symbolic_link",
        "tar_hard_link",
        "tar_gzip_drift",
        "tar_bzip2_drift",
        "tar_xz_drift",
        "tar_zstd_drift",
    }
)
FIXTURE_MANIFEST_V2_SHA256 = "d61bb6ca361bb4cc93b091233199e7031f1aa462b823d0cd6d2cc70130b1ce84"
DETERMINISTIC_PROVENANCE_SHA256 = "89c7c4a03a3aff522d0076313c7f6d0c04f1d71989b8eba63b8d5aa0ada23888"
CURATION_PROVENANCE_SHA256 = "da3db4f15acd1530ae3649906d621633ffb541f56a5b9c2236c7a88665ce1a54"
PRIVATE_FIELDS = frozenset(
    {"Path", "Comment", "Symbolic Link", "Hard Link", "Copy Link", "User", "Group"}
)
BOOL_FIELDS = frozenset(
    {
        "Folder",
        "Encrypted",
        "Solid",
        "Alternate Stream",
        "Anti",
        "Commented",
        "Split Before",
        "Split After",
    }
)
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
        raw = (root / "fixture-manifest.json").read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED") from error
    if not isinstance(manifest, dict):
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    profile = manifest.get("profile")
    if profile == FIXTURE_PROFILE:
        keys, fixture_keys, expected_count = MANIFEST_KEYS, FIXTURE_KEYS, 9
    elif profile == FIXTURE_PROFILE_V2:
        keys, fixture_keys, expected_count = MANIFEST_KEYS_V2, FIXTURE_KEYS_V2, 18
        if (
            raw != _canonical(manifest)
            or hashlib.sha256(raw).hexdigest() != FIXTURE_MANIFEST_V2_SHA256
        ):
            raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    else:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    if set(manifest) != keys:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != expected_count:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    seen: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != fixture_keys:
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
        if profile == FIXTURE_PROFILE:
            if EXPECTED_FIXTURES.get(identifier) != (
                fixture.get("format_kind"),
                fixture.get("record_role"),
                relative,
            ):
                raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
        else:
            case_kind, provenance = fixture.get("case_kind"), fixture.get("provenance_ref")
            direct = fixture.get("record_role") == "DIRECT_MEMBER"
            if (
                identifier not in V2_FIXTURE_IDS
                or not isinstance(provenance, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9./-]{2,127}", provenance)
                or (direct and case_kind not in CASE_KINDS)
                or (not direct and case_kind != "OUTER_STREAM_DRIFT")
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
        by_id[identifier] = fixture
    expected_ids = set(EXPECTED_FIXTURES) if profile == FIXTURE_PROFILE else set(V2_FIXTURE_IDS)
    if seen != expected_ids:
        raise MeasurementError("FIXTURE_MANIFEST_REJECTED")
    if profile == FIXTURE_PROFILE_V2:
        _validate_v2_matrix(manifest.get("matrix"), by_id)
        _validate_deterministic_provenance(root, by_id)
        _validate_curation_provenance(root, by_id)
    return fixtures


def _validate_v2_matrix(value: object, fixtures: dict[str, dict[str, Any]]) -> None:
    if not isinstance(value, list) or len(value) != len(DIRECT_FORMATS) * len(CASE_KINDS):
        raise MeasurementError("FIXTURE_MATRIX_REJECTED")
    seen: set[tuple[str, str]] = set()
    referenced: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != MATRIX_KEYS:
            raise MeasurementError("FIXTURE_MATRIX_REJECTED")
        format_kind, case_kind = item.get("format_kind"), item.get("case_kind")
        disposition, evidence_ref = item.get("disposition"), item.get("evidence_ref")
        key = (format_kind, case_kind)
        if (
            format_kind not in DIRECT_FORMATS
            or case_kind not in CASE_KINDS
            or disposition not in DISPOSITIONS
            or key in seen
            or not isinstance(evidence_ref, str)
            or not re.fullmatch(
                r"(?:fixture|source|boundary):[A-Za-z0-9_./,:-]{3,160}",
                evidence_ref,
            )
        ):
            raise MeasurementError("FIXTURE_MATRIX_REJECTED")
        seen.add(key)
        if disposition == "MEASURED":
            if not evidence_ref.startswith("fixture:"):
                raise MeasurementError("FIXTURE_MATRIX_REJECTED")
            fixture_id = evidence_ref.removeprefix("fixture:")
            fixture = fixtures.get(fixture_id)
            if fixture is None or (fixture["format_kind"], fixture["case_kind"]) != key:
                raise MeasurementError("FIXTURE_MATRIX_REJECTED")
            referenced.add(fixture_id)
        elif evidence_ref.startswith("fixture:"):
            raise MeasurementError("FIXTURE_MATRIX_REJECTED")
    expected = {
        (format_kind, case_kind)
        for format_kind in DIRECT_FORMATS
        for case_kind in CASE_KINDS
    }
    if seen != expected:
        raise MeasurementError("FIXTURE_MATRIX_REJECTED")
    direct_ids = {
        fixture_id
        for fixture_id, fixture in fixtures.items()
        if fixture["record_role"] == "DIRECT_MEMBER"
    }
    if referenced != direct_ids:
        raise MeasurementError("FIXTURE_MATRIX_REJECTED")


def _validate_curation_provenance(root: Path, fixtures: dict[str, dict[str, Any]]) -> None:
    path = root / "curation-provenance.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED") from error
    if (
        len(raw) > 32_768
        or raw != _canonical(value)
        or hashlib.sha256(raw).hexdigest() != CURATION_PROVENANCE_SHA256
        or not isinstance(value, dict)
        or value.get("profile") != "archive-7zip-public-fixture-provenance/v2"
        or value.get("command_profile") != "archive-7zip-public-encrypted-fixture-curation/v2"
        or value.get("public_password") != "PUBLIC-FIXTURE-NOT-A-SECRET-v2"
        or value.get("image_manifest_digest")
        != "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
        or value.get("tool_version") != "26.02"
        or value.get("environment", {}).get("timezone") != "UTC"
        or value.get("redistribution", {}).get("status") != "ALLOWED"
    ):
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    archives = value.get("archives")
    if not isinstance(archives, dict) or set(archives) != {
        "zip-all-encrypted.zip",
        "zip-mixed.zip",
        "seven-z-all-encrypted.7z",
        "seven-z-mixed.7z",
    }:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    commands = {name: archive.get("commands") for name, archive in sorted(archives.items())}
    if value.get("commands_sha256") != hashlib.sha256(_canonical(commands)).hexdigest():
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    expected_ref = f"public-curated-encrypted/{CURATION_PROVENANCE_SHA256}"
    curated_paths = {
        fixture["path"]
        for fixture in fixtures.values()
        if fixture.get("provenance_ref") == expected_ref
    }
    if curated_paths != set(archives):
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    for fixture in fixtures.values():
        if fixture.get("provenance_ref") != expected_ref:
            continue
        archive = archives.get(fixture["path"])
        if not isinstance(archive, dict) or archive.get("sha256") != fixture["sha256"]:
            raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")


def _validate_deterministic_provenance(
    root: Path, fixtures: dict[str, dict[str, Any]]
) -> None:
    path = root / "deterministic-provenance.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED") from error
    if (
        len(raw) > 32_768
        or raw != _canonical(value)
        or hashlib.sha256(raw).hexdigest() != DETERMINISTIC_PROVENANCE_SHA256
        or not isinstance(value, dict)
        or value.get("profile")
        != "archive-7zip-deterministic-fixture-provenance/v2"
        or value.get("generator_profile")
        != "archive-7zip-public-deterministic-fixture-generation/v2"
        or value.get("redistribution", {}).get("status") != "ALLOWED"
        or value.get("python_generator", {}).get("timezone") != "UTC"
        or value.get("python_generator", {}).get("workdir") != "/work"
        or value.get("seven_zip_generator", {}).get("timezone") != "UTC"
    ):
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    generator = value.get("python_generator")
    seven_zip = value.get("seven_zip_generator")
    if not isinstance(generator, dict) or not isinstance(seven_zip, dict):
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    source = root / str(generator.get("source_path"))
    try:
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError as error:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED") from error
    if source_digest != generator.get("source_sha256"):
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    commands = {
        "python_generator": generator.get("command"),
        "seven_zip_generator": seven_zip.get("command"),
    }
    if value.get("commands_sha256") != hashlib.sha256(_canonical(commands)).hexdigest():
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    recorded = value.get("fixtures")
    expected_paths = {
        "zip-plaintext.zip",
        "zip-directory.zip",
        "seven-z-directory.7z",
        "tar-directory.tar",
        "tar-symbolic-link.tar",
        "tar-hard-link.tar",
    }
    if not isinstance(recorded, dict) or set(recorded) != expected_paths:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    expected_ref = f"deterministic-public/{DETERMINISTIC_PROVENANCE_SHA256}"
    bound = {
        fixture["path"]: fixture["sha256"]
        for fixture in fixtures.values()
        if fixture.get("provenance_ref") == expected_ref
    }
    if set(bound) != expected_paths:
        raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")
    for name, digest in bound.items():
        item = recorded.get(name)
        if not isinstance(item, dict) or item.get("output_sha256_runs") != [
            digest,
            digest,
        ]:
            raise MeasurementError("FIXTURE_PROVENANCE_REJECTED")


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


def _classify(field: str, value: str, *, strict_bool: bool = True) -> str:
    if field in BOOL_FIELDS:
        if value == "+":
            return "BOOL_PLUS"
        if value == "-":
            return "BOOL_MINUS"
        if strict_bool:
            raise MeasurementError("BOOL_VALUE_REJECTED")
    if not value:
        return "EMPTY"
    if field == "Path":
        return "PRIVATE_LOCATOR_DISCARDED"
    if field in PRIVATE_FIELDS:
        return "PRIVATE_NONEMPTY_DISCARDED"
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
            record = {
                "fixture_id": fixture["id"],
                "fixture_sha256": fixture["sha256"],
                "format_kind": fixture["format_kind"],
                "record_role": fixture["record_role"],
                "exit_code": 0,
                "record_ordinal": len(records) + 1,
                "fields": fields,
            }
            if "case_kind" in fixture:
                record["case_kind"] = fixture["case_kind"]
            records.append(record)
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
        fields.append(
            {
                "name": name,
                "value_class": _classify(
                    name,
                    value,
                    strict_bool="case_kind" in fixture,
                ),
            }
        )
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
    fixtures = load_fixture_manifest(fixture_root)
    for fixture in fixtures:
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
    result: dict[str, object] = {
        "profile": PROFILE_V2 if fixtures and "case_kind" in fixtures[0] else PROFILE,
        "image_manifest_digest": lock["runtime_platform_manifest_digest"],
        "tool_version": lock["version"],
        "command_profile": "archive-listing/v1",
        "command_sha256": hashlib.sha256("\0".join(COMMAND).encode()).hexdigest(),
        "records": records,
    }
    if fixtures and "case_kind" in fixtures[0]:
        manifest_raw = (fixture_root / "fixture-manifest.json").read_bytes()
        manifest = json.loads(manifest_raw)
        result.update(
            {
                "fixture_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                "matrix_sha256": hashlib.sha256(
                    _canonical(manifest["matrix"])
                ).hexdigest(),
                "deterministic_provenance_sha256": DETERMINISTIC_PROVENANCE_SHA256,
                "curation_provenance_sha256": CURATION_PROVENANCE_SHA256,
            }
        )
    return result


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
