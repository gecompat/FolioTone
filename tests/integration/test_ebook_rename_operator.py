from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

import pytest
from alembic import command
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError

from foliotone.core import EntityId, MediaType, PresenceState, ReviewDecisionValue
from foliotone.ebook_operation_recipes import (
    EbookOperationDependencyKind,
    EbookOperationRecipePlan,
)
from foliotone.ebook_rename import (
    EbookRenameCapabilityProbeSnapshot,
    EbookRenameDependencyScopeAxis,
    EbookRenameDependencyScopeMode,
    EbookRenamePhysicalPreparationEvidence,
    EbookRenameRunStatus,
    ResolvedEbookRenameCapability,
    ResolvedEbookRenameDependencyScope,
    build_ebook_rename_capability_probe,
    build_ebook_rename_physical_evidence,
)
from foliotone.ebook_rename.linux_backend import (
    LinuxEbookRenameBackendError,
    LinuxEbookRenameBackendErrorCode,
    LinuxEbookRenamePhysicalSnapshot,
    LinuxEbookRenamePhysicalState,
)
from foliotone.index import (
    FingerprintWriter,
    HashMode,
    IncrementalScanner,
    ScanRootBinding,
    SQLiteIndexStore,
)
from foliotone.persistence import alembic_config, create_sqlite_engine, schema
from foliotone.persistence.ebook_operation_recipe import SQLiteEbookOperationRecipeStore
from foliotone.persistence.ebook_rename import SQLiteEbookRenameStore
from foliotone.persistence.scan_root_lease import SQLiteScanRootWriteLeaseStore
from foliotone.workflows.ebook_rename_operation import (
    EbookRenameOperatorError,
    EbookRenameOperatorErrorCode,
    EbookRenameOperatorService,
)
from foliotone.workflows.ebook_rename_planning import EbookRenamePlanningService
from foliotone.workflows.ebook_rename_status import SQLiteEbookRenameStatusReportReader

_PAYLOAD = b"FolioTone synthetic e-book rename fixture\n"
_SOURCE_LOCATOR = "private/synthetic-source.epub"
_TARGET_LOCATOR = "private/synthetic-renamed.epub"


class _Clock:
    def __init__(self) -> None:
        self._value = datetime(2026, 8, 23, 21, 0, tzinfo=UTC)
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            value = self._value
            self._value += timedelta(milliseconds=10)
            return value


@dataclass(frozen=True, slots=True)
class _CapabilityResolver:
    capability: ResolvedEbookRenameCapability

    def resolve(self, capability_id: EntityId) -> ResolvedEbookRenameCapability:
        if capability_id != self.capability.ebook_rename_capability_id:
            raise AssertionError("unexpected capability")
        return self.capability


@dataclass(frozen=True, slots=True)
class _ScopeResolver:
    scope: ResolvedEbookRenameDependencyScope

    def resolve(self, scope_id: EntityId) -> ResolvedEbookRenameDependencyScope:
        if scope_id != self.scope.dependency_scope_id:
            raise AssertionError("unexpected dependency scope")
        return self.scope

    def all_scopes(self) -> tuple[ResolvedEbookRenameDependencyScope, ...]:
        return (self.scope,)


