from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGING_ROOT = REPOSITORY_ROOT / "packaging" / "ebook-tools"


def _load_prepare_module() -> ModuleType:
    module_path = PACKAGING_ROOT / "prepare_ebook_toolchain.py"
    spec = importlib.util.spec_from_file_location("prepare_ebook_toolchain", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_toolchain_lock_is_complete_and_content_addressed() -> None:
    payload = json.loads((PACKAGING_ROOT / "toolchain.lock.json").read_text(encoding="utf-8"))

    assert payload["profile"] == "ebook-toolchain-linux-amd64/v1"
    assert payload["platform"] == "linux/amd64"
    assert "@sha256:" in payload["base_image"]
    assert payload["debian_snapshot"] == "20260807T000000Z"
    assert [item["id"] for item in payload["components"]] == [
        "calibre",
        "poppler",
        "temurin-jre",
        "epubcheck",
    ]
    for component in payload["components"]:
        assert component["url"].startswith("https://")
        assert len(component["sha256"]) == 64
        assert component["size_bytes"] > 0
        assert component["license"]


def test_unpacker_rejects_archive_traversal_and_accepts_bounded_paths() -> None:
    module = _load_prepare_module()

    assert module._stripped_path("root/bin/tool", 1) == PurePosixPath("bin/tool")
    with pytest.raises(ValueError, match="escapes destination"):
        module._stripped_path("../escape", 0)
    with pytest.raises(ValueError, match="must be relative"):
        module._validate_link_target(PurePosixPath("bin/tool"), "/outside")


def test_windows_provisioning_is_explicit_and_supports_wsl_linux_docker() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "provision-ebook-tools.ps1").read_text(
        encoding="utf-8"
    )

    assert "Test-NativeLinuxDocker" in script
    assert "Test-WslLinuxDocker" in script
    assert "--platform linux/amd64" in script
    assert "ebook-tools-doctor" in script
    assert "--network none" in script
    for forbidden in ("winget ", "choco ", "Install-Package", "ebook-analyze"):
        assert forbidden not in script


def test_optional_compose_profile_keeps_sources_read_only() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert 'profiles: ["ebook-tools"]' in compose
    assert "packaging/ebook-tools/Dockerfile" in compose
    assert ':/media/ebooks:ro"' in compose
    assert "read_only: true" in compose
    assert "network_mode: none" in compose
    assert "!packaging/ebook-tools/**" in dockerignore


def test_image_recipe_runs_doctor_and_carries_license_material() -> None:
    recipe = (PACKAGING_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM --platform=linux/amd64" in recipe
    assert "foliotone ebook-tools-doctor" in recipe
    assert "THIRD_PARTY_NOTICES.md" in recipe
    assert "/usr/share/licenses/poppler/COPYING" in recipe
    assert ":latest" not in recipe
