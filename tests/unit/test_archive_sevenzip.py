from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import io
import json
import os
import shutil
import socket
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import foliotone.archive.sevenzip as sevenzip_module
from foliotone.archive.sevenzip import (
    ARCHIVE_7ZIP_TOOL_MANIFEST,
    ARCHIVE_IMAGE_REFERENCE,
    ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
    ArchiveImageBootstrapLockedLock,
    ArchiveImageBootstrapPendingLock,
    ArchiveRuntimeDiagnosticCode,
    ArchiveSevenZipRuntimeAvailability,
    archive_7zip_capabilities,
    archive_7zip_runtime_availability,
    build_7zzs_extraction_command,
    build_7zzs_information_command,
    build_7zzs_integrity_command,
    build_7zzs_listing_command,
    load_archive_image_lock,
    load_archive_runtime_release,
    parse_7zzs_information_output,
    provision_archive_7zip_runtime,
)
from foliotone.core.enums import ToolCapability

PACKAGE_ROOT = (
    Path(__file__).parents[2] / "packaging" / "archive" / "7zip-26.02"
)


def _canonical_write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _docker_inspect(release: dict[str, object]) -> dict[str, object]:
    reference = (
        f"{ARCHIVE_IMAGE_REFERENCE}@{release['runtime_platform_manifest_digest']}"
    )
    return {
        "Architecture": "amd64",
        "Config": {
            "Cmd": None,
            "Entrypoint": ["/usr/local/bin/7zzs"],
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
            "Labels": {
                "org.opencontainers.image.source": "https://github.com/gecompat/FolioTone"
            },
            "User": "65532:65532",
            "WorkingDir": "/workspace",
        },
        "Id": release["runtime_config_digest"],
        "Os": "linux",
        "RepoDigests": [reference],
        "RootFS": {
            "Layers": [
                release["runtime_rootfs_diff_id"],
                release["runtime_workdir_diff_id"],
            ],
            "Type": "layers",
        },
    }


def _runtime_paths(tmp_path: Path) -> dict[str, Any]:
    oci = tmp_path / "runtime.oci.tar"
    oci.write_bytes(b"synthetic-verified-by-test-double")
    scan_root = tmp_path / "scan-root"
    scan_root.mkdir()
    private_parent = tmp_path / "private-runtime"
    private_parent.mkdir()
    if sevenzip_module.os.name != "nt":
        private_parent.chmod(0o700)
    artifact = tmp_path / "runtime-manifest.json"
    lock = json.loads((PACKAGE_ROOT / "archive-image.lock.json").read_text())
    artifact.write_bytes(
        json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": lock["runtime_config_digest"],
                    "size": lock["runtime_config_size_bytes"],
                },
                "layers": [
                    {
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                        "digest": lock["runtime_rootfs_layer_digest"],
                        "size": lock["runtime_rootfs_layer_size_bytes"],
                        "annotations": {
                            "buildkit/rewritten-timestamp": "1782345600"
                        },
                    },
                    {
                        "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                        "digest": lock["runtime_workdir_layer_digest"],
                        "size": lock["runtime_workdir_layer_size_bytes"],
                        "annotations": {
                            "buildkit/rewritten-timestamp": "1782345600"
                        },
                    },
                ],
            },
            indent=2,
        ).encode()
    )
    return {
        "_attestation_artifact_path": artifact,
        "evidence_directory": PACKAGE_ROOT / "archive-runtime-evidence",
        "local_state_root": private_parent / "trust-state",
        "lock_path": PACKAGE_ROOT / "archive-image.lock.json",
        "oci_layout_path": oci,
        "private_state_parent": private_parent,
        "release_path": PACKAGE_ROOT / "archive-runtime-release.json",
        "revocations_path": PACKAGE_ROOT / "archive-runtime-revocations.json",
        "scan_roots": (scan_root,),
    }


def _availability(paths: dict[str, Any], now: datetime) -> ArchiveSevenZipRuntimeAvailability:
    return archive_7zip_runtime_availability(
        paths["lock_path"],
        release_path=paths["release_path"],
        revocations_path=paths["revocations_path"],
        evidence_directory=paths["evidence_directory"],
        local_state_root=paths["local_state_root"],
        private_state_parent=paths["private_state_parent"],
        scan_roots=paths["scan_roots"],
        oci_layout_path=paths["oci_layout_path"],
        now=now,
    )


