"""Static regression gate for the W9 metadata-correction package."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import foliotone.metadata_correction as metadata_correction

ROOT = Path(__file__).resolve().parents[2] / "src" / "foliotone" / "metadata_correction"
PERSISTENCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "foliotone"
    / "persistence"
    / "metadata_correction.py"
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


def test_metadata_correction_package_has_no_mutating_import_call_or_surface() -> None:
    files = tuple(sorted(ROOT.glob("*.py")))
    assert files
    findings: list[str] = []

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        findings.append(f"{path.name}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    findings.append(f"{path.name}:import:{module}")
            elif isinstance(node, ast.Call):
                qualified = _qualified_name(node.func)
                leaf = None if qualified is None else qualified.rsplit(".", 1)[-1]
                if qualified in FORBIDDEN_CALLS or leaf in FORBIDDEN_METHOD_LEAVES:
                    findings.append(f"{path.name}:call:{qualified}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_") and FORBIDDEN_PUBLIC_SURFACE.match(node.name):
                    findings.append(f"{path.name}:surface:{node.name}")

    for name in metadata_correction.__all__:
        if FORBIDDEN_PUBLIC_SURFACE.match(name):
            findings.append(f"__all__:surface:{name}")

    assert findings == []


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
    tree = ast.parse(source)
    imports: list[str] = []
    calls: list[str] = []
    surfaces: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            qualified = _qualified_name(node.func)
            leaf = None if qualified is None else qualified.rsplit(".", 1)[-1]
            if qualified in FORBIDDEN_CALLS or leaf in FORBIDDEN_METHOD_LEAVES:
                calls.append(qualified)
        elif isinstance(node, ast.FunctionDef) and FORBIDDEN_PUBLIC_SURFACE.match(node.name):
            surfaces.append(node.name)

    assert {"os", "pathlib", "subprocess"} <= set(imports)
    assert {"write_bytes", "os.rename", "run"} <= set(calls)
    assert surfaces == ["execute"]


def test_metadata_correction_store_has_no_source_media_or_execution_surface() -> None:
    tree = ast.parse(PERSISTENCE.read_text(encoding="utf-8"), filename=str(PERSISTENCE))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("os", "pathlib", "shutil", "subprocess")):
                    findings.append(f"import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(("os", "pathlib", "shutil", "subprocess")):
                findings.append(f"import:{module}")
        elif isinstance(node, ast.Call):
            qualified = _qualified_name(node.func)
            leaf = None if qualified is None else qualified.rsplit(".", 1)[-1]
            if qualified in FORBIDDEN_CALLS or leaf in FORBIDDEN_METHOD_LEAVES:
                findings.append(f"call:{qualified}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_") and FORBIDDEN_PUBLIC_SURFACE.match(node.name):
                findings.append(f"surface:{node.name}")

    assert findings == []
