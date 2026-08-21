from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest

from foliotone.archive.container_sandbox import (
    ArchiveContainerRequest,
    ArchiveLinuxContainerRunner,
    ArchiveRuntimePreflightInputs,
    ArchiveVolumeSource,
    DockerCliSandboxBackend,
    LocalSandboxFilesystem,
)
from foliotone.archive.process_runner import ArchiveProcessRunner, SubprocessLauncher
from foliotone.archive.provider import (
    ArchiveSevenZipProvider,
    _ArchiveWrapperReuseEvidence,
    build_archive_volume_group_fingerprint,
)
from foliotone.archive.safety_policy import ArchiveSafetyStatus
from foliotone.archive.sevenzip import build_7zzs_listing_command
from foliotone.archive.signatures import ArchiveListingStatus, observe_archive_signature_v2
from foliotone.archive.workflow import ArchiveEncryptionStatus, ArchiveIntegrityStatus


def test_provisioned_provider_lists_and_tests_fixture_without_source_mutation(
    tmp_path: Path,
) -> None:
    if sys.platform != "linux":
        pytest.skip("native Windows archive sandbox is intentionally unavailable")
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() not in {0, 65_532}:
        pytest.skip("numeric 65532 ownership projection is unavailable")

    private_parent = os.environ.get("FOLIOTONE_ARCHIVE_PRIVATE_STATE_PARENT")
    local_state = os.environ.get("FOLIOTONE_ARCHIVE_LOCAL_STATE_ROOT")
    oci_layout = os.environ.get("FOLIOTONE_ARCHIVE_OCI_LAYOUT")
    if not all((private_parent, local_state, oci_layout)):
        pytest.skip("provisioned offline archive runtime paths are not configured")
    assert private_parent is not None
    assert local_state is not None
    assert oci_layout is not None

    repository_root = Path(__file__).parents[2]
    package_root = repository_root / "packaging" / "archive" / "7zip-26.02"
    fixture = (
        repository_root
        / "tests"
        / "fixtures"
        / "archive"
        / "7zip-26.02"
        / "v2"
        / "zip-plaintext.zip"
    )
    fixture_bytes = fixture.read_bytes()
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    scan_root = tmp_path / "synthetic-scan"
    temp_root = tmp_path / "sandbox-temp"
    scan_root.mkdir(mode=0o700)
    temp_root.mkdir(mode=0o700)
    source = scan_root / "fixture.zip"
    shutil.copyfile(fixture, source)
    source.chmod(0o600)

    preflight = ArchiveRuntimePreflightInputs(
        package_root / "archive-image.lock.json",
        package_root / "archive-runtime-release.json",
        package_root / "archive-runtime-revocations.json",
        package_root / "archive-runtime-evidence",
        Path(local_state),
        Path(private_parent),
        Path(oci_layout),
    )
    process_runner = ArchiveProcessRunner(SubprocessLauncher())
    docker = DockerCliSandboxBackend.discover(process_runner)
    filesystem = LocalSandboxFilesystem()
    if docker is None or not filesystem.supports_linux_sandbox:
        pytest.skip("local locked Linux archive runtime is unavailable")

    runner = ArchiveLinuxContainerRunner(
        temp_root=temp_root,
        runtime_preflight=preflight,
        filesystem=filesystem,
        docker=docker,
        process_runner=process_runner,
    )
    request = ArchiveContainerRequest(
        (ArchiveVolumeSource(source, len(fixture_bytes), fixture_sha256, "archive"),),
        build_7zzs_listing_command(),
        (scan_root,),
    )
    outcome = ArchiveSevenZipProvider(runner).inspect(
        request,
        signature=observe_archive_signature_v2(source.name, fixture_bytes[:512]),
        archive_observation_id="synthetic-archive-observation",
        archive_full_sha256=fixture_sha256,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
    )

    assert outcome.result is not None
    assert outcome.result.listing_status is ArchiveListingStatus.LISTED
    assert outcome.result.integrity_status is ArchiveIntegrityStatus.PASSED
    assert outcome.result.encryption_status is ArchiveEncryptionStatus.NONE
    assert len(outcome.executions) == 2
    assert outcome.result.member_count == 1
    assert not hasattr(outcome.result, "members")
    assert source.read_bytes() == fixture_bytes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == fixture_sha256
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    "fixture_name",
    ["tar.tar.gz", "tar.tar.bz2", "tar.tar.xz", "tar.tar.zst"],
)
def test_provisioned_provider_streams_each_wrapper_twice_without_handoff(
    tmp_path: Path,
    fixture_name: str,
) -> None:
    if sys.platform != "linux":
        pytest.skip("native Windows archive sandbox is intentionally unavailable")
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() not in {0, 65_532}:
        pytest.skip("numeric 65532 ownership projection is unavailable")
    private_parent = os.environ.get("FOLIOTONE_ARCHIVE_PRIVATE_STATE_PARENT")
    local_state = os.environ.get("FOLIOTONE_ARCHIVE_LOCAL_STATE_ROOT")
    oci_layout = os.environ.get("FOLIOTONE_ARCHIVE_OCI_LAYOUT")
    if not all((private_parent, local_state, oci_layout)):
        pytest.skip("provisioned offline archive runtime paths are not configured")
    assert private_parent is not None
    assert local_state is not None
    assert oci_layout is not None

    repository_root = Path(__file__).parents[2]
    package_root = repository_root / "packaging" / "archive" / "7zip-26.02"
    fixture = (
        repository_root
        / "tests/fixtures/archive/7zip-26.02/v1/outer"
        / fixture_name
    )
    fixture_bytes = fixture.read_bytes()
    fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()
    scan_root = tmp_path / "synthetic-wrapper-scan"
    temp_root = tmp_path / "wrapper-sandbox-temp"
    scan_root.mkdir(mode=0o700)
    temp_root.mkdir(mode=0o700)
    source = scan_root / fixture_name
    shutil.copyfile(fixture, source)
    source.chmod(0o600)
    preflight = ArchiveRuntimePreflightInputs(
        package_root / "archive-image.lock.json",
        package_root / "archive-runtime-release.json",
        package_root / "archive-runtime-revocations.json",
        package_root / "archive-runtime-evidence",
        Path(local_state),
        Path(private_parent),
        Path(oci_layout),
    )
    process_runner = ArchiveProcessRunner(SubprocessLauncher())
    docker = DockerCliSandboxBackend.discover(process_runner)
    filesystem = LocalSandboxFilesystem()
    if docker is None or not filesystem.supports_linux_sandbox:
        pytest.skip("local locked Linux archive runtime is unavailable")
    runner = ArchiveLinuxContainerRunner(
        temp_root=temp_root,
        runtime_preflight=preflight,
        filesystem=filesystem,
        docker=docker,
        process_runner=process_runner,
    )
    request = ArchiveContainerRequest(
        (ArchiveVolumeSource(source, len(fixture_bytes), fixture_sha256, "archive"),),
        build_7zzs_listing_command(),
        (scan_root,),
    )
    outcome = ArchiveSevenZipProvider(runner).inspect(
        request,
        signature=observe_archive_signature_v2(source.name, fixture_bytes[:512]),
        archive_observation_id="synthetic-wrapper-observation",
        archive_full_sha256=fixture_sha256,
        volume_group_fingerprint=build_archive_volume_group_fingerprint(request),
    )

    assert outcome.result is not None
    assert outcome.result.listing_status is ArchiveListingStatus.LISTED
    assert outcome.result.integrity_status is ArchiveIntegrityStatus.PASSED
    assert outcome.result.encryption_status is ArchiveEncryptionStatus.NONE
    assert outcome.result.extraction_policy_status is ArchiveSafetyStatus.POLICY_REJECTED
    assert outcome._extraction_handoff is None
    assert isinstance(outcome._wrapper_reuse_evidence, _ArchiveWrapperReuseEvidence)
    assert outcome._wrapper_reuse_evidence.inner_stream_size_bytes == 2_048
    assert (
        outcome._wrapper_reuse_evidence.inner_stream_sha256
        == "eadd731905c30e6e2412522a7b6b089730f3b260b5c68224b4cfb732dcf352c4"
    )
    assert source.read_bytes() == fixture_bytes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == fixture_sha256
    assert list(temp_root.iterdir()) == []