def _provision(
    paths: dict[str, Any],
    now: datetime,
    *,
    refresh: bool = False,
) -> None:
    provision_archive_7zip_runtime(
        local_state_root=paths["local_state_root"],
        private_state_parent=paths["private_state_parent"],
        scan_roots=paths["scan_roots"],
        oci_layout_path=paths["oci_layout_path"],
        attestation_artifact_path=paths["_attestation_artifact_path"],
        now=now,
        refresh=refresh,
    )


def _install_runtime_seams(
    monkeypatch: pytest.MonkeyPatch,
    release: dict[str, object],
) -> dict[str, object]:
    outputs: dict[str, object] = {
        "docker": _docker_inspect(release),
        "docker_calls": 0,
        "gh_calls": 0,
        "gh_returncode": 0,
        "acl_trusted": True,
        "manifest_gate_ok": True,
        "source_gate_ok": True,
        "online_calls": [],
    }
    monkeypatch.setenv("GH_TOKEN", "synthetic-test-token")

    class Response:
        def __init__(self, payload: bytes, headers: dict[str, str]) -> None:
            self.status = 200
            self.headers = headers
            self._payload = io.BytesIO(payload)

        def read(self, size: int = -1) -> bytes:
            return self._payload.read(size)

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            self._payload.close()

    class Opener:
        def __init__(self, module: Any) -> None:
            self.module = module

        def open(self, request: Any, timeout: int) -> Response:
            del timeout
            url = request.full_url
            calls = outputs["online_calls"]
            assert isinstance(calls, list)
            calls.append(url)
            if url == self.module.MANIFEST_URL:
                if request.get_header("Authorization") is None:
                    body = b"authentication required"
                    headers = Message()
                    headers["Content-Length"] = str(len(body))
                    headers["WWW-Authenticate"] = self.module.CHALLENGE
                    raise urllib.error.HTTPError(
                        url, 401, "Unauthorized", headers, io.BytesIO(body)
                    )
                manifest = self.module._reviewed_manifest_bytes()
                digest = self.module.MANIFEST_DIGEST
                if not outputs["manifest_gate_ok"]:
                    digest = "sha256:" + "0" * 64
                return Response(
                    manifest,
                    {
                        "Content-Length": str(len(manifest)),
                        "Content-Type": self.module.MANIFEST_MEDIA_TYPE,
                        "Docker-Content-Digest": digest,
                    },
                )
            if url.startswith(self.module.REGISTRY_REALM):
                payload = b'{"token":"ephemeral"}'
                return Response(payload, {"Content-Length": str(len(payload))})
            visibility = "public" if outputs["source_gate_ok"] else "private"
            payload = json.dumps(
                {
                    "repository": {"full_name": "gecompat/FolioTone"},
                    "visibility": visibility,
                },
                separators=(",", ":"),
            ).encode()
            return Response(payload, {"Content-Length": str(len(payload))})

    monkeypatch.setattr(
        sevenzip_module, "_provisioning_opener", lambda module: Opener(module)
    )
    identity = SimpleNamespace(
        runtime_platform_manifest_digest=release["runtime_platform_manifest_digest"],
        runtime_platform_manifest_size_bytes=release[
            "runtime_platform_manifest_size_bytes"
        ],
        runtime_config_digest=release["runtime_config_digest"],
        runtime_config_size_bytes=release["runtime_config_size_bytes"],
        runtime_rootfs_layer_digest=release["runtime_rootfs_layer_digest"],
        runtime_rootfs_layer_size_bytes=release["runtime_rootfs_layer_size_bytes"],
        runtime_rootfs_diff_id=release["runtime_rootfs_diff_id"],
        runtime_workdir_layer_digest=release["runtime_workdir_layer_digest"],
        runtime_workdir_layer_size_bytes=release["runtime_workdir_layer_size_bytes"],
        runtime_workdir_diff_id=release["runtime_workdir_diff_id"],
    )
    monkeypatch.setattr(sevenzip_module, "_inspect_oci_layout_identity", lambda _path: identity)

    def process(
        command: list[str],
        *,
        env: dict[str, str],
        timeout: float,
        maximum_stdout: int,
    ) -> tuple[int, bytes]:
        del env, timeout, maximum_stdout
        executable = Path(command[0]).name.lower()
        if executable == "powershell.exe":
            acl = {
                "owner": "S-1-5-21-1",
                "current": "S-1-5-21-1",
                "access": [
                    {"sid": "S-1-5-21-1", "type": "Allow"},
                    {"sid": "S-1-5-18", "type": "Allow"},
                    {"sid": "S-1-5-32-544", "type": "Allow"},
                ],
            }
            if not outputs["acl_trusted"]:
                acl["access"].append({"sid": "S-1-1-0", "type": "Allow"})
            return 0, json.dumps(acl).encode()
        if len(command) > 2 and command[1:3] == ["image", "inspect"]:
            outputs["docker_calls"] = int(outputs["docker_calls"]) + 1
            return 0, json.dumps([outputs["docker"]]).encode()
        outputs["gh_calls"] = int(outputs["gh_calls"]) + 1
        predicate_type = command[command.index("--predicate-type") + 1]
        predicate = (
            sevenzip_module._expected_custom_predicate(release)
            if predicate_type == release["custom_slsa_predicate_type"]
            else json.loads(
                (PACKAGE_ROOT / "archive-image.spdx.json").read_text(encoding="utf-8")
            )
        )
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicate": predicate,
            "predicateType": predicate_type,
            "subject": [
                {
                    "digest": {
                        "sha256": str(
                            release["runtime_platform_manifest_digest"]
                        ).removeprefix("sha256:")
                    },
                    "name": release["image_repository"],
                }
            ],
        }
        return int(outputs["gh_returncode"]), json.dumps(
            [{"verificationResult": {"statement": statement}}]
        ).encode()

    monkeypatch.setattr(sevenzip_module, "_run_bounded_process", process)
    return outputs


