from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "docs/planning"
BACKLOG = PLANNING / "BACKLOG.md"
STATUS = PLANNING / "PROJECT_STATUS.md"
HANDOVER = PLANNING / "HANDOVER.md"
IMPLEMENTATION = PLANNING / "IMPLEMENTATION_PLAN.md"
FUTURE_MAP = PLANNING / "FUTURE_CAPABILITY_MAP.md"
ADR = ROOT / "docs/decisions/ADR-0058-book-collection-state-and-local-projections.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backlog_has_one_canonical_next_product_slice() -> None:
    backlog = _text(BACKLOG)

    assert backlog.count("| CS-01 | NEXT |") == 1
    assert "| CS-02 | PLANNED |" in backlog
    assert "| CS-03 | PLANNED |" in backlog
    assert "| W10-005 | READY |" in backlog
    assert "| OPS-001 | READY |" in backlog
    assert "Andere Planungsdokumente erläutern diese Aufgaben" in backlog


def test_book_completion_is_not_hidden_in_planned_cross_domain_rows() -> None:
    backlog = _text(BACKLOG)

    for item in range(1, 7):
        assert f"| W6-00{item} | DONE |" in backlog
    for item in range(1, 4):
        assert f"| W8-00{item} | DONE |" in backlog
    assert "| W5A-004 | DONE |" in backlog
    assert "| W5A-006 | PLANNED |" in backlog
    assert "| W6-008 | PLANNED |" in backlog
    assert "| W7-002 | DONE |" in backlog
    assert "| W7-004 | PLANNED |" in backlog


def test_collection_state_contract_is_discoverable_and_privacy_bounded() -> None:
    adr = _text(ADR)
    documentation_index = _text(ROOT / "docs/README.md")

    required = (
        "- Status: Accepted",
        "collection-state/v1",
        "collection-state-diff/v1",
        "collection-query/v1",
        "library-health/v1",
        "--private-details",
        "keinen Gesamtscore",
        "keine Source Media",
        "Music W4",
    )
    assert all(marker in adr for marker in required)
    assert "ADR-0058" in documentation_index


def test_current_planning_sources_agree_on_delivery_front() -> None:
    for path in (STATUS, HANDOVER, IMPLEMENTATION, FUTURE_MAP):
        content = _text(path)
        assert "CS-01" in content, path
        assert "CS-02" in content, path
        assert "CS-03" in content, path
        assert "W10-005" in content, path


def test_current_status_does_not_reintroduce_superseded_w10_claims() -> None:
    status = _text(STATUS)
    handover = _text(HANDOVER)
    stale_claims = (
        "S-W10-02 folgt",
        "jede reale W10-Ausführung einschließlich Quarantäne",
        "W10 bleibt bis zu einer späteren expliziten ADR blockiert",
        "Die aktive Archive-Welle",
    )

    for claim in stale_claims:
        assert claim not in status
        assert claim not in handover
    assert "nicht atomar" in status
    assert "FG-W10-MOVE-BACKEND" in status
    assert "Capability-Auflösung" in handover
