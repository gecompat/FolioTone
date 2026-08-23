from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, insert

from foliotone.cli.main import main
from foliotone.core import (
    ARCHIVE_COLLECTION_PLAN_PROFILE,
    ARCHIVE_COLLECTION_PROFILE,
    EntityId,
    ReviewDecisionValue,
)
from foliotone.ebook_operation_recipes import (
    EbookOperationDependencyKind,
    EbookOperationDependencyState,
    EbookOperationPlanStatus,
)
from foliotone.ebook_rename import dependency_scopes
from foliotone.ebook_rename.dependency_scopes import (
    EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
    EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV,
    EbookRenameDependencyScopeAxis,
    EbookRenameDependencyScopeMode,
    EbookRenameDependencySnapshotKind,
    ResolvedEbookRenameDependencyScope,
)
from foliotone.persistence import (
    SQLiteEbookOperationRecipeStore,
    archive_collection_schema,
    calibre_library_schema,
    create_sqlite_engine,
    schema,
)
from foliotone.workflows.ebook_rename_planning import (
    EbookRenamePlanningError,
    EbookRenamePlanningService,
)

NOW = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
ROOT_ID = EntityId.parse("b1000000-0000-0000-0000-000000000001")
SCAN_ID = EntityId.parse("b2000000-0000-0000-0000-000000000001")
FILE_ID = EntityId.parse("b3000000-0000-0000-0000-000000000001")
OBSERVATION_ID = EntityId.parse("b4000000-0000-0000-0000-000000000001")
FINGERPRINT_ID = EntityId.parse("b5000000-0000-0000-0000-000000000001")
SCOPE_ID = EntityId.parse("b6000000-0000-0000-0000-000000000001")
PRIVATE_SOURCE = "private/synthetic-secret-source.epub"


@dataclass(frozen=True, slots=True)
class _ScopeResolver:
    scope: ResolvedEbookRenameDependencyScope

    def resolve(self, dependency_scope_id: EntityId) -> ResolvedEbookRenameDependencyScope:
        if dependency_scope_id != self.scope.dependency_scope_id:
            raise AssertionError("unexpected scope")
        return self.scope

    def all_scopes(self) -> tuple[ResolvedEbookRenameDependencyScope, ...]:
        return (self.scope,)


def _scope(
    rules: dict[
        EbookOperationDependencyKind,
        tuple[EbookRenameDependencySnapshotKind, EntityId],
    ]
    | None = None,
) -> ResolvedEbookRenameDependencyScope:
    rules = rules or {}
    return ResolvedEbookRenameDependencyScope(
        dependency_scope_id=SCOPE_ID,
        scan_root_id=ROOT_ID,
        version=1,
        axes=tuple(
            EbookRenameDependencyScopeAxis(
                kind=kind,
                mode=(
                    EbookRenameDependencyScopeMode.MANAGED
                    if kind in rules
                    else EbookRenameDependencyScopeMode.NOT_APPLICABLE
                ),
                snapshot_kind=None if kind not in rules else rules[kind][0],
                snapshot_id=None if kind not in rules else rules[kind][1],
            )
            for kind in EbookOperationDependencyKind
        ),
    )


def _database(database: Path) -> tuple[Path, Engine]:
    engine = create_sqlite_engine(database)
    _seed_source(engine)
    return database, engine