def test_only_fixed_read_only_argv_shapes_and_archive_capabilities_are_exposed() -> None:
    assert archive_7zip_capabilities() == frozenset(
        {
            ToolCapability.ARCHIVE_LISTING,
            ToolCapability.ARCHIVE_INTEGRITY,
            ToolCapability.ARCHIVE_EXTRACTION,
        }
    )
    assert build_7zzs_information_command() == ("/usr/local/bin/7zzs", "i")
    assert build_7zzs_listing_command() == (
        "/usr/local/bin/7zzs", "l", "-slt", "-ba", "-bd", "-bb0", "-bso1", "-bse2",
        "-bsp0", "-sccUTF-8", "--", "/workspace/input/archive",
    )
    assert build_7zzs_integrity_command() == (
        "/usr/local/bin/7zzs", "t", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0",
        "-sccUTF-8", "-mmt=1", "--", "/workspace/input/archive",
    )
    assert build_7zzs_extraction_command() == (
        "/usr/local/bin/7zzs", "x", "-y", "-bd", "-bb0", "-bso1", "-bse2", "-bsp0",
        "-sccUTF-8", "-mmt=1", "-o/workspace/output", "--", "/workspace/input/archive",
    )
    commands = (
        build_7zzs_listing_command(),
        build_7zzs_integrity_command(),
        build_7zzs_extraction_command(),
    )
    for command in commands:
        assert "-p" not in command
        assert not any(argument.startswith("-p") for argument in command)
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.accepted_exit_codes == frozenset({0})
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.network_enabled is False
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.listing_profile == "archive-listing/v1"
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.integrity_profile == "archive-integrity/v1"
    assert ARCHIVE_7ZIP_TOOL_MANIFEST.extraction_profile == "archive-extraction/v1"


def test_information_parser_accepts_only_bounded_exact_7zzs_2602_output() -> None:
    valid = (
        b"\n7-Zip (z) 26.02 (x64) : Copyright (c) 1999-2026 Igor Pavlov : 2026-06-25\n"
        b"\nFormats:\n  C   F         7z       7z            7 z BC AF ' 1C\n"
    )
    assert parse_7zzs_information_output([valid[:17], valid[17:]]) is True
    assert parse_7zzs_information_output([valid.replace(b"26.02", b"26.01")]) is False
    assert parse_7zzs_information_output([b"x" * 262_145]) is False


