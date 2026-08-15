import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import event

from foliotone.core import EntityId, EntityKind, ToolCapability, ToolExecutionStatus
from foliotone.persistence import create_sqlite_engine, migrate, repository
from foliotone.tooling import (
    ToolArtifact,
    ToolArtifactRequirement,
    ToolExecution,
    ToolProviderDescriptor,
    ToolResult,
    ToolReuseRequest,
)
from foliotone.tooling.runtime import ToolRuntime
from foliotone.workflows.evidence import ToolEvidenceReader

NOW = datetime(2026, 8, 15, 13, 0, tzinfo=UTC)


def test_reader_reuses_only_latest_exact_success_with_intact_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    artifact_root = tmp_path / "artifacts"
    runtime = ToolRuntime(engine, artifact_root, work_root=tmp_path / "work")
    descriptor = ToolProviderDescriptor(
        provider_id="fixture",
        display_name="Fixture evidence",
        adapter_version="fixture/1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    target_id = EntityId.new()
    execution = _execution(
        descriptor,
        target_id,
        status=ToolExecutionStatus.SUCCEEDED,
    )
    repository(engine, ToolExecution).save(execution)
    artifact = _artifact(artifact_root, execution.id, b"trusted evidence")
    repository(engine, ToolArtifact).save(artifact)
    result = ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type="fixture",
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=target_id,
        key="status",
        value="OK",
    )
    repository(engine, ToolResult).save(result)
    request = ToolReuseRequest(
        descriptor=descriptor,
        capability=ToolCapability.STATUS_REPORT,
        tool_version="fixture 1.0",
        input_identity=f"file-observation:{target_id}",
        config_identity="fixture:v1",
        required_artifacts=(ToolArtifactRequirement("FIXTURE", 1024),),
    )
    reader = ToolEvidenceReader(engine, runtime)
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.upper().split()))

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        snapshot = reader.find_reusable(
            request,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=target_id,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert snapshot is not None
    assert snapshot.run.execution == execution
    assert snapshot.results == (result,)
    assert len(statements) == 4
    assert all(" WHERE " in statement for statement in statements)

    artifact_path = artifact_root / artifact.relative_path
    artifact_path.write_bytes(b"tampered evidence")
    assert (
        reader.find_reusable(
            request,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=target_id,
        )
        is None
    )


def test_latest_failed_exact_attempt_prevents_older_success_reuse(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    artifact_root = tmp_path / "artifacts"
    runtime = ToolRuntime(engine, artifact_root, work_root=tmp_path / "work")
    descriptor = ToolProviderDescriptor(
        provider_id="fixture",
        display_name="Fixture evidence",
        adapter_version="fixture/1",
        capabilities=frozenset({ToolCapability.STATUS_REPORT}),
    )
    target_id = EntityId.new()
    successful = _execution(
        descriptor,
        target_id,
        status=ToolExecutionStatus.SUCCEEDED,
    )
    repository(engine, ToolExecution).save(successful)
    repository(engine, ToolArtifact).save(
        _artifact(artifact_root, successful.id, b"older success")
    )
    failed = _execution(
        descriptor,
        target_id,
        status=ToolExecutionStatus.FAILED,
        started_at=NOW + timedelta(minutes=1),
    )
    repository(engine, ToolExecution).save(failed)
    request = ToolReuseRequest(
        descriptor=descriptor,
        capability=ToolCapability.STATUS_REPORT,
        tool_version="fixture 1.0",
        input_identity=f"file-observation:{target_id}",
        config_identity="fixture:v1",
        required_artifacts=(ToolArtifactRequirement("FIXTURE", 1024),),
    )

    assert (
        ToolEvidenceReader(engine, runtime).find_reusable(
            request,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=target_id,
        )
        is None
    )


def _execution(
    descriptor: ToolProviderDescriptor,
    target_id: EntityId,
    *,
    status: ToolExecutionStatus,
    started_at: datetime = NOW,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id=descriptor.provider_id,
        tool_version="fixture 1.0",
        adapter_version=descriptor.adapter_version,
        capability=ToolCapability.STATUS_REPORT,
        input_identity=f"file-observation:{target_id}",
        config_identity="fixture:v1",
        started_at=started_at,
        finished_at=started_at,
        status=status,
        exit_code=0 if status is ToolExecutionStatus.SUCCEEDED else 1,
        error_summary=None if status is ToolExecutionStatus.SUCCEEDED else "fixture failure",
    )


def _artifact(
    artifact_root: Path,
    execution_id: EntityId,
    data: bytes,
) -> ToolArtifact:
    path = artifact_root / str(execution_id) / "fixture.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return ToolArtifact(
        id=EntityId.new(),
        execution_id=execution_id,
        artifact_type="FIXTURE",
        relative_path=path.relative_to(artifact_root).as_posix(),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
