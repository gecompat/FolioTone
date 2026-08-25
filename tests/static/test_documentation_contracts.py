import json
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
    ".ai/foundation/FOUNDATION_RULESET.md",
    ".ai/foundation/AI_REPOSITORY_FOUNDATION_NOTICE.md",
    ".ai/foundation/PROJECT_RULES.md",
    ".ai/foundation/SEMANTIC_INTEGRATION_POLICY.md",
    ".ai/foundation/PERSISTENT_IDENTITY_POLICY.md",
    ".ai/foundation/ARTIFACT_REGISTRATION_POLICY.md",
    ".ai/foundation/schemas/artifact-record.schema.json",
    ".ai/foundation/schemas/artifact-registry.schema.json",
    ".ai/foundation/schemas/artifact-registration-request.schema.json",
    ".ai/foundation/reference_clients/artifact_reference.py",
    ".ai/foundation/reference_clients/ArtifactReference.ps1",
    ".ai/foundation/WORKING_RULES.md",
    ".ai/foundation/MODEL_ROUTING_POLICY.md",
    ".ai/foundation/VALIDATION_POLICY.md",
    ".ai/foundation/DATA_PRIVACY_AND_CONFIDENTIALITY.md",
    ".ai/foundation/SECURITY_AND_SAFE_OPERATIONS.md",
    ".ai/foundation/DOCUMENTATION_POLICY.md",
    ".ai/foundation/THIRD_PARTY_AND_LICENSING.md",
    ".ai/foundation/SOURCE_AND_EVIDENCE_POLICY.md",
    ".ai/foundation/DEPENDENCY_POLICY.md",
    ".ai/foundation/repo_map.yaml",
    "docs/planning/AI_WORKFLOW.md",
    "docs/planning/ARTIFACT_REGISTRATION.md",
    "docs/planning/artifact_registry.json",
    "docs/planning/EBOOK_CONTINUATION_PLAN.md",
    "docs/decisions/DEC-0001-book-only-fixity-monitoring.md",
    "docs/decisions/DEC-0002-deterministic-epub-transformation.md",
    "docs/planning/artifacts/DEC-0001.json",
    "docs/planning/artifacts/DEC-0002.json",
    "docs/planning/artifacts/GATE-0001.json",
    "docs/planning/artifacts/WI-0001.json",
    "docs/planning/artifacts/WI-0002.json",
    "docs/planning/artifacts/WI-0003.json",
    "docs/planning/artifacts/WI-0004.json",
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

USER_GUIDE_PATHS = (
    "docs/user-guide/README.md",
    "docs/user-guide/INSTALLATION.md",
    "docs/user-guide/SCHNELLSTART.md",
    "docs/user-guide/BENUTZERHANDBUCH.md",
    "docs/user-guide/CLI.md",
)

USER_GUIDE_IMAGES = (
    "docs/user-guide/images/01-anmeldung.jpg",
    "docs/user-guide/images/02-ebook-uebersicht.jpg",
    "docs/user-guide/images/03-suche-treffer.jpg",
    "docs/user-guide/images/04-collectionstate-details.jpg",
    "docs/user-guide/images/05-rename-workflow.jpg",
)


def test_root_readme_protected_license_prefix_is_unchanged() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(PROTECTED_README_PREFIX)


def test_documentation_governance_files_exist() -> None:
    missing = [path for path in REQUIRED_GOVERNANCE_PATHS if not (ROOT / path).is_file()]
    assert missing == []


def test_ebook_user_guide_has_two_installation_paths_and_canonical_indexes() -> None:
    missing = [path for path in USER_GUIDE_PATHS if not (ROOT / path).is_file()]
    installation = (ROOT / "docs/user-guide/INSTALLATION.md").read_text(
        encoding="utf-8"
    )
    quickstart = (ROOT / "docs/user-guide/SCHNELLSTART.md").read_text(
        encoding="utf-8"
    )
    handbook = (ROOT / "docs/user-guide/BENUTZERHANDBUCH.md").read_text(
        encoding="utf-8"
    )
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    documentation_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")

    assert missing == []
    assert "## Variante A: Docker oder Podman Compose" in installation
    assert "## Variante B: native Python-Installation" in installation
    assert "docker compose --profile local-surface up" in installation
    assert "podman compose --profile local-surface up" in installation
    assert "foliotone surface-api" in installation
    assert "[zentralen Installationsanleitung](INSTALLATION.md)" in quickstart
    assert "[Installationsanleitung](INSTALLATION.md)" in handbook
    assert "python -m pip install ." not in quickstart
    assert "python -m pip install ." not in handbook
    for path in USER_GUIDE_PATHS:
        relative = path.removeprefix("docs/")
        assert relative in documentation_index
    assert "docs/user-guide/SCHNELLSTART.md" in root_readme
    assert "docs/user-guide/BENUTZERHANDBUCH.md" in root_readme


