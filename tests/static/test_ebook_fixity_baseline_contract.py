from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from foliotone.fixity import EbookFixityBaselineStatusSnapshot
from foliotone.persistence.fixity_schema import EBOOK_FIXITY_BASELINE_TABLES

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_baseline_slice_has_no_surface_network_w10_or_source_write_dependency() -> None:
    source_files = (
        "src/foliotone/fixity/contracts.py",
        "src/foliotone/fixity/confirmation.py",
        "src/foliotone/fixity/hashing.py",
        "src/foliotone/persistence/fixity.py",
        "src/foliotone/workflows/fixity_baseline.py",
    )
    forbidden_imports = (
        "foliotone.cli",
        "foliotone.surface",
        "foliotone.quarantine",
        "foliotone.metadata_write",
        "foliotone.ebook_rename",
        "httpx",
        "requests",
        "socket",
        "subprocess",
    )
    for relative in source_files:
        tree = ast.parse(_text(relative), filename=relative)
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for name in imported
            for forbidden in forbidden_imports
        ), relative

    hashing = _text("src/foliotone/fixity/hashing.py")
    for mutation in ("os.remove", "os.unlink", "os.rename", "os.replace", "os.write"):
        assert mutation not in hashing


def test_persistence_keeps_absolute_paths_out_and_private_values_out_of_status() -> None:
    columns = {column.name for table in EBOOK_FIXITY_BASELINE_TABLES for column in table.columns}
    status_fields = {item.name for item in fields(EbookFixityBaselineStatusSnapshot)}

    assert "absolute_path" not in columns
    assert "physical_path" not in columns
    assert "source_root" not in columns
    assert "relative_locator" not in status_fields
    assert "expected_sha256" not in status_fields
    assert "content_digest" not in status_fields


def test_decision_planning_and_governance_match_the_implemented_slice() -> None:
    decision = _text("docs/decisions/DEC-0001-book-only-fixity-monitoring.md")
    backlog = _text("docs/planning/BACKLOG.md")
    status = _text("docs/planning/PROJECT_STATUS.md")
    agents = _text("AGENTS.md")
    future = _text("docs/planning/FUTURE_CAPABILITY_MAP.md")
    attributes = _text(".gitattributes")

    assert "ebook-fixity-baseline/v1" in decision
    assert "ACCEPT FIXITY BASELINE <manifest-id>" in decision
    assert "| NEXT WAVE | Keine bis zur Detailentscheidung |" in backlog
    assert "| WI-0003 (`FUT-009`) | BLOCKED |" in backlog
    assert "Migration `0035_ebook_fixity_baseline`" in status
    assert "SQLite-`query_only`-Projektion" in status
    assert "CLI plus the completed staged" in agents
    assert "ADR-0066-Same-Parent-Rename" in future
    assert "* text=auto eol=lf" in attributes
