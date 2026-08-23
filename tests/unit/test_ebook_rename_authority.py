from __future__ import annotations

import stat
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from foliotone.core import EntityId
from foliotone.ebook_operation_recipes import (
    EbookOperationDependencyKind,
    EbookOperationDependencySnapshot,
    EbookOperationDependencyState,
    EbookOperationKind,
    EbookOperationProcessorKind,
    EbookOperationReviewState,
    build_ebook_operation_processor_requirement,
    build_ebook_operation_recipe_candidate,
    build_ebook_operation_recipe_plan,
)
from foliotone.ebook_rename import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EBOOK_RENAME_PROCESSOR_PROFILE,
    EbookRenameAuthorityError,
    EbookRenameAuthorityErrorCode,
    EbookRenameDependencyScopeAxis,
    EbookRenameDependencyScopeMode,
    EbookRenameExecutionEvent,
    EbookRenameRunStatus,
    ResolvedEbookRenameCapability,
    ResolvedEbookRenameDependencyScope,
    build_ebook_rename_authorization,
    build_ebook_rename_backend_binding,
    build_ebook_rename_capability_probe,
    build_ebook_rename_physical_evidence,
    build_ebook_rename_preparation,
    build_ebook_rename_run,
    ebook_rename_dependency_axis_material_fingerprint,
    ebook_rename_dependency_scope_material_fingerprint,
    validate_ebook_rename_event_history,
)
from foliotone.persistence import OwnedScanRootWriteLease, ScanRootWriteOwnerKind
from tests.unit.test_ebook_operation_recipes import (
    NOW,
    _candidate_inputs,
    _plan_inputs,
    _review,
)


def _plan_and_scope():
    base = _candidate_inputs(EbookOperationKind.FILE_RENAME)
    primary = base.sources[0]
    scope = ResolvedEbookRenameDependencyScope(
        dependency_scope_id=EntityId.new(),
        scan_root_id=primary.scan_root_id,
        version=1,
        axes=tuple(
            EbookRenameDependencyScopeAxis(
                kind=kind,
                mode=EbookRenameDependencyScopeMode.NOT_APPLICABLE,
            )
            for kind in EbookOperationDependencyKind
        ),
    )
    scope_material = ebook_rename_dependency_scope_material_fingerprint(scope)
    dependencies = tuple(
        EbookOperationDependencySnapshot(
            kind=kind,
            state=EbookOperationDependencyState.NOT_APPLICABLE,
            snapshot_kind=EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
            snapshot_id=primary.observation_id,
            material_fingerprint=ebook_rename_dependency_axis_material_fingerprint(
                scope_material_fingerprint=scope_material,
                scan_root_id=primary.scan_root_id,
                source_scan_run_id=primary.source_scan_run_id,
                observation_id=primary.observation_id,
                kind=kind,
                state=EbookOperationDependencyState.NOT_APPLICABLE,
                snapshot_kind=EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
                snapshot_id=primary.observation_id,
                snapshot_material=scope_material,
            ),
        )
        for kind in EbookOperationDependencyKind
    )
    processor = build_ebook_operation_processor_requirement(
        kind=EbookOperationProcessorKind.FOLIOTONE_NATIVE,
        processor_profile=EBOOK_RENAME_PROCESSOR_PROFILE,
        configuration_fingerprint="b" * 64,
    )
    candidate = build_ebook_operation_recipe_candidate(
        replace(
            base,
            processor_requirement=processor,
            dependencies=dependencies,
        ),
        clock=lambda: NOW,
    )
    review = _review(candidate, EbookOperationReviewState.ACCEPTED)
    plan = build_ebook_operation_recipe_plan(
        _plan_inputs(candidate, review),
        clock=lambda: NOW,
    )
    return plan, scope


def _material():
    plan, scope = _plan_and_scope()
    source = plan.candidate.sources[0]
    base = Path.cwd().resolve()
    capability = ResolvedEbookRenameCapability(
        ebook_rename_capability_id=EntityId.new(),
        scan_root_id=source.scan_root_id,
        scan_root_directory=base / "synthetic-private-source",
        probe_directory=base / "synthetic-private-probe",
        version=1,
        configuration_fingerprint="c" * 64,
    )
    authorized_at = NOW.replace(microsecond=0)
    probe = build_ebook_rename_capability_probe(
        capability,
        filesystem_type="xfs",
        filesystem_identity_fingerprint="d" * 64,
        kernel_release="6.12.0-synthetic",
        probed_at=authorized_at - timedelta(seconds=2),
        openat2_supported=True,
        renameat2_noreplace_supported=True,
        directory_fsync_supported=True,
        root_probe_same_filesystem=True,
    )
    lease = OwnedScanRootWriteLease(
        scan_root_id=source.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.EBOOK_RENAME_PREPARATION,
        owner_run_id=EntityId.new(),
        lease_token="private-token",
        fence_epoch=7,
        acquired_at=authorized_at - timedelta(seconds=3),
        heartbeat_at=authorized_at - timedelta(seconds=3),
        lease_expires_at=authorized_at + timedelta(minutes=20),
    )
    physical = build_ebook_rename_physical_evidence(
        plan,
        source_device=11,
        source_inode=22,
        source_mode=stat.S_IFREG | 0o600,
        source_uid=1000,
        source_gid=1000,
        source_link_count=1,
        source_size_bytes=source.expected_size_bytes,
        source_mtime_ns=123456789,
        source_modified_at=source.expected_modified_at,
        source_full_sha256=source.expected_full_sha256,
        source_xattr_fingerprint="e" * 64,
        target_physically_absent=True,
        target_historically_absent=True,
        captured_at=authorized_at,
    )
    preparation = build_ebook_rename_preparation(
        plan,
        physical,
        capability,
        probe,
        scope,
        lease,
        authorized_at=authorized_at,
        prepared_at=authorized_at + timedelta(seconds=1),
    )
    authorization = build_ebook_rename_authorization(
        preparation,
        expires_at=authorized_at + timedelta(minutes=15),
    )
    return plan, capability, probe, preparation, authorization


