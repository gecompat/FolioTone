from __future__ import annotations

import hashlib
import os
import platform
import stat
import sys
import tempfile
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import (
    EbookOperationKind,
    EbookOperationProcessorKind,
    EbookOperationReviewState,
    build_ebook_operation_expected_output,
    build_ebook_operation_processor_requirement,
    build_ebook_operation_recipe_candidate,
    build_ebook_operation_recipe_plan,
    build_ebook_operation_source_snapshot,
)
from foliotone.ebook_rename import (
    EBOOK_RENAME_PROCESSOR_PROFILE,
    ResolvedEbookRenameCapability,
    build_ebook_rename_authorization,
    build_ebook_rename_backend_binding,
    build_ebook_rename_preparation,
    build_ebook_rename_run,
)
from foliotone.ebook_rename.linux_backend import (
    LinuxEbookRenameBackend,
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
    LinuxEbookRenamePhysicalState,
)
from foliotone.persistence import OwnedScanRootWriteLease, ScanRootWriteOwnerKind
from tests.unit.test_ebook_operation_recipes import (
    NOW,
    _candidate_inputs,
    _plan_inputs,
    _review,
)
from tests.unit.test_ebook_rename_authority import _plan_and_scope

pytestmark = pytest.mark.skipif(
    sys.platform != "linux"
    or platform.machine().lower() not in {"x86_64", "amd64"}
    or not Path("/dev/shm").is_dir(),
    reason="RN03 native backend requires Linux x86_64 tmpfs",
)

AUTHORITY_NOW = NOW.replace(microsecond=0)


def _synthetic_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            "<?xml version='1.0'?><container/>",
        )


def _material(base: Path) -> dict[str, Any]:
    root = base / "root"
    probe_directory = base / "probe"
    parent = root / "library"
    root.mkdir()
    probe_directory.mkdir()
    parent.mkdir()
    source_path = parent / "Old.epub"
    target_path = parent / "New.epub"
    _synthetic_epub(source_path)
    os.utime(source_path, ns=(1_700_000_000_000_000_000,) * 2)
    details = source_path.stat(follow_symlinks=False)
    payload_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    modified_at = datetime.fromtimestamp(details.st_mtime, tz=UTC)

    base_inputs = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    template_plan, scope = _plan_and_scope()
    template_source = base_inputs.sources[0]
    source = build_ebook_operation_source_snapshot(
        ordinal=0,
        role=template_source.role,
        scan_root_id=template_source.scan_root_id,
        source_scan_run_id=template_source.source_scan_run_id,
        source_scan_run_status=template_source.source_scan_run_status,
        file_id=template_source.file_id,
        observation_id=template_source.observation_id,
        relative_locator=template_source.relative_locator,
        format_label="EPUB",
        expected_presence_state=template_source.expected_presence_state,
        expected_full_sha256=payload_hash,
        expected_size_bytes=details.st_size,
        expected_modified_at=modified_at,
        expected_observed_at=NOW,
    )
    expected_output = build_ebook_operation_expected_output(
        operation_kind=EbookOperationKind.FILE_RENAME,
        format_label="EPUB",
        expected_full_sha256=payload_hash,
        expected_size_bytes=details.st_size,
    )
    processor = build_ebook_operation_processor_requirement(
        kind=EbookOperationProcessorKind.FOLIOTONE_NATIVE,
        processor_profile=EBOOK_RENAME_PROCESSOR_PROFILE,
        configuration_fingerprint="b" * 64,
    )
    candidate = build_ebook_operation_recipe_candidate(
        replace(
            base_inputs,
            sources=(source,),
            expected_output=expected_output,
            processor_requirement=processor,
            dependencies=template_plan.candidate.dependencies,
        ),
        clock=lambda: NOW,
    )
    plan = build_ebook_operation_recipe_plan(
        _plan_inputs(
            candidate,
            _review(candidate, EbookOperationReviewState.ACCEPTED),
        ),
        clock=lambda: NOW,
    )
    capability = ResolvedEbookRenameCapability(
        ebook_rename_capability_id=EntityId.new(),
        scan_root_id=source.scan_root_id,
        scan_root_directory=root,
        probe_directory=probe_directory,
        version=1,
        configuration_fingerprint="c" * 64,
    )
    backend = LinuxEbookRenameBackend()
    probe = backend.probe(capability, probed_at=AUTHORITY_NOW)
    preparation_owner_id = EntityId.new()
    preparation_lease = OwnedScanRootWriteLease(
        scan_root_id=source.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION,
        owner_run_id=preparation_owner_id,
        lease_token="synthetic-preparation-token",
        fence_epoch=3,
        acquired_at=AUTHORITY_NOW,
        heartbeat_at=AUTHORITY_NOW,
        lease_expires_at=AUTHORITY_NOW + timedelta(minutes=20),
    )
    physical = backend.capture_preparation_evidence(
        capability=capability,
        probe=probe,
        plan=plan,
        target_historically_absent=True,
        captured_at=AUTHORITY_NOW + timedelta(seconds=1),
    )
    preparation = build_ebook_rename_preparation(
        plan,
        physical,
        capability,
        probe,
        scope,
        preparation_lease,
        authorized_at=AUTHORITY_NOW + timedelta(seconds=2),
        prepared_at=AUTHORITY_NOW + timedelta(seconds=3),
    )
    authorization = build_ebook_rename_authorization(
        preparation,
        expires_at=AUTHORITY_NOW + timedelta(minutes=10),
    )
    run_id = EntityId.new()
    run_lease = OwnedScanRootWriteLease(
        scan_root_id=source.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        owner_run_id=run_id,
        lease_token="synthetic-run-token",
        fence_epoch=4,
        acquired_at=AUTHORITY_NOW + timedelta(seconds=4),
        heartbeat_at=AUTHORITY_NOW + timedelta(seconds=4),
        lease_expires_at=AUTHORITY_NOW + timedelta(minutes=20),
    )
    run = build_ebook_rename_run(
        authorization,
        capability,
        probe,
        run_lease,
        run_id=run_id,
        created_at=AUTHORITY_NOW + timedelta(seconds=5),
    )
    binding = build_ebook_rename_backend_binding(
        run,
        authorization,
        probe,
        bound_at=run.created_at,
    )
    return {
        "backend": backend,
        "capability": capability,
        "probe": probe,
        "preparation": preparation,
        "authorization": authorization,
        "binding": binding,
        "run": run,
        "source_path": source_path,
        "target_path": target_path,
        "source_locator": source.relative_locator,
        "target_locator": plan.candidate.target.relative_locator,
    }


