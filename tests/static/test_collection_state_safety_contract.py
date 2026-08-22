from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_FILES = (
    ROOT / "src/foliotone/persistence/collection_state.py",
    ROOT / "src/foliotone/workflows/collection_state.py",
)


def test_collection_state_builder_has_no_source_or_external_execution_dependencies() -> None:
    forbidden_modules = {
        "httpx",
        "os",
        "requests",
        "shutil",
        "subprocess",
        "urllib",
    }
    forbidden_prefixes = (
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


def test_collection_state_cli_surface_stays_inside_accepted_adr_0058_scope() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    assert cli.count('"collection-state-build"') >= 3
    assert cli.count('"collection-state-report"') >= 3
    assert "collection-state-delete" not in cli
    assert "collection-state-execute" not in cli
    assert "collection-state-mutate" not in cli