def test_preparation_and_authorization_are_deterministic_and_private() -> None:
    plan, capability, probe, preparation, authorization = _material()
    source = plan.candidate.sources[0]

    assert build_ebook_rename_authorization(
        preparation,
        expires_at=authorization.expires_at,
    ) == authorization
    assert source.relative_locator not in repr(preparation)
    assert plan.candidate.target.relative_locator not in repr(preparation)
    assert source.expected_full_sha256 not in repr(preparation)
    assert str(capability.scan_root_directory) not in repr(capability)
    assert probe.id == build_ebook_rename_capability_probe(
        capability,
        filesystem_type="xfs",
        filesystem_identity_fingerprint="d" * 64,
        kernel_release="6.12.0-synthetic",
        probed_at=probe.probed_at,
        openat2_supported=True,
        renameat2_noreplace_supported=True,
        directory_fsync_supported=True,
        root_probe_same_filesystem=True,
    ).id


def test_failed_probe_and_authorization_over_15_minutes_fail_closed() -> None:
    _plan, capability, probe, preparation, _authorization = _material()

    with pytest.raises(
        EbookRenameAuthorityError,
        match="^PROBE_INVALID$",
    ) as failed_probe:
        build_ebook_rename_capability_probe(
            capability,
            filesystem_type="xfs",
            filesystem_identity_fingerprint="d" * 64,
            kernel_release="6.12.0-synthetic",
            probed_at=probe.probed_at,
            openat2_supported=True,
            renameat2_noreplace_supported=False,
            directory_fsync_supported=True,
            root_probe_same_filesystem=True,
        )
    assert failed_probe.value.code is EbookRenameAuthorityErrorCode.PROBE_INVALID

    with pytest.raises(
        EbookRenameAuthorityError,
        match="^AUTHORIZATION_WINDOW_INVALID$",
    ):
        build_ebook_rename_authorization(
            preparation,
            expires_at=preparation.authorized_at + timedelta(minutes=15, seconds=1),
        )


def test_run_binding_and_event_history_allow_only_fixed_transitions() -> None:
    _plan, capability, probe, _preparation, authorization = _material()
    run_id = EntityId.new()
    lease = OwnedScanRootWriteLease(
        scan_root_id=authorization.scan_root_id,
        owner_kind=ScanRootWriteOwnerKind.EBOOK_RENAME_RUN,
        owner_run_id=run_id,
        lease_token="private-run-token",
        fence_epoch=9,
        acquired_at=authorization.prepared_at,
        heartbeat_at=authorization.prepared_at,
        lease_expires_at=authorization.expires_at + timedelta(minutes=1),
    )
    run = build_ebook_rename_run(
        authorization,
        capability,
        probe,
        lease,
        run_id=run_id,
        created_at=authorization.prepared_at + timedelta(seconds=1),
    )
    binding = build_ebook_rename_backend_binding(
        run,
        authorization,
        probe,
        bound_at=run.created_at,
    )
    prepared = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=1,
        status=EbookRenameRunStatus.PREPARED,
        occurred_at=run.created_at,
        fence_epoch=lease.fence_epoch,
        confirmation_digest="f" * 64,
    )
    relocated = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=2,
        status=EbookRenameRunStatus.RELOCATED,
        occurred_at=run.created_at + timedelta(seconds=1),
        fence_epoch=lease.fence_epoch,
    )
    immediate = EbookRenameExecutionEvent(
        run_id=run.id,
        sequence_no=3,
        status=EbookRenameRunStatus.IMMEDIATE_VERIFIED,
        occurred_at=run.created_at + timedelta(seconds=2),
        fence_epoch=lease.fence_epoch,
    )

    validate_ebook_rename_event_history((prepared, relocated, immediate))
    assert binding.run_id == run.id
    assert binding.probe_id == probe.id

    invalid = replace(
        relocated,
        status=EbookRenameRunStatus.SCAN_HANDOFF,
    )
    with pytest.raises(EbookRenameAuthorityError, match="^EVENT_INVALID$"):
        validate_ebook_rename_event_history((prepared, invalid))