def test_runtime_stays_fail_closed_until_all_post_merge_evidence_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = tmp_path / "lock.json"
    template_path = (
        Path(__file__).parents[2]
        / "packaging"
        / "archive"
        / "7zip-26.02"
        / "archive-image.lock.json"
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    lock.write_text(json.dumps(template), encoding="utf-8")
    assert isinstance(load_archive_image_lock(lock), ArchiveImageBootstrapLockedLock)
    unavailable = archive_7zip_runtime_availability(lock)
    assert (unavailable.profile, unavailable.available, unavailable.reason) == (
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE, False, "TOOL_UNAVAILABLE",
    )
    paths = _runtime_paths(tmp_path)
    paths["lock_path"] = lock
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    outputs = _install_runtime_seams(monkeypatch, release)
    no_state = _availability(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    assert no_state.diagnostic_code is ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING
    assert outputs["docker_calls"] == 0
    digest = template["runtime_platform_manifest_digest"]
    pending = dict(template)
    pending["state"] = "BOOTSTRAP_PENDING"
    for field in (
        "runtime_platform_manifest_digest",
        "runtime_config_digest",
        "runtime_rootfs_layer_digest",
        "runtime_rootfs_diff_id",
        "runtime_workdir_layer_digest",
        "runtime_workdir_diff_id",
    ):
        pending[field] = "UNVERIFIED"
    for field in (
        "runtime_platform_manifest_size_bytes",
        "runtime_config_size_bytes",
        "runtime_rootfs_layer_size_bytes",
        "runtime_workdir_layer_size_bytes",
    ):
        pending[field] = 0
    lock.write_text(json.dumps(pending), encoding="utf-8")
    assert isinstance(load_archive_image_lock(lock), ArchiveImageBootstrapPendingLock)
    still_unavailable = archive_7zip_runtime_availability(lock)
    assert still_unavailable.available is False
    pending["published_public_source_associated"] = True
    lock.write_text(json.dumps(pending), encoding="utf-8")
    assert load_archive_image_lock(lock) is None
    with pytest.raises(ValueError):
        ArchiveSevenZipRuntimeAvailability(
            ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE, True, "AVAILABLE", None
        )
    available = ArchiveSevenZipRuntimeAvailability(
        ARCHIVE_LINUX_CONTAINER_RUNNER_PROFILE,
        True,
        "AVAILABLE",
        f"{ARCHIVE_IMAGE_REFERENCE}@{digest}",
    )
    assert available.image_reference is not None


def test_checked_in_release_is_closed_canonical_and_content_addressed() -> None:
    release_path = PACKAGE_ROOT / "archive-runtime-release.json"
    release = load_archive_runtime_release(release_path)
    assert release is not None
    assert release["profile"] == "archive-runtime-release/v1"
    assert release["state"] == "RELEASE_ACCEPTED"
    assert release["repository_commit"] == "b7191098697664725eb073f2c6a6ca01325c96dd"
    assert release["workflow_invocation_id"].endswith(
        "/actions/runs/32345177882/attempts/1"
    )
    assert release["runtime_platform_manifest_digest"] == (
        "sha256:26c9c2fa32f93210a46fcf6b9651006038f9e766a1d791b463ce9875815a8287"
    )
    material = dict(release)
    release_id = material.pop("release_id")
    assert release_id == hashlib.sha256(
        b"archive-runtime-release/v1\0"
        + sevenzip_module._canonical_json_bytes(material)
    ).hexdigest()
    assert release_id == "d635998970bb2bccb36bd5e2f320842e353cab6aaad0c6d67ed541e756640ff1"


@pytest.mark.parametrize(
    "field",
    sorted(sevenzip_module._RELEASE_FIELDS),
)
def test_every_release_field_mutation_fails_closed(tmp_path: Path, field: str) -> None:
    release = json.loads(
        (PACKAGE_ROOT / "archive-runtime-release.json").read_text(encoding="utf-8")
    )
    release[field] = None
    candidate = tmp_path / "release.json"
    _canonical_write(candidate, release)
    assert load_archive_runtime_release(candidate) is None


def test_release_rejects_unknown_duplicate_pending_and_noncanonical_bytes(
    tmp_path: Path,
) -> None:
    raw = (PACKAGE_ROOT / "archive-runtime-release.json").read_text(encoding="utf-8")
    release = json.loads(raw)
    for label, mutate in (
        ("unknown", lambda value: value.update({"unknown": True})),
        ("pending", lambda value: value.update({"state": "PENDING"})),
        (
            "placeholder",
            lambda value: value.update({"custom_slsa_bundle_sha256": "UNVERIFIED"}),
        ),
    ):
        candidate = tmp_path / f"{label}.json"
        mutate(release := json.loads(raw))
        _canonical_write(candidate, release)
        assert load_archive_runtime_release(candidate) is None
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(raw[:-2] + ',"state":"RELEASE_ACCEPTED"}\n', encoding="utf-8")
    assert load_archive_runtime_release(duplicate) is None
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(json.loads(raw), indent=2) + "\n", encoding="utf-8")
    assert load_archive_runtime_release(pretty) is None


def test_explicit_provisioning_and_per_run_offline_availability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    outputs = _install_runtime_seams(monkeypatch, release)

    instant = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    _provision(paths, instant)
    assert outputs["gh_calls"] == 2
    state = json.loads(
        (paths["local_state_root"] / "state.json").read_text(encoding="utf-8")
    )
    assert set(state) == sevenzip_module._STATE_FIELDS
    assert state["release_id"] == release["release_id"]
    available = _availability(paths, instant + timedelta(seconds=1))
    assert available.reason == "AVAILABLE"
    assert available.diagnostic_code is None
    assert available.image_reference == sevenzip_module._EXPECTED_IMAGE_REFERENCE


@pytest.mark.parametrize(
    "stage",
    [
        "before_state_file_fsync",
        "before_state_directory_fsync",
        "before_state_replace",
        "before_parent_directory_fsync",
    ],
)
def test_initial_provisioning_never_accepts_partial_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(sevenzip_module, "_call_failure_hook", fail)
    with pytest.raises(RuntimeError):
        _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    if paths["local_state_root"].exists():
        assert json.loads(
            (paths["local_state_root"] / "state.json").read_text(encoding="utf-8")
        )["profile"] == "archive-runtime-local-state/v1"


def test_missing_corrupt_clock_rollback_expiry_and_revocation_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    missing = _availability(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    assert missing.diagnostic_code is ArchiveRuntimeDiagnosticCode.LOCAL_STATE_MISSING
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    state_path = paths["local_state_root"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["highest_observed_utc"] = "2026-08-20T08:10:00Z"
    _canonical_write(state_path, state)
    rollback = _availability(paths, datetime(2026, 8, 20, 8, 4, 59, tzinfo=UTC))
    assert rollback.diagnostic_code is ArchiveRuntimeDiagnosticCode.CLOCK_ROLLBACK
    expired = _availability(paths, datetime(2026, 11, 18, 7, 42, 23, tzinfo=UTC))
    assert expired.diagnostic_code is ArchiveRuntimeDiagnosticCode.RELEASE_EXPIRED
    revocations = json.loads(paths["revocations_path"].read_text(encoding="utf-8"))
    revocations["release_ids"] = [release["release_id"]]
    denied = tmp_path / "revoked.json"
    _canonical_write(denied, revocations)
    revoked_paths = dict(paths)
    revoked_paths["revocations_path"] = denied
    revoked = _availability(revoked_paths, datetime(2026, 8, 20, 8, 10, tzinfo=UTC))
    assert revoked.diagnostic_code is ArchiveRuntimeDiagnosticCode.REVOKED
    state_path.write_bytes(b"{\"partial\":")
    corrupt = _availability(paths, datetime(2026, 8, 20, 8, 10, tzinfo=UTC))
    assert corrupt.diagnostic_code is ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID


def test_per_run_preflight_has_a_hard_network_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert _availability(paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC)).available


@pytest.mark.parametrize(
    ("path", "diagnostic"),
    [
        (("Config", "User"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Config", "Env"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Config", "Entrypoint"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Config", "WorkingDir"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Config", "Labels"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Config", "Cmd"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("RootFS", "Layers"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("RootFS", "Type"), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Id",), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Architecture",), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("Os",), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
        (("RepoDigests",), ArchiveRuntimeDiagnosticCode.IMAGE_INSPECT_MISMATCH),
    ],
)
def test_each_docker_identity_mutation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    diagnostic: ArchiveRuntimeDiagnosticCode,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    good = _docker_inspect(release)
    outputs = _install_runtime_seams(monkeypatch, release)
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    bad = copy.deepcopy(good)
    target: object = bad
    for component in path[:-1]:
        assert isinstance(target, dict)
        target = target[component]
    assert isinstance(target, dict)
    target[path[-1]] = "wrong"
    outputs["docker"] = bad
    result = _availability(paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC))
    assert result.diagnostic_code is diagnostic


@pytest.mark.parametrize(
    "evidence_name",
    ["custom-slsa.jsonl", "spdx.jsonl", "trusted_root.jsonl"],
)
def test_each_checked_evidence_file_byte_mutation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_name: str,
) -> None:
    paths = _runtime_paths(tmp_path)
    copied_evidence = tmp_path / "reviewed-evidence"
    shutil.copytree(paths["evidence_directory"], copied_evidence)
    paths["evidence_directory"] = copied_evidence
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    evidence_path = copied_evidence / evidence_name
    payload = bytearray(evidence_path.read_bytes())
    payload[len(payload) // 2] ^= 1
    evidence_path.write_bytes(payload)
    result = _availability(paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC))
    assert result.diagnostic_code is ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH


@pytest.mark.parametrize(
    ("denylist_field", "release_field"),
    [
        ("release_ids", "release_id"),
        ("runtime_platform_manifest_digests", "runtime_platform_manifest_digest"),
        ("repository_commits", "repository_commit"),
        ("bundle_sha256_values", "custom_slsa_bundle_sha256"),
        ("bundle_sha256_values", "spdx_bundle_sha256"),
    ],
)
def test_each_revocation_denylist_category_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    denylist_field: str,
    release_field: str,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    revocations = json.loads(paths["revocations_path"].read_text(encoding="utf-8"))
    revocations[denylist_field] = [release[release_field]]
    denied = tmp_path / "denied.json"
    _canonical_write(denied, revocations)
    paths["revocations_path"] = denied
    result = _availability(paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC))
    assert result.diagnostic_code is ArchiveRuntimeDiagnosticCode.REVOKED


