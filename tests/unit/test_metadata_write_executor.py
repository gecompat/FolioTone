from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from foliotone.core import EntityId
from foliotone.metadata_write.authorization import (
    MetadataWriteExecutionEvent,
    MetadataWriteRunStatus,
)
from foliotone.metadata_write.capabilities import ResolvedMetadataWriteCapability
from foliotone.metadata_write.executor import (
    MetadataWriteExecutorError,
    MetadataWriteExecutorErrorCode,
    execute_epub3_title_metadata_write,
    recover_epub3_title_metadata_write,
)
from foliotone.metadata_write.linux_backend import (
    LinuxMetadataWriteBackendError,
    LinuxMetadataWriteBackendErrorCode,
    LinuxMetadataWritePhysicalSnapshot,
    LinuxMetadataWritePhysicalState,
)
from foliotone.persistence.metadata_write import MetadataWriteSourceSnapshot
from foliotone.persistence.scan_root_lease import (
    OwnedScanRootWriteLease,
    ScanRootWriteOwnerKind,
)

NOW = datetime(2026, 8, 22, 20, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("b1000000-0000-0000-0000-000000000001")
FILE_ID = EntityId.parse("b1000000-0000-0000-0000-000000000002")
OBSERVATION_ID = EntityId.parse("b1000000-0000-0000-0000-000000000003")
PLAN_ID = EntityId.parse("b1000000-0000-0000-0000-000000000004")
AUTHORIZATION_ID = EntityId.parse("b1000000-0000-0000-0000-000000000005")
CAPABILITY_ID = EntityId.parse("b1000000-0000-0000-0000-000000000006")
RUN_ID = EntityId.parse("b1000000-0000-0000-0000-000000000007")
PRIVATE_PATH = "private/synthetic-book.epub"
SOURCE = b"synthetic source"
OUTPUT = b"synthetic output"


def _sha(value: bytes | str) -> str:
    data = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(data).hexdigest()


class _Store:
    def __init__(self, source: MetadataWriteSourceSnapshot) -> None:
        self.source = source
        self.binding: object | None = None
        self.events = [
            MetadataWriteExecutionEvent(
                RUN_ID,
                1,
                MetadataWriteRunStatus.CREATED,
                NOW + timedelta(seconds=1),
                2,
            )
        ]
        self.recovery_checks = 0
        self.bound_at: datetime | None = None
        self.execution_checked_at: list[datetime] = []
        self.recovery_checked_at: list[datetime] = []

    def bind_backend(self, *_args, **kwargs):
        self.binding = object()
        self.bound_at = kwargs["bound_at"]
        return self.binding

    def require_execution_source(self, *_args, **kwargs):
        self.execution_checked_at.append(kwargs["checked_at"])
        return self.source

    def require_recovery_source(self, *_args, **kwargs):
        self.recovery_checks += 1
        self.recovery_checked_at.append(kwargs["checked_at"])
        return self.source

    def require_prepared_execution_source(self, *_args, **kwargs):
        self.execution_checked_at.append(kwargs["checked_at"])
        return self.source

    def get_backend_binding(self, _run_id):
        return self.binding

    def events_for_run(self, _run_id):
        return tuple(self.events)

    def append_event(self, value, _lease):
        assert value.sequence_no == len(self.events) + 1
        self.events.append(value)
        return value


class _Session:
    def __init__(
        self,
        *,
        state: LinuxMetadataWritePhysicalState = (
            LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY
        ),
        fail_preserve: bool = False,
    ) -> None:
        self.state = state
        self.fail_preserve = fail_preserve
        self.closed = False
        self.restore_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def read_source_bytes(self) -> bytes:
        return SOURCE

    def prepare_output(self, _staged_output: Path):
        self.state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        return self.classify()

    def revalidate_prepared(self):
        return self.classify()

    def exchange(self):
        self.state = LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_ORIGINAL_DRAFT
        return self.classify()

    def preserve_original(self):
        if self.fail_preserve:
            raise LinuxMetadataWriteBackendError(
                LinuxMetadataWriteBackendErrorCode.IO_FAILED
            )
        self.state = (
            LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
        )
        return self.classify()

    def restore_original(self):
        self.restore_calls += 1
        self.state = LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
        return self.classify()

    def classify(self):
        return self.confirmation_for(self.state)

    def confirmation_for(self, state: LinuxMetadataWritePhysicalState):
        return LinuxMetadataWritePhysicalSnapshot(state, _sha(state.value))


class _Backend:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.source_relative_path: str | None = None

    def open_session(self, *, source_relative_path: str, **_kwargs):
        self.source_relative_path = source_relative_path
        return self.session


class _TickingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        value = NOW + timedelta(seconds=2 + self.calls)
        self.calls += 1
        return value


def _context(tmp_path: Path):
    for name in ("source", "recovery", "stage"):
        directory = tmp_path / name
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    capability = ResolvedMetadataWriteCapability(
        CAPABILITY_ID,
        ROOT_ID,
        tmp_path / "source",
        tmp_path / "recovery",
    )
    authorization = SimpleNamespace(
        id=AUTHORIZATION_ID,
        plan_id=PLAN_ID,
        plan_content_hash="3" * 64,
        scan_root_id=ROOT_ID,
        file_id=FILE_ID,
        observation_id=OBSERVATION_ID,
        source_sha256=_sha(SOURCE),
        source_size_bytes=len(SOURCE),
        expected_output_sha256=_sha(OUTPUT),
        expected_output_size_bytes=len(OUTPUT),
        metadata_write_capability_id=CAPABILITY_ID,
        authorized_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        metadata_tool_version="metadata/1",
        epubcheck_tool_version="epubcheck/1",
        text_tool_version="text/1",
        cover_tool_version="cover/1",
        validator_set_fingerprint="4" * 64,
    )
    run = SimpleNamespace(id=RUN_ID)
    lease = OwnedScanRootWriteLease(
        scan_root_id=ROOT_ID,
        owner_kind=ScanRootWriteOwnerKind.METADATA_WRITE_RUN,
        owner_run_id=RUN_ID,
        lease_token="synthetic-executor",
        fence_epoch=2,
        acquired_at=NOW,
        heartbeat_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=15),
    )
    source = MetadataWriteSourceSnapshot(
        run_id=RUN_ID,
        authorization_id=AUTHORIZATION_ID,
        plan_id=PLAN_ID,
        scan_root_id=ROOT_ID,
        file_id=FILE_ID,
        observation_id=OBSERVATION_ID,
        relative_path=PRIVATE_PATH,
        source_sha256=_sha(SOURCE),
        source_size_bytes=len(SOURCE),
        expected_modified_at=NOW,
    )
    plan = SimpleNamespace(id=PLAN_ID)
    return capability, authorization, run, lease, source, plan


