from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_FILES = (
    ROOT / "src/foliotone/collection_state/diff.py",
    ROOT / "src/foliotone/collection_state/query.py",
    ROOT / "src/foliotone/persistence/collection_query.py",
    ROOT / "src/foliotone/persistence/collection_state_diff.py",
    ROOT / "src/foliotone/workflows/collection_state_query.py",
)


def test_diff_and_query_implementations_do_not_open_media_or_external_tools() -> None:
    forbidden_modules = {"httpx", "os", "requests", "shutil", "subprocess", "urllib"}
    forbidden_prefixes = (
        "foliotone.adapters",
        "foliotone.analyzers",
        "foliotone.providers",
        "foliotone.tooling",
    )
    forbidden_calls = {"open", "remove", "rename", "rmdir", "unlink"}

    for path in IMPLEMENTATION_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".", 1)[0] not in forbidden_modules, path
                    assert not alias.name.startswith(forbidden_prefixes), path
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".", 1)[0] not in forbidden_modules, path
                assert not module.startswith(forbidden_prefixes), path
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in forbidden_calls, path
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in forbidden_calls, path


def test_query_schema_is_metadata_only_and_has_no_query_history() -> None:
    schema = (ROOT / "src/foliotone/persistence/collection_query_schema.py").read_text(
        encoding="utf-8"
    )
    migration = (
        ROOT / "src/foliotone/persistence/alembic/versions/0024_collection_state_diff_query.py"
    ).read_text(encoding="utf-8")

    assert "collection_query_values_fts" in migration
    assert "WHEN new.value_kind='METADATA_CANDIDATE'" in migration
    assert "metadata_candidate" in schema.lower()
    for forbidden in (
        "absolute_path",
        "relative_path",
        "content_text",
        "ocr_text",
        "query_history",
        "query_text",
    ):
        assert forbidden not in schema.lower()
        assert forbidden not in migration.lower()


def test_cli_exposes_only_the_accepted_read_only_cs02_surface() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")

    assert cli.count('"collection-state-diff"') >= 2
    assert cli.count('"collection-search"') >= 2
    assert '"--private-details"' in cli
    assert "PRIVATE_DETAILS_REQUIRE_TEXT" in cli
    for forbidden in (
        "collection-query-sql",
        "collection-search-history",
        "collection-state-diff-execute",
        "collection-search-api",
    ):
        assert forbidden not in cli
