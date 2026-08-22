from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "src/foliotone/persistence/metadata_correction_report.py"
CLI = ROOT / "src/foliotone/cli/main.py"


def test_metadata_correction_report_has_no_source_or_execution_dependencies() -> None:
    tree = ast.parse(REPORT.read_text(encoding="utf-8"), filename=str(REPORT))
    forbidden_modules = {
        "httpx",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "subprocess",
        "urllib",
    }
    forbidden_calls = {"open", "remove", "rename", "replace", "rmdir", "unlink"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".", 1)[0] not in forbidden_modules
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".", 1)[0] not in forbidden_modules
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls


def test_metadata_correction_report_contract_excludes_private_material() -> None:
    report = REPORT.read_text(encoding="utf-8")
    for forbidden in (
        '"relative_path"',
        '"value"',
        '"expected_full_sha256"',
        '"metadata_evidence_fingerprint"',
        '"carrier_state_fingerprint"',
        '"material_fingerprint"',
        '"source_ref"',
        '"target_reference_id"',
    ):
        assert forbidden not in report
    for required in (
        '"plan_id"',
        '"candidate_id"',
        '"field_path"',
        '"operation"',
        '"review_status"',
        '"blocker_codes"',
    ):
        assert required in report


def test_metadata_correction_cli_is_true_read_only_and_non_executable() -> None:
    cli = CLI.read_text(encoding="utf-8")
    command = '"ebook-metadata-correction-report"'
    assert cli.count(command) >= 3
    runner_start = cli.index("def _run_ebook_metadata_correction_report")
    runner_end = cli.index("\ndef _print_ebook_metadata_correction_report", runner_start)
    runner = cli[runner_start:runner_end]
    assert "create_sqlite_read_only_engine(database)" in runner
    assert "create_sqlite_engine(" not in runner
    assert "migrate(" not in runner

    parser_start = cli.index("metadata_correction_report = subparsers.add_parser")
    parser_end = cli.index("archive_collection_status = subparsers.add_parser", parser_start)
    parser_block = cli[parser_start:parser_end]
    assert '"--private-details"' not in parser_block
    for forbidden in (
        "ebook-metadata-correction-execute",
        "ebook-metadata-correction-apply",
        "ebook-metadata-correction-write",
    ):
        assert forbidden not in cli