def _verified(authorization, stage_directory: Path):
    output_path = stage_directory / "output.epub"
    staged = SimpleNamespace(
        plan_id=authorization.plan_id,
        plan_content_hash=authorization.plan_content_hash,
        input_sha256=authorization.source_sha256,
        input_size_bytes=authorization.source_size_bytes,
        output_sha256=authorization.expected_output_sha256,
        output_size_bytes=authorization.expected_output_size_bytes,
        output_path=output_path,
    )
    validation = SimpleNamespace(
        output_sha256=authorization.expected_output_sha256,
        metadata_tool_version=authorization.metadata_tool_version,
        epubcheck_tool_version=authorization.epubcheck_tool_version,
        text_tool_version=authorization.text_tool_version,
        cover_tool_version=authorization.cover_tool_version,
        validator_set_fingerprint=authorization.validator_set_fingerprint,
    )
    return SimpleNamespace(staged_files=staged, validation=validation)


def _patch_staging(
    monkeypatch: pytest.MonkeyPatch,
    authorization,
) -> None:
    monkeypatch.setattr(
        "foliotone.metadata_write.executor.preflight_epub3_title_write",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "foliotone.metadata_write.executor.build_epub3_title_package_patch",
        lambda *_args, **_kwargs: object(),
    )

    def build(stage_directory, *_args, **_kwargs):
        return _verified(authorization, stage_directory)

    monkeypatch.setattr(
        "foliotone.metadata_write.executor.build_and_verify_private_epub3_title_stage",
        build,
    )