def _seed_source(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {
                "id": str(ROOT_ID),
                "name": "synthetic-ebook-rename-root",
                "media_type": "EBOOK",
                "enabled": True,
            },
        )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": str(SCAN_ID),
                "scan_root_id": str(ROOT_ID),
                "started_at": (NOW - timedelta(minutes=1)).isoformat(),
                "status": "COMPLETED",
                "completed_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(schema.file_records),
            {
                "id": str(FILE_ID),
                "scan_root_id": str(ROOT_ID),
                "relative_path": PRIVATE_SOURCE,
                "size_bytes": 4096,
                "modified_at": NOW.isoformat(),
                "media_type": "EBOOK",
                "presence_state": "PRESENT",
                "first_seen_at": NOW.isoformat(),
                "last_seen_at": NOW.isoformat(),
                "missing_since_at": None,
                "consecutive_missing_scans": 0,
            },
        )
        connection.execute(
            insert(schema.file_observations),
            {
                "id": str(OBSERVATION_ID),
                "file_id": str(FILE_ID),
                "scan_run_id": str(SCAN_ID),
                "relative_path": PRIVATE_SOURCE,
                "size_bytes": 4096,
                "modified_at": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(schema.fingerprints),
            {
                "id": str(FINGERPRINT_ID),
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(OBSERVATION_ID),
                "kind": "FILE_SHA256",
                "algorithm": "sha256",
                "algorithm_version": "1",
                "value": "a" * 64,
                "created_at": NOW.isoformat(),
                "tool_execution_id": None,
            },
        )


def test_service_creates_reviews_and_reproducible_non_executable_plan(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope()),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "renamed.epub")
    first_preview = service.preview(proposal.candidate_id)
    decision = service.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    repeated_proposal = service.propose(
        OBSERVATION_ID,
        SCOPE_ID,
        "renamed.epub",
    )
    first = service.plan(proposal.candidate_id)
    second = service.plan(proposal.candidate_id)

    assert proposal.review_state.value == "PENDING"
    assert set(proposal.dependency_states) == {
        EbookOperationDependencyState.NOT_APPLICABLE
    }
    assert first_preview.status is EbookOperationPlanStatus.REVIEW_REQUIRED
    assert decision.sequence_no == 1
    assert repeated_proposal.candidate_id == proposal.candidate_id
    assert repeated_proposal.review_item_id == proposal.review_item_id
    assert repeated_proposal.review_state.value == "ACCEPTED"
    assert first.status is EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
    assert first.blocker_codes == ()
    assert first.plan_id == second.plan_id
    candidate = SQLiteEbookOperationRecipeStore(engine).get_candidate(
        proposal.candidate_id
    )
    assert candidate is not None
    assert candidate.target.relative_locator == "private/renamed.epub"
    assert "synthetic-secret" not in repr(first_preview)
    engine.dispose()


def test_missing_managed_coverage_remains_unknown_and_blocks_plan(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    missing = {
        kind: (EbookRenameDependencySnapshotKind.TOOL_RESULT, EntityId.new())
        for kind in EbookOperationDependencyKind
    }
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope(missing)),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "unknown.epub")
    service.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    plan = service.plan(proposal.candidate_id)

    assert set(proposal.dependency_states) == {EbookOperationDependencyState.UNKNOWN}
    assert plan.status is EbookOperationPlanStatus.BLOCKED
    assert set(plan.blocker_codes) == {
        "DEPENDENCY_EVIDENCE_INCOMPLETE",
        "PRECONDITION_INCOMPLETE",
    }
    engine.dispose()


def test_explicit_current_tool_coverage_can_prove_known_none(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    rules: dict[
        EbookOperationDependencyKind,
        tuple[EbookRenameDependencySnapshotKind, EntityId],
    ] = {}
    with engine.begin() as connection:
        for ordinal, kind in enumerate(EbookOperationDependencyKind, start=1):
            execution_id = EntityId.parse(
                f"b7000000-0000-0000-0000-{ordinal:012d}"
            )
            result_id = EntityId.parse(f"b8000000-0000-0000-0000-{ordinal:012d}")
            connection.execute(
                insert(schema.tool_executions),
                {
                    "id": str(execution_id),
                    "provider_id": "foliotone-ebook-dependency-audit",
                    "tool_version": "1",
                    "adapter_version": "ebook-rename-dependency-audit/1",
                    "capability": "COMPLETENESS_ANALYSIS",
                    "input_identity": f"file-observation:{OBSERVATION_ID}",
                    "config_identity": f"synthetic-{kind.value.lower()}",
                    "started_at": NOW.isoformat(),
                    "finished_at": NOW.isoformat(),
                    "status": "SUCCEEDED",
                    "exit_code": 0,
                    "error_summary": None,
                },
            )
            connection.execute(
                insert(schema.tool_results),
                {
                    "id": str(result_id),
                    "execution_id": str(execution_id),
                    "result_type": "ebook-rename-dependency-coverage/v1",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(OBSERVATION_ID),
                    "key": kind.value,
                    "value": "KNOWN_NONE",
                    "confidence": 1.0,
                    "explanation": "synthetic complete coverage",
                },
            )
            rules[kind] = (EbookRenameDependencySnapshotKind.TOOL_RESULT, result_id)
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope(rules)),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "covered.epub")
    service.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    plan = service.plan(proposal.candidate_id)

    assert set(proposal.dependency_states) == {
        EbookOperationDependencyState.KNOWN_NONE
    }
    assert plan.status is EbookOperationPlanStatus.APPROVED_NON_EXECUTABLE
    engine.dispose()


