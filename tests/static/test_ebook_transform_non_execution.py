from __future__ import annotations

import ast
from pathlib import Path

TRANSFORM_ROOT = Path("src/foliotone/ebook_transform")
FORBIDDEN_IMPORTS = {
    "foliotone.adapters",
    "foliotone.application",
    "foliotone.cli",
    "foliotone.metadata_correction",
    "foliotone.metadata_write",
    "foliotone.persistence",
    "foliotone.tooling",
    "os",
    "pathlib",
    "subprocess",
    "tempfile",
}
FORBIDDEN_PUBLIC_WORDS = {
    "apply",
    "authorization",
    "capability",
    "execute",
    "path",
    "publish",
    "recovery",
    "rename",
}


def test_ebook_transform_has_no_execution_or_writer_dependencies() -> None:
    for path in TRANSFORM_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            assert not any(
                name == forbidden or name.startswith(f"{forbidden}.")
                for name in names
                for forbidden in FORBIDDEN_IMPORTS
            ), path


def test_ebook_transform_public_surface_is_byte_only_and_non_executable() -> None:
    module = ast.parse((TRANSFORM_ROOT / "__init__.py").read_text(encoding="utf-8"))
    exported = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    names = {
        element.value
        for element in exported.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert not any(word in name.casefold() for word in FORBIDDEN_PUBLIC_WORDS for name in names)
    assert {"canonicalize_epub3", "inspect_epub3", "verify_canonical_epub3"} <= names