def test_ebook_user_guide_screenshots_are_linked_jpegs_with_synthetic_context() -> None:
    guide = "\n".join(
        (ROOT / path).read_text(encoding="utf-8") for path in USER_GUIDE_PATHS
    )
    assert "eigens erzeugten synthetischen" in guide
    assert "Bilder enthalten keine privaten Dateinamen" in guide
    for path in USER_GUIDE_IMAGES:
        image = ROOT / path
        payload = image.read_bytes()
        assert payload.startswith(b"\xff\xd8\xff")
        assert payload.endswith(b"\xff\xd9")
        assert len(payload) >= 20_000
        assert guide.count(f"images/{image.name}") == 1


def test_agents_routes_documentation_changes_to_canonical_policies() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/quality/DOCUMENTATION_STYLE.md" in agents
    assert "docs/quality/LANGUAGE_AND_TERMINOLOGY.md" in agents
    assert "docs/reference/GLOSSARY.md" in agents
    assert "protected" in agents.lower() or "geschützt" in agents.lower()


def test_foundation_baseline_is_discoverable_and_versioned() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    ruleset = (ROOT / ".ai/foundation/FOUNDATION_RULESET.md").read_text(
        encoding="utf-8"
    )

    assert agents.count("<!-- AI_REPOSITORY_FOUNDATION:BEGIN v1 -->") == 1
    assert agents.count("<!-- AI_REPOSITORY_FOUNDATION:END -->") == 1
    assert ".ai/foundation/FOUNDATION_RULESET.md" in agents
    assert ".ai/foundation/SEMANTIC_INTEGRATION_POLICY.md" in agents
    assert "docs/planning/ARTIFACT_REGISTRATION.md" in agents
    assert "Ruleset version: 1.4.0" in ruleset
    assert "PERSISTENT_IDENTITY_POLICY.md" in ruleset
    assert "ARTIFACT_REGISTRATION_POLICY.md" in ruleset


def test_documentation_index_links_the_registered_identity_decision() -> None:
    documentation_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    decision_path = ROOT / "docs/decisions/ADR-0070-foundation-v14-identity-registration.md"

    assert decision_path.is_file()
    assert (
        "[ADR-0070](decisions/ADR-0070-foundation-v14-identity-registration.md)"
        in documentation_index
    )


def test_artifact_registration_authority_is_discoverable_and_consistent() -> None:
    registration = (ROOT / "docs/planning/ARTIFACT_REGISTRATION.md").read_text(
        encoding="utf-8"
    )
    registry = json.loads(
        (ROOT / "docs/planning/artifact_registry.json").read_text(encoding="utf-8")
    )
    artifacts = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "docs/planning/artifacts").glob("*.json")
    }

    assert "ADOPT_FORWARD" in registration
    assert "DEFERRED" in registration
    assert registry["profile"] == "foundation-artifact-registry/v1"
    assert registry["registry_revision"] == 7
    assert registry["allocations"] == {
        artifact["human_ref"]: artifact["artifact_uid"]
        for artifact in artifacts.values()
    }
    assert all(
        artifact["registration_state"] == "REGISTERED"
        for artifact in artifacts.values()
    )
    assert artifacts["WI-0001"]["metadata"]["wave"] == "W0"
    assert artifacts["WI-0001"]["metadata"]["tier"] == "FRONTIER"
    assert artifacts["WI-0001"]["relations"] == [
        {"type": "governed_by", "target": "ADR-0070"}
    ]
    assert artifacts["DEC-0001"]["status"] == "ACCEPTED"
    assert artifacts["WI-0003"]["status"] == "BLOCKED"
    assert artifacts["GATE-0001"]["status"] == "PLANNED"
    assert artifacts["WI-0004"]["status"] == "BLOCKED"


def test_foundation_attribution_is_complete_and_namespaced() -> None:
    notice = (
        ROOT / ".ai/foundation/AI_REPOSITORY_FOUNDATION_NOTICE.md"
    ).read_text(encoding="utf-8")

    assert "Copyright (c) 2026 Gerhard P" in notice
    assert "Permission is hereby granted, free of charge" in notice
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in notice
    assert (
        "This notice applies only to material transferred from the "
        "AI Repository Foundation"
    ) in notice


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


def test_wave_workflow_requires_a_two_parent_merge_commit() -> None:
    workflow = (ROOT / "docs/planning/AI_WORKFLOW.md").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Merge-Commit mit genau zwei Eltern" in workflow
    assert "Squash- und Rebase-Merges sind" in workflow
    assert 'test "$parent_count" -eq 2' in ci


def test_calibre_capture_status_is_closed_consistently() -> None:
    backlog = (ROOT / "docs/planning/BACKLOG.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/planning/PROJECT_STATUS.md").read_text(encoding="utf-8")

    assert "| S-EB07-11B2B | DONE |" in backlog
    assert "Capture-Orchestrierung bleibt offen" not in status
    assert "Capture-Orchestrierung gegen eine konfigurierte Calibre-Bibliothek bleibt" not in status
    assert "Calibre-Capture-Schiene aus ADR-0033 ist damit" in status
