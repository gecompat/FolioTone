from __future__ import annotations

import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from foliotone.cli import main as cli_main
from foliotone.tooling.ebook_readiness import (
    EbookToolchainReadinessReport,
    VersionCommandResult,
    inspect_ebook_toolchain,
)


def _resolver(executable: str) -> str | None:
    if executable == "missing":
        return None
    return executable


def _ready_runner(argv: tuple[str, ...]) -> VersionCommandResult:
    executable = Path(argv[0]).name
    if executable == "java" and "-jar" in argv:
        return VersionCommandResult(0, "EPUBCheck v5.3.0\n", "")
    outputs = {
        "ebook-meta": "ebook-meta (calibre 9.13.0)\n",
        "ebook-convert": "ebook-convert (calibre 9.13.0)\n",
        "calibre-debug": "calibre-debug (calibre 9.13.0)\n",
        "pdfinfo": "pdfinfo version 26.07.0\n",
        "pdftotext": "pdftotext version 26.07.0\n",
        "java": 'openjdk version "21.0.12" 2026-07-21 LTS\n',
    }
    return VersionCommandResult(0, outputs[executable], "")


def test_doctor_reports_every_supported_format_ready(tmp_path: Path) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")

    report = inspect_ebook_toolchain(
        epubcheck_jar=jar,
        provisioned_profile="ebook-toolchain-linux-amd64/v1",
        runner=_ready_runner,
        resolver=_resolver,
    )

    assert report.ready
    assert [tool.status for tool in report.tools] == ["READY"] * 7
    assert [item.format for item in report.formats] == ["EPUB", "MOBI", "AZW", "AZW3", "PDF"]
    assert all(item.ready for item in report.formats)
    assert report.as_dict()["status"] == "READY"


def test_missing_poppler_blocks_only_pdf(tmp_path: Path) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")

    report = inspect_ebook_toolchain(
        pdfinfo_executable="missing",
        pdftotext_executable="missing",
        epubcheck_jar=jar,
        runner=_ready_runner,
        resolver=_resolver,
    )

    assert not report.ready
    by_format = {item.format: item for item in report.formats}
    assert all(by_format[name].ready for name in ("EPUB", "MOBI", "AZW", "AZW3"))
    assert by_format["PDF"].status == "NOT_READY"
    assert by_format["PDF"].unavailable_tools == ("pdfinfo", "pdftotext")


def test_incompatible_calibre_is_reported_before_format_readiness(tmp_path: Path) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")

    def old_calibre(argv: tuple[str, ...]) -> VersionCommandResult:
        if Path(argv[0]).name.startswith(("ebook-", "calibre-")):
            return VersionCommandResult(0, "calibre 9.9.0\n", "")
        return _ready_runner(argv)

    report = inspect_ebook_toolchain(
        epubcheck_jar=jar,
        runner=old_calibre,
        resolver=_resolver,
    )

    by_tool = {tool.tool: tool for tool in report.tools}
    assert by_tool["ebook-meta"].status == "INCOMPATIBLE"
    assert by_tool["ebook-meta"].reason is not None
    assert "9.10.0" in by_tool["ebook-meta"].reason
    assert next(item for item in report.formats if item.format == "PDF").ready
    assert not next(item for item in report.formats if item.format == "EPUB").ready


def test_doctor_json_is_path_free_and_uses_nonzero_not_ready_exit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")
    report = inspect_ebook_toolchain(
        pdfinfo_executable="missing",
        pdftotext_executable="missing",
        epubcheck_jar=jar,
        runner=_ready_runner,
        resolver=_resolver,
    )
    monkeypatch.setattr(cli_main, "inspect_ebook_toolchain", lambda **_kwargs: report)

    result = cli_main.main(["ebook-tools-doctor", "--json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "ebook-toolchain-doctor/v1"
    assert payload["status"] == "NOT_READY"
    assert str(tmp_path) not in json.dumps(payload)


def test_doctor_text_output_explains_explicit_provisioning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")
    report: EbookToolchainReadinessReport = inspect_ebook_toolchain(
        epubcheck_jar=jar,
        runner=_ready_runner,
        resolver=_resolver,
    )
    monkeypatch.setattr(cli_main, "inspect_ebook_toolchain", lambda **_kwargs: report)

    assert cli_main.main(["ebook-tools-doctor"]) == 0

    output = capsys.readouterr().out
    assert "E-book toolchain: READY" in output
    assert "EPUB" in output
    assert "PDF" in output
    assert "analysis commands never install or update tools" in output


def test_failed_version_probe_does_not_project_executable_or_output_paths(tmp_path: Path) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")

    def leaking_runner(argv: tuple[str, ...]) -> VersionCommandResult:
        if Path(argv[0]).name == "pdfinfo":
            raise OSError(f"could not execute {argv[0]}")
        return _ready_runner(argv)

    report = inspect_ebook_toolchain(
        pdfinfo_executable=str(tmp_path / "private" / "pdfinfo"),
        epubcheck_jar=jar,
        runner=leaking_runner,
        resolver=_resolver,
    )

    serialized = json.dumps(report.as_dict())
    assert str(tmp_path) not in serialized
    assert next(tool for tool in report.tools if tool.tool == "pdfinfo").reason == (
        "version command could not be completed"
    )


def test_unknown_provisioned_profile_is_not_projected(tmp_path: Path) -> None:
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"synthetic")

    report = inspect_ebook_toolchain(
        epubcheck_jar=jar,
        provisioned_profile=str(tmp_path / "private-profile"),
        runner=_ready_runner,
        resolver=_resolver,
    )

    assert report.provisioned_profile == "UNMANAGED_LOCAL"