def test_explicit_current_tool_presence_overrides_not_applicable_and_blocks(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    execution_id = EntityId.parse("b7000000-0000-0000-0000-000000000099")
    result_id = EntityId.parse("b8000000-0000-0000-0000-000000000099")
    with engine.begin() as connection:
        connection.execute(
            insert(schema.tool_executions),
            {
                "id": str(execution_id),
                "provider_id": "foliotone-ebook-dependency-audit",
                "tool_version": "1",
                "adapter_version": "ebook-rename-dependency-audit/1",
                "capability": "COMPLETENESS_ANALYSIS",
                "input_identity": f"file-observation:{OBSERVATION_ID}",
                "config_identity": "synthetic-sidecar-presence",
                "started_at": NOW.isoformat(),
                "finished_at": NOW.isoformat(),
                "status": "SUCCEEDED",
                "exit_code": 0,
                "error_summary": None,
            },
        )
        connection.execute(
            insert(schema.tool_results),
            {
                "id": str(result_id),
                "execution_id": str(execution_id),
                "result_type": "ebook-rename-dependency-coverage/v1",
                "target_kind": "FILE_OBSERVATION",
                "target_id": str(OBSERVATION_ID),
                "key": EbookOperationDependencyKind.SIDECAR.value,
                "value": "KNOWN_PRESENT",
                "confidence": 1.0,
                "explanation": "synthetic explicit presence",
            },
        )
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope()),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "present.epub")
    service.review(proposal.candidate_id, ReviewDecisionValue.ACCEPT)
    plan = service.plan(proposal.candidate_id)
    candidate = SQLiteEbookOperationRecipeStore(engine).get_candidate(
        proposal.candidate_id
    )

    assert candidate is not None
    states = {value.kind: value.state for value in candidate.dependencies}
    assert states[EbookOperationDependencyKind.SIDECAR] is (
        EbookOperationDependencyState.KNOWN_PRESENT
    )
    assert any(value.kind == "TOOL_RESULT" for value in candidate.evidence_refs)
    assert plan.status is EbookOperationPlanStatus.BLOCKED
    assert plan.blocker_codes == ("PRECONDITION_INCOMPLETE",)
    engine.dispose()


def test_complete_unbounded_archive_collection_run_can_prove_known_none(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    run_id = EntityId.parse("b9000000-0000-0000-0000-000000000001")
    with engine.begin() as connection:
        connection.execute(
            insert(archive_collection_schema.archive_collection_runs),
            {
                "id": str(run_id),
                "scan_root_id": str(ROOT_ID),
                "source_scan_run_id": str(SCAN_ID),
                "profile": ARCHIVE_COLLECTION_PROFILE,
                "plan_profile": ARCHIVE_COLLECTION_PLAN_PROFILE,
                "worker_count": 1,
                "plan_limit": None,
                "started_at": NOW.isoformat(),
                "status": "COMPLETED",
                "fence_epoch": 1,
                "planned_count": 0,
                "hash_evidence_missing_count": 0,
                "missing_volume_count": 0,
                "unsupported_volume_count": 0,
                "ambiguous_volume_count": 0,
                "name_collision_count": 0,
                "orphan_volume_count": 0,
                "plan_content_hash": "e" * 64,
                "completed_at": NOW.isoformat(),
                "heartbeat_at": None,
                "lease_token": None,
                "lease_expires_at": None,
            },
        )
    rules = {
        EbookOperationDependencyKind.ARCHIVE: (
            EbookRenameDependencySnapshotKind.ARCHIVE_COLLECTION_RUN,
            run_id,
        ),
        EbookOperationDependencyKind.VOLUME_GROUP: (
            EbookRenameDependencySnapshotKind.ARCHIVE_COLLECTION_RUN,
            run_id,
        ),
    }
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope(rules)),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "archive-covered.epub")
    candidate = SQLiteEbookOperationRecipeStore(engine).get_candidate(
        proposal.candidate_id
    )

    assert candidate is not None
    states = {value.kind: value.state for value in candidate.dependencies}
    assert states[EbookOperationDependencyKind.ARCHIVE] is (
        EbookOperationDependencyState.KNOWN_NONE
    )
    assert states[EbookOperationDependencyKind.VOLUME_GROUP] is (
        EbookOperationDependencyState.KNOWN_NONE
    )
    engine.dispose()


