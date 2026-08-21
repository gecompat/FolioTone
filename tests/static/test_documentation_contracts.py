from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROTECTED_README_PREFIX = "\n".join(
    (
        "# FolioTone",
        "",
        "---",
        "---",
        "# ⚠️ READ BEFORE USE",
        "",
        "## License notice",
        "",
        (
            "**NOTICE: This software is NOT Open Source. Use is governed by a custom "
            "Community & Attribution License.**"
        ),
        "",
        "1. **NO RESALE:** Selling or charging for access to this software is strictly prohibited.",
        (
            "2. **ATTRIBUTION REQUIRED:** You must preserve the copyright notice for "
            "**gecompat - Gerhard Pisch**."
        ),
        (
            "3. **NO LIABILITY:** Use this software at your own risk. The author is "
            "**NOT liable** for any damages, data loss, or business interruptions."
        ),
        "",
        "Full legal terms can be found in the [LICENSE.md](./LICENSE.md) file.",
        "",
        "---",
        "## Lizenzhinweis",
        "",
        (
            "**NOTIZ: FolioTone ist keine Open-Source-Software. Die Nutzung richtet sich nach der "
            "projektspezifischen Community & Attribution License.**"
        ),
        "",
        (
            "1. **NO RESALE:** Der Verkauf der Software und das Entgelt für den Zugang zur "
            "Software sind untersagt."
        ),
        (
            "2. **ATTRIBUTION REQUIRED:** Der Copyright-Hinweis für **gecompat – Gerhard Pisch** "
            "muss erhalten bleiben."
        ),
        (
            "3. **NO LIABILITY:** Die Nutzung erfolgt auf eigenes Risiko; der Autor "
            "**haftet nicht** für Schäden, Datenverlust oder Betriebsunterbrechungen."
        ),
        "",
        "Maßgeblich ist der vollständige Wortlaut in [LICENSE.md](./LICENSE.md).",
        "",
        "# ⚠️ READ BEFORE USE",
        "",
        "---",
        "---",
        "",
    )
) + "\n"

REQUIRED_GOVERNANCE_PATHS = (
    "docs/planning/AI_WORKFLOW.md",
    "docs/planning/AI_TOOL_ADAPTERS.md",
    "docs/planning/MODEL_ROUTING_POLICY.md",
    "docs/quality/TEST_POLICY.md",
    "docs/quality/DOCUMENTATION_STYLE.md",
    "docs/quality/LANGUAGE_AND_TERMINOLOGY.md",
    "docs/reference/GLOSSARY.md",
    "docs/README.md",
    ".github/copilot-instructions.md",
    ".junie/AGENTS.md",
)

DOCKER_CONTEXT_ALLOWLIST = (
    "**",
    "!Dockerfile",
    "!pyproject.toml",
    "!README.md",
    "!packaging/",
    "!packaging/ebook-tools/",
    "!packaging/ebook-tools/**",
    "!src/",
    "!src/**",
)


def test_root_readme_protected_license_prefix_is_unchanged() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(PROTECTED_README_PREFIX)


def test_documentation_governance_files_exist() -> None:
    missing = [path for path in REQUIRED_GOVERNANCE_PATHS if not (ROOT / path).is_file()]
    assert missing == []


def test_agents_routes_documentation_changes_to_canonical_policies() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/quality/DOCUMENTATION_STYLE.md" in agents
    assert "docs/quality/LANGUAGE_AND_TERMINOLOGY.md" in agents
    assert "docs/reference/GLOSSARY.md" in agents
    assert "protected" in agents.lower() or "geschützt" in agents.lower()


def test_copilot_routes_documentation_changes_to_same_policies() -> None:
    instructions = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    assert "DOCUMENTATION_STYLE.md" in instructions
    assert "LANGUAGE_AND_TERMINOLOGY.md" in instructions
    assert "GLOSSARY.md" in instructions
    assert "Lizenzblock" in instructions


def test_agent_strategy_is_vendor_neutral_and_adapters_are_thin() -> None:
    policy = (ROOT / "docs/planning/MODEL_ROUTING_POLICY.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs/planning/AI_WORKFLOW.md").read_text(encoding="utf-8")
    adapters = (ROOT / "docs/planning/AI_TOOL_ADAPTERS.md").read_text(encoding="utf-8")
    copilot = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    junie = (ROOT / ".junie/AGENTS.md").read_text(encoding="utf-8")

    for tier in ("LOCAL", "ECONOMICAL", "BALANCED", "FRONTIER"):
        assert f"`{tier}`" in policy
    assert "gpt-" not in policy.lower()
    assert "Genau ein Implementierungsagent" in workflow
    assert "Databricks Genie Code" in adapters
    assert "Databricks Genie Agents" in adapters
    assert "AGENTS.md" in copilot
    assert "AGENTS.md" in junie


def test_legacy_project_name_is_absent_from_public_markdown() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT).as_posix()
        if ".git" in path.parts:
            continue
        if "MediaCurator" in path.read_text(encoding="utf-8"):
            offenders.append(relative)
    assert offenders == []


def test_docker_build_context_is_restricted_to_packaged_application_inputs() -> None:
    rules = tuple(
        line
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert rules == DOCKER_CONTEXT_ALLOWLIST


def test_post_merge_diff_check_preserves_byte_identical_renames() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "git diff-tree -M --check HEAD^1 HEAD" in workflow
    assert "git diff-tree --check HEAD^1 HEAD" not in workflow


def test_calibre_capture_status_is_closed_consistently() -> None:
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/planning/PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "| S-EB07-11B2B | DONE |" in backlog
    assert "Capture-Orchestrierung bleibt offen" not in status
    assert "Capture-Orchestrierung gegen eine konfigurierte Calibre-Bibliothek bleibt" not in status
    assert "Calibre-Capture-Schiene aus ADR-0033 ist damit" in status