def _open_session(material: dict[str, Any]):
    return material["backend"].open_session(
        capability=material["capability"],
        probe=material["probe"],
        preparation=material["preparation"],
        authorization=material["authorization"],
        binding=material["binding"],
        run=material["run"],
        source_relative_locator=material["source_locator"],
        target_relative_locator=material["target_locator"],
    )


def test_native_tmpfs_probe_forward_verification_and_reverse_recovery() -> None:
    with tempfile.TemporaryDirectory(prefix="foliotone-rn03-", dir="/dev/shm") as raw:
        material = _material(Path(raw))
        with _open_session(material) as session:
            assert (
                session.revalidate_forward_preconditions().state
                is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
            )
            session.rename_forward()
            assert (
                session.verify_forward().state
                is LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
            )
            session.rename_reverse()
            assert (
                session.verify_recovery().state
                is LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
            )
        assert material["source_path"].is_file()
        assert not material["target_path"].exists()


def test_native_tmpfs_target_collision_and_hardlink_drift_do_not_mutate() -> None:
    with tempfile.TemporaryDirectory(prefix="foliotone-rn03-", dir="/dev/shm") as raw:
        material = _material(Path(raw))
        material["target_path"].write_bytes(b"synthetic collision")
        with _open_session(material) as session:
            with pytest.raises(
                LinuxEbookRenameBackendError,
                match="^TARGET_COLLISION$",
            ) as collision:
                session.revalidate_forward_preconditions()
        assert collision.value.code is LinuxEbookRenameBackendErrorCode.TARGET_COLLISION
        assert material["source_path"].is_file()

    with tempfile.TemporaryDirectory(prefix="foliotone-rn03-", dir="/dev/shm") as raw:
        material = _material(Path(raw))
        alias = material["source_path"].with_name("Alias.epub")
        os.link(material["source_path"], alias)
        assert stat.S_ISREG(alias.stat().st_mode)
        with _open_session(material) as session:
            with pytest.raises(
                LinuxEbookRenameBackendError,
                match="^SOURCE_STALE$",
            ) as stale:
                session.revalidate_forward_preconditions()
        assert stale.value.code is LinuxEbookRenameBackendErrorCode.SOURCE_STALE
        assert material["source_path"].is_file()
        assert not material["target_path"].exists()