class _PortableSession:
    def __init__(
        self,
        source: Path,
        target: Path,
        *,
        fail_forward_verification: bool,
    ) -> None:
        self._source = source
        self._target = target
        self._fail_forward_verification = fail_forward_verification

    def __enter__(self) -> _PortableSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        pass

    def classify(self) -> LinuxEbookRenamePhysicalSnapshot:
        source_exact = self._source.is_file() and self._source.read_bytes() == _PAYLOAD
        target_exact = self._target.is_file() and self._target.read_bytes() == _PAYLOAD
        if source_exact and not self._target.exists():
            state = LinuxEbookRenamePhysicalState.SOURCE_EXACT_TARGET_ABSENT
        elif target_exact and not self._source.exists():
            state = LinuxEbookRenamePhysicalState.SOURCE_ABSENT_TARGET_EXACT
        else:
            state = LinuxEbookRenamePhysicalState.AMBIGUOUS
        return LinuxEbookRenamePhysicalSnapshot(
            state=state,
            confirmation_digest="3" * 64,
        )

    def revalidate_forward_preconditions(self) -> LinuxEbookRenamePhysicalSnapshot:
        return self.classify()

    def rename_forward(self) -> None:
        if self._target.exists():
            raise FileExistsError("synthetic target collision")
        self._source.rename(self._target)

    def verify_forward(self) -> LinuxEbookRenamePhysicalSnapshot:
        if self._fail_forward_verification:
            self._fail_forward_verification = False
            raise LinuxEbookRenameBackendError(
                LinuxEbookRenameBackendErrorCode.STATE_AMBIGUOUS
            )
        return self.classify()

    def rename_reverse(self) -> None:
        if self._source.exists():
            raise FileExistsError("synthetic source collision")
        self._target.rename(self._source)

    def verify_recovery(self) -> LinuxEbookRenamePhysicalSnapshot:
        return self.classify()


class _PortableBackend:
    def __init__(
        self,
        capability: ResolvedEbookRenameCapability,
        *,
        fail_forward_verification: bool,
    ) -> None:
        self._capability = capability
        self._fail_forward_verification = fail_forward_verification

    def probe(
        self,
        capability: ResolvedEbookRenameCapability,
        *,
        probed_at: datetime,
    ) -> EbookRenameCapabilityProbeSnapshot:
        assert capability == self._capability
        return build_ebook_rename_capability_probe(
            capability,
            filesystem_type="ext4",
            filesystem_identity_fingerprint="4" * 64,
            kernel_release="portable-test",
            probed_at=probed_at,
            openat2_supported=True,
            renameat2_noreplace_supported=True,
            directory_fsync_supported=True,
            root_probe_same_filesystem=True,
        )

    def capture_preparation_evidence(
        self,
        *,
        capability: ResolvedEbookRenameCapability,
        probe: EbookRenameCapabilityProbeSnapshot,
        plan: EbookOperationRecipePlan,
        target_historically_absent: bool,
        captured_at: datetime,
    ) -> EbookRenamePhysicalPreparationEvidence:
        del probe
        source = plan.candidate.sources[0]
        target = plan.candidate.target
        source_path = capability.scan_root_directory.joinpath(
            *source.relative_locator.split("/")
        )
        target_path = capability.scan_root_directory.joinpath(
            *target.relative_locator.split("/")
        )
        details = source_path.stat()
        return build_ebook_rename_physical_evidence(
            plan,
            source_device=max(1, details.st_dev),
            source_inode=max(1, details.st_ino),
            source_mode=details.st_mode,
            source_uid=getattr(details, "st_uid", 0),
            source_gid=getattr(details, "st_gid", 0),
            source_link_count=details.st_nlink,
            source_size_bytes=details.st_size,
            source_mtime_ns=details.st_mtime_ns,
            source_modified_at=source.expected_modified_at,
            source_full_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
            source_xattr_fingerprint="5" * 64,
            target_physically_absent=not target_path.exists(),
            target_historically_absent=target_historically_absent,
            captured_at=captured_at,
        )

    def open_session(
        self,
        *,
        source_relative_locator: str,
        target_relative_locator: str,
        **_kwargs: object,
    ) -> _PortableSession:
        session = _PortableSession(
            self._capability.scan_root_directory.joinpath(
                *source_relative_locator.split("/")
            ),
            self._capability.scan_root_directory.joinpath(
                *target_relative_locator.split("/")
            ),
            fail_forward_verification=self._fail_forward_verification,
        )
        self._fail_forward_verification = False
        return session


@dataclass(frozen=True, slots=True)
class _Scenario:
    engine: Engine
    service: EbookRenameOperatorService
    plan_id: EntityId
    plan_content_hash: str
    capability_id: EntityId
    source: Path
    target: Path


