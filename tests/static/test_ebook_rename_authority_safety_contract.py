from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = ROOT / "src/foliotone/ebook_rename/authority.py"
CAPABILITIES = ROOT / "src/foliotone/ebook_rename/capabilities.py"
STORE = ROOT / "src/foliotone/persistence/ebook_rename.py"
STATUS = ROOT / "src/foliotone/workflows/ebook_rename_status.py"
BACKEND = ROOT / "src/foliotone/ebook_rename/linux_backend.py"
EXECUTOR = ROOT / "src/foliotone/ebook_rename/executor.py"
CLI = ROOT / "src/foliotone/cli/main.py"


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def test_rn02_has_no_source_media_mutation_or_external_execution_primitive() -> None:
    forbidden_imports = {
        "httpx",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_calls = {
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.unlink",
        "shutil.copy",
        "shutil.copy2",
        "shutil.move",
        "subprocess.run",
    }
    forbidden_leaves = {
        "copyfile",
        "hardlink_to",
        "rename",
        "rmdir",
        "symlink_to",
        "unlink",
        "write_bytes",
        "write_text",
    }

    findings: list[str] = []
    for path in (AUTHORITY, CAPABILITIES, STORE, STATUS):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in forbidden_imports:
                        findings.append(f"{path.name}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".", 1)[0] in forbidden_imports:
                    findings.append(f"{path.name}:import:{module}")
            elif isinstance(node, ast.Call):
                qualified = _qualified_name(node.func)
                leaf = None if qualified is None else qualified.rsplit(".", 1)[-1]
                if qualified in forbidden_calls or leaf in forbidden_leaves:
                    findings.append(f"{path.name}:call:{qualified}")

    assert findings == []


def test_rn02_status_contract_excludes_every_private_binder() -> None:
    source = STATUS.read_text(encoding="utf-8")
    for forbidden in (
        '"source_locator_digest"',
        '"target_locator_digest"',
        '"source_full_sha256"',
        '"source_inode"',
        '"source_device"',
        '"source_xattr_fingerprint"',
        '"capability_configuration_fingerprint"',
        '"filesystem_identity_fingerprint"',
        '"fence_epoch"',
        '"confirmation_digest"',
    ):
        assert forbidden not in source
    for required in (
        '"run_id"',
        '"authorization_id"',
        '"plan_id"',
        '"scan_root_id"',
        '"status"',
        '"events"',
    ):
        assert required in source


def test_rn03_backend_exists_while_cli_and_reconciliation_remain_closed() -> None:
    migration = (
        ROOT
        / "src/foliotone/persistence/alembic/versions/0031_ebook_rename_operations.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert "ebook_rename_preparations" in (
        ROOT / "src/foliotone/persistence/ebook_rename_schema.py"
    ).read_text(encoding="utf-8")
    assert "EBOOK_RENAME_PREPARATION" in source
    assert "EBOOK_RENAME_RUN" in source
    assert "no_update" in source
    assert "no_delete" in source
    assert "events_append_only" in source
    assert EXECUTOR.exists()
    assert BACKEND.exists()
    assert not (
        ROOT
        / "src/foliotone/persistence/alembic/versions/0032_ebook_rename_reconciliation.py"
    ).exists()

    cli = CLI.read_text(encoding="utf-8")
    for command in (
        "ebook-rename-authorize",
        "ebook-rename-execute",
        "ebook-rename-recover",
        "ebook-rename-status",
    ):
        assert command not in cli


def test_rn03_uses_only_the_fixed_linux_noreplace_boundary() -> None:
    backend_source = BACKEND.read_text(encoding="utf-8")
    executor_source = EXECUTOR.read_text(encoding="utf-8")
    combined = backend_source + executor_source
    for forbidden in (
        "os.rename(",
        "os.replace(",
        "shutil.",
        "subprocess.",
        "metadata_write",
        "quarantine",
        "copyfile(",
    ):
        assert forbidden not in combined
    for required in (
        "_SYS_OPENAT2_X86_64: Final = 437",
        "_SYS_RENAMEAT2_X86_64: Final = 316",
        "_RENAME_NOREPLACE: Final = 1",
        "_RESOLVE_BENEATH",
        "_RESOLVE_NO_SYMLINKS",
        "_RESOLVE_NO_MAGICLINKS",
        "_RESOLVE_NO_XDEV",
        "MIN_EBOOK_RENAME_MUTATION_LEASE_REMAINING",
    ):
        assert required in combined

    tree = ast.parse(backend_source, filename=str(BACKEND))
    unlink_functions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(
            isinstance(child, ast.Call)
            and _qualified_name(child.func) == "os.unlink"
            for child in ast.walk(node)
        ):
            unlink_functions.append(node.name)
    assert unlink_functions == ["_probe_noreplace"]
