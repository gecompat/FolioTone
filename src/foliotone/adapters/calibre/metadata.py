"""Read-only calibre ``ebook-meta`` integration using bounded OPF evidence."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import repository
from foliotone.tooling import ToolProviderDescriptor, ToolResult
from foliotone.tooling.runtime import (
    LocalCommand,
    ToolRunOutcome,
    ToolRuntime,
    WorkspaceOutput,
)
from foliotone.tooling.structured import StructuredOutputError

from .common import CalibreAdapterError, calibre_version_policy, validated_observed_file

CALIBRE_PROVIDER = ToolProviderDescriptor(
    provider_id="calibre",
    display_name="calibre ebook-meta",
    adapter_version="ebook-meta-opf/1",
    capabilities=frozenset({ToolCapability.READ_METADATA}),
)
CALIBRE_OPF_ARTIFACT = "CALIBRE_OPF"
CALIBRE_CONFIG_IDENTITY = "ebook-meta:to-opf:parser-v1"
MAX_OPF_BYTES = 4 * 1024 * 1024
MAX_RESULT_COUNT = 256
MAX_RESULT_VALUE_CHARS = 4096
_SAFE_KEY_PART = re.compile(r"[^a-z0-9._-]+")


class CalibreMetadataError(RuntimeError):
    """A safe, user-facing calibre adapter failure."""


@dataclass(frozen=True, slots=True)
class CalibreMetadataOutcome:
    """Auditable tool run plus raw metadata observations derived from its OPF."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]


class CalibreMetadataAnalyzer:
    """Run the immutable ``ebook-meta FILE --to-opf metadata.opf`` command shape."""

    def __init__(
        self,
        engine: Engine,
        runtime: ToolRuntime,
        *,
        executable: str = "ebook-meta",
    ) -> None:
        if not executable.strip():
            raise ValueError("executable must not be empty")
        self._result_repo = repository(engine, ToolResult)
        self._runtime = runtime
        self._executable = executable

    def analyze(
        self,
        source_root: Path,
        observation: FileObservation,
    ) -> CalibreMetadataOutcome:
        """Extract metadata without exposing calibre's write-capable CLI options."""
        try:
            source_file = validated_observed_file(source_root, observation)
        except CalibreAdapterError as error:
            raise CalibreMetadataError(str(error)) from error
        run = self._runtime.execute_local(
            CALIBRE_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(str(source_file), "--to-opf", "metadata.opf"),
                capability=ToolCapability.READ_METADATA,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                outputs=(
                    WorkspaceOutput(
                        artifact_type=CALIBRE_OPF_ARTIFACT,
                        relative_path="metadata.opf",
                        max_bytes=MAX_OPF_BYTES,
                    ),
                ),
                version_policy=calibre_version_policy,
            ),
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_CONFIG_IDENTITY,
        )
        if run.execution.status is not ToolExecutionStatus.SUCCEEDED:
            return CalibreMetadataOutcome(run=run, results=())

        opf_artifacts = tuple(
            artifact
            for artifact in run.artifacts
            if artifact.artifact_type == CALIBRE_OPF_ARTIFACT
        )
        if len(opf_artifacts) != 1:
            raise CalibreMetadataError("calibre did not produce exactly one OPF artifact")
        try:
            opf = self._runtime.read_artifact_bytes(
                opf_artifacts[0],
                max_bytes=MAX_OPF_BYTES,
            )
        except StructuredOutputError as error:
            raise CalibreMetadataError("calibre OPF artifact validation failed") from error

        results = parse_calibre_opf(
            opf,
            execution_id=run.execution.id,
            observation_id=observation.id,
        )
        for result in results:
            self._result_repo.save(result)
        return CalibreMetadataOutcome(run=run, results=results)


def parse_calibre_opf(
    data: bytes,
    *,
    execution_id: EntityId,
    observation_id: EntityId,
) -> tuple[ToolResult, ...]:
    """Parse selected raw OPF fields without treating them as canonical metadata."""
    if len(data) > MAX_OPF_BYTES:
        raise CalibreMetadataError("calibre OPF exceeds the configured size limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CalibreMetadataError("calibre OPF is not valid UTF-8") from error
    upper_text = text.upper()
    if "<!DOCTYPE" in upper_text or "<!ENTITY" in upper_text:
        raise CalibreMetadataError("calibre OPF contains a forbidden document declaration")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise CalibreMetadataError("calibre OPF is not well-formed XML") from error
    if _local_name(root.tag) != "package":
        raise CalibreMetadataError("calibre OPF has an unexpected root element")

    metadata = next(
        (element for element in root.iter() if _local_name(element.tag) == "metadata"),
        None,
    )
    if metadata is None:
        raise CalibreMetadataError("calibre OPF does not contain metadata")

    values: list[tuple[str, str]] = []
    for source_name, target_key in (
        ("title", "title"),
        ("creator", "creator"),
        ("identifier", "identifier"),
        ("language", "language"),
        ("publisher", "publisher"),
        ("date", "date"),
        ("subject", "subject"),
    ):
        for element in metadata.iter():
            if _local_name(element.tag) != source_name:
                continue
            key = target_key
            if source_name == "creator":
                role = _safe_key_part(_attribute(element, "role"))
                if role:
                    key = f"creator:{role}"
            elif source_name == "identifier":
                scheme = _safe_key_part(_attribute(element, "scheme"))
                if scheme:
                    key = f"identifier:{scheme}"
            _append_value(values, key, _element_text(element))

    for element in metadata.iter():
        if _local_name(element.tag) != "meta":
            continue
        name = (_attribute(element, "name") or _attribute(element, "property")).lower()
        if name not in {"calibre:series", "calibre:series_index"}:
            continue
        key = "series" if name == "calibre:series" else "series_index"
        value = _attribute(element, "content") or _element_text(element)
        _append_value(values, key, value)

    return tuple(
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type="calibre_metadata",
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key=key,
            value=value,
        )
        for key, value in values
    )


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _attribute(element: ElementTree.Element, name: str) -> str:
    for attribute_name, value in element.attrib.items():
        if _local_name(attribute_name) == name:
            return value.strip()
    return ""


def _element_text(element: ElementTree.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _safe_key_part(value: str) -> str:
    return _SAFE_KEY_PART.sub("-", value.lower()).strip("-")[:64]


def _append_value(values: list[tuple[str, str]], key: str, value: str) -> None:
    normalized = " ".join(value.split())
    if not normalized:
        return
    if len(normalized) > MAX_RESULT_VALUE_CHARS:
        raise CalibreMetadataError("calibre OPF contains an oversized metadata value")
    if len(values) >= MAX_RESULT_COUNT:
        raise CalibreMetadataError("calibre OPF contains too many metadata values")
    values.append((key, normalized))
