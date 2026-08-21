"""Root-wide SQLite write ownership with monotonic fencing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Engine, Table, insert, update
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from foliotone.core import EntityId
from foliotone.persistence import schema
from foliotone.persistence._mapping import datetime_to_db, required_datetime_from_db


class ScanRootWriteLeaseError(RuntimeError):
    """A root writer is active, expired, or no longer owns its fence."""


class ScanRootWriteOwnerKind(StrEnum):
    """Root-scoped writer kinds participating in the shared fence."""

    SCAN_RUN = "SCAN_RUN"
    EBOOK_CANDIDATE_HASH_RUN = "EBOOK_CANDIDATE_HASH_RUN"
    EBOOK_COLLECTION_RUN = "EBOOK_COLLECTION_RUN"
    EBOOK_ANALYSIS = "EBOOK_ANALYSIS"
    ARCHIVE_COLLECTION_RUN = "ARCHIVE_COLLECTION_RUN"


@dataclass(frozen=True, slots=True)
class OwnedScanRootWriteLease:
    """Opaque ownership proof for one root-wide writer invocation."""

    scan_root_id: EntityId
    owner_kind: ScanRootWriteOwnerKind
    owner_run_id: EntityId
    lease_token: str = field(repr=False)
    fence_epoch: int
    acquired_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        if not self.lease_token:
            raise ValueError("lease_token must not be empty")
        if self.fence_epoch <= 0:
            raise ValueError("fence_epoch must be positive")
        if self.heartbeat_at < self.acquired_at:
            raise ValueError("heartbeat precedes acquisition")
        if self.lease_expires_at <= self.heartbeat_at:
            raise ValueError("lease must expire after heartbeat")


@dataclass(frozen=True, slots=True)
class ScanRootWriteScope:
    """Thread-local proof used by generic persistence sinks during analysis."""

    lease: OwnedScanRootWriteLease
    clock: Callable[[], datetime]


_ACTIVE_WRITE_SCOPE: ContextVar[ScanRootWriteScope | None] = ContextVar(
    "foliotone_scan_root_write_scope",
    default=None,
)


@contextmanager
def scan_root_write_scope(
    lease: OwnedScanRootWriteLease,
    clock: Callable[[], datetime],
) -> Iterator[None]:
    """Fence generic repository writes performed in the current worker context."""

    token = _ACTIVE_WRITE_SCOPE.set(ScanRootWriteScope(lease=lease, clock=clock))
    try:
        yield
    finally:
        _ACTIVE_WRITE_SCOPE.reset(token)


def fence_scoped_write(connection: Connection) -> None:
    """Apply the active root fence to one generic repository transaction."""

    scope = _ACTIVE_WRITE_SCOPE.get()
    if scope is None:
        return
    table = schema.scan_root_write_leases
    result = connection.execute(
        update(table)
        .where(
            *_owned_conditions(
                table,
                scope.lease,
                _required_datetime_to_db(scope.clock()),
            )
        )
        .values(heartbeat_at=table.c.heartbeat_at)
    )
    _require_owned(result.rowcount)


class SQLiteScanRootWriteLeaseStore:
    """Acquire, renew, fence, and release one writer per ScanRoot."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def acquire(
        self,
        scan_root_id: EntityId,
        owner_kind: ScanRootWriteOwnerKind,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        if not isinstance(owner_kind, ScanRootWriteOwnerKind):
            raise TypeError("owner_kind must be ScanRootWriteOwnerKind")
        if not lease_token:
            raise ValueError("lease_token must not be empty")
        if lease_expires_at <= acquired_at:
            raise ValueError("lease must expire after acquisition")

        with self._engine.begin() as connection:
            return self.acquire_in_transaction(
                connection,
                scan_root_id,
                owner_kind,
                owner_run_id,
                lease_token=lease_token,
                acquired_at=acquired_at,
                lease_expires_at=lease_expires_at,
            )

    def acquire_in_transaction(
        self,
        connection: Connection,
        scan_root_id: EntityId,
        owner_kind: ScanRootWriteOwnerKind,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        """Acquire inside the exact transaction that creates the owner run."""

        if not isinstance(owner_kind, ScanRootWriteOwnerKind):
            raise TypeError("owner_kind must be ScanRootWriteOwnerKind")
        if not lease_token:
            raise ValueError("lease_token must not be empty")
        if lease_expires_at <= acquired_at:
            raise ValueError("lease must expire after acquisition")
        table = schema.scan_root_write_leases
        acquired = _required_datetime_to_db(acquired_at)
        connection.execute(
            insert(table)
            .values(scan_root_id=str(scan_root_id), fence_epoch=0)
            .prefix_with("OR IGNORE")
        )
        result = connection.execute(
            update(table)
            .where(
                table.c.scan_root_id == str(scan_root_id),
                table.c.lease_token.is_(None),
                table.c.fence_epoch < 2**63 - 1,
            )
            .values(
                owner_kind=owner_kind.value,
                owner_run_id=str(owner_run_id),
                lease_token=lease_token,
                lease_expires_at=_required_datetime_to_db(lease_expires_at),
                heartbeat_at=acquired,
                acquired_at=acquired,
                fence_epoch=table.c.fence_epoch + 1,
            )
        )
        if result.rowcount != 1:
            raise ScanRootWriteLeaseError(
                "an active writer already owns this ScanRoot"
            )
        epoch = int(
            connection.execute(
                table.select().with_only_columns(table.c.fence_epoch).where(
                    table.c.scan_root_id == str(scan_root_id)
                )
            ).scalar_one()
        )
        return OwnedScanRootWriteLease(
            scan_root_id=scan_root_id,
            owner_kind=owner_kind,
            owner_run_id=owner_run_id,
            lease_token=lease_token,
            fence_epoch=epoch,
            acquired_at=acquired_at,
            heartbeat_at=acquired_at,
            lease_expires_at=lease_expires_at,
        )

    def takeover_expired(
        self,
        expired: OwnedScanRootWriteLease,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        with self._engine.begin() as connection:
            return self.takeover_expired_in_transaction(
                connection,
                expired,
                owner_run_id,
                lease_token=lease_token,
                acquired_at=acquired_at,
                lease_expires_at=lease_expires_at,
            )

    def takeover_expired_in_transaction(
        self,
        connection: Connection,
        expired: OwnedScanRootWriteLease,
        owner_run_id: EntityId,
        *,
        lease_token: str,
        acquired_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        """Replace one expired same-kind owner after its run is recoverable."""

        if not lease_token:
            raise ValueError("lease_token must not be empty")
        if acquired_at < expired.lease_expires_at:
            raise ScanRootWriteLeaseError("ScanRoot writer lease is still active")
        if lease_expires_at <= acquired_at:
            raise ValueError("lease must expire after acquisition")
        table = schema.scan_root_write_leases
        acquired = _required_datetime_to_db(acquired_at)
        result = connection.execute(
            update(table)
            .where(
                table.c.scan_root_id == str(expired.scan_root_id),
                table.c.owner_kind == expired.owner_kind.value,
                table.c.owner_run_id == str(expired.owner_run_id),
                table.c.lease_token == expired.lease_token,
                table.c.fence_epoch == expired.fence_epoch,
                table.c.lease_expires_at <= acquired,
                table.c.fence_epoch < 2**63 - 1,
            )
            .values(
                owner_run_id=str(owner_run_id),
                lease_token=lease_token,
                fence_epoch=table.c.fence_epoch + 1,
                lease_expires_at=_required_datetime_to_db(lease_expires_at),
                heartbeat_at=acquired,
                acquired_at=acquired,
            )
        )
        if result.rowcount != 1:
            raise ScanRootWriteLeaseError(
                "expired ScanRoot writer could not be recovered"
            )
        return OwnedScanRootWriteLease(
            scan_root_id=expired.scan_root_id,
            owner_kind=expired.owner_kind,
            owner_run_id=owner_run_id,
            lease_token=lease_token,
            fence_epoch=expired.fence_epoch + 1,
            acquired_at=acquired_at,
            heartbeat_at=acquired_at,
            lease_expires_at=lease_expires_at,
        )

    def current(self, scan_root_id: EntityId) -> OwnedScanRootWriteLease | None:
        with self._engine.connect() as connection:
            return self.current_in_transaction(connection, scan_root_id)

    @staticmethod
    def current_in_transaction(
        connection: Connection,
        scan_root_id: EntityId,
    ) -> OwnedScanRootWriteLease | None:
        row = connection.execute(
            schema.scan_root_write_leases.select().where(
                schema.scan_root_write_leases.c.scan_root_id == str(scan_root_id),
                schema.scan_root_write_leases.c.lease_token.is_not(None),
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        return OwnedScanRootWriteLease(
            scan_root_id=EntityId.parse(str(row["scan_root_id"])),
            owner_kind=ScanRootWriteOwnerKind(str(row["owner_kind"])),
            owner_run_id=EntityId.parse(str(row["owner_run_id"])),
            lease_token=str(row["lease_token"]),
            fence_epoch=int(row["fence_epoch"]),
            acquired_at=_required_datetime_from_db(row["acquired_at"]),
            heartbeat_at=_required_datetime_from_db(row["heartbeat_at"]),
            lease_expires_at=_required_datetime_from_db(row["lease_expires_at"]),
        )

    def heartbeat(
        self,
        lease: OwnedScanRootWriteLease,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        if lease_expires_at <= heartbeat_at:
            raise ValueError("lease must expire after heartbeat")
        with self._engine.begin() as connection:
            return self.heartbeat_in_transaction(
                connection,
                lease,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )

    def heartbeat_in_transaction(
        self,
        connection: Connection,
        lease: OwnedScanRootWriteLease,
        *,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> OwnedScanRootWriteLease:
        if lease_expires_at <= heartbeat_at:
            raise ValueError("lease must expire after heartbeat")
        table = schema.scan_root_write_leases
        heartbeat = _required_datetime_to_db(heartbeat_at)
        result = connection.execute(
            update(table)
            .where(*_owned_conditions(table, lease, heartbeat))
            .values(
                heartbeat_at=heartbeat,
                lease_expires_at=_required_datetime_to_db(lease_expires_at),
            )
        )
        _require_owned(result.rowcount)
        return replace(
            lease,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )

    def fence(
        self,
        connection: Connection,
        lease: OwnedScanRootWriteLease,
        now: datetime,
    ) -> None:
        """Take the SQLite write lock and prove ownership in this transaction."""

        table = schema.scan_root_write_leases
        result = connection.execute(
            update(table)
            .where(*_owned_conditions(table, lease, _required_datetime_to_db(now)))
            .values(heartbeat_at=table.c.heartbeat_at)
        )
        _require_owned(result.rowcount)

    def release(
        self,
        lease: OwnedScanRootWriteLease,
        *,
        released_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            self.release_in_transaction(connection, lease, released_at=released_at)

    def release_in_transaction(
        self,
        connection: Connection,
        lease: OwnedScanRootWriteLease,
        *,
        released_at: datetime,
    ) -> None:
        table = schema.scan_root_write_leases
        released = _required_datetime_to_db(released_at)
        result = connection.execute(
            update(table)
            .where(*_owned_conditions(table, lease, released))
            .values(
                owner_kind=None,
                owner_run_id=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                acquired_at=None,
            )
        )
        _require_owned(result.rowcount)

    def release_if_owned_in_transaction(
        self,
        connection: Connection,
        lease: OwnedScanRootWriteLease,
        *,
        released_at: datetime,
    ) -> bool:
        table = schema.scan_root_write_leases
        result = connection.execute(
            update(table)
            .where(
                *_owned_conditions(
                    table,
                    lease,
                    _required_datetime_to_db(released_at),
                )
            )
            .values(
                owner_kind=None,
                owner_run_id=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                acquired_at=None,
            )
        )
        return result.rowcount == 1


def _owned_conditions(
    table: Table,
    lease: OwnedScanRootWriteLease,
    now: str,
) -> tuple[ColumnElement[bool], ...]:
    return (
        table.c.scan_root_id == str(lease.scan_root_id),
        table.c.owner_kind == lease.owner_kind.value,
        table.c.owner_run_id == str(lease.owner_run_id),
        table.c.lease_token == lease.lease_token,
        table.c.fence_epoch == lease.fence_epoch,
        table.c.lease_expires_at > now,
    )


def _require_owned(rowcount: int | None) -> None:
    if rowcount != 1:
        raise ScanRootWriteLeaseError(
            "ScanRoot write lease is unavailable, expired, or fenced"
        )


def _required_datetime_to_db(value: datetime) -> str:
    encoded = datetime_to_db(value)
    if encoded is None:
        raise AssertionError("non-null lease datetime encoded as None")
    return encoded


def _required_datetime_from_db(value: object) -> datetime:
    return required_datetime_from_db(str(value))