@pytest.mark.parametrize(
    ("state_field", "higher_generation"),
    [("release_generation", 2), ("highest_revocation_generation", 2)],
)
def test_observed_generation_rollback_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state_field: str,
    higher_generation: int,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    state_path = paths["local_state_root"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state[state_field] = higher_generation
    _canonical_write(state_path, state)
    result = _availability(paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC))
    assert result.diagnostic_code is ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK


def test_initial_policy_rejects_stale_revocation_generation() -> None:
    release = json.loads(
        (PACKAGE_ROOT / "archive-runtime-release.json").read_text(encoding="utf-8")
    )
    release["minimum_revocation_generation"] = 2
    revocations = json.loads(
        (PACKAGE_ROOT / "archive-runtime-revocations.json").read_text(encoding="utf-8")
    )
    state = {
        "highest_observed_utc": "2026-08-20T08:00:00Z",
        "highest_revocation_generation": 1,
        "release_generation": 1,
    }
    with pytest.raises(RuntimeError) as failure:
        sevenzip_module._verify_time_and_generations(
            release,
            revocations,
            state,
            datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
        )
    assert str(failure.value) == ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK


@pytest.mark.parametrize(
    "stage",
    [
        "before_state_file_fsync",
        "before_state_replace",
        "before_parent_directory_fsync",
    ],
)
def test_refresh_interruption_leaves_complete_old_or_new_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    first = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    _provision(paths, first)
    state_path = paths["local_state_root"] / "state.json"
    old_state = json.loads(state_path.read_text(encoding="utf-8"))

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError("synthetic refresh interruption")

    monkeypatch.setattr(sevenzip_module, "_call_failure_hook", fail)
    with pytest.raises(RuntimeError):
        _provision(
            paths,
            first + timedelta(minutes=1),
            refresh=True,
        )
    surviving_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(surviving_state) == sevenzip_module._STATE_FIELDS
    assert surviving_state["provisioned_at"] in {
        old_state["provisioned_at"],
        "2026-08-20T08:01:00Z",
    }
    monkeypatch.setattr(sevenzip_module, "_call_failure_hook", lambda _stage: None)
    assert _availability(paths, first + timedelta(minutes=1, seconds=1)).available


