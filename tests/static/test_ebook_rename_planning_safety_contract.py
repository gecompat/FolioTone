from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            values.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            values.add(node.func.attr)
    return values


def test_rn01_application_surface_has_no_source_mutation_primitive() -> None:
    planning = ROOT / "src/foliotone/workflows/ebook_rename_planning.py"
    target = ROOT / "src/foliotone/ebook_rename/target.py"
    forbidden = {
        "chmod",
        "copy",
        "copy2",
        "link",
        "mkdir",
        "move",
        "remove",
        "rename",
        "renames",
        "replace",
        "rmdir",
        "unlink",
    }

    assert not ((_calls(planning) | _calls(target)) & forbidden)
    text = planning.read_text(encoding="utf-8")
    for forbidden_module in ("shutil", "subprocess", "foliotone.adapters"):
        assert forbidden_module not in text


def test_rn01_target_input_stays_private_and_rn04_commands_are_separate() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")

    for command in (
        "ebook-rename-propose",
        "ebook-rename-preview",
        "ebook-rename-review",
        "ebook-rename-plan",
    ):
        assert cli.count(f'"{command}"') >= 2
    assert "_read_ebook_rename_target_basename" in cli
    assert "sys.stdin.readline(1026)" in cli
    assert '"--target"' not in cli
    assert '"--target-basename"' not in cli
    assert '"--private-details"' in cli
    assert "PRIVATE_DETAILS_REQUIRE_TEXT" in cli
    for operation_command in (
        "ebook-rename-authorize",
        "ebook-rename-execute",
        "ebook-rename-recover",
        "ebook-rename-status",
    ):
        assert cli.count(f'"{operation_command}"') >= 2


def test_rn01_stays_on_recipe_store_while_rn02_owns_0031() -> None:
    migrations = ROOT / "src/foliotone/persistence/alembic/versions"
    assert (migrations / "0031_ebook_rename_operations.py").is_file()
    workflow = (
        ROOT / "src/foliotone/workflows/ebook_rename_planning.py"
    ).read_text(encoding="utf-8")
    assert "SQLiteEbookOperationRecipeStore" in workflow
    assert "SQLiteResolutionReviewStore" in workflow
    assert "SQLiteEbookRenameStore" not in workflow
    assert "APPROVED_NON_EXECUTABLE" not in workflow
