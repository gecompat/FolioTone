"""Static guard against accidental full-schema migration per test case."""

import ast
from pathlib import Path


def test_head_migrations_are_limited_to_template_and_migration_contracts() -> None:
    tests_root = Path(__file__).parents[1]
    offenders: list[str] = []

    for source_path in sorted(tests_root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        for node in ast.walk(tree):
            if not _is_default_head_migration(node):
                continue
            function = _enclosing_function(node, parents)
            function_name = function.name if function is not None else "<module>"
            is_template = (
                source_path.name == "conftest.py"
                and function_name == "_head_database_template"
            )
            if not is_template and "migration" not in function_name:
                offenders.append(
                    f"{source_path.relative_to(tests_root)}:{node.lineno}:{function_name}"
                )

    assert offenders == [], (
        "tests against schema head must copy head_database instead of running migrate(): "
        + ", ".join(offenders)
    )


def _is_default_head_migration(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "migrate":
        return False
    has_revision_keyword = any(keyword.arg == "revision" for keyword in node.keywords)
    return len(node.args) < 2 and not has_revision_keyword


def _enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(current)
    return None