def test_public_provisioning_has_no_authorizing_callbacks_and_crypto_is_mandatory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameters = inspect.signature(provision_archive_7zip_runtime).parameters
    assert "docker_inspect" not in parameters
    assert "provisioning_verifier" not in parameters
    assert "gh_executable" not in parameters
    assert "failure_hook" not in parameters
    assert "release_path" not in parameters
    assert "revocations_path" not in parameters
    assert "evidence_directory" not in parameters
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    outputs = _install_runtime_seams(monkeypatch, release)
    outputs["gh_returncode"] = 1
    with pytest.raises(RuntimeError):
        _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    assert outputs["gh_calls"] == 1
    assert not paths["local_state_root"].exists()


def test_direct_public_provisioning_cannot_bypass_online_gates_or_substitute_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    outputs = _install_runtime_seams(monkeypatch, release)
    instant = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)

    outputs["manifest_gate_ok"] = False
    with pytest.raises(RuntimeError) as manifest_failure:
        _provision(paths, instant)
    assert str(manifest_failure.value) == ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
    assert outputs["gh_calls"] == 0
    assert outputs["docker_calls"] == 0
    assert not paths["local_state_root"].exists()

    outputs["manifest_gate_ok"] = True
    outputs["source_gate_ok"] = False
    with pytest.raises(RuntimeError) as source_failure:
        _provision(paths, instant)
    assert str(source_failure.value) == ArchiveRuntimeDiagnosticCode.EVIDENCE_MISMATCH
    assert outputs["gh_calls"] == 0
    assert outputs["docker_calls"] == 0
    assert not paths["local_state_root"].exists()

    obsolete_policy_arguments = {
        "release_path": tmp_path / "alternate-release.json",
        "revocations_path": tmp_path / "alternate-revocations.json",
        "evidence_directory": tmp_path / "alternate-evidence",
    }
    with pytest.raises(TypeError):
        cast(Any, provision_archive_7zip_runtime)(
            local_state_root=paths["local_state_root"],
            private_state_parent=paths["private_state_parent"],
            scan_roots=paths["scan_roots"],
            oci_layout_path=paths["oci_layout_path"],
            attestation_artifact_path=paths["_attestation_artifact_path"],
            now=instant,
            **obsolete_policy_arguments,
        )

    outputs["source_gate_ok"] = True
    _provision(paths, instant)
    assert int(cast(int, outputs["gh_calls"])) == 2
    assert int(cast(int, outputs["docker_calls"])) == 1