def _scenario(
    head_database: Path,
    tmp_path: Path,
    *,
    fail_forward_verification: bool = False,
) -> _Scenario:
    engine = create_sqlite_engine(head_database)
    clock = _Clock()
    scan_root_directory = (tmp_path / "scan-root").resolve()
    probe_directory = (tmp_path / "probe").resolve()
    source = scan_root_directory.joinpath(*_SOURCE_LOCATOR.split("/"))
    target = scan_root_directory.joinpath(*_TARGET_LOCATOR.split("/"))
    source.parent.mkdir(parents=True)
    probe_directory.mkdir()
    source.write_bytes(_PAYLOAD)

    index = SQLiteIndexStore(engine)
    root = index.get_or_create_root("synthetic-ebook-rename-operator", MediaType.EBOOK)
    initial = IncrementalScanner(
        index,
        hash_mode=HashMode.FULL,
        hash_workers=1,
        fingerprint_writer=FingerprintWriter(engine),
        clock=clock,
    ).scan(root, ScanRootBinding(scan_root_directory))
    with engine.connect() as connection:
        observation_id = EntityId.parse(
            str(
                connection.execute(
                    select(schema.file_observations.c.id).where(
                        schema.file_observations.c.scan_run_id == str(initial.run.id),
                        schema.file_observations.c.relative_path == _SOURCE_LOCATOR,
                    )
                ).scalar_one()
            )
        )

    scope = ResolvedEbookRenameDependencyScope(
        dependency_scope_id=EntityId.new(),
        scan_root_id=root.id,
        version=1,
        axes=tuple(
            EbookRenameDependencyScopeAxis(
                kind=kind,
                mode=EbookRenameDependencyScopeMode.NOT_APPLICABLE,
            )
            for kind in EbookOperationDependencyKind
        ),
    )
    scope_resolver = _ScopeResolver(scope)
    planning = EbookRenamePlanningService(engine, scope_resolver, clock=clock)
    proposal = planning.propose(observation_id, scope.dependency_scope_id, "synthetic-renamed.epub")
    planning.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    planned = planning.plan(proposal.candidate_id)
    plan = SQLiteEbookOperationRecipeStore(engine).get_plan(planned.plan_id)
    assert plan is not None
    assert plan.candidate.target.relative_locator == _TARGET_LOCATOR

    capability = ResolvedEbookRenameCapability(
        ebook_rename_capability_id=EntityId.new(),
        scan_root_id=root.id,
        scan_root_directory=scan_root_directory,
        probe_directory=probe_directory,
        version=1,
        configuration_fingerprint="6" * 64,
    )
    backend = _PortableBackend(
        capability,
        fail_forward_verification=fail_forward_verification,
    )
    service = EbookRenameOperatorService(
        engine,
        capability_resolver=_CapabilityResolver(capability),
        dependency_scope_resolver=scope_resolver,
        backend=backend,
        clock=clock,
    )
    return _Scenario(
        engine=engine,
        service=service,
        plan_id=plan.id,
        plan_content_hash=plan.content_hash,
        capability_id=capability.ebook_rename_capability_id,
        source=source,
        target=target,
    )


def _authorize(scenario: _Scenario):
    return scenario.service.authorize(
        plan_id=scenario.plan_id,
        plan_content_hash=scenario.plan_content_hash,
        capability_id=scenario.capability_id,
    )


