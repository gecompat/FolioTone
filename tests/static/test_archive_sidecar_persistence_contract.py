from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / "docs/decisions/ADR-0055-archive-sidecar-inventory-persistence.md"


def test_archive_sidecar_inventory_contract_is_closed_and_non_executing() -> None:
    text = ADR.read_text(encoding="utf-8")

    required = (
        "- Status: Accepted",
        "archive-sidecar-inventory/v1",
        "0021_archive_sidecar_inventory",
        "archive_sidecar_inventories",
        "archive_sidecar_inventory_items",
        "33 Kindzeilen (`limit + 1`)",
        "40d517c3-c650-5760-8b8b-6e8e6665989b",
        "ix_file_observations_run_path",
        "keine vom Caller behauptete Sidecar-Liste",
        "`list_all()`-, Offset-",
        "freie 7-Zip-Prosa oder grobe Exitcodes",
        "keine Dateiöffnung",
        "neue öffentliche CLI-Felder",
        "S-EBAR-07A",
    )
    assert all(marker in text for marker in required)


def test_planning_sources_agree_on_the_next_bounded_package() -> None:
    files = (
        "docs/planning/PROJECT_STATUS.md",
        "docs/planning/BACKLOG.md",
        "docs/planning/EBOOK_SPARK_WORK_PACKAGES.md",
        "docs/planning/EBOOK_ENDGAME_IMPLEMENTATION_PLAN.md",
        "docs/planning/EBOOK_DEDUPLICATION_ARCHIVE_ROADMAP.md",
    )
    contents = [(ROOT / name).read_text(encoding="utf-8") for name in files]

    assert all("S-EBAR-07A" in text for text in contents)
    assert "| W3-019 | IN PROGRESS |" in contents[1]
    assert "FG-A3-MEMBER-BYTE bleibt" in contents[3]
