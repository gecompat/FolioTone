"""Conservative reconstruction of exact persisted e-book analyzer outcomes."""

from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy import Engine

from foliotone.adapters.calibre.cover import (
    CALIBRE_COVER_ARTIFACT,
    CALIBRE_COVER_RESULT_TYPE,
    MAX_COVER_BYTES,
    MAX_COVER_RESULT_BYTES,
    CalibreCoverOutcome,
    parse_calibre_cover_result,
)
from foliotone.adapters.calibre.metadata import (
    CALIBRE_METADATA_RESULT,
    MAX_OPF_BYTES,
    CalibreMetadataError,
    CalibreMetadataOutcome,
    project_calibre_opf,
)
from foliotone.adapters.calibre.text import (
    MAX_TEXT_BYTES,
    CalibreTextError,
    CalibreTextOutcome,
    normalize_ebook_text,
)
from foliotone.adapters.epubcheck.validation import (
    MAX_EPUBCHECK_REPORT_BYTES,
    EpubCheckError,
    EpubCheckOutcome,
    parse_epubcheck_report,
)
from foliotone.adapters.poppler.pdf import (
    MAX_PDF_TEXT_BYTES,
    MAX_PDFINFO_BYTES,
    PopplerPdfError,
    PopplerPdfOutcome,
    parse_pdfinfo_output,
)
from foliotone.analyzers.ebook import (
    COVER_FINGERPRINT_KIND,
    COVER_FINGERPRINT_PROFILE,
    EBOOK_METADATA_CANDIDATE_RESULT,
    EbookCoverError,
    EbookTextError,
    build_cover_fingerprint,
    build_normalized_text_fingerprint,
    fingerprint_ebook_cover,
)
from foliotone.analyzers.ebook import (
    normalize_ebook_text as normalize_shared_ebook_text,
)
from foliotone.core import EntityId, EntityKind, FileObservation
from foliotone.tooling import (
    ToolArtifact,
    ToolArtifactRequirement,
    ToolResult,
    ToolReuseRequest,
)
from foliotone.tooling.runtime import ToolRuntime
from foliotone.tooling.structured import StructuredOutputError
from foliotone.workflows.evidence import ToolEvidenceReader, ToolEvidenceSnapshot


