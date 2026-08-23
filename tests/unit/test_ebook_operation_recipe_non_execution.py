"""Static non-execution gate for the W9 e-book operation recipe package."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import foliotone.ebook_operation_recipes as ebook_operation_recipes

ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "foliotone"
    / "ebook_operation_recipes"
)
FORBIDDEN_IMPORT_PREFIXES = (
    "foliotone.adapters",
    "foliotone.cli",
    "foliotone.persistence",
    "foliotone.tooling",
    "importlib",
    "os",
    "pathlib",
    "shutil",
    "subprocess",
    "tempfile",
)
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "importlib.import_module",
    "open",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.unlink",
    "run",
    "shutil.move",
    "shutil.rmtree",
    "subprocess.run",
}
FORBIDDEN_METHOD_LEAVES = {
    "remove",
    "rename",
    "replace_bytes",
    "rmdir",
    "run",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
FORBIDDEN_PUBLIC_SURFACE = re.compile(
    r"^(?:apply|delete|execute|move|purge|quarantine|rename|write)(?:_|$)"
)


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def _find_execution_shapes(tree: ast.AST, filename: str) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    findings.append(f"{filename}:import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                findings.append(f"{filename}:import:{module}")
        elif isinstance(node, ast.Call):
            qualified = _qualified_name(node.func)
            leaf = None if qualified is None else qualified.rsplit(".", 1)[-1]
            if qualified in FORBIDDEN_CALLS or leaf in FORBIDDEN_METHOD_LEAVES:
                findings.append(f"{filename}:call:{qualified}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_") and FORBIDDEN_PUBLIC_SURFACE.match(node.name):
                findings.append(f"{filename}:surface:{node.name}")
    return findings


def test_recipe_package_has_no_mutating_import_call_or_public_surface() -> None:
    files = tuple(sorted(ROOT.glob("*.py")))
    assert files
    findings: list[str] = []

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        findings.extend(_find_execution_shapes(tree, path.name))

    for name in ebook_operation_recipes.__all__:
        if FORBIDDEN_PUBLIC_SURFACE.match(name):
            findings.append(f"__all__:surface:{name}")

    assert findings == []


def test_recipe_package_contains_no_known_external_write_command() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("*.py"))
    ).lower()

    assert "ebook-convert" not in source
    assert "calibredb add" not in source
    assert "calibredb set_metadata" not in source
    assert "7z u" not in source


def test_non_execution_gate_rejects_representative_write_shapes() -> None:
    source = """
import os
from pathlib import Path
from subprocess import run

def execute(path):
    Path(path).write_bytes(b"changed")
    os.rename(path, "target")
    run(["tool", "--write"])
"""
    findings = _find_execution_shapes(ast.parse(source), "synthetic.py")

    assert "synthetic.py:import:os" in findings
    assert "synthetic.py:import:pathlib" in findings
    assert "synthetic.py:import:subprocess" in findings
    assert "synthetic.py:call:write_bytes" in findings
    assert "synthetic.py:call:os.rename" in findings
    assert "synthetic.py:call:run" in findings
    assert "synthetic.py:surface:execute" in findings
