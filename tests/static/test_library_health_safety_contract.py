from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HEALTH_FILES = (
    ROOT / "src/foliotone/collection_state/health.py",
    ROOT / "src/foliotone/persistence/library_health.py",
    ROOT / "src/foliotone/workflows/library_health.py",
)


def test_library_health_has_no_source_tool_provider_network_or_mutation_dependencies() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in HEALTH_FILES)
    forbidden = (
        "foliotone.adapters",
        "foliotone.tooling.runtime",
        "requests",
        "httpx",
        "urllib",
        "os.rename",
        "shutil.move",
        "unlink(",
        "remove(",
        "subprocess",
    )
    for token in forbidden:
        assert token not in combined


def test_library_health_report_contract_remains_path_and_digest_free() -> None:
    workflow = (ROOT / "src/foliotone/workflows/library_health.py").read_text(encoding="utf-8")
    cli = (ROOT / "src/foliotone/cli/main.py").read_text(encoding="utf-8")
    assert '"library-health-report"' in cli
    assert "create_sqlite_read_only_engine(database)" in cli
    assert '"relative_path"' not in workflow
    assert '"metadata"' not in workflow
    assert '"content_digest"' not in workflow
    assert '"fingerprint"' not in workflow
    assert '"file_id"' in workflow
    assert '"observation_id"' in workflow


def test_adr_0060_keeps_api_ui_music_and_source_mutation_out_of_scope() -> None:
    adr = (ROOT / "docs/decisions/ADR-0060-multidimensional-library-health.md").read_text(
        encoding="utf-8"
    )
    assert "keine API" in adr
    assert "keine UI" in adr
    assert "keine Music-" in adr
    assert "keinen Source-Media-Zugriff" in adr
    assert "Es gibt keinen" in adr and "Gesamtscore" in adr