def test_complete_current_calibre_snapshot_can_prove_known_none(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    snapshot_id = EntityId.parse("ba000000-0000-0000-0000-000000000001")
    with engine.begin() as connection:
        connection.execute(
            insert(calibre_library_schema.calibre_library_snapshots),
            {
                "id": str(snapshot_id),
                "scan_root_id": str(ROOT_ID),
                "source_scan_run_id": str(SCAN_ID),
                "profile": "calibre-library-snapshot/v1",
                "adapter_version": "calibredb-library/1",
                "tool_version": "7.0.0",
                "parser_version": "calibre-library-parser/1",
                "library_identity_digest": "b" * 64,
                "initial_inventory_digest": "c" * 64,
                "final_inventory_digest": "c" * 64,
                "status": "COMPLETED",
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
            },
        )
    rules = {
        kind: (
            EbookRenameDependencySnapshotKind.CALIBRE_SNAPSHOT,
            snapshot_id,
        )
        for kind in (
            EbookOperationDependencyKind.CALIBRE,
            EbookOperationDependencyKind.SIDECAR,
            EbookOperationDependencyKind.EXTERNAL_LIBRARY,
        )
    }
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope(rules)),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "calibre-covered.epub")
    candidate = SQLiteEbookOperationRecipeStore(engine).get_candidate(
        proposal.candidate_id
    )

    assert candidate is not None
    states = {value.kind: value.state for value in candidate.dependencies}
    for kind in rules:
        assert states[kind] is EbookOperationDependencyState.KNOWN_NONE
    engine.dispose()


def test_existing_calibre_relationship_overrides_not_applicable_scope(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    snapshot_id = EntityId.new()
    record_id = EntityId.new()
    format_id = EntityId.new()
    with engine.begin() as connection:
        connection.execute(
            insert(calibre_library_schema.calibre_library_snapshots),
            {
                "id": str(snapshot_id),
                "scan_root_id": str(ROOT_ID),
                "source_scan_run_id": str(SCAN_ID),
                "profile": "calibre-library-snapshot/v1",
                "adapter_version": "calibredb-library/1",
                "tool_version": "7.0.0",
                "parser_version": "calibre-library-parser/1",
                "library_identity_digest": "b" * 64,
                "initial_inventory_digest": "c" * 64,
                "final_inventory_digest": "c" * 64,
                "status": "COMPLETED",
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(calibre_library_schema.calibre_library_records),
            {
                "id": str(record_id),
                "snapshot_id": str(snapshot_id),
                "calibre_record_id": 1,
                "metadata_fingerprint": "d" * 64,
                "calibre_uuid": None,
                "title": None,
                "authors_json": "[]",
                "identifiers_json": "{}",
                "last_modified_at": NOW.isoformat(),
            },
        )
        connection.execute(
            insert(calibre_library_schema.calibre_library_formats),
            {
                "id": str(format_id),
                "record_snapshot_id": str(record_id),
                "format_label": "EPUB",
                "relative_locator": PRIVATE_SOURCE,
                "declared_size_bytes": 4096,
                "observation_id": str(OBSERVATION_ID),
            },
        )
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope()),
        clock=lambda: NOW,
    )

    proposal = service.propose(OBSERVATION_ID, SCOPE_ID, "calibre.epub")
    candidate = SQLiteEbookOperationRecipeStore(engine).get_candidate(
        proposal.candidate_id
    )

    assert candidate is not None
    states = {value.kind: value.state for value in candidate.dependencies}
    assert states[EbookOperationDependencyKind.CALIBRE] is (
        EbookOperationDependencyState.KNOWN_PRESENT
    )
    assert states[EbookOperationDependencyKind.EXTERNAL_LIBRARY] is (
        EbookOperationDependencyState.KNOWN_PRESENT
    )
    engine.dispose()


def test_target_history_blocks_proposal_without_creating_candidate(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.file_records),
            {
                "id": str(EntityId.new()),
                "scan_root_id": str(ROOT_ID),
                "relative_path": "private/used.epub",
                "size_bytes": 0,
                "modified_at": NOW.isoformat(),
                "media_type": "EBOOK",
                "presence_state": "MISSING",
                "first_seen_at": NOW.isoformat(),
                "last_seen_at": NOW.isoformat(),
                "missing_since_at": NOW.isoformat(),
                "consecutive_missing_scans": 1,
            },
        )
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope()),
        clock=lambda: NOW,
    )

    with pytest.raises(EbookRenamePlanningError, match="^TARGET_HISTORY_PRESENT$"):
        service.propose(OBSERVATION_ID, SCOPE_ID, "used.epub")
    engine.dispose()


