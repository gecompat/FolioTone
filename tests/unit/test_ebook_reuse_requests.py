from datetime import UTC, datetime
from pathlib import Path

from foliotone.adapters.calibre.cover import (
    CALIBRE_COVER_RESULT_ARTIFACT,
    CalibreCoverAnalyzer,
)
from foliotone.adapters.calibre.metadata import CALIBRE_OPF_ARTIFACT, CalibreMetadataAnalyzer
from foliotone.adapters.calibre.text import CALIBRE_TEXT_ARTIFACT, CalibreTextAnalyzer
from foliotone.adapters.epubcheck.validation import (
    EPUBCHECK_REPORT_ARTIFACT,
    EpubCheckAnalyzer,
)
from foliotone.adapters.poppler.pdf import POPPLER_TEXT_ARTIFACT, PopplerPdfAnalyzer
from foliotone.core import EntityId, FileObservation
from foliotone.persistence import create_sqlite_engine, migrate
from foliotone.tooling import ToolProviderDescriptor
from foliotone.tooling.runtime import LocalCommand, LocalToolProbe

NOW = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


class ProbeRuntime:
    def __init__(self, versions: dict[str, str]) -> None:
        self.versions = versions
        self.calls: list[tuple[ToolProviderDescriptor, LocalCommand]] = []

    def probe_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
    ) -> LocalToolProbe:
        self.calls.append((descriptor, command))
        version = self.versions.get(command.executable)
        if version is None:
            return LocalToolProbe(None, "unavailable", "fixture executable unavailable")
        return LocalToolProbe(command.executable, version)


def test_all_adapters_expose_exact_versioned_reuse_requests(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    runtime = ProbeRuntime(
        {
            "ebook-meta-test": "ebook-meta (calibre 9.13.0)",
            "ebook-convert-test": "ebook-convert.exe (calibre 9.13.0)",
            "calibre-debug-test": "calibre-debug.exe (calibre 9.13.0)",
            "java-test": "EPUBCheck v5.3.0",
            "pdfinfo-test": "pdfinfo version 26.07.0",
            "pdftotext-test": "pdftotext version 26.07.0",
        }
    )
    observation = _observation("books/example.epub")
    metadata = CalibreMetadataAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="ebook-meta-test",
    ).reuse_request(observation)
    text = CalibreTextAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="ebook-convert-test",
    ).reuse_request(observation)
    cover = CalibreCoverAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="calibre-debug-test",
    ).reuse_request(observation)
    validation = EpubCheckAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        java_executable="java-test",
        epubcheck_jar=tmp_path / "epubcheck.jar",
    ).reuse_request(observation)
    pdf = PopplerPdfAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        pdfinfo_executable="pdfinfo-test",
        pdftotext_executable="pdftotext-test",
    ).reuse_requests(_observation("books/example.pdf"))

    assert metadata is not None
    assert text is not None
    assert cover is not None
    assert validation is not None
    assert pdf is not None
    assert metadata.required_artifacts[0].artifact_type == CALIBRE_OPF_ARTIFACT
    assert text.required_artifacts[0].artifact_type == CALIBRE_TEXT_ARTIFACT
    assert cover.required_artifacts[0].artifact_type == CALIBRE_COVER_RESULT_ARTIFACT
    assert validation.required_artifacts[0].artifact_type == EPUBCHECK_REPORT_ARTIFACT
    assert pdf[0].required_artifacts[0].artifact_type == "STDOUT"
    assert pdf[1].required_artifacts[0].artifact_type == POPPLER_TEXT_ARTIFACT
    assert all(
        request.input_identity == f"file-observation:{observation.id}"
        for request in (metadata, text, cover, validation)
    )
    assert runtime.calls[3][1].version_args == (
        "-jar",
        str((tmp_path / "epubcheck.jar").resolve()),
        "--version",
    )


def test_unavailable_tool_never_creates_reuse_request(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    migrate(database)
    engine = create_sqlite_engine(database)
    runtime = ProbeRuntime({})

    request = CalibreMetadataAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="missing-tool",
    ).reuse_request(_observation("books/example.epub"))

    assert request is None


def _observation(relative_path: str) -> FileObservation:
    return FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=123,
        modified_at=NOW,
        observed_at=NOW,
    )
