from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
PURE_SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/contracts.py",
    ROOT / "src/foliotone/metadata_write/epub_title.py",
)
STAGING_SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/staging.py",
    ROOT / "src/foliotone/metadata_write/validation.py",
)
MW03_SOURCE_FILES = (
    ROOT / "src/foliotone/metadata_write/authorization.py",
    ROOT / "src/foliotone/metadata_write/capabilities.py",
    ROOT / "src/foliotone/persistence/metadata_write.py",
    ROOT / "src/foliotone/persistence/metadata_write_schema.py",
    ROOT / "src/foliotone/persistence/alembic/versions/0027_metadata_write_operations.py",
    ROOT / "src/foliotone/workflows/metadata_write_report.py",
)
MW04_BACKEND = ROOT / "src/foliotone/metadata_write/linux_backend.py"
MW04_EXECUTOR = ROOT / "src/foliotone/metadata_write/executor.py"


def test_pure_epub_title_slice_has_no_filesystem_process_database_or_network_surface() -> None:
    forbidden_import_roots = {
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlalchemy",
        "subprocess",
        "tempfile",
        "urllib",
    }
    forbidden_name_calls = {
        "open",
    }
    forbidden_attribute_calls = {
        "remove",
        "rename",
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }

    for source_file in PURE_SOURCE_FILES:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_attributes.add(node.func.attr)
        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_names.isdisjoint(forbidden_name_calls)
        assert called_attributes.isdisjoint(forbidden_attribute_calls)


def test_private_staging_has_no_source_commit_cli_persistence_or_network_surface() -> None:
    forbidden_import_roots = {
        "socket",
        "sqlalchemy",
        "urllib",
    }
    forbidden_attribute_calls = {
        "copy2",
        "execute_container",
        "execute_local",
        "move",
        "remove",
        "rename",
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }

    for source_file in STAGING_SOURCE_FILES:
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_file))
        imported_roots: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)
        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_attributes.isdisjoint(forbidden_attribute_calls)
        assert "shutil.copy" not in source
        assert "shutil.move" not in source
        assert "foliotone.persistence" not in source
        assert "foliotone.cli" not in source


def test_private_validator_invokes_processes_without_a_shell() -> None:
    validation = STAGING_SOURCE_FILES[1]
    tree = ast.parse(validation.read_text(encoding="utf-8"), filename=str(validation))
    process_calls = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    )

    assert len(process_calls) == 1
    shell_keywords = tuple(
        keyword
        for keyword in process_calls[0].keywords
        if keyword.arg == "shell"
    )
    assert len(shell_keywords) == 1
    assert isinstance(shell_keywords[0].value, ast.Constant)
    assert shell_keywords[0].value.value is False


def test_metadata_write_cli_uses_only_the_fixed_application_boundary() -> None:
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    persistence_files = tuple((ROOT / "src/foliotone/persistence").rglob("*.py"))

    assert "foliotone.metadata_write" not in cli
    assert "epub-title-write" not in cli
    assert "foliotone.workflows.metadata_write_operation" in cli
    assert "metadata-write-authorize" in cli
    assert "metadata-write-execute" in cli
    assert "metadata-write-recover" in cli
    assert "metadata-write-status" in cli
    assert "LinuxMetadataWriteBackend" not in cli
    assert "RENAME_EXCHANGE" not in cli
    assert "RENAME_NOREPLACE" not in cli
    assert {
        path.relative_to(ROOT).as_posix()
        for path in persistence_files
        if "foliotone.metadata_write" in path.read_text(encoding="utf-8")
    } == {"src/foliotone/persistence/metadata_write.py"}


def test_mw03_authorization_and_status_slice_cannot_mutate_source_media() -> None:
    forbidden_import_roots = {
        "httpx",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_name_calls = {"open"}
    forbidden_attribute_calls = {
        "chmod",
        "chown",
        "copy",
        "copy2",
        "mkdir",
        "move",
        "remove",
        "rename",
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }

    for source_file in MW03_SOURCE_FILES:
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_file))
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        called_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_attributes.add(node.func.attr)
        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_names.isdisjoint(forbidden_name_calls)
        assert called_attributes.isdisjoint(forbidden_attribute_calls)
        assert "O_WRONLY" not in source
        assert "O_RDWR" not in source
        assert "O_CREAT" not in source
        assert "os.replace" not in source
        assert "foliotone.cli" not in source
    assert "foliotone.persistence" not in MW03_SOURCE_FILES[0].read_text(encoding="utf-8")


def test_mw04_keeps_all_source_mutation_inside_the_fixed_linux_backend() -> None:
    backend_source = MW04_BACKEND.read_text(encoding="utf-8")
    backend_tree = ast.parse(backend_source, filename=str(MW04_BACKEND))
    forbidden_import_roots = {
        "httpx",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_attributes = {
        "copy",
        "copy2",
        "move",
        "remove",
        "rename",
        "rmdir",
        "unlink",
    }
    imported_roots: set[str] = set()
    called_attributes: set[str] = set()
    rename_flags: list[str] = []
    for node in ast.walk(backend_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                called_attributes.add(node.func.attr)
            elif isinstance(node.func, ast.Name) and node.func.id == "_renameat2":
                flag = node.args[-1]
                assert isinstance(flag, ast.Name)
                rename_flags.append(flag.id)

    assert imported_roots.isdisjoint(forbidden_import_roots)
    assert called_attributes.isdisjoint(forbidden_attributes)
    assert rename_flags
    assert set(rename_flags) == {"_RENAME_EXCHANGE", "_RENAME_NOREPLACE"}
    assert "os.rename" not in backend_source
    assert "os.replace" not in backend_source
    assert "copy+delete" not in backend_source.lower()


def test_mw04_executor_accepts_no_source_path_or_rename_controls() -> None:
    source = MW04_EXECUTOR.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MW04_EXECUTOR))
    public_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name
        in {
            "execute_epub3_title_metadata_write",
            "recover_epub3_title_metadata_write",
        }
    }
    assert set(public_functions) == {
        "execute_epub3_title_metadata_write",
        "recover_epub3_title_metadata_write",
    }
    forbidden_parameters = {
        "source",
        "source_path",
        "source_relative_path",
        "target",
        "target_path",
        "flags",
        "rename_flags",
        "syscall",
        "syscall_number",
    }
    for function in public_functions.values():
        parameters = {
            argument.arg
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            )
        }
        assert parameters.isdisjoint(forbidden_parameters)

    forbidden_import_roots = {
        "httpx",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_mutations = {
        "copy",
        "copy2",
        "move",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "unlink",
    }
    imported_roots: set[str] = set()
    called_attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)
    assert imported_roots.isdisjoint(forbidden_import_roots)
    assert called_attributes.isdisjoint(forbidden_mutations)
    assert "foliotone.cli" not in source
    assert "_RENAME_EXCHANGE" not in source
    assert "_RENAME_NOREPLACE" not in source
