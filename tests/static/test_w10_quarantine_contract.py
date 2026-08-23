from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/decisions/ADR-0056-fenced-quarantine-only-consolidation.md"


def test_w10_quarantine_contract_keeps_the_interim_boundary_explicit() -> None:
    text = ADR.read_text(encoding="utf-8")
    required = (
        "- Status: Accepted",
        "quarantine-authorization/v1",
        "quarantine-execution/v1",
        "APPROVED_NON_EXECUTABLE",
        "CONSOLIDATION_QUARANTINE_RUN",
        "FG-W10-MOVE-BACKEND",
        "Interim amendment",
        "os.rename",
        "nicht atomar",
        "Cross-Volume-Moves",
        "kein bestimmtes Dateisystem",
        "Copy+Delete",
        "Metadatenwrite",
        "S-W10-01",
        "S-W10-04",
        "W10-005",
        "FOLIOTONE_QUARANTINE_CAPABILITIES_FILE",
        "quarantine-authorize",
        "quarantine-execute",
        "quarantine-recover",
    )
    assert all(marker in text for marker in required)


def test_w10_backlog_keeps_atomic_hardening_separate_from_interim_execution() -> None:
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/planning/PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "| W10-001 | DECISION |" in backlog
    assert "| W10-002 | DONE |" in backlog
    assert "FG-W10-MOVE-BACKEND" in backlog
    assert "| W10-005 | DONE |" in backlog
    assert "S-W10-01" in status and "abgeschlossen" in status
    assert "S-W10-02" in status
    assert "Interim" in status


def test_s_w10_05c_opens_only_the_confirmed_interim_execute_path() -> None:
    workflow = (
        ROOT / "src/foliotone/workflows/quarantine_operation.py"
    ).read_text(encoding="utf-8")
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    persistence = (
        ROOT / "src/foliotone/persistence/quarantine.py"
    ).read_text(encoding="utf-8")
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    authorize = _method_source(workflow, "QuarantineOperatorService", "authorize")
    execute = _method_source(workflow, "QuarantineOperatorService", "execute")

    assert "create_or_get_authorization" in authorize
    assert "self._executor" not in authorize
    assert "self._executor(" in execute
    assert "execute_interim_quarantine" in workflow
    assert "create_confirmed_prepared_run" in persistence
    assert "confirmation_digest=confirmation_digest" in workflow
    assert "os.rename" not in workflow
    assert "shutil" not in workflow
    assert '"quarantine-authorize"' in cli
    assert '"quarantine-execute"' in cli
    assert "| S-W10-05B | DONE |" in backlog
    assert "| S-W10-05C | DONE |" in backlog


def test_s_w10_05d_recovers_by_fixed_physical_state_without_another_move() -> None:
    workflow = (
        ROOT / "src/foliotone/workflows/quarantine_operation.py"
    ).read_text(encoding="utf-8")
    recovery = (
        ROOT / "src/foliotone/quarantine/recovery.py"
    ).read_text(encoding="utf-8")
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    recover = _method_source(workflow, "QuarantineOperatorService", "recover")

    assert "self._recovery(" in recover
    assert "recover_interim_quarantine" in workflow
    assert "SOURCE_EXACT_TARGET_ABSENT" in recovery
    assert "SOURCE_ABSENT_TARGET_EXACT" in recovery
    assert "RECOVERY_STATE_AMBIGUOUS" in recovery
    assert "os.rename" not in recovery
    assert "shutil" not in recovery
    assert '"quarantine-recover"' in cli
    assert "| W10-005 | DONE |" in backlog
    assert "| S-W10-05D | DONE |" in backlog


def _method_source(module_source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(module_source)
    owner = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    value = ast.get_source_segment(module_source, method)
    assert value is not None
    return value
