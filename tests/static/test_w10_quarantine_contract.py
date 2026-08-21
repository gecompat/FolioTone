from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/decisions/ADR-0056-fenced-quarantine-only-consolidation.md"


def test_w10_quarantine_contract_is_narrow_and_filesystem_neutral() -> None:
    text = ADR.read_text(encoding="utf-8")
    required = (
        "- Status: Accepted",
        "quarantine-authorization/v1",
        "quarantine-execution/v1",
        "APPROVED_NON_EXECUTABLE",
        "CONSOLIDATION_QUARANTINE_RUN",
        "FG-W10-MOVE-BACKEND",
        "atomaren No-Replace-Move",
        "Cross-Volume-Moves",
        "kein bestimmtes Dateisystem",
        "keine reale Mutation",
        "Copy+Delete",
        "Metadatenwrite",
        "S-W10-01",
        "S-W10-04",
    )
    assert all(marker in text for marker in required)


def test_w10_backlog_keeps_execution_blocked_until_backend_gate() -> None:
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/planning/PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "| W10-001 | DECISION |" in backlog
    assert "| W10-002 | BLOCKED |" in backlog
    assert "FG-W10-MOVE-BACKEND" in backlog
    assert "S-W10-01" in status
    assert "keine reale Mutation" in status
