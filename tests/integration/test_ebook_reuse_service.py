import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import Engine

from foliotone.adapters.calibre.cover import (
    CALIBRE_COVER_ARTIFACT,
    CALIBRE_COVER_CONFIG_IDENTITY,
    CALIBRE_COVER_PROVIDER,
    CALIBRE_COVER_RESULT_ARTIFACT,
    CALIBRE_COVER_RESULT_TYPE,
    MAX_COVER_RESULT_BYTES,
)
from foliotone.adapters.calibre.metadata import (
    CALIBRE_CONFIG_IDENTITY,
    CALIBRE_OPF_ARTIFACT,
    CALIBRE_PROVIDER,
    MAX_OPF_BYTES,
    project_calibre_opf,
)
from foliotone.adapters.calibre.text import (
    CALIBRE_TEXT_ARTIFACT,
    CALIBRE_TEXT_CONFIG_IDENTITY,
    CALIBRE_TEXT_PROVIDER,
    MAX_TEXT_BYTES,
    normalize_ebook_text,
)
from foliotone.adapters.epubcheck.validation import (
    EPUBCHECK_CONFIG_IDENTITY,
    EPUBCHECK_PROVIDER,
    EPUBCHECK_REPORT_ARTIFACT,
    MAX_EPUBCHECK_REPORT_BYTES,
    parse_epubcheck_report,
)
from foliotone.adapters.poppler.pdf import (
    MAX_PDF_TEXT_BYTES,
    MAX_PDFINFO_BYTES,
    POPPLER_INFO_CONFIG_IDENTITY,
    POPPLER_INFO_PROVIDER,
    POPPLER_TEXT_ARTIFACT,
    POPPLER_TEXT_CONFIG_IDENTITY,
    POPPLER_TEXT_PROVIDER,
    parse_pdfinfo_output,
)
from foliotone.analyzers.ebook import (
    build_cover_fingerprint,
    build_normalized_text_fingerprint,
    fingerprint_ebook_cover,
)
from foliotone.analyzers.ebook import (
    normalize_ebook_text as normalize_shared_ebook_text,
)
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import (
    ToolArtifact,
    ToolArtifactRequirement,
    ToolExecution,
    ToolProviderDescriptor,
    ToolResult,
    ToolReuseRequest,
)
from foliotone.tooling.runtime import ToolRuntime
from foliotone.workflows import EbookAnalysisReuseService

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
SAMPLE_OPF = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">
  <metadata>
    <dc:title>Synthetic Reuse</dc:title>
    <dc:creator>Ada Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
