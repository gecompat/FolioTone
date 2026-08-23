"""Focused lease-boundary coverage for the quarantine operator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.core import EntityId
from foliotone.persistence.quarantine import (
    QuarantineExecutionRun,
    QuarantineStoreError,
)
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
)
from foliotone.workflows.quarantine_operation import (
    QuarantineOperatorError,
    QuarantineOperatorErrorCode,
    QuarantineOperatorService,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("e1000000-0000-0000-0000-000000000001")
OLD_RUN_ID = EntityId.parse("e1000000-0000-0000-0000-000000000002")
NEW_RUN_ID = EntityId.parse("e1000000-0000-0000-0000-000000000003")


class _LeaseStore:
    def __init__(self, current: OwnedScanRootWriteLease) -> None:
        self.current_value = current
        self.taken_over = False

    def current(self, _scan_root_id: EntityId) -> OwnedScanRootWriteLease:
        return self.current_value

    def takeover_expired(
        self,
        expired: OwnedScanRootWriteLease,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        assert expired is self.current_value
        self.taken_over = True
        return OwnedScanRootWriteLease(
            ROOT_ID,
            ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
            owner_run_id,
            lease_token,
            expired.fence_epoch + 1,
            acquired_at,
            acquired_at,
            lease_expires_at,
        )


class _RunStore:
    def __init__(
        self,
        persisted: QuarantineExecutionRun | None,
        leases: _LeaseStore,
    ) -> None:
        self.persisted = persisted
        self.leases = leases

    def takeover_expired_preparedless_lease(
        self,
        expired: OwnedScanRootWriteLease,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        if self.persisted is not None:
            raise QuarantineStoreError("synthetic persisted run requires recovery")
        return self.leases.takeover_expired(
            expired,
            owner_run_id,
            lease_token=lease_token,
            acquired_at=acquired_at,
            lease_expires_at=lease_expires_at,
        )


def test_expired_preparedless_quarantine_lease_can_be_safely_fenced_out() -> None:
    service, leases = _service(None)

    acquired = service._acquire_run_lease(NEW_RUN_ID, ROOT_ID)

    assert acquired.owner_run_id == NEW_RUN_ID
    assert acquired.fence_epoch == 8
    assert acquired.lease_expires_at == NOW + timedelta(minutes=30)
    assert leases.taken_over is True


def test_expired_lease_with_a_persisted_run_remains_recovery_only() -> None:
    persisted = QuarantineExecutionRun(
        OLD_RUN_ID,
        EntityId.new(),
        EntityId.new(),
        ROOT_ID,
        EntityId.new(),
        EntityId.new(),
        "a" * 64,
        NOW - timedelta(minutes=10),
    )
    service, leases = _service(persisted)

    with pytest.raises(QuarantineOperatorError) as captured:
        service._acquire_run_lease(NEW_RUN_ID, ROOT_ID)

    assert captured.value.code is QuarantineOperatorErrorCode.FENCED_OUT
    assert leases.taken_over is False


def _service(
    persisted: QuarantineExecutionRun | None,
) -> tuple[QuarantineOperatorService, _LeaseStore]:
    expired = OwnedScanRootWriteLease(
        ROOT_ID,
        ScanRootWriteOwnerKind.CONSOLIDATION_QUARANTINE_RUN,
        OLD_RUN_ID,
        "expired-synthetic-token",
        7,
        NOW - timedelta(minutes=10),
        NOW - timedelta(minutes=10),
        NOW - timedelta(minutes=1),
    )
    leases = _LeaseStore(expired)
    service = object.__new__(QuarantineOperatorService)
    service._clock = lambda: NOW
    service._leases = leases
    service._quarantine = _RunStore(persisted, leases)
    return service, leases