def test_conflicting_full_hash_history_blocks_proposal(
    head_database: Path,
) -> None:
    _database_path, engine = _database(head_database)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.fingerprints),
            [
                {
                    "id": f"{prefix}5000000-0000-0000-0000-000000000001",
                    "target_kind": "FILE_OBSERVATION",
                    "target_id": str(OBSERVATION_ID),
                    "kind": "FILE_SHA256",
                    "algorithm": "sha256",
                    "algorithm_version": "1",
                    "value": value,
                    "created_at": NOW.isoformat(),
                    "tool_execution_id": None,
                }
                for prefix, value in (
                    ("a", "b" * 64),
                    ("c", "a" * 64),
                    ("d", "a" * 64),
                    ("e", "a" * 64),
                )
            ],
        )
    service = EbookRenamePlanningService(
        engine,
        _ScopeResolver(_scope()),
        clock=lambda: NOW,
    )

    with pytest.raises(EbookRenamePlanningError, match="^SOURCE_HASH_UNAVAILABLE$"):
        service.propose(OBSERVATION_ID, SCOPE_ID, "conflicted.epub")
    engine.dispose()


def _scope_document() -> dict[str, object]:
    return {
        "dependency_scopes": [
            {
                "dependency_scope_id": str(SCOPE_ID),
                "scan_root_id": str(ROOT_ID),
                "profile": EBOOK_RENAME_DEPENDENCY_SCOPE_PROFILE,
                "version": 1,
                "axes": {
                    kind.value: {"mode": "NOT_APPLICABLE"}
                    for kind in EbookOperationDependencyKind
                },
            }
        ]
    }


def test_cli_end_to_end_is_path_free_except_explicit_private_preview(
    tmp_path: Path,
    head_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, engine = _database(head_database)
    engine.dispose()
    config = tmp_path / "dependency-scopes.json"
    config.write_text(json.dumps(_scope_document()), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv(EBOOK_RENAME_DEPENDENCY_SCOPES_FILE_ENV, str(config))
    if os.name == "nt":
        monkeypatch.setattr(
            dependency_scopes,
            "_verify_configuration_protection",
            lambda _: None,
        )
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-renamed.epub\n"))

    assert (
        main(
            [
                "ebook-rename-propose",
                "--observation-id",
                str(OBSERVATION_ID),
                "--dependency-scope-id",
                str(SCOPE_ID),
                "--database",
                str(database),
                "--output",
                "json",
            ]
        )
        == 0
    )
    proposal_output = capsys.readouterr()
    proposal = json.loads(proposal_output.out)
    candidate_id = proposal["candidate_id"]
    assert PRIVATE_SOURCE not in proposal_output.out
    assert "cli-renamed.epub" not in proposal_output.out
    assert "cli-renamed.epub" not in proposal_output.err

    preview_args = [
        "ebook-rename-preview",
        "--candidate-id",
        candidate_id,
        "--database",
        str(database),
    ]
    assert main([*preview_args, "--output", "json"]) == 0
    standard = capsys.readouterr().out
    assert PRIVATE_SOURCE not in standard
    assert "cli-renamed.epub" not in standard

    assert main([*preview_args, "--private-details", "--output", "text"]) == 0
    private = capsys.readouterr().out
    assert PRIVATE_SOURCE in private
    assert "private/cli-renamed.epub" in private

    assert (
        main(
            [
                "ebook-rename-review",
                "--candidate-id",
                candidate_id,
                "--decision",
                "ACCEPT",
                "--database",
                str(database),
                "--output",
                "json",
            ]
        )
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["decision"] == "ACCEPT"

    assert (
        main(
            [
                "ebook-rename-plan",
                "--candidate-id",
                candidate_id,
                "--database",
                str(database),
                "--output",
                "json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "APPROVED_NON_EXECUTABLE"
    assert plan["execution_state"] == "NOT_EXECUTABLE"
    assert PRIVATE_SOURCE not in json.dumps(plan)

    assert main([*preview_args, "--private-details", "--output", "json"]) == 2
    error = json.loads(capsys.readouterr().out)
    assert error["error"]["code"] == "PRIVATE_DETAILS_REQUIRE_TEXT"
