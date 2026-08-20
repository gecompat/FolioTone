"""Verify the reviewed archive format lock without regenerating it."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

LOCK_PROFILE = "archive-7zip-format-lock/v1"
MEASUREMENT_PROFILE = "archive-7zip-format-measurement/v2"
FIXTURE_PROFILE = "archive-7zip-format-fixtures/v2"
SIGNATURE_PROFILE = "archive-signature-observer/v2"
COMPATIBILITY_PROFILE = "archive-publication-storage-compatibility/v1"
MEASUREMENT_SHA256 = "da01ed9108a5ea63097cd1894aa4fbb264f658d65a833e8db3cb526180f2d266"
FIXTURE_MANIFEST_SHA256 = "d61bb6ca361bb4cc93b091233199e7031f1aa462b823d0cd6d2cc70130b1ce84"
MATRIX_SHA256 = "c2f3e8e3ff7c5244d71e9a7b2f97a6fea3bc120e6f179a080820024a6c8c6f99"
PROVENANCE_SHA256 = {
    "curation": "da3db4f15acd1530ae3649906d621633ffb541f56a5b9c2236c7a88665ce1a54",
    "deterministic": "89c7c4a03a3aff522d0076313c7f6d0c04f1d71989b8eba63b8d5aa0ada23888",
}
DIRECT_FAMILIES = ("ZIP", "RAR4", "RAR5", "SEVEN_Z", "TAR")
CASE_KINDS = (
    "PLAINTEXT_REGULAR",
    "DIRECTORY",
    "ALL_ENCRYPTED",
    "MIXED",
    "ENCRYPTED_DIRECTORY",
    "SYMBOLIC_LINK",
    "HARD_LINK",
    "COPY_LINK",
)
DISPOSITIONS = {"MEASURED", "FORMAT_UNSUPPORTED", "EVIDENCE_UNAVAILABLE"}
VALUE_CLASSES = {
    "BOOL_MINUS",
    "BOOL_PLUS",
    "CANONICAL_UINT",
    "CRC32",
    "EMPTY",
    "PRIVATE_LOCATOR_DISCARDED",
    "PRIVATE_NONEMPTY_DISCARDED",
    "TECHNICAL_NONEMPTY_DISCARDED",
    "TIMESTAMP",
}
MEASUREMENT_KEYS = {
    "command_profile",
    "command_sha256",
    "curation_provenance_sha256",
    "deterministic_provenance_sha256",
    "fixture_manifest_sha256",
    "image_manifest_digest",
    "matrix_sha256",
    "profile",
    "records",
    "tool_version",
}
FIXTURE_KEYS = {
    "case_kind",
    "format_kind",
    "id",
    "min_records",
    "path",
    "provenance_ref",
    "record_role",
    "sha256",
}
RECORD_KEYS = {
    "case_kind",
    "exit_code",
    "fields",
    "fixture_id",
    "fixture_sha256",
    "format_kind",
    "record_ordinal",
    "record_role",
}
OUTER_KINDS = {
    "TAR_GZIP": "GZIP",
    "TAR_BZIP2": "BZIP2",
    "TAR_XZ": "XZ",
    "TAR_ZSTD": "ZSTD",
}
V2_FIXTURE_IDS = {
    "rar4_plaintext",
    "rar5_plaintext",
    "seven_z_all_encrypted",
    "seven_z_directory",
    "seven_z_mixed",
    "seven_z_plaintext",
    "tar_bzip2_drift",
    "tar_directory",
    "tar_gzip_drift",
    "tar_hard_link",
    "tar_plaintext",
    "tar_symbolic_link",
    "tar_xz_drift",
    "tar_zstd_drift",
    "zip_all_encrypted",
    "zip_directory",
    "zip_mixed",
    "zip_plaintext",
}
PROVENANCE_KEYS = {
    "curation": {
        "archives",
        "command_profile",
        "commands_sha256",
        "container",
        "environment",
        "image_manifest_digest",
        "profile",
        "public_password",
        "redistribution",
        "source_files",
        "tool_version",
    },
    "deterministic": {
        "commands_sha256",
        "fixtures",
        "generation_order",
        "generator_profile",
        "profile",
        "python_generator",
        "redistribution",
        "seven_zip_generator",
    },
}
PROVENANCE_PROFILES = {
    "curation": "archive-7zip-public-fixture-provenance/v2",
    "deterministic": "archive-7zip-deterministic-fixture-provenance/v2",
}


class FormatLockError(RuntimeError):
    """Fixed, path-free format-lock verification failure."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormatLockError("FORMAT_LOCK_INPUT_INVALID") from error
    if not isinstance(value, dict):
        raise FormatLockError("FORMAT_LOCK_INPUT_INVALID")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _require_keys(value: dict[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise FormatLockError(code)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_provenance(name: str, provenance_bytes: bytes, claimed: object) -> None:
    if name not in PROVENANCE_KEYS:
        raise FormatLockError("PROVENANCE_INVALID")
    try:
        provenance = json.loads(provenance_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FormatLockError("PROVENANCE_INVALID") from error
    if not isinstance(provenance, dict) or provenance_bytes != _canonical(provenance):
        raise FormatLockError("PROVENANCE_INVALID")
    if (
        set(provenance) != PROVENANCE_KEYS[name]
        or provenance.get("profile") != PROVENANCE_PROFILES[name]
    ):
        raise FormatLockError("PROVENANCE_SCHEMA_INVALID")
    if (
        hashlib.sha256(provenance_bytes).hexdigest() != PROVENANCE_SHA256[name]
        or claimed != PROVENANCE_SHA256[name]
    ):
        raise FormatLockError("PROVENANCE_DIGEST_MISMATCH")


def _handling(value_class: str) -> str:
    if value_class == "EMPTY":
        return "EMPTY"
    if value_class.endswith("_DISCARDED"):
        return "DISCARD"
    return "REQUIRED"


def _record_profile(record: dict[str, Any]) -> dict[str, Any]:
    _require_keys(record, RECORD_KEYS, "MEASUREMENT_RECORD_INVALID")
    fields = record.get("fields")
    if not isinstance(fields, list) or not fields:
        raise FormatLockError("MEASUREMENT_RECORD_INVALID")
    projected_fields: list[dict[str, str]] = []
    names: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        _require_keys(field, {"name", "value_class"}, "MEASUREMENT_RECORD_INVALID")
        name = field.get("name")
        value_class = field.get("value_class")
        if not isinstance(name, str) or not name or name in names:
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        names.add(name)
        if value_class not in VALUE_CLASSES:
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        projected_fields.append(
            {
                "handling": _handling(value_class),
                "name": name,
                "value_class": value_class,
            }
        )
    ordinal = record.get("record_ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise FormatLockError("MEASUREMENT_RECORD_INVALID")
    return {"fields": projected_fields, "record_ordinal": ordinal}


def expected_lock(
    fixture_manifest: dict[str, Any], measurement: dict[str, Any]
) -> dict[str, Any]:
    _require_keys(
        fixture_manifest,
        {"fixtures", "matrix", "profile"},
        "FIXTURE_MANIFEST_INVALID",
    )
    _require_keys(measurement, MEASUREMENT_KEYS, "MEASUREMENT_SCHEMA_INVALID")
    if fixture_manifest.get("profile") != FIXTURE_PROFILE:
        raise FormatLockError("FIXTURE_PROFILE_MISMATCH")
    if measurement.get("profile") != MEASUREMENT_PROFILE:
        raise FormatLockError("MEASUREMENT_PROFILE_MISMATCH")

    fixture_items = fixture_manifest.get("fixtures")
    matrix = fixture_manifest.get("matrix")
    records = measurement.get("records")
    if not isinstance(fixture_items, list) or not isinstance(matrix, list):
        raise FormatLockError("FIXTURE_MANIFEST_INVALID")
    if not isinstance(records, list):
        raise FormatLockError("MEASUREMENT_RECORD_INVALID")

    fixtures: dict[str, dict[str, Any]] = {}
    for item in fixture_items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise FormatLockError("FIXTURE_MANIFEST_INVALID")
        _require_keys(item, FIXTURE_KEYS, "FIXTURE_MANIFEST_INVALID")
        if item["id"] in fixtures:
            raise FormatLockError("FIXTURE_MANIFEST_INVALID")
        if (
            not _is_sha256(item.get("sha256"))
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or not isinstance(item.get("provenance_ref"), str)
            or not item["provenance_ref"]
            or isinstance(item.get("min_records"), bool)
            or not isinstance(item.get("min_records"), int)
            or item["min_records"] < 1
        ):
            raise FormatLockError("FIXTURE_MANIFEST_INVALID")
        fixtures[item["id"]] = item
    if set(fixtures) != V2_FIXTURE_IDS:
        raise FormatLockError("FIXTURE_UNIVERSE_INVALID")

    validated_records: list[dict[str, Any]] = []
    ordinals: dict[str, set[int]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        _record_profile(record)
        fixture_id = record.get("fixture_id")
        if not isinstance(fixture_id, str):
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        fixture = fixtures.get(fixture_id)
        exit_code = record.get("exit_code")
        if (
            fixture is None
            or record.get("fixture_sha256") != fixture["sha256"]
            or record.get("format_kind") != fixture["format_kind"]
            or record.get("case_kind") != fixture["case_kind"]
            or record.get("record_role") != fixture["record_role"]
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code != 0
        ):
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        fixture_ordinals = ordinals.setdefault(fixture["id"], set())
        ordinal = record["record_ordinal"]
        if ordinal in fixture_ordinals:
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")
        fixture_ordinals.add(ordinal)
        validated_records.append(record)
    if len(validated_records) != 21:
        raise FormatLockError("MEASUREMENT_RECORD_COUNT_INVALID")
    for fixture_id, fixture_ordinals in ordinals.items():
        if fixture_ordinals != set(range(1, fixtures[fixture_id]["min_records"] + 1)):
            raise FormatLockError("MEASUREMENT_RECORD_INVALID")

    expected_cells = {
        (storage_family, case_kind)
        for storage_family in DIRECT_FAMILIES
        for case_kind in CASE_KINDS
    }
    observed_cells: set[tuple[str, str]] = set()
    consumed_records: set[int] = set()
    capabilities: list[dict[str, Any]] = []
    for cell in matrix:
        if not isinstance(cell, dict):
            raise FormatLockError("CAPABILITY_MATRIX_INVALID")
        _require_keys(
            cell,
            {"case_kind", "disposition", "evidence_ref", "format_kind"},
            "CAPABILITY_MATRIX_INVALID",
        )
        storage_family = cell.get("format_kind")
        case_kind = cell.get("case_kind")
        disposition = cell.get("disposition")
        evidence_ref = cell.get("evidence_ref")
        key = (storage_family, case_kind)
        if (
            key not in expected_cells
            or key in observed_cells
            or disposition not in DISPOSITIONS
            or not isinstance(evidence_ref, str)
            or not evidence_ref
        ):
            raise FormatLockError("CAPABILITY_MATRIX_INVALID")
        observed_cells.add(key)
        capability: dict[str, Any] = {
            "case_kind": case_kind,
            "disposition": disposition,
            "evidence_ref": evidence_ref,
            "optional_fields": [],
            "record_profiles": [],
            "storage_family": storage_family,
        }
        matching_records = [
            record
            for record in validated_records
            if record.get("format_kind") == storage_family
            and record.get("case_kind") == case_kind
            and record.get("record_role") == "DIRECT_MEMBER"
        ]
        if disposition == "MEASURED":
            if not evidence_ref.startswith("fixture:"):
                raise FormatLockError("CAPABILITY_EVIDENCE_INVALID")
            fixture_id = evidence_ref.removeprefix("fixture:")
            fixture = fixtures.get(fixture_id)
            if fixture is None or not matching_records:
                raise FormatLockError("CAPABILITY_EVIDENCE_INVALID")
            expected_count = fixture.get("min_records")
            if len(matching_records) != expected_count:
                raise FormatLockError("CAPABILITY_EVIDENCE_INVALID")
            if any(record.get("fixture_id") != fixture_id for record in matching_records):
                raise FormatLockError("CAPABILITY_EVIDENCE_INVALID")
            capability["fixture_id"] = fixture_id
            capability["fixture_sha256"] = fixture.get("sha256")
            capability["record_profiles"] = [
                _record_profile(record) for record in matching_records
            ]
            consumed_records.update(id(record) for record in matching_records)
        elif matching_records:
            raise FormatLockError("CAPABILITY_EVIDENCE_INVALID")
        capabilities.append(capability)
    if observed_cells != expected_cells:
        raise FormatLockError("CAPABILITY_MATRIX_INVALID")

    outer_stream_observations: list[dict[str, Any]] = []
    for format_kind, outer_kind in OUTER_KINDS.items():
        matching = [
            record
            for record in validated_records
            if record.get("format_kind") == format_kind
            and record.get("case_kind") == "OUTER_STREAM_DRIFT"
            and record.get("record_role") == "OUTER_STREAM"
        ]
        fixture = next(
            (
                item
                for item in fixtures.values()
                if item.get("format_kind") == format_kind
                and item.get("case_kind") == "OUTER_STREAM_DRIFT"
            ),
            None,
        )
        if len(matching) != 1 or fixture is None:
            raise FormatLockError("OUTER_STREAM_EVIDENCE_INVALID")
        outer_stream_observations.append(
            {
                "disposition": "OUTER_COMPRESSION_ONLY",
                "fixture_id": fixture["id"],
                "fixture_sha256": fixture["sha256"],
                "outer_compression_kind": outer_kind,
                "record_profiles": [_record_profile(matching[0])],
                "runtime_authorized": False,
                "storage_family": "UNKNOWN",
            }
        )
        consumed_records.add(id(matching[0]))

    if len(consumed_records) != len(validated_records):
        raise FormatLockError("MEASUREMENT_RECORD_UNCONSUMED")
    consumed_fixture_ids = {record["fixture_id"] for record in validated_records}
    if consumed_fixture_ids != V2_FIXTURE_IDS:
        raise FormatLockError("FIXTURE_CONSUMPTION_INVALID")

    return {
        "capabilities": capabilities,
        "compatibility_profile": COMPATIBILITY_PROFILE,
        "fixture_manifest_profile": FIXTURE_PROFILE,
        "fixture_manifest_sha256": measurement.get("fixture_manifest_sha256"),
        "identities": {
            "command_profile": measurement.get("command_profile"),
            "command_sha256": measurement.get("command_sha256"),
            "curation_provenance_sha256": measurement.get(
                "curation_provenance_sha256"
            ),
            "deterministic_provenance_sha256": measurement.get(
                "deterministic_provenance_sha256"
            ),
            "image_manifest_digest": measurement.get("image_manifest_digest"),
            "matrix_sha256": measurement.get("matrix_sha256"),
            "tool_version": measurement.get("tool_version"),
        },
        "measurement_profile": MEASUREMENT_PROFILE,
        "measurement_sha256": hashlib.sha256(_canonical(measurement)).hexdigest(),
        "outer_stream_observations": outer_stream_observations,
        "profile": LOCK_PROFILE,
        "signature_observer_profile": SIGNATURE_PROFILE,
        "stale_on_change": [
            "capability",
            "compatibility_profile",
            "fixture",
            "measurement",
            "ordered_field_profile",
            "signature_observer_profile",
            "tool_or_command_identity",
        ],
    }


def verify_lock(
    *, fixture_manifest_path: Path, measurement_path: Path, lock_path: Path, digest_path: Path
) -> None:
    fixture_manifest = _load_object(fixture_manifest_path)
    measurement = _load_object(measurement_path)
    fixture_bytes = fixture_manifest_path.read_bytes()
    measurement_bytes = measurement_path.read_bytes()
    if fixture_bytes != _canonical(fixture_manifest):
        raise FormatLockError("FIXTURE_MANIFEST_NOT_CANONICAL")
    if measurement_bytes != _canonical(measurement):
        raise FormatLockError("MEASUREMENT_NOT_CANONICAL")
    if hashlib.sha256(measurement_bytes).hexdigest() != MEASUREMENT_SHA256:
        raise FormatLockError("MEASUREMENT_DIGEST_MISMATCH")
    if (
        hashlib.sha256(fixture_bytes).hexdigest() != FIXTURE_MANIFEST_SHA256
        or measurement.get("fixture_manifest_sha256") != FIXTURE_MANIFEST_SHA256
    ):
        raise FormatLockError("FIXTURE_MANIFEST_DIGEST_MISMATCH")
    matrix = fixture_manifest.get("matrix")
    if (
        hashlib.sha256(_canonical(matrix)).hexdigest() != MATRIX_SHA256
        or measurement.get("matrix_sha256") != MATRIX_SHA256
    ):
        raise FormatLockError("CAPABILITY_MATRIX_DIGEST_MISMATCH")
    for name in ("deterministic", "curation"):
        provenance_path = fixture_manifest_path.with_name(f"{name}-provenance.json")
        try:
            provenance_bytes = provenance_path.read_bytes()
        except OSError as error:
            raise FormatLockError("PROVENANCE_INVALID") from error
        _validate_provenance(
            name, provenance_bytes, measurement.get(f"{name}_provenance_sha256")
        )
    fixture_root = fixture_manifest_path.parent.resolve()
    fixtures = fixture_manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise FormatLockError("FIXTURE_MANIFEST_INVALID")
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("path"), str):
            raise FormatLockError("FIXTURE_MANIFEST_INVALID")
        unresolved_path = fixture_root.joinpath(fixture["path"])
        fixture_path = unresolved_path.resolve()
        if fixture_root not in fixture_path.parents:
            raise FormatLockError("FIXTURE_PATH_INVALID")
        try:
            mode = unresolved_path.lstat().st_mode
            fixture_bytes = unresolved_path.read_bytes()
        except OSError as error:
            raise FormatLockError("FIXTURE_INVALID") from error
        if not stat.S_ISREG(mode) or hashlib.sha256(fixture_bytes).hexdigest() != fixture.get(
            "sha256"
        ):
            raise FormatLockError("FIXTURE_INVALID")
    lock = _load_object(lock_path)
    expected = expected_lock(fixture_manifest, measurement)
    canonical = _canonical(lock)
    if lock != expected or lock_path.read_bytes() != canonical:
        raise FormatLockError("FORMAT_LOCK_CONTENT_MISMATCH")
    try:
        expected_digest = digest_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise FormatLockError("FORMAT_LOCK_DIGEST_INVALID") from error
    observed_digest = hashlib.sha256(canonical).hexdigest() + "\n"
    if expected_digest != observed_digest:
        raise FormatLockError("FORMAT_LOCK_DIGEST_MISMATCH")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--digest", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        verify_lock(
            fixture_manifest_path=args.fixtures,
            measurement_path=args.measurement,
            lock_path=args.lock,
            digest_path=args.digest,
        )
    except FormatLockError as error:
        print(str(error))
        return 2
    print("FORMAT_LOCK_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
