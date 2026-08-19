import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from foliotone.adapters.calibre.cover import (
    CALIBRE_COVER_ARTIFACT,
    CALIBRE_COVER_CONFIG_IDENTITY,
    CALIBRE_COVER_FORMATS,
    CALIBRE_COVER_PROVIDER,
    CALIBRE_COVER_RESULT_ARTIFACT,
    CALIBRE_COVER_SUFFIXES,
    MAX_COVER_BYTES,
    MAX_COVER_RESULT_BYTES,
    CalibreCoverAnalyzer,
    CalibreCoverError,
)
from foliotone.analyzers.ebook import (
    COVER_FINGERPRINT_KIND,
    COVER_FINGERPRINT_PROFILE,
    EbookCoverError,
    fingerprint_ebook_cover,
)
from foliotone.core import (
    EntityId,
    FileObservation,
    Fingerprint,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import ToolArtifact, ToolExecution, ToolProviderDescriptor, ToolResult
from foliotone.tooling.runtime import LocalCommand, ToolRunOutcome

pytestmark = pytest.mark.usefixtures("head_database")

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


def test_cover_fingerprint_is_versioned_deterministic_and_bounded() -> None:
    data = _descending_png()

    normalized = fingerprint_ebook_cover(data)

    assert normalized.image_format == "PNG"
    assert normalized.width == 9
    assert normalized.height == 8
    assert normalized.value == "ffffffffffffffff"
    assert COVER_FINGERPRINT_PROFILE.startswith(
        "horizontal-luma-9x8-lanczos-v1+pillow-"
    )


def test_cover_fingerprint_rejects_invalid_and_excessive_images() -> None:
    with pytest.raises(EbookCoverError, match="supported safe raster"):
        fingerprint_ebook_cover(b"not an image")

    with pytest.raises(EbookCoverError, match="pixel limit"):
        fingerprint_ebook_cover(_descending_png(), max_pixels=10)

    with pytest.raises(EbookCoverError, match="size limit"):
        fingerprint_ebook_cover(_descending_png(), max_bytes=1)


class RecordingRuntime:
    def __init__(
        self,
        execution: ToolExecution,
        *,
        source_sha256: str,
        status: str,
        cover: bytes | None,
        cover_bytes: int | None = None,
    ) -> None:
        self.descriptor: ToolProviderDescriptor | None = None
        self.command: LocalCommand | None = None
        self.input_identity: str | None = None
        self.config_identity: str | None = None
        self.json_reads = 0
        self.cover_reads = 0
        self.cover = cover
        self.payload = {
            "cover_bytes": len(cover) if cover_bytes is None and cover is not None else (
                cover_bytes or 0
            ),
            "source_sha256": source_sha256,
            "status": status,
        }
        result_data = json.dumps(self.payload).encode()
        artifacts = [
            ToolArtifact(
                id=EntityId.new(),
                execution_id=execution.id,
                artifact_type=CALIBRE_COVER_RESULT_ARTIFACT,
                relative_path="synthetic/cover-result.json",
                size_bytes=len(result_data),
                sha256=hashlib.sha256(result_data).hexdigest(),
            )
        ]
        if cover is not None:
            artifacts.append(
                ToolArtifact(
                    id=EntityId.new(),
                    execution_id=execution.id,
                    artifact_type=CALIBRE_COVER_ARTIFACT,
                    relative_path="synthetic/cover.bin",
                    size_bytes=len(cover),
                    sha256=hashlib.sha256(cover).hexdigest(),
                )
            )
        self.outcome = ToolRunOutcome(execution, tuple(artifacts), "", "")

    def execute_local(
        self,
        descriptor: ToolProviderDescriptor,
        command: LocalCommand,
        *,
        input_identity: str,
        config_identity: str | None = None,
    ) -> ToolRunOutcome:
        self.descriptor = descriptor
        self.command = command
        self.input_identity = input_identity
        self.config_identity = config_identity
        return self.outcome

    def read_json_artifact(self, artifact: ToolArtifact, *, max_bytes: int) -> object:
        self.json_reads += 1
        assert artifact.artifact_type == CALIBRE_COVER_RESULT_ARTIFACT
        assert max_bytes == MAX_COVER_RESULT_BYTES
        return self.payload

    def read_artifact_bytes(self, artifact: ToolArtifact, *, max_bytes: int) -> bytes:
        self.cover_reads += 1
        assert artifact.artifact_type == CALIBRE_COVER_ARTIFACT
        assert max_bytes == MAX_COVER_BYTES
        assert self.cover is not None
        return self.cover


@pytest.mark.parametrize(
    "relative_path",
    (
        "books/example.epub",
        "books/example.mobi",
        "books/example.azw",
        "books/example.azw3",
    ),
)
def test_analyzer_uses_fixed_command_and_persists_cover_evidence(
    tmp_path: Path,
    relative_path: str,
) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path=relative_path,
    )
    execution = _successful_execution(observation)
    repository(engine, ToolExecution).save(execution)
    cover = _descending_png()
    runtime = RecordingRuntime(
        execution,
        source_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
        status="COVER_EXTRACTED",
        cover=cover,
    )

    outcome = CalibreCoverAnalyzer(
        engine,
        runtime,  # type: ignore[arg-type]
        executable="calibre-debug-test",
    ).analyze(source_root, observation)

    assert runtime.descriptor == CALIBRE_COVER_PROVIDER
    assert CALIBRE_COVER_PROVIDER.adapter_version == "calibre-debug-cover/1"
    assert CALIBRE_COVER_FORMATS == ("EPUB", "MOBI", "AZW", "AZW3")
    assert CALIBRE_COVER_SUFFIXES == frozenset(
        {".epub", ".mobi", ".azw", ".azw3"}
    )
    assert runtime.command is not None
    assert runtime.command.executable == "calibre-debug-test"
    assert runtime.command.args[0] == "-e"
    assert runtime.command.args[1].endswith("extract_cover.py")
    assert runtime.command.args[2:] == (
        "--",
        str(source_file.resolve()),
        "cover.bin",
        "cover-result.json",
        str(observation.size_bytes),
        str(MAX_COVER_BYTES),
    )
    assert runtime.command.capability is ToolCapability.FINGERPRINT
    assert runtime.command.timeout_seconds == 120.0
    assert runtime.command.environment == {"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"}
    assert runtime.command.workspace_environment == {
        "CALIBRE_CONFIG_DIRECTORY": "calibre-config"
    }
    assert runtime.command.outputs[0].required is True
    assert runtime.command.outputs[1].required is False
    assert runtime.input_identity == f"file-observation:{observation.id}"
    assert runtime.config_identity == CALIBRE_COVER_CONFIG_IDENTITY
    assert runtime.json_reads == 1
    assert runtime.cover_reads == 1

    assert {(result.key, result.value) for result in outcome.results} == {
        ("cover_status", "COVER_EXTRACTED"),
        ("image_format", "PNG"),
        ("display_width", "9"),
        ("display_height", "8"),
    }
    assert set(outcome.results) == set(repository(engine, ToolResult).list_all())
    assert outcome.fingerprint is not None
    assert repository(engine, Fingerprint).list_all() == [outcome.fingerprint]
    assert outcome.fingerprint.target_id == observation.id
    assert outcome.fingerprint.kind == COVER_FINGERPRINT_KIND
    assert outcome.fingerprint.algorithm == "dhash-64"
    assert outcome.fingerprint.algorithm_version == COVER_FINGERPRINT_PROFILE
    assert outcome.fingerprint.value == "ffffffffffffffff"
    assert outcome.fingerprint.tool_execution_id == execution.id
    assert outcome.fingerprint.created_at == NOW