</package>
"""


def test_metadata_and_text_are_rebuilt_from_exact_private_artifacts(tmp_path: Path) -> None:
    engine, artifact_root, runtime, service = _environment(tmp_path)
    observation = _observation("books/example.epub")

    metadata_execution = _execution(
        CALIBRE_PROVIDER,
        ToolCapability.READ_METADATA,
        "ebook-meta (calibre 9.13.0)",
        CALIBRE_CONFIG_IDENTITY,
        observation,
    )
    metadata_request = _persist_run(
        engine,
        artifact_root,
        metadata_execution,
        CALIBRE_PROVIDER,
        CALIBRE_CONFIG_IDENTITY,
        CALIBRE_OPF_ARTIFACT,
        SAMPLE_OPF,
        MAX_OPF_BYTES,
    )
    projection = project_calibre_opf(
        SAMPLE_OPF,
        execution_id=metadata_execution.id,
        observation_id=observation.id,
    )
    _save_results(engine, projection.all_results)

    text_data = b"  Synthetic\r\nreuse text  "
    text_execution = _execution(
        CALIBRE_TEXT_PROVIDER,
        ToolCapability.EXTRACT_TEXT,
        "ebook-convert.exe (calibre 9.13.0)",
        CALIBRE_TEXT_CONFIG_IDENTITY,
        observation,
    )
    text_request = _persist_run(
        engine,
        artifact_root,
        text_execution,
        CALIBRE_TEXT_PROVIDER,
        CALIBRE_TEXT_CONFIG_IDENTITY,
        CALIBRE_TEXT_ARTIFACT,
        text_data,
        MAX_TEXT_BYTES,
    )
    normalized = normalize_ebook_text(text_data)
    text_results = _text_results(
        text_execution,
        observation,
        "calibre_text_analysis",
        normalized.character_count,
        bool(normalized.text),
    )
    fingerprint = build_normalized_text_fingerprint(
        normalized,
        observation,
        text_execution,
    )
    _save_results(engine, text_results)
    assert fingerprint is not None
    repository(engine, Fingerprint).save(fingerprint)

    metadata = service.metadata(metadata_request, observation)
    text = service.text(text_request, observation)

    assert metadata is not None
    assert metadata.run.execution.id == metadata_execution.id
    assert set(metadata.results) == set(projection.observations)
    assert set(metadata.candidates) == set(projection.candidates)
    assert text is not None
    assert text.run.execution.id == text_execution.id
    assert text.fingerprint == fingerprint

    repository(engine, ToolResult).save(
        ToolResult(
            id=EntityId.new(),
            execution_id=metadata_execution.id,
            result_type="unexpected",
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            key="unexpected",
            value="must invalidate reuse",
        )
    )
    assert service.metadata(metadata_request, observation) is None
    runtime.verify_artifact(
        _artifacts(engine, metadata_execution.id)[0],
        max_bytes=MAX_OPF_BYTES,
    )


def test_cover_and_epubcheck_reuse_reproduce_derived_evidence(tmp_path: Path) -> None:
    engine, artifact_root, _runtime, service = _environment(tmp_path)
    observation = _observation("books/example.epub")
    cover = _png()
    cover_execution = _execution(
        CALIBRE_COVER_PROVIDER,
        ToolCapability.FINGERPRINT,
        "calibre-debug.exe (calibre 9.13.0)",
        CALIBRE_COVER_CONFIG_IDENTITY,
        observation,
    )
    repository(engine, ToolExecution).save(cover_execution)
    _save_artifact(
        engine,
        artifact_root,
        cover_execution.id,
        CALIBRE_COVER_RESULT_ARTIFACT,
        json.dumps(
            {
                "cover_bytes": len(cover),
                "source_sha256": "a" * 64,
                "status": "COVER_EXTRACTED",
            }
        ).encode(),
    )
    _save_artifact(
        engine,
        artifact_root,
        cover_execution.id,
        CALIBRE_COVER_ARTIFACT,
        cover,
    )
    cover_request = ToolReuseRequest(
        descriptor=CALIBRE_COVER_PROVIDER,
        capability=ToolCapability.FINGERPRINT,
        tool_version=cover_execution.tool_version,
        input_identity=cover_execution.input_identity,
        config_identity=CALIBRE_COVER_CONFIG_IDENTITY,
        required_artifacts=(
            ToolArtifactRequirement(
                CALIBRE_COVER_RESULT_ARTIFACT,
                MAX_COVER_RESULT_BYTES,
            ),
        ),
    )
    normalized_cover = fingerprint_ebook_cover(cover)
    cover_results = tuple(
        _result(cover_execution, observation, CALIBRE_COVER_RESULT_TYPE, key, value)
        for key, value in (
            ("cover_status", "COVER_EXTRACTED"),
            ("image_format", normalized_cover.image_format),
            ("display_width", str(normalized_cover.width)),
            ("display_height", str(normalized_cover.height)),
        )
    )
    cover_fingerprint = build_cover_fingerprint(
        normalized_cover,
        observation,
        cover_execution,
    )
    _save_results(engine, cover_results)
    repository(engine, Fingerprint).save(cover_fingerprint)

    report = {
        "messages": [{"ID": "OPF-001", "severity": "WARNING"}],
        "checker": {
            "filename": "example.epub",
            "checkerVersion": "5.3.0",
            "nFatal": 0,
            "nError": 0,
            "nWarning": 1,
            "nUsage": 0,
        },
    }
    report_data = json.dumps(report).encode()
    validation_execution = _execution(
        EPUBCHECK_PROVIDER,
        ToolCapability.STRUCTURAL_VALIDATION,
        "EPUBCheck v5.3.0",
        EPUBCHECK_CONFIG_IDENTITY,
        observation,
    )
    validation_request = _persist_run(
        engine,
        artifact_root,
        validation_execution,
        EPUBCHECK_PROVIDER,
        EPUBCHECK_CONFIG_IDENTITY,
        EPUBCHECK_REPORT_ARTIFACT,
        report_data,
        MAX_EPUBCHECK_REPORT_BYTES,
    )
    validation_results = parse_epubcheck_report(
        report,
        execution_id=validation_execution.id,
        observation_id=observation.id,
        expected_filename="example.epub",
        expected_tool_version=validation_execution.tool_version,
    )
    _save_results(engine, validation_results)

    cover_outcome = service.cover(cover_request, observation)
    validation_outcome = service.validation(validation_request, observation)

    assert cover_outcome is not None
    assert cover_outcome.fingerprint == cover_fingerprint
    assert validation_outcome is not None
    assert validation_outcome.conformance_status == "CONFORMANT"


def test_pdf_pair_is_atomic_and_reuses_only_when_both_parts_match(tmp_path: Path) -> None:
    engine, artifact_root, _runtime, service = _environment(tmp_path)
    observation = _observation("books/example.pdf", size_bytes=123)
    info_data = b"Pages: 2\nFile size: 123 bytes\nEncrypted: no\nPDF version: 1.7\n"
    info_execution = _execution(
        POPPLER_INFO_PROVIDER,
        ToolCapability.TECHNICAL_METADATA,
        "pdfinfo version 26.07.0",
        POPPLER_INFO_CONFIG_IDENTITY,
        observation,
    )
    info_request = _persist_run(
        engine,
        artifact_root,
        info_execution,
        POPPLER_INFO_PROVIDER,
        POPPLER_INFO_CONFIG_IDENTITY,
        "STDOUT",
        info_data,
        MAX_PDFINFO_BYTES,
    )
    metadata = parse_pdfinfo_output(
        info_data,
        execution_id=info_execution.id,
        observation_id=observation.id,
    )
    _save_results(engine, metadata)

    text_data = b"Synthetic PDF text"
    text_execution = _execution(
        POPPLER_TEXT_PROVIDER,
        ToolCapability.EXTRACT_TEXT,
        "pdftotext version 26.07.0",
        POPPLER_TEXT_CONFIG_IDENTITY,
        observation,
    )
    text_request = _persist_run(
        engine,
        artifact_root,
        text_execution,
        POPPLER_TEXT_PROVIDER,
        POPPLER_TEXT_CONFIG_IDENTITY,
        POPPLER_TEXT_ARTIFACT,
        text_data,
        MAX_PDF_TEXT_BYTES,
    )
    normalized = normalize_shared_ebook_text(text_data, max_bytes=MAX_PDF_TEXT_BYTES)
    text_results = _text_results(
        text_execution,
        observation,
        "poppler_pdf_text_analysis",
        normalized.character_count,
        bool(normalized.text),
    )
    fingerprint = build_normalized_text_fingerprint(
        normalized,
        observation,
        text_execution,
    )
    _save_results(engine, text_results)
    assert fingerprint is not None
    repository(engine, Fingerprint).save(fingerprint)

    outcome = service.pdf((info_request, text_request), observation)

    assert outcome is not None
    assert outcome.info_run.execution.id == info_execution.id
    assert outcome.text_run.execution.id == text_execution.id
    assert outcome.fingerprint == fingerprint

    text_artifact = _artifacts(engine, text_execution.id)[0]
    (artifact_root / text_artifact.relative_path).write_bytes(b"tampered")
    assert service.pdf((info_request, text_request), observation) is None


def _environment(
    tmp_path: Path,
) -> tuple[Engine, Path, ToolRuntime, EbookAnalysisReuseService]:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    artifact_root = tmp_path / "artifacts"
    runtime = ToolRuntime(engine, artifact_root, work_root=tmp_path / "work")
    return engine, artifact_root, runtime, EbookAnalysisReuseService(engine, runtime)


def _observation(relative_path: str, *, size_bytes: int = 123) -> FileObservation:
    return FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=size_bytes,
        modified_at=NOW,
        observed_at=NOW,
    )


def _execution(
    descriptor: ToolProviderDescriptor,
    capability: ToolCapability,
    tool_version: str,
    config_identity: str,
    observation: FileObservation,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id=descriptor.provider_id,
        tool_version=tool_version,
        adapter_version=descriptor.adapter_version,
        capability=capability,
        input_identity=f"file-observation:{observation.id}",
        config_identity=config_identity,
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )


def _persist_run(
    engine: Engine,
    artifact_root: Path,
    execution: ToolExecution,
    descriptor: ToolProviderDescriptor,
    config_identity: str,
    artifact_type: str,
    data: bytes,
    max_bytes: int,
) -> ToolReuseRequest:
    repository(engine, ToolExecution).save(execution)
    _save_artifact(engine, artifact_root, execution.id, artifact_type, data)
    return ToolReuseRequest(
        descriptor=descriptor,
        capability=execution.capability,
        tool_version=execution.tool_version,
        input_identity=execution.input_identity,
        config_identity=config_identity,
        required_artifacts=(ToolArtifactRequirement(artifact_type, max_bytes),),
    )


def _save_artifact(
    engine: Engine,
    artifact_root: Path,
    execution_id: EntityId,
    artifact_type: str,
    data: bytes,
) -> ToolArtifact:
    filename = f"{artifact_type.lower()}.bin"
    path = artifact_root / str(execution_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    artifact = ToolArtifact(
        id=EntityId.new(),
        execution_id=execution_id,
        artifact_type=artifact_type,
        relative_path=path.relative_to(artifact_root).as_posix(),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    repository(engine, ToolArtifact).save(artifact)
    return artifact


def _save_results(engine: Engine, results: tuple[ToolResult, ...]) -> None:
    for result in results:
        repository(engine, ToolResult).save(result)


def _text_results(
    execution: ToolExecution,
    observation: FileObservation,
    result_type: str,
    character_count: int,
    has_text: bool,
) -> tuple[ToolResult, ...]:
    return (
        _result(
            execution,
            observation,
            result_type,
            "text_status",
            "TEXT_EXTRACTED" if has_text else "NO_TEXT",
        ),
        _result(
            execution,
            observation,
            result_type,
            "normalized_character_count",
            str(character_count),
        ),
    )


def _result(
    execution: ToolExecution,
    observation: FileObservation,
    result_type: str,
    key: str,
    value: str,
) -> ToolResult:
    return ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type=result_type,
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        key=key,
        value=value,
    )


def _artifacts(engine: Engine, execution_id: EntityId) -> list[ToolArtifact]:
    return [
        artifact
        for artifact in repository(engine, ToolArtifact).list_all()
        if artifact.execution_id == execution_id
    ]


def _png() -> bytes:
    image = Image.new("RGB", (9, 8), color="white")
    for x in range(9):
        for y in range(8):
            value = 255 - x * 20
            image.putpixel((x, y), (value, value, value))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