def test_oci_inspector_path_is_fixed_and_caller_recipe_is_never_imported(
    tmp_path: Path,
) -> None:
    release = load_archive_runtime_release(PACKAGE_ROOT / "archive-runtime-release.json")
    assert release is not None
    marker = tmp_path / "caller-inspector-imported"
    (tmp_path / "inspect_oci_layout.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8",
    )
    oci = tmp_path / "invalid.oci.tar"
    oci.write_bytes(b"not an OCI layout")
    with pytest.raises(RuntimeError):
        sevenzip_module._verify_oci_layout(oci, release)
    assert not marker.exists()
    assert len(inspect.signature(sevenzip_module._verify_oci_layout).parameters) == 2


@pytest.mark.parametrize(
    "predicate_path",
    [
        ("buildDefinition", "internalParameters", "base", "digest"),
        ("runDetails", "builder", "version", "buildkit"),
        ("runDetails", "byproducts", 0, "annotations", "size"),
    ],
)
def test_complete_custom_predicate_semantics_are_closed(
    predicate_path: tuple[str | int, ...],
) -> None:
    release = load_archive_runtime_release(PACKAGE_ROOT / "archive-runtime-release.json")
    assert release is not None
    bundle = json.loads(
        (PACKAGE_ROOT / "archive-runtime-evidence" / "custom-slsa.jsonl").read_text()
    )
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    expected = sevenzip_module._expected_custom_predicate(release)
    target: Any = statement["predicate"]
    for component in predicate_path[:-1]:
        target = target[component]
    target[predicate_path[-1]] = "adversarial"
    with pytest.raises(RuntimeError):
        sevenzip_module._verify_statement(
            statement,
            release,
            custom_slsa=True,
            expected_custom=expected,
        )


def test_successful_preflight_advances_revocation_generation_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    instant = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    _provision(paths, instant)
    revocations = json.loads(paths["revocations_path"].read_text(encoding="utf-8"))
    revocations["generation"] = 2
    newer = tmp_path / "revocations-generation-2.json"
    _canonical_write(newer, revocations)
    paths["revocations_path"] = newer
    assert _availability(paths, instant + timedelta(seconds=1)).available
    state = json.loads(
        (paths["local_state_root"] / "state.json").read_text(encoding="utf-8")
    )
    assert state["highest_revocation_generation"] == 2