def test_executor_stops_at_original_preserved_and_hides_locator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    _patch_staging(monkeypatch, authorization)
    store = _Store(source)
    session = _Session()
    backend = _Backend(session)
    clock = _TickingClock()

    result = execute_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        private_stage_root=tmp_path / "stage",
        clock=clock,
        backend=backend,
    )

    assert result.status is MetadataWriteRunStatus.ORIGINAL_PRESERVED
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
    ]
    assert backend.source_relative_path == PRIVATE_PATH
    assert PRIVATE_PATH not in repr(result)
    assert session.closed is True
    assert store.bound_at is not None
    assert store.execution_checked_at == [
        NOW + timedelta(seconds=3),
        NOW + timedelta(seconds=4),
        NOW + timedelta(seconds=5),
        NOW + timedelta(seconds=6),
    ]
    assert store.recovery_checked_at == [NOW + timedelta(seconds=8)]


def test_executor_recovers_an_exact_post_exchange_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    _patch_staging(monkeypatch, authorization)
    store = _Store(source)
    session = _Session(fail_preserve=True)

    with pytest.raises(MetadataWriteExecutorError) as raised:
        execute_epub3_title_metadata_write(
            store=store,  # type: ignore[arg-type]
            run=run,  # type: ignore[arg-type]
            authorization=authorization,  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            capability=capability,
            lease=lease,
            private_stage_root=tmp_path / "stage",
            clock=lambda: NOW + timedelta(seconds=2),
            backend=_Backend(session),
        )

    assert raised.value.code is MetadataWriteExecutorErrorCode.VALIDATION_FAILED
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.VALIDATION_FAILED,
        MetadataWriteRunStatus.RECOVERED,
    ]
    assert session.restore_calls == 1
    assert session.closed is True


def test_executor_refuses_source_draft_without_safe_lease_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    _patch_staging(monkeypatch, authorization)
    lease = replace(
        lease,
        lease_expires_at=NOW + timedelta(minutes=10),
    )
    store = _Store(source)
    session = _Session()

    with pytest.raises(MetadataWriteExecutorError) as raised:
        execute_epub3_title_metadata_write(
            store=store,  # type: ignore[arg-type]
            run=run,  # type: ignore[arg-type]
            authorization=authorization,  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            capability=capability,
            lease=lease,
            private_stage_root=tmp_path / "stage",
            clock=lambda: NOW + timedelta(minutes=9),
            backend=_Backend(session),
        )

    assert raised.value.code is MetadataWriteExecutorErrorCode.FENCED_OUT
    assert session.state is LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_ONLY
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.FENCED_OUT,
    ]
    assert session.closed is True


def test_executor_rechecks_lease_immediately_before_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    _patch_staging(monkeypatch, authorization)
    lease = replace(
        lease,
        lease_expires_at=NOW + timedelta(minutes=10),
    )
    store = _Store(source)
    session = _Session()
    times = iter(
        [NOW + timedelta(seconds=2)] * 4
        + [NOW + timedelta(minutes=9)] * 5
    )

    with pytest.raises(MetadataWriteExecutorError) as raised:
        execute_epub3_title_metadata_write(
            store=store,  # type: ignore[arg-type]
            run=run,  # type: ignore[arg-type]
            authorization=authorization,  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            capability=capability,
            lease=lease,
            private_stage_root=tmp_path / "stage",
            clock=lambda: next(times),
            backend=_Backend(session),
        )

    assert raised.value.code is MetadataWriteExecutorErrorCode.FENCED_OUT
    assert session.state is (
        LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
    )
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.FENCED_OUT,
    ]
    assert session.restore_calls == 0
    assert session.closed is True


def test_recovery_reconstructs_a_crash_after_original_preservation(
    tmp_path: Path,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    store = _Store(source)
    store.binding = object()
    store.events.append(
        MetadataWriteExecutionEvent(
            RUN_ID,
            2,
            MetadataWriteRunStatus.PREPARED,
            NOW + timedelta(seconds=2),
            lease.fence_epoch,
            confirmation_digest="5" * 64,
        )
    )
    session = _Session(
        state=LinuxMetadataWritePhysicalState.SOURCE_OUTPUT_WITH_PRESERVED_ORIGINAL
    )

    result = recover_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        clock=lambda: NOW + timedelta(seconds=3),
        backend=_Backend(session),
    )

    assert result.status is MetadataWriteRunStatus.RECOVERED
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.EXCHANGED,
        MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        MetadataWriteRunStatus.RECOVERED,
    ]
    assert store.recovery_checks == 3
    assert session.restore_calls == 1
    assert session.closed is True


