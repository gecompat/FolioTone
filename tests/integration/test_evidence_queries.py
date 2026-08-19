from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pytest
from pytest import MonkeyPatch
from sqlalchemy import Engine, event, insert, text

from foliotone.core import (
    EntityId,
    EntityKind,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import (
    MAX_EVIDENCE_QUERY_EXECUTIONS,
    MAX_EVIDENCE_QUERY_FINGERPRINTS,
    MAX_EVIDENCE_QUERY_RESULTS,
    create_sqlite_engine,
    evidence_queries,
    load_observation_evidence,
    repository,
    schema,
)
from foliotone.tooling import ToolExecution, ToolResult

NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)
DISTRACTOR_COUNT = 10_000


def test_observation_evidence_query_is_indexed_bounded_and_collection_independent(
    tmp_path: Path,
    head_database: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database = head_database
    engine = create_sqlite_engine(database)
    left_id = EntityId.parse("00000000-0000-0000-0000-000000000001")
    right_id = EntityId.parse("00000000-0000-0000-0000-000000000002")
    target_execution = _execution(left_id, "00000000-0000-0000-0000-000000000003")
    target_result = ToolResult(
        id=EntityId.parse("00000000-0000-0000-0000-000000000004"),
        execution_id=target_execution.id,
        result_type="fixture",
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=left_id,
        key="safe_key",
        value="safe_value",
    )
    target_fingerprint = Fingerprint(
        id=EntityId.parse("00000000-0000-0000-0000-000000000005"),
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=right_id,
        kind="FILE_SHA256",
        algorithm="sha256",
        algorithm_version="fixture/v1",
        value="0" * 64,
        created_at=NOW,
    )
    repository(engine, ToolExecution).save(target_execution)
    repository(engine, ToolResult).save(target_result)
    repository(engine, Fingerprint).save(target_fingerprint)
    _insert_distractors(engine)

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
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    started = perf_counter()
    try:
        records = load_observation_evidence(engine, {left_id, right_id})
    finally:
        elapsed = perf_counter() - started
        event.remove(engine, "before_cursor_execute", record_statement)

    assert records.executions == (target_execution,)
    assert records.results == (target_result,)
    assert records.fingerprints == (target_fingerprint,)
    assert len(statements) == 3
    normalized_statements = tuple(
        " ".join(statement.upper().split()) for statement in statements
    )
    assert all(" WHERE " in statement for statement in normalized_statements)
    assert elapsed < 2.0
    assert MAX_EVIDENCE_QUERY_EXECUTIONS < DISTRACTOR_COUNT
    assert MAX_EVIDENCE_QUERY_RESULTS < DISTRACTOR_COUNT * 2
    assert MAX_EVIDENCE_QUERY_FINGERPRINTS < DISTRACTOR_COUNT

    plans = _query_plans(engine, left_id)
    assert "ix_tool_executions_input_capability_provider_started" in plans[0]
    assert "ix_tool_results_target_execution" in plans[1]
    assert "ix_fingerprints_target_kind_execution" in plans[2]

    monkeypatch.setattr(evidence_queries, "MAX_EVIDENCE_QUERY_RESULTS", 0)
    with pytest.raises(
        evidence_queries.EvidenceQueryLimitError,
        match="ToolResult Evidence exceeds",
    ):
        evidence_queries.load_observation_evidence(engine, {left_id, right_id})


def _execution(observation_id: EntityId, execution_id: str) -> ToolExecution:
    return ToolExecution(
        id=EntityId.parse(execution_id),
        provider_id="fixture-provider",
        tool_version="fixture 1.0",
        adapter_version="fixture-provider/1",
        capability=ToolCapability.READ_METADATA,
        input_identity=f"file-observation:{observation_id}",
        config_identity="fixture:v1",
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )


def _insert_distractors(engine: Engine) -> None:
    timestamp = NOW.isoformat()
    execution_rows: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    fingerprint_rows: list[dict[str, object]] = []
    for index in range(DISTRACTOR_COUNT):
        execution_id = f"10000000-0000-0000-0000-{index:012d}"
        target_id = f"20000000-0000-0000-0000-{index:012d}"
        execution_rows.append(
            {
                "id": execution_id,
                "provider_id": "distractor-provider",
                "tool_version": "fixture 1.0",
                "adapter_version": "distractor-provider/1",
                "capability": "READ_METADATA",
                "input_identity": f"file-observation:{target_id}",
                "config_identity": "fixture:v1",
                "started_at": timestamp,
                "finished_at": timestamp,
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            }
        )
        result_rows.append(
            {
                "id": f"30000000-0000-0000-0000-{index:012d}",
                "execution_id": execution_id,
                "result_type": "fixture",
                "target_kind": "FILE_OBSERVATION",
                "target_id": target_id,
                "key": "distractor",
                "value": "not selected",
                "confidence": None,
                "explanation": None,
            }
        )
        fingerprint_rows.append(
            {
                "id": f"40000000-0000-0000-0000-{index:012d}",
                "target_kind": "FILE_OBSERVATION",
                "target_id": target_id,
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "fixture/v1",
                "value": f"{index:064x}",
                "created_at": timestamp,
                "tool_execution_id": execution_id,
            }
        )
    with engine.begin() as connection:
        connection.execute(insert(schema.tool_executions), execution_rows)
        connection.execute(insert(schema.tool_results), result_rows)
        connection.execute(insert(schema.fingerprints), fingerprint_rows)


def _query_plans(
    engine: Engine,
    observation_id: EntityId,
) -> tuple[str, str, str]:
    parameters = {
        "identity": f"file-observation:{observation_id}",
        "kind": EntityKind.FILE_OBSERVATION.value,
        "target": str(observation_id),
    }
    statements = (
        "SELECT * FROM tool_executions WHERE input_identity IN (:identity) "
        f"ORDER BY id LIMIT {MAX_EVIDENCE_QUERY_EXECUTIONS + 1}",
        "SELECT * FROM tool_results WHERE target_kind = :kind "
        "AND target_id IN (:target) ORDER BY id "
        f"LIMIT {MAX_EVIDENCE_QUERY_RESULTS + 1}",
        "SELECT * FROM fingerprints WHERE target_kind = :kind "
        "AND target_id IN (:target) ORDER BY id "
        f"LIMIT {MAX_EVIDENCE_QUERY_FINGERPRINTS + 1}",
    )
    plans: list[str] = []
    with engine.connect() as connection:
        for statement in statements:
            rows = connection.execute(
                text(f"EXPLAIN QUERY PLAN {statement}"), parameters
            ).all()
            plans.append(" ".join(str(value) for row in rows for value in row))
    assert len(plans) == 3
    return plans[0], plans[1], plans[2]