def test_acceptance_floor_and_same_generation_refresh_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    _install_runtime_seams(monkeypatch, release)
    accepted = datetime(2026, 8, 20, 7, 42, 22, tzinfo=UTC)
    with pytest.raises(RuntimeError) as early:
        _provision(paths, accepted - timedelta(seconds=1))
    assert str(early.value) == ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
    assert not paths["local_state_root"].exists()
    _provision(paths, accepted)
    before = _availability(paths, accepted - timedelta(seconds=1))
    assert before.diagnostic_code is ArchiveRuntimeDiagnosticCode.RELEASE_NOT_ACCEPTED
    changed = dict(release)
    changed["offline_not_after"] = "2026-11-18T07:42:21Z"
    material = dict(changed)
    material.pop("release_id")
    changed["release_id"] = hashlib.sha256(
        b"archive-runtime-release/v1\0"
        + sevenzip_module._canonical_json_bytes(material)
    ).hexdigest()
    release_bytes = sevenzip_module._canonical_json_bytes(changed) + b"\n"
    state = json.loads(
        (paths["local_state_root"] / "state.json").read_text(encoding="utf-8")
    )
    with pytest.raises(RuntimeError) as failure:
        sevenzip_module._verify_refresh_release_transition(
            changed, release_bytes, state
        )
    assert str(failure.value) == ArchiveRuntimeDiagnosticCode.GENERATION_ROLLBACK
    changed["generation"] = 2
    material = dict(changed)
    material.pop("release_id")
    changed["release_id"] = hashlib.sha256(
        b"archive-runtime-release/v1\0"
        + sevenzip_module._canonical_json_bytes(material)
    ).hexdigest()
    sevenzip_module._verify_refresh_release_transition(
        changed,
        sevenzip_module._canonical_json_bytes(changed) + b"\n",
        state,
    )
    _provision(paths, accepted + timedelta(seconds=2), refresh=True)


def test_private_state_boundary_rejects_empty_scan_roots_bad_acl_and_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _runtime_paths(tmp_path)
    release = load_archive_runtime_release(paths["release_path"])
    assert release is not None
    outputs = _install_runtime_seams(monkeypatch, release)
    empty_roots = dict(paths)
    empty_roots["scan_roots"] = ()
    with pytest.raises(RuntimeError):
        _provision(empty_roots, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    inside_scan = dict(paths)
    inside_scan["private_state_parent"] = paths["scan_roots"][0]
    inside_scan["local_state_root"] = paths["scan_roots"][0] / "trust-state"
    with pytest.raises(RuntimeError):
        _provision(inside_scan, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    _provision(paths, datetime(2026, 8, 20, 8, 0, tzinfo=UTC))
    if os.name == "nt":
        outputs["acl_trusted"] = False
    else:
        paths["private_state_parent"].chmod(0o755)
    acl_result = _availability(
        paths, datetime(2026, 8, 20, 8, 0, 1, tzinfo=UTC)
    )
    assert acl_result.diagnostic_code is ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID
    if os.name == "nt":
        outputs["acl_trusted"] = True
    else:
        paths["private_state_parent"].chmod(0o700)
    state_path = paths["local_state_root"] / "state.json"
    real_state = tmp_path / "real-state.json"
    state_path.replace(real_state)
    try:
        state_path.symlink_to(real_state)
    except OSError:
        pytest.skip("platform cannot create the adversarial state symlink")
    symlink_result = _availability(
        paths, datetime(2026, 8, 20, 8, 0, 2, tzinfo=UTC)
    )
    assert symlink_result.diagnostic_code is ArchiveRuntimeDiagnosticCode.LOCAL_STATE_INVALID


def test_bounded_process_kills_overflow_and_timeout_without_returning_raw_bytes() -> None:
    executable = sys.executable
    with pytest.raises(RuntimeError, match="exceeded"):
        sevenzip_module._run_bounded_process(
            [executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*200000)"],
            env={"PATH": sevenzip_module.os.environ.get("PATH", "")},
            timeout=10,
            maximum_stdout=1_024,
        )
    with pytest.raises(TimeoutError, match="timed out"):
        sevenzip_module._run_bounded_process(
            [
                executable,
                "-c",
                (
                    "import subprocess,sys,time;"
                    "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
                    "time.sleep(60)"
                ),
            ],
            env={"PATH": sevenzip_module.os.environ.get("PATH", "")},
            timeout=0.2,
            maximum_stdout=1_024,
        )