def test_recovery_cancels_an_unexchanged_prepared_draft_idempotently(
    tmp_path: Path,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    store = _Store(source)
    store.binding = object()
    store.events.append(
        MetadataWriteExecutionEvent(
            RUN_ID,
            2,
            MetadataWriteRunStatus.PREPARED,
            NOW + timedelta(seconds=2),
            lease.fence_epoch,
            confirmation_digest="5" * 64,
        )
    )
    session = _Session(
        state=LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
    )
    backend = _Backend(session)

    result = recover_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        clock=lambda: NOW + timedelta(seconds=3),
        backend=backend,
    )
    retry = recover_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        clock=lambda: NOW + timedelta(seconds=4),
        backend=backend,
    )

    assert result.status is MetadataWriteRunStatus.CANCELLED
    assert retry == result
    assert [event.status for event in store.events] == [
        MetadataWriteRunStatus.CREATED,
        MetadataWriteRunStatus.PREPARED,
        MetadataWriteRunStatus.CANCELLED,
    ]
    assert session.restore_calls == 0


def test_recovery_journals_an_already_restored_exchange_idempotently(
    tmp_path: Path,
) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    store = _Store(source)
    store.binding = object()
    for sequence, status in enumerate(
        (
            MetadataWriteRunStatus.PREPARED,
            MetadataWriteRunStatus.EXCHANGED,
            MetadataWriteRunStatus.ORIGINAL_PRESERVED,
        ),
        start=2,
    ):
        store.events.append(
            MetadataWriteExecutionEvent(
                RUN_ID,
                sequence,
                status,
                NOW + timedelta(seconds=sequence),
                lease.fence_epoch,
                confirmation_digest="5" * 64,
            )
        )
    session = _Session(
        state=LinuxMetadataWritePhysicalState.SOURCE_ORIGINAL_WITH_OUTPUT_DRAFT
    )
    backend = _Backend(session)

    result = recover_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        clock=lambda: NOW + timedelta(seconds=6),
        backend=backend,
    )
    retry = recover_epub3_title_metadata_write(
        store=store,  # type: ignore[arg-type]
        run=run,  # type: ignore[arg-type]
        authorization=authorization,  # type: ignore[arg-type]
        plan=plan,  # type: ignore[arg-type]
        capability=capability,
        lease=lease,
        clock=lambda: NOW + timedelta(seconds=7),
        backend=backend,
    )

    assert result.status is MetadataWriteRunStatus.RECOVERED
    assert retry == result
    assert store.events[-1].status is MetadataWriteRunStatus.RECOVERED
    assert session.restore_calls == 0


def test_recovery_never_mutates_an_ambiguous_distribution(tmp_path: Path) -> None:
    capability, authorization, run, lease, source, plan = _context(tmp_path)
    store = _Store(source)
    store.binding = object()
    store.events.append(
        MetadataWriteExecutionEvent(
            RUN_ID,
            2,
            MetadataWriteRunStatus.PREPARED,
            NOW + timedelta(seconds=2),
            lease.fence_epoch,
            confirmation_digest="5" * 64,
        )
    )
    session = _Session(state=LinuxMetadataWritePhysicalState.AMBIGUOUS)

    with pytest.raises(MetadataWriteExecutorError) as raised:
        recover_epub3_title_metadata_write(
            store=store,  # type: ignore[arg-type]
            run=run,  # type: ignore[arg-type]
            authorization=authorization,  # type: ignore[arg-type]
            plan=plan,  # type: ignore[arg-type]
            capability=capability,
            lease=lease,
            clock=lambda: NOW + timedelta(seconds=3),
            backend=_Backend(session),
        )

    assert raised.value.code is MetadataWriteExecutorErrorCode.MANUAL_RECOVERY_REQUIRED
    assert store.events[-1].status is MetadataWriteRunStatus.MANUAL_RECOVERY_REQUIRED
    assert session.restore_calls == 0
    assert session.closed is True
