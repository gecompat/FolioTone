#!/usr/bin/env python3
"""Dependency-free reference client for the Foundation artifact registration contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REGISTRY_PROFILE = "foundation-artifact-registry/v1"
UID_RE = re.compile(r"^urn:uuid:([0-9a-fA-F-]{36})$")
DEFAULT_PREFIXES = {
    "CAP": {"kind": "capability", "next_sequence": 1, "width": 4},
    "REQ": {"kind": "requirement", "next_sequence": 1, "width": 4},
    "WI": {"kind": "work_item", "next_sequence": 1, "width": 4},
    "DEC": {"kind": "decision", "next_sequence": 1, "width": 4},
    "GATE": {"kind": "gate", "next_sequence": 1, "width": 4},
    "RISK": {"kind": "risk", "next_sequence": 1, "width": 4},
    "EXP": {"kind": "experiment", "next_sequence": 1, "width": 4},
    "OPS": {"kind": "operational_work", "next_sequence": 1, "width": 4},
    "INC": {"kind": "incident", "next_sequence": 1, "width": 4},
    "REL": {"kind": "release", "next_sequence": 1, "width": 4},
    "TEST": {"kind": "test", "next_sequence": 1, "width": 4},
}


class RegistrationError(RuntimeError):
    pass


def uuid7_urn() -> str:
    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << 48:
        raise RegistrationError("current timestamp does not fit UUIDv7 48-bit timestamp")
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return f"urn:uuid:{uuid.UUID(int=value)}"


def normalize_uid(raw: str | None) -> str:
    value = raw or uuid7_urn()
    match = UID_RE.fullmatch(value)
    if not match:
        raise RegistrationError("artifact UID must use urn:uuid:<uuid>")
    parsed = uuid.UUID(match.group(1))
    if parsed.version not in {4, 7}:
        raise RegistrationError("Foundation reference client accepts UUIDv4 or UUIDv7 artifact UIDs")
    return f"urn:uuid:{str(parsed)}"


def initial_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile": REGISTRY_PROFILE,
        "registry_revision": 0,
        "prefixes": json.loads(json.dumps(DEFAULT_PREFIXES)),
        "allocations": {},
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistrationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RegistrationError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistrationError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@contextmanager
def registry_lock(registry_path: Path) -> Iterator[None]:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.with_name(registry_path.name + ".lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RegistrationError(f"registry lock already exists: {lock_path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != 1 or registry.get("profile") != REGISTRY_PROFILE:
        raise RegistrationError("unsupported registry schema/profile")
    revision = registry.get("registry_revision")
    if not isinstance(revision, int) or revision < 0:
        raise RegistrationError("registry_revision must be a non-negative integer")
    prefixes = registry.get("prefixes")
    allocations = registry.get("allocations")
    if not isinstance(prefixes, dict) or not prefixes:
        raise RegistrationError("registry prefixes must be a non-empty object")
    if not isinstance(allocations, dict):
        raise RegistrationError("registry allocations must be an object")

    kinds: set[str] = set()
    for prefix, row in prefixes.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix) or not isinstance(row, dict):
            raise RegistrationError(f"invalid prefix registry entry: {prefix}")
        kind = row.get("kind")
        sequence = row.get("next_sequence")
        width = row.get("width")
        if not isinstance(kind, str) or not kind or kind in kinds:
            raise RegistrationError(f"prefix kind must be unique and non-empty: {prefix}")
        kinds.add(kind)
        if not isinstance(sequence, int) or sequence < 1:
            raise RegistrationError(f"invalid next_sequence for {prefix}")
        if not isinstance(width, int) or width < 1:
            raise RegistrationError(f"invalid width for {prefix}")

    seen_uids: set[str] = set()
    for human_ref, artifact_uid in allocations.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-[0-9]+", human_ref):
            raise RegistrationError(f"invalid allocated human reference: {human_ref}")
        normalized = normalize_uid(str(artifact_uid))
        if normalized in seen_uids:
            raise RegistrationError(f"artifact UID has multiple final human references: {normalized}")
        seen_uids.add(normalized)


def check_expected_revision(registry: dict[str, Any], expected: int | None) -> None:
    if expected is not None and registry["registry_revision"] != expected:
        raise RegistrationError(
            f"stale registry revision: expected {expected}, actual {registry['registry_revision']}"
        )


def prefix_for_kind(registry: dict[str, Any], kind: str) -> str:
    matches = [prefix for prefix, row in registry["prefixes"].items() if row["kind"] == kind]
    if len(matches) != 1:
        raise RegistrationError(f"kind must resolve to exactly one prefix: {kind}")
    return matches[0]


def allocate(registry: dict[str, Any], kind: str, artifact_uid: str) -> str:
    prefix = prefix_for_kind(registry, kind)
    row = registry["prefixes"][prefix]
    sequence = int(row["next_sequence"])
    width = max(int(row["width"]), len(str(sequence)))
    human_ref = f"{prefix}-{sequence:0{width}d}"
    if human_ref in registry["allocations"]:
        raise RegistrationError(f"allocation collision: {human_ref}")
    if artifact_uid in registry["allocations"].values():
        existing = next(ref for ref, uid_value in registry["allocations"].items() if uid_value == artifact_uid)
        raise RegistrationError(f"artifact UID already registered as {existing}")
    registry["allocations"][human_ref] = artifact_uid
    row["next_sequence"] = sequence + 1
    registry["registry_revision"] += 1
    return human_ref


def artifact_record(uid_value: str, human_ref: str | None, kind: str, title: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_uid": uid_value,
        "human_ref": human_ref,
        "kind": kind,
        "title": title,
        "registration_state": "REGISTERED" if human_ref else "DRAFT",
        "aliases": [],
        "external_refs": [],
        "relations": [],
    }


def output_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    path: Path = args.registry
    with registry_lock(path):
        if path.exists():
            raise RegistrationError(f"registry already exists: {path}")
        registry = initial_registry()
        atomic_write_json(path, registry)
    return registry


def cmd_new(args: argparse.Namespace) -> dict[str, Any]:
    registry_path: Path = args.registry
    uid_value = normalize_uid(args.uid)
    if not args.kind or not args.title:
        raise RegistrationError("new requires --kind and --title")

    if args.mode == "DEFERRED":
        registry = load_json(registry_path)
        validate_registry(registry)
        prefix_for_kind(registry, args.kind)
        artifact = artifact_record(uid_value, None, args.kind, args.title)
    else:
        with registry_lock(registry_path):
            registry = load_json(registry_path)
            validate_registry(registry)
            check_expected_revision(registry, args.expected_registry_revision)
            human_ref = allocate(registry, args.kind, uid_value)
            atomic_write_json(registry_path, registry)
        artifact = artifact_record(uid_value, human_ref, args.kind, args.title)

    if args.artifact:
        atomic_write_json(args.artifact, artifact)
    return artifact


def cmd_register(args: argparse.Namespace) -> dict[str, Any]:
    if not args.artifact:
        raise RegistrationError("register requires --artifact")
    artifact = load_json(args.artifact)
    uid_value = normalize_uid(str(artifact.get("artifact_uid", "")))
    kind = artifact.get("kind")
    if not isinstance(kind, str) or not kind:
        raise RegistrationError("artifact kind is required")
    existing_ref = artifact.get("human_ref")

    with registry_lock(args.registry):
        registry = load_json(args.registry)
        validate_registry(registry)
        check_expected_revision(registry, args.expected_registry_revision)
        if existing_ref:
            if registry["allocations"].get(existing_ref) != uid_value:
                raise RegistrationError("artifact human_ref is not registered to its UID")
            return artifact

        recovered_ref = next((ref for ref, value in registry["allocations"].items() if value == uid_value), None)
        if recovered_ref:
            human_ref = recovered_ref
        else:
            human_ref = allocate(registry, kind, uid_value)
            atomic_write_json(args.registry, registry)

    artifact["human_ref"] = human_ref
    artifact["registration_state"] = "REGISTERED"
    atomic_write_json(args.artifact, artifact)
    return artifact


def cmd_resolve(args: argparse.Namespace) -> dict[str, Any]:
    if not args.human_ref:
        raise RegistrationError("resolve requires --human-ref")
    registry = load_json(args.registry)
    validate_registry(registry)
    uid_value = registry["allocations"].get(args.human_ref)
    if not uid_value:
        raise RegistrationError(f"human reference is not registered: {args.human_ref}")
    return {"schema_version": 1, "human_ref": args.human_ref, "artifact_uid": uid_value}


def cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_json(args.registry)
    validate_registry(registry)
    return {
        "schema_version": 1,
        "valid": True,
        "registry_revision": registry["registry_revision"],
        "allocation_count": len(registry["allocations"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["init", "new", "register", "resolve", "validate"])
    parser.add_argument("--registry", type=Path, default=Path(".ai/identity/registry.json"))
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--mode", choices=["DIRECT", "DEFERRED"], default="DIRECT")
    parser.add_argument("--kind")
    parser.add_argument("--title")
    parser.add_argument("--uid")
    parser.add_argument("--human-ref")
    parser.add_argument("--expected-registry-revision", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "init": cmd_init,
        "new": cmd_new,
        "register": cmd_register,
        "resolve": cmd_resolve,
        "validate": cmd_validate,
    }
    try:
        result = commands[args.operation](args)
        output_json(result)
        return 0
    except (OSError, RegistrationError) as exc:
        print(f"[BLOCK] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