def test_analyzer_records_no_embedded_cover_without_fingerprint(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _successful_execution(observation)
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(
        execution,
        source_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
        status="NO_EMBEDDED_COVER",
        cover=None,
    )

    outcome = CalibreCoverAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert [(result.key, result.value) for result in outcome.results] == [
        ("cover_status", "NO_EMBEDDED_COVER")
    ]
    assert outcome.fingerprint is None
    assert repository(engine, Fingerprint).list_all() == []
    assert runtime.cover_reads == 0


def test_analyzer_rejects_changed_source_before_invoking_calibre(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _successful_execution(observation)
    runtime = RecordingRuntime(
        execution,
        source_sha256="0" * 64,
        status="NO_EMBEDDED_COVER",
        cover=None,
    )
    source_file.write_bytes(b"changed after observation")

    analyzer = CalibreCoverAnalyzer(engine, runtime)  # type: ignore[arg-type]
    with pytest.raises(CalibreCoverError, match="changed"):
        analyzer.analyze(source_root, observation)
    assert runtime.command is None


def test_analyzer_rejects_source_digest_change_during_analysis(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(tmp_path)
    execution = _successful_execution(observation)
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(
        execution,
        source_sha256="0" * 64,
        status="NO_EMBEDDED_COVER",
        cover=None,
    )

    with pytest.raises(CalibreCoverError, match="changed during"):
        CalibreCoverAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert repository(engine, ToolResult).list_all() == []


@pytest.mark.parametrize("suffix", (".pdf", ".azw4", ".kfx"))
def test_analyzer_rejects_unsupported_format_before_invoking_calibre(
    tmp_path: Path,
    suffix: str,
) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, _source_file, observation = _synthetic_observation(
        tmp_path,
        relative_path=f"books/example{suffix}",
    )
    execution = _successful_execution(observation)
    runtime = RecordingRuntime(
        execution,
        source_sha256="0" * 64,
        status="NO_EMBEDDED_COVER",
        cover=None,
    )

    with pytest.raises(CalibreCoverError, match="only EPUB, MOBI, AZW, or AZW3"):
        CalibreCoverAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
            source_root,
            observation,
        )
    assert runtime.command is None


def test_failed_extraction_is_not_mislabeled_as_no_cover(tmp_path: Path) -> None:
    database = tmp_path / "foliotone.db"
    engine = create_sqlite_engine(database)
    source_root, source_file, observation = _synthetic_observation(tmp_path)
    execution = _execution(
        observation,
        status=ToolExecutionStatus.FAILED,
        exit_code=2,
        error_summary="exit code 2",
    )
    repository(engine, ToolExecution).save(execution)
    runtime = RecordingRuntime(
        execution,
        source_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
        status="NO_EMBEDDED_COVER",
        cover=None,
    )

    outcome = CalibreCoverAnalyzer(engine, runtime).analyze(  # type: ignore[arg-type]
        source_root,
        observation,
    )

    assert outcome.run.execution.status is ToolExecutionStatus.FAILED
    assert outcome.results == ()
    assert outcome.fingerprint is None
    assert runtime.json_reads == 0
    assert repository(engine, ToolResult).list_all() == []


def _descending_png() -> bytes:
    image = Image.new("L", (9, 8))
    image.putdata([255 - x * 20 for _y in range(8) for x in range(9)])
    stream = BytesIO()
    image.save(stream, format="PNG")
    image.close()
    return stream.getvalue()


def _synthetic_observation(
    tmp_path: Path,
    *,
    relative_path: str = "books/example.epub",
) -> tuple[Path, Path, FileObservation]:
    source_root = tmp_path / "media"
    source_file = source_root.joinpath(*relative_path.split("/"))
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"synthetic ebook")
    stat = source_file.stat()
    observation = FileObservation(
        id=EntityId.new(),
        file_id=EntityId.new(),
        scan_run_id=EntityId.new(),
        relative_path=relative_path,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        observed_at=NOW,
    )
    return source_root, source_file, observation


def _successful_execution(observation: FileObservation) -> ToolExecution:
    return _execution(
        observation,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )


def _execution(
    observation: FileObservation,
    *,
    status: ToolExecutionStatus,
    exit_code: int,
    error_summary: str | None = None,
) -> ToolExecution:
    return ToolExecution(
        id=EntityId.new(),
        provider_id="calibre",
        tool_version="calibre-debug.exe (calibre 9.13.0)",
        adapter_version="calibre-debug-cover/1",
        capability=ToolCapability.FINGERPRINT,
        input_identity=f"file-observation:{observation.id}",
        config_identity=CALIBRE_COVER_CONFIG_IDENTITY,
        started_at=NOW,
        finished_at=NOW,
        status=status,
        exit_code=exit_code,
        error_summary=error_summary,
    )