class EbookAnalysisReuseService:
    """Rebuild typed outcomes only from exact, intact and internally consistent evidence."""

    def __init__(self, engine: Engine, runtime: ToolRuntime) -> None:
        self._runtime = runtime
        self._reader = ToolEvidenceReader(engine, runtime)

    def metadata(
        self,
        request: ToolReuseRequest | None,
        observation: FileObservation,
    ) -> CalibreMetadataOutcome | None:
        snapshot = self._snapshot(request, observation)
        if snapshot is None:
            return None
        try:
            data = self._read_artifact(snapshot, request, max_bytes=MAX_OPF_BYTES)
            expected = project_calibre_opf(
                data,
                execution_id=snapshot.run.execution.id,
                observation_id=observation.id,
            )
        except (CalibreMetadataError, StructuredOutputError):
            return None
        if not snapshot.matches_results(expected.all_results) or snapshot.fingerprints:
            return None
        observations = tuple(
            result
            for result in snapshot.results
            if result.result_type == CALIBRE_METADATA_RESULT
        )
        candidates = tuple(
            result
            for result in snapshot.results
            if result.result_type == EBOOK_METADATA_CANDIDATE_RESULT
        )
        if len(observations) + len(candidates) != len(snapshot.results):
            return None
        return CalibreMetadataOutcome(snapshot.run, observations, candidates)

    def text(
        self,
        request: ToolReuseRequest | None,
        observation: FileObservation,
    ) -> CalibreTextOutcome | None:
        snapshot = self._snapshot(request, observation)
        if snapshot is None:
            return None
        try:
            data = self._read_artifact(snapshot, request, max_bytes=MAX_TEXT_BYTES)
            normalized = normalize_ebook_text(data)
            expected_results = _text_results(
                snapshot.run.execution.id,
                observation.id,
                "calibre_text_analysis",
                normalized.character_count,
                bool(normalized.text),
            )
            fingerprint = build_normalized_text_fingerprint(
                normalized,
                observation,
                snapshot.run.execution,
            )
        except (CalibreTextError, EbookTextError, StructuredOutputError):
            return None
        expected_fingerprints = () if fingerprint is None else (fingerprint,)
        if not snapshot.matches_results(expected_results) or not snapshot.matches_fingerprints(
            expected_fingerprints
        ):
            return None
        persisted = snapshot.fingerprints[0] if snapshot.fingerprints else None
        return CalibreTextOutcome(snapshot.run, snapshot.results, persisted)

    def cover(
        self,
        request: ToolReuseRequest | None,
        observation: FileObservation,
    ) -> CalibreCoverOutcome | None:
        snapshot = self._snapshot(request, observation)
        if snapshot is None or any(
            result.result_type != CALIBRE_COVER_RESULT_TYPE
            for result in snapshot.results
        ):
            return None
        values = _unique_values(snapshot.results)
        status = values.get("cover_status")
        try:
            result_artifact = _single_required_artifact(snapshot, request)
            extraction = parse_calibre_cover_result(
                self._runtime.read_json_artifact(
                    result_artifact,
                    max_bytes=MAX_COVER_RESULT_BYTES,
                )
            )
        except (EbookCoverError, StructuredOutputError):
            return None
        if extraction.status != status:
            return None
        if status == "NO_EMBEDDED_COVER":
            if (
                set(values) != {"cover_status"}
                or snapshot.fingerprints
                or extraction.cover_bytes != 0
            ):
                return None
            if any(
                artifact.artifact_type == CALIBRE_COVER_ARTIFACT
                for artifact in snapshot.run.artifacts
            ):
                return None
            return CalibreCoverOutcome(snapshot.run, snapshot.results, None)
        if status != "COVER_EXTRACTED":
            return None
        requirement = ToolArtifactRequirement(CALIBRE_COVER_ARTIFACT, MAX_COVER_BYTES)
        if not self._reader.has_intact_artifact(snapshot, requirement):
            return None
        try:
            data = _artifact_bytes(
                self._runtime,
                snapshot,
                CALIBRE_COVER_ARTIFACT,
                MAX_COVER_BYTES,
            )
            if extraction.cover_bytes != len(data):
                return None
            normalized = fingerprint_ebook_cover(data, max_bytes=MAX_COVER_BYTES)
            expected_results = (
                _result(snapshot, observation, "cover_status", "COVER_EXTRACTED"),
                _result(snapshot, observation, "image_format", normalized.image_format),
                _result(snapshot, observation, "display_width", str(normalized.width)),
                _result(snapshot, observation, "display_height", str(normalized.height)),
            )
            fingerprint = build_cover_fingerprint(
                normalized,
                observation,
                snapshot.run.execution,
            )
        except (EbookCoverError, StructuredOutputError):
            return None
        if not snapshot.matches_results(expected_results) or not snapshot.matches_fingerprints(
            (fingerprint,)
        ):
            return None
        persisted = snapshot.fingerprints[0]
        if (
            persisted.kind != COVER_FINGERPRINT_KIND
            or persisted.algorithm_version != COVER_FINGERPRINT_PROFILE
        ):
            return None
        return CalibreCoverOutcome(snapshot.run, snapshot.results, persisted)

    def validation(
        self,
        request: ToolReuseRequest | None,
        observation: FileObservation,
    ) -> EpubCheckOutcome | None:
        snapshot = self._snapshot(request, observation)
        if snapshot is None:
            return None
        try:
            artifact = _single_required_artifact(snapshot, request)
            report = self._runtime.read_json_artifact(
                artifact,
                max_bytes=MAX_EPUBCHECK_REPORT_BYTES,
            )
            expected = parse_epubcheck_report(
                report,
                execution_id=snapshot.run.execution.id,
                observation_id=observation.id,
                expected_filename=PurePosixPath(observation.relative_path).name,
                expected_tool_version=snapshot.run.execution.tool_version,
            )
        except (EpubCheckError, StructuredOutputError):
            return None
        if not snapshot.matches_results(expected) or snapshot.fingerprints:
            return None
        return EpubCheckOutcome(snapshot.run, snapshot.results)

    def pdf(
        self,
        requests: tuple[ToolReuseRequest, ToolReuseRequest] | None,
        observation: FileObservation,
    ) -> PopplerPdfOutcome | None:
        if requests is None:
            return None
        info = self._snapshot(requests[0], observation)
        text = self._snapshot(requests[1], observation)
        if info is None or text is None:
            return None
        try:
            info_data = self._read_artifact(
                info,
                requests[0],
                max_bytes=MAX_PDFINFO_BYTES,
            )
            expected_metadata = parse_pdfinfo_output(
                info_data,
                execution_id=info.run.execution.id,
                observation_id=observation.id,
            )
            reported_size = next(
                (value.value for value in expected_metadata if value.key == "file_size_bytes"),
                None,
            )
            if reported_size is None or int(reported_size) != observation.size_bytes:
                return None

            text_data = self._read_artifact(
                text,
                requests[1],
                max_bytes=MAX_PDF_TEXT_BYTES,
            )
            normalized = normalize_shared_ebook_text(
                text_data,
                max_bytes=MAX_PDF_TEXT_BYTES,
            )
            expected_text = _text_results(
                text.run.execution.id,
                observation.id,
                "poppler_pdf_text_analysis",
                normalized.character_count,
                bool(normalized.text),
            )
            fingerprint = build_normalized_text_fingerprint(
                normalized,
                observation,
                text.run.execution,
            )
        except (PopplerPdfError, EbookTextError, StructuredOutputError, ValueError):
            return None
        expected_fingerprints = () if fingerprint is None else (fingerprint,)
        if (
            not info.matches_results(expected_metadata)
            or info.fingerprints
            or not text.matches_results(expected_text)
            or not text.matches_fingerprints(expected_fingerprints)
        ):
            return None
        persisted = text.fingerprints[0] if text.fingerprints else None
        return PopplerPdfOutcome(
            info_run=info.run,
            text_run=text.run,
            metadata_results=info.results,
            text_results=text.results,
            fingerprint=persisted,
        )

    def _snapshot(
        self,
        request: ToolReuseRequest | None,
        observation: FileObservation,
    ) -> ToolEvidenceSnapshot | None:
        return self._reader.find_reusable(
            request,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
        )

    def _read_artifact(
        self,
        snapshot: ToolEvidenceSnapshot,
        request: ToolReuseRequest | None,
        *,
        max_bytes: int,
    ) -> bytes:
        if request is None:
            raise StructuredOutputError("reuse request is unavailable")
        artifact = _single_required_artifact(snapshot, request)
        return self._runtime.read_artifact_bytes(artifact, max_bytes=max_bytes)