def test_operator_executes_scans_and_atomically_verifies_one_synthetic_rename(
    head_database: Path,
    tmp_path: Path,
) -> None:
    scenario = _scenario(head_database, tmp_path)
    authorization = _authorize(scenario)
    prompt = scenario.service.confirmation_prompt(
        plan_id=scenario.plan_id,
        plan_content_hash=scenario.plan_content_hash,
        capability_id=scenario.capability_id,
        authorization_id=authorization.authorization_id,
    )

    result = scenario.service.execute(
        plan_id=scenario.plan_id,
        plan_content_hash=scenario.plan_content_hash,
        capability_id=scenario.capability_id,
        authorization_id=authorization.authorization_id,
        confirmation_text=prompt,
    )
    repeated = scenario.service.execute(
        plan_id=scenario.plan_id,
        plan_content_hash=scenario.plan_content_hash,
        capability_id=scenario.capability_id,
        authorization_id=authorization.authorization_id,
        confirmation_text=prompt,
    )

    assert result.status is EbookRenameRunStatus.VERIFIED
    assert repeated == result
    assert scenario.source.exists() is False
    assert scenario.target.read_bytes() == _PAYLOAD
    assert result.scan_run_id is not None
    assert result.target_observation_id is not None
    assert result.collection_state_snapshot_id is not None
    store = SQLiteEbookRenameStore(scenario.engine)
    assert tuple(event.status for event in store.events_for_run(result.run_id)) == (
        EbookRenameRunStatus.PREPARED,
        EbookRenameRunStatus.RELOCATED,
        EbookRenameRunStatus.IMMEDIATE_VERIFIED,
        EbookRenameRunStatus.SCAN_HANDOFF,
        EbookRenameRunStatus.VERIFIED,
    )
    report = SQLiteEbookRenameStatusReportReader(store).read(result.run_id)
    assert report.reconciliation is not None
    assert report.reconciliation.target_observation_id == result.target_observation_id
    assert SQLiteScanRootWriteLeaseStore(scenario.engine).current(result.scan_root_id) is None
    rendered = str(report.payload())
    assert _SOURCE_LOCATOR not in rendered
    assert _TARGET_LOCATOR not in rendered
    assert scenario.plan_content_hash not in rendered
    with pytest.raises(IntegrityError, match="immutable e-book rename reconciliation"):
        with scenario.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ebook_rename_reconciliations SET expected_size_bytes=0 "
                    "WHERE run_id=:run_id"
                ),
                {"run_id": str(result.run_id)},
            )
    scenario.engine.dispose()
    with pytest.raises(
        RuntimeError,
        match="e-book rename reconciliation prevents migration downgrade",
    ):
        command.downgrade(
            alembic_config(head_database),
            "0031_ebook_rename_operations",
        )


def test_recovery_reconciles_the_restored_source_without_inventing_target_history(
    head_database: Path,
    tmp_path: Path,
) -> None:
    scenario = _scenario(
        head_database,
        tmp_path,
        fail_forward_verification=True,
    )
    authorization = _authorize(scenario)
    prompt = scenario.service.confirmation_prompt(
        plan_id=scenario.plan_id,
        plan_content_hash=scenario.plan_content_hash,
        capability_id=scenario.capability_id,
        authorization_id=authorization.authorization_id,
    )

    with pytest.raises(EbookRenameOperatorError, match="^STALE$") as failure:
        scenario.service.execute(
            plan_id=scenario.plan_id,
            plan_content_hash=scenario.plan_content_hash,
            capability_id=scenario.capability_id,
            authorization_id=authorization.authorization_id,
            confirmation_text=prompt,
        )
    assert failure.value.code is EbookRenameOperatorErrorCode.STALE
    run = SQLiteEbookRenameStore(scenario.engine).get_run_for_authorization(
        authorization.authorization_id
    )
    assert run is not None

    result = scenario.service.recover(run_id=run.id)
    repeated = scenario.service.recover(run_id=run.id)

    assert result.status is EbookRenameRunStatus.RECOVERED
    assert repeated == result
    assert scenario.source.read_bytes() == _PAYLOAD
    assert scenario.target.exists() is False
    with scenario.engine.connect() as connection:
        target_history = connection.execute(
            select(schema.file_records.c.id).where(
                schema.file_records.c.scan_root_id == str(result.scan_root_id),
                schema.file_records.c.relative_path == _TARGET_LOCATOR,
            )
        ).all()
        source_presence = connection.execute(
            select(schema.file_records.c.presence_state).where(
                schema.file_records.c.scan_root_id == str(result.scan_root_id),
                schema.file_records.c.relative_path == _SOURCE_LOCATOR,
            )
        ).scalar_one()
    assert target_history == []
    assert source_presence == PresenceState.PRESENT.value
    report = SQLiteEbookRenameStatusReportReader(
        SQLiteEbookRenameStore(scenario.engine)
    ).read(result.run_id)
    assert report.status is EbookRenameRunStatus.RECOVERED
    assert report.reconciliation is not None
    assert report.reconciliation.source_observation_id is not None
    assert report.reconciliation.target_file_id is None
    scenario.engine.dispose()
