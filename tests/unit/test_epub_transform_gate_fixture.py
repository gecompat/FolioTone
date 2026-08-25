from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType

FIXTURE_ROOT = Path("tests/fixtures/ebook_transform/gate-0001")
GENERATOR = FIXTURE_ROOT / "generate_fixture.py"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_0001_fixture", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_fixture_is_byte_stable_and_matches_manifest(tmp_path: Path) -> None:
    generator = _load_generator()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    first = generator.generate_fixture(tmp_path / "first")
    second = generator.generate_fixture(tmp_path / "second")

    assert first == second
    assert first == {
        key: manifest[key]
        for key in (
            "profile",
            "source_sha256",
            "source_size_bytes",
            "reviewed_metadata_sha256",
            "reviewed_metadata_size_bytes",
        )
    }
    assert (tmp_path / "first/source.epub").read_bytes() == (
        tmp_path / "second/source.epub"
    ).read_bytes()


def test_gate_fixture_contains_the_required_semantic_oracles(tmp_path: Path) -> None:
    generator = _load_generator()
    generator.generate_fixture(tmp_path)

    with zipfile.ZipFile(tmp_path / "source.epub") as archive:
        assert archive.namelist() == [name for name, _content in generator.ENTRIES]
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        package = archive.read("EPUB/package.opf")
        assert b"Synthetische Reihe" in package
        assert b'property="group-position"' in package
        assert b'properties="cover-image"' in package
        assert b'<itemref idref="chapter"/>' in package
        assert archive.read("EPUB/chapter.xhtml") == generator.CHAPTER
        assert archive.read("EPUB/cover.png") == generator.COVER


def test_gate_fixture_readme_forbids_committed_outputs_and_authority() -> None:
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "nicht eingecheckt" in readme
    assert "keine Writer- oder W10-Autorisierung" in readme