def _single_required_artifact(
    snapshot: ToolEvidenceSnapshot,
    request: ToolReuseRequest | None,
) -> ToolArtifact:
    if request is None or len(request.required_artifacts) != 1:
        raise StructuredOutputError("reuse request does not identify one artifact")
    artifact_type = request.required_artifacts[0].artifact_type
    matches = tuple(
        artifact
        for artifact in snapshot.run.artifacts
        if artifact.artifact_type == artifact_type
    )
    if len(matches) != 1:
        raise StructuredOutputError("required reuse artifact is unavailable")
    return matches[0]


def _artifact_bytes(
    runtime: ToolRuntime,
    snapshot: ToolEvidenceSnapshot,
    artifact_type: str,
    max_bytes: int,
) -> bytes:
    matches = tuple(
        artifact
        for artifact in snapshot.run.artifacts
        if artifact.artifact_type == artifact_type
    )
    if len(matches) != 1:
        raise StructuredOutputError("conditional reuse artifact is unavailable")
    return runtime.read_artifact_bytes(matches[0], max_bytes=max_bytes)


def _text_results(
    execution_id: EntityId,
    observation_id: EntityId,
    result_type: str,
    character_count: int,
    has_text: bool,
) -> tuple[ToolResult, ...]:
    return (
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type=result_type,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key="text_status",
            value="TEXT_EXTRACTED" if has_text else "NO_TEXT",
        ),
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type=result_type,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key="normalized_character_count",
            value=str(character_count),
        ),
    )


def _result(
    snapshot: ToolEvidenceSnapshot,
    observation: FileObservation,
    key: str,
    value: str,
) -> ToolResult:
    return ToolResult(
        id=EntityId.new(),
        execution_id=snapshot.run.execution.id,
        result_type=CALIBRE_COVER_RESULT_TYPE,
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        key=key,
        value=value,
    )


def _unique_values(results: tuple[ToolResult, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for result in results:
        if result.key in values:
            return {}
        values[result.key] = result.value
    return values
