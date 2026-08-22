from __future__ import annotations

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
    )
    assert all(marker in text for marker in required)


def test_w10_backlog_keeps_atomic_hardening_separate_from_interim_execution() -> None:
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/planning/PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "| W10-001 | DECISION |" in backlog
    assert "| W10-002 | DONE |" in backlog
    assert "FG-W10-MOVE-BACKEND" in backlog
    assert "S-W10-01" in status and "abgeschlossen" in status
    assert "S-W10-02" in status
    assert "Interim" in status
