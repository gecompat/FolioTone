from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from foliotone.archive.container_sandbox import (
    ArchiveContainerRequest,
    ArchiveContainerRunStatus,
    ArchiveLinuxContainerRunner,
    ArchiveRuntimePreflightInputs,
    ArchiveVolumeSource,
    DockerCliSandboxBackend,
    LocalSandboxFilesystem,
)
from foliotone.archive.process_runner import ArchiveProcessRunner, SubprocessLauncher
from foliotone.archive.sevenzip import (
    archive_7zip_runtime_availability,
    build_7zzs_information_command,
    parse_7zzs_information_output,
)


def test_provisioned_local_digest_runs_without_pull_and_leaves_source_unchanged(
    tmp_path: Path,
) -> None:
    if sys.platform != "linux":
        pytest.skip("native Windows archive sandbox is intentionally unavailable")
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() not in {0, 65_532}:
        pytest.skip("numeric 65532 ownership projection is not available to this test user")

    private_parent_raw = os.environ.get("FOLIOTONE_ARCHIVE_PRIVATE_STATE_PARENT")
    local_state_raw = os.environ.get("FOLIOTONE_ARCHIVE_LOCAL_STATE_ROOT")
    oci_layout_raw = os.environ.get("FOLIOTONE_ARCHIVE_OCI_LAYOUT")
    if not all((private_parent_raw, local_state_raw, oci_layout_raw)):
        pytest.skip("provisioned offline archive runtime paths are not configured")
    assert private_parent_raw is not None
    assert local_state_raw is not None
    assert oci_layout_raw is not None

    repository_root = Path(__file__).parents[2]
    package_root = repository_root / "packaging" / "archive" / "7zip-26.02"
    scan_root = tmp_path / "synthetic-scan"
    temp_root = tmp_path / "sandbox-temp"
    scan_root.mkdir(mode=0o700)
    temp_root.mkdir(mode=0o700)
    source = scan_root / "archive.fixture"
    source_bytes = b"FolioTone synthetic archive-runner input\n"
    source.write_bytes(source_bytes)
    source.chmod(0o600)

    preflight = ArchiveRuntimePreflightInputs(
        package_root / "archive-image.lock.json",
        package_root / "archive-runtime-release.json",
        package_root / "archive-runtime-revocations.json",
        package_root / "archive-runtime-evidence",
        Path(local_state_raw),
        Path(private_parent_raw),
        Path(oci_layout_raw),
    )
    availability = archive_7zip_runtime_availability(
        preflight.lock_path,
        release_path=preflight.release_path,
        revocations_path=preflight.revocations_path,
        evidence_directory=preflight.evidence_directory,
        local_state_root=preflight.local_state_root,
        private_state_parent=preflight.private_state_parent,
        scan_roots=(scan_root,),
        oci_layout_path=preflight.oci_layout_path,
    )
    if not availability.available:
        pytest.skip(f"offline archive runtime unavailable: {availability.diagnostic_code}")

    process_runner = ArchiveProcessRunner(SubprocessLauncher())
    docker = DockerCliSandboxBackend.discover(process_runner)
    if docker is None:
        pytest.skip("local Docker CLI is unavailable")
    filesystem = LocalSandboxFilesystem()
    if not filesystem.supports_linux_sandbox:
        pytest.skip("Linux no-follow/ACL sandbox primitives are unavailable")

    request = ArchiveContainerRequest(
        (
            ArchiveVolumeSource(
                source,
                len(source_bytes),
                hashlib.sha256(source_bytes).hexdigest(),
                "archive",
            ),
        ),
        build_7zzs_information_command(),
        (scan_root,),
    )
    stdout_chunks: list[bytes] = []
    result = ArchiveLinuxContainerRunner(
        temp_root=temp_root,
        runtime_preflight=preflight,
        filesystem=filesystem,
        docker=docker,
        process_runner=process_runner,
    ).run(
        request,
        stdout_consumer=lambda chunk: stdout_chunks.append(chunk) is None,
        stderr_classifier=lambda _chunk: True,
    )

    assert result.status is ArchiveContainerRunStatus.COMPLETED
    assert parse_7zzs_information_output(stdout_chunks) is True
    assert source.read_bytes() == source_bytes
    assert list(temp_root.iterdir()) == []
