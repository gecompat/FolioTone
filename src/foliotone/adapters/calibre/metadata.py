"""Read-only calibre ``ebook-meta`` integration using bounded OPF evidence."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from foliotone.analyzers.ebook import EbookMetadataCandidate
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import repository
from foliotone.tooling import (
    ToolArtifactRequirement,
    ToolProviderDescriptor,
    ToolResult,
    ToolReuseRequest,
)
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
    adapter_version="ebook-meta-opf/2",
    capabilities=frozenset({ToolCapability.READ_METADATA}),
)
CALIBRE_OPF_ARTIFACT = "CALIBRE_OPF"
CALIBRE_CONFIG_IDENTITY = "ebook-meta:to-opf:parser-v2:candidate-v1"
CALIBRE_METADATA_RESULT = "calibre_metadata"
MAX_OPF_BYTES = 4 * 1024 * 1024
MAX_RESULT_COUNT = 256
MAX_CANDIDATE_RESULT_COUNT = 1024
MAX_RESULT_VALUE_CHARS = 4096
_SAFE_KEY_PART = re.compile(r"[^a-z0-9._-]+")
_REFINEMENT_PROPERTIES = frozenset(
    {"collection-type", "file-as", "group-position", "identifier-type", "role"}
)
_MARC_RELATOR_ROLES = {
    "aut": "author",
    "bkp": "book_producer",
    "ctb": "contributor",
    "edt": "editor",
    "ill": "illustrator",
    "nrt": "narrator",
    "oth": "other",
    "trl": "translator",
}
_IDENTIFIER_NAMESPACE_ALIASES = {
    "isbn": "isbn",
    "isbn-10": "isbn",
    "isbn-13": "isbn",
    "isbn10": "isbn",
    "isbn13": "isbn",
    "mobi-asin": "asin",
}


class CalibreMetadataError(RuntimeError):
    """A safe, user-facing calibre adapter failure."""


@dataclass(frozen=True, slots=True)
class CalibreMetadataOutcome:
    """Auditable tool run plus raw observations and non-canonical candidates."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]
    candidates: tuple[ToolResult, ...] = ()

    @property
    def all_results(self) -> tuple[ToolResult, ...]:
        """Return every persisted result while retaining the raw-results API."""
        return self.results + self.candidates


@dataclass(frozen=True, slots=True)
class CalibreMetadataProjection:
    """Raw OPF evidence plus versioned FolioTone metadata candidates."""

    observations: tuple[ToolResult, ...]
    candidates: tuple[ToolResult, ...]

    @property
    def all_results(self) -> tuple[ToolResult, ...]:
        """Return observations and candidates in persistence order."""
        return self.observations + self.candidates


@dataclass(frozen=True, slots=True)
class _Refinement:
    value: str
    scheme: str


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

    def reuse_request(self, observation: FileObservation) -> ToolReuseRequest | None:
        """Describe exact reusable metadata evidence after a safe version probe."""
        probe = self._runtime.probe_local(
            CALIBRE_PROVIDER,
            LocalCommand(
                executable=self._executable,
                args=(),
                capability=ToolCapability.READ_METADATA,
                environment={"CALIBRE_ALLOW_PYTHON_TEMPLATES": "0"},
                workspace_environment={"CALIBRE_CONFIG_DIRECTORY": "calibre-config"},
                version_policy=calibre_version_policy,
            ),
        )
        if not probe.usable:
            return None
        return ToolReuseRequest(
            descriptor=CALIBRE_PROVIDER,
            capability=ToolCapability.READ_METADATA,
            tool_version=probe.tool_version,
            input_identity=f"file-observation:{observation.id}",
            config_identity=CALIBRE_CONFIG_IDENTITY,
            required_artifacts=(
                ToolArtifactRequirement(CALIBRE_OPF_ARTIFACT, MAX_OPF_BYTES),
            ),
        )

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
            return CalibreMetadataOutcome(run=run, results=(), candidates=())

        opf_artifacts = tuple(
            artifact for artifact in run.artifacts if artifact.artifact_type == CALIBRE_OPF_ARTIFACT
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

        projection = project_calibre_opf(
            opf,
            execution_id=run.execution.id,
            observation_id=observation.id,
        )
        for result in projection.all_results:
            self._result_repo.save(result)
        return CalibreMetadataOutcome(
            run=run,
            results=projection.observations,
            candidates=projection.candidates,
        )


def parse_calibre_opf(
    data: bytes,
    *,
    execution_id: EntityId,
    observation_id: EntityId,
) -> tuple[ToolResult, ...]:
    """Parse raw OPF fields without treating them as canonical metadata.

    This compatibility entry point intentionally returns only provider-shaped
    observations. New code that also needs FolioTone candidates should use
    :func:`project_calibre_opf`.
    """
    return project_calibre_opf(
        data,
        execution_id=execution_id,
        observation_id=observation_id,
    ).observations


def project_calibre_opf(
    data: bytes,
    *,
    execution_id: EntityId,
    observation_id: EntityId,
) -> CalibreMetadataProjection:
    """Project bounded OPF 2/3 evidence into raw observations and candidates."""
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

    refinements = _collect_refinements(metadata)
    values: list[tuple[str, str]] = []
    candidate_values: list[EbookMetadataCandidate] = []
    contributor_index = 0
    identifier_index = 0

    field_mappings = (
        ("title", "title", "title"),
        ("creator", "creator", None),
        ("contributor", "contributor", None),
        ("identifier", "identifier", None),
        ("language", "language", "language"),
        ("publisher", "publisher", "publisher"),
        ("date", "date", "publication_date"),
        ("subject", "subject", "subject"),
        ("description", "description", "description"),
        ("rights", "rights", "rights"),
        ("type", "type", "type"),
    )
    for source_name, target_key, candidate_key in field_mappings:
        elements = tuple(
            element for element in metadata.iter() if _local_name(element.tag) == source_name
        )
        for source_index, element in enumerate(elements, start=1):
            value = _element_text(element)
            source_location = f"opf.{source_name}[{source_index}]"
            if source_name in {"creator", "contributor"}:
                contributor_index += 1
                roles = _role_terms(element, refinements)
                role_key = _safe_key_part(roles[0].value) if roles else ""
                key = f"{target_key}:{role_key}" if role_key else target_key
                _append_value(values, key, value)
                _append_contributor_candidates(
                    candidate_values,
                    index=contributor_index,
                    source_name=source_name,
                    source_location=source_location,
                    value=value,
                    roles=roles,
                    sort_names=_refined_terms(element, refinements, "file-as"),
                )
                for sort_name in _refined_terms(element, refinements, "file-as"):
                    sort_key = (
                        f"{target_key}_file_as:{role_key}"
                        if role_key
                        else (f"{target_key}_file_as")
                    )
                    _append_value(values, sort_key, sort_name.value)
                continue

            if source_name == "identifier":
                identifier_index += 1
                source_namespaces = _identifier_terms(element, refinements)
                namespace_key = (
                    _safe_key_part(source_namespaces[0].value) if source_namespaces else ""
                )
                key = f"identifier:{namespace_key}" if namespace_key else "identifier"
                _append_value(values, key, value)
                _append_identifier_candidates(
                    candidate_values,
                    index=identifier_index,
                    source_location=source_location,
                    value=value,
                    source_namespaces=source_namespaces,
                )
                continue

            _append_value(values, target_key, value)
            if candidate_key is not None:
                _append_candidate_value(
                    candidate_values,
                    candidate_key,
                    value,
                    f"{source_location}.text",
                )
            if source_name == "title":
                for sort_name in _refined_terms(element, refinements, "file-as"):
                    _append_value(values, "title_sort", sort_name.value)
                    _append_candidate_value(
                        candidate_values,
                        "title_sort",
                        sort_name.value,
                        f"{source_location}.file-as",
                    )

    legacy_series: list[tuple[str, str]] = []
    legacy_positions: list[tuple[str, str]] = []
    meta_occurrences: dict[str, int] = {}
    for element in metadata.iter():
        if _local_name(element.tag) != "meta":
            continue
        name = (_attribute(element, "name") or _attribute(element, "property")).lower()
        if name not in {
            "calibre:rating",
            "calibre:series",
            "calibre:series_index",
            "calibre:title_sort",
        }:
            continue
        key = {
            "calibre:rating": "rating",
            "calibre:series": "series",
            "calibre:series_index": "series_index",
            "calibre:title_sort": "title_sort",
        }[name]
        value = _attribute(element, "content") or _element_text(element)
        if not value.strip():
            continue
        _append_value(values, key, value)
        meta_occurrences[name] = meta_occurrences.get(name, 0) + 1
        source_location = f"opf.meta[{name}][{meta_occurrences[name]}]"
        if name == "calibre:series":
            legacy_series.append((value, source_location))
        elif name == "calibre:series_index":
            legacy_positions.append((value, source_location))
        else:
            _append_candidate_value(candidate_values, key, value, source_location)

    series_index = _append_legacy_series_candidates(
        candidate_values,
        names=legacy_series,
        positions=legacy_positions,
    )
    _append_opf3_series(
        metadata,
        refinements,
        values,
        candidate_values,
        starting_index=series_index,
    )

    observations = tuple(
        ToolResult(
            id=EntityId.new(),
            execution_id=execution_id,
            result_type=CALIBRE_METADATA_RESULT,
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation_id,
            key=key,
            value=value,
        )
        for key, value in values
    )
    candidates = tuple(
        candidate.to_tool_result(
            execution_id=execution_id,
            observation_id=observation_id,
        )
        for candidate in candidate_values
    )
    return CalibreMetadataProjection(observations=observations, candidates=candidates)


def _collect_refinements(
    metadata: ElementTree.Element,
) -> dict[str, dict[str, tuple[_Refinement, ...]]]:
    collected: dict[str, dict[str, list[_Refinement]]] = {}
    refinement_count = 0
    for element in metadata.iter():
        if _local_name(element.tag) != "meta":
            continue
        target = _attribute(element, "refines")
        property_name = _attribute(element, "property").lower()
        if not target.startswith("#") or property_name not in _REFINEMENT_PROPERTIES:
            continue
        value = _attribute(element, "content") or _element_text(element)
        normalized = " ".join(value.split())
        if not normalized:
            continue
        if len(normalized) > MAX_RESULT_VALUE_CHARS:
            raise CalibreMetadataError("calibre OPF contains an oversized metadata value")
        if refinement_count >= MAX_CANDIDATE_RESULT_COUNT:
            raise CalibreMetadataError("calibre OPF contains too many metadata refinements")
        target_properties = collected.setdefault(target[1:], {})
        target_properties.setdefault(property_name, []).append(
            _Refinement(value=normalized, scheme=_attribute(element, "scheme"))
        )
        refinement_count += 1
    return {
        target: {name: tuple(items) for name, items in properties.items()}
        for target, properties in collected.items()
    }


def _refined_terms(
    element: ElementTree.Element,
    refinements: dict[str, dict[str, tuple[_Refinement, ...]]],
    property_name: str,
) -> tuple[_Refinement, ...]:
    terms: list[_Refinement] = []
    attribute_value = _attribute(element, property_name)
    if attribute_value:
        terms.append(_Refinement(value=attribute_value, scheme=""))
    element_id = _attribute(element, "id")
    if element_id:
        terms.extend(refinements.get(element_id, {}).get(property_name, ()))
    return _unique_terms(terms)


def _role_terms(
    element: ElementTree.Element,
    refinements: dict[str, dict[str, tuple[_Refinement, ...]]],
) -> tuple[_Refinement, ...]:
    return _refined_terms(element, refinements, "role")


def _identifier_terms(
    element: ElementTree.Element,
    refinements: dict[str, dict[str, tuple[_Refinement, ...]]],
) -> tuple[_Refinement, ...]:
    terms: list[_Refinement] = []
    scheme = _attribute(element, "scheme")
    if scheme:
        terms.append(_Refinement(value=scheme, scheme="opf:scheme"))
    element_id = _attribute(element, "id")
    if element_id:
        terms.extend(refinements.get(element_id, {}).get("identifier-type", ()))
    return _unique_terms(terms)


def _unique_terms(terms: list[_Refinement]) -> tuple[_Refinement, ...]:
    unique: list[_Refinement] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        normalized = (term.value, term.scheme)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(term)
    return tuple(unique)


def _append_contributor_candidates(
    candidates: list[EbookMetadataCandidate],
    *,
    index: int,
    source_name: str,
    source_location: str,
    value: str,
    roles: tuple[_Refinement, ...],
    sort_names: tuple[_Refinement, ...],
) -> None:
    prefix = f"contributor.{index}"
    _append_candidate_value(candidates, f"{prefix}.name", value, f"{source_location}.text")
    _append_candidate_value(
        candidates,
        f"{prefix}.source_element",
        source_name,
        source_location,
    )
    for role_index, role in enumerate(roles, start=1):
        suffix = "" if len(roles) == 1 else f".{role_index}"
        _append_candidate_value(
            candidates,
            f"{prefix}.source_role{suffix}",
            role.value,
            f"{source_location}.role",
        )
        if role.scheme:
            _append_candidate_value(
                candidates,
                f"{prefix}.source_role_scheme{suffix}",
                role.scheme,
                f"{source_location}.role.scheme",
            )
        mapped_role = _mapped_marc_role(role)
        if mapped_role is not None:
            _append_candidate_value(
                candidates,
                f"{prefix}.role{suffix}",
                mapped_role,
                f"{source_location}.role",
            )
    for sort_index, sort_name in enumerate(sort_names, start=1):
        suffix = "" if len(sort_names) == 1 else f".{sort_index}"
        _append_candidate_value(
            candidates,
            f"{prefix}.sort_name{suffix}",
            sort_name.value,
            f"{source_location}.file-as",
        )


def _mapped_marc_role(role: _Refinement) -> str | None:
    scheme = role.scheme.lower().strip()
    if scheme and _safe_key_part(scheme) not in {"marc", "marc-relators"}:
        return None
    return _MARC_RELATOR_ROLES.get(role.value.lower().strip())


def _append_identifier_candidates(
    candidates: list[EbookMetadataCandidate],
    *,
    index: int,
    source_location: str,
    value: str,
    source_namespaces: tuple[_Refinement, ...],
) -> None:
    prefix = f"identifier.{index}"
    _append_candidate_value(candidates, f"{prefix}.value", value, f"{source_location}.text")
    for namespace_index, source_namespace in enumerate(source_namespaces, start=1):
        suffix = "" if len(source_namespaces) == 1 else f".{namespace_index}"
        source_property = "scheme" if source_namespace.scheme == "opf:scheme" else "identifier-type"
        _append_candidate_value(
            candidates,
            f"{prefix}.source_namespace{suffix}",
            source_namespace.value,
            f"{source_location}.{source_property}",
        )
        if source_namespace.scheme and source_namespace.scheme != "opf:scheme":
            _append_candidate_value(
                candidates,
                f"{prefix}.source_namespace_scheme{suffix}",
                source_namespace.scheme,
                f"{source_location}.{source_property}.scheme",
            )
        namespace = _normalized_identifier_namespace(source_namespace)
        if namespace is not None:
            _append_candidate_value(
                candidates,
                f"{prefix}.namespace{suffix}",
                namespace,
                f"{source_location}.{source_property}",
            )
    if not source_namespaces:
        inferred_namespace = _namespace_from_identifier_value(value)
        if inferred_namespace is not None:
            _append_candidate_value(
                candidates,
                f"{prefix}.namespace",
                inferred_namespace,
                f"{source_location}.text-prefix",
            )


def _normalized_identifier_namespace(term: _Refinement) -> str | None:
    scheme = _safe_key_part(term.scheme)
    value = _safe_key_part(term.value)
    if scheme == "onix-codelist5":
        return "isbn" if term.value.strip() in {"02", "15"} else None
    if scheme == "opf-scheme":
        return _IDENTIFIER_NAMESPACE_ALIASES.get(value, value or None)
    if not scheme:
        return _IDENTIFIER_NAMESPACE_ALIASES.get(value)
    return None


def _namespace_from_identifier_value(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized.startswith("urn:isbn:") or normalized.startswith("isbn:"):
        return "isbn"
    if normalized.startswith("urn:uuid:"):
        return "uuid"
    return None


def _append_legacy_series_candidates(
    candidates: list[EbookMetadataCandidate],
    *,
    names: list[tuple[str, str]],
    positions: list[tuple[str, str]],
) -> int:
    count = max(len(names), len(positions))
    for index in range(count):
        prefix = f"series.{index + 1}"
        if index < len(names):
            value, source_location = names[index]
            _append_candidate_value(candidates, f"{prefix}.name", value, source_location)
        if index < len(positions):
            value, source_location = positions[index]
            _append_candidate_value(candidates, f"{prefix}.position", value, source_location)
    return count


def _append_opf3_series(
    metadata: ElementTree.Element,
    refinements: dict[str, dict[str, tuple[_Refinement, ...]]],
    observations: list[tuple[str, str]],
    candidates: list[EbookMetadataCandidate],
    *,
    starting_index: int,
) -> None:
    series_index = starting_index
    collection_index = 0
    for element in metadata.iter():
        if _local_name(element.tag) != "meta":
            continue
        if _attribute(element, "property").lower() != "belongs-to-collection":
            continue
        collection_index += 1
        element_id = _attribute(element, "id")
        properties = refinements.get(element_id, {}) if element_id else {}
        collection_types = properties.get("collection-type", ())
        if not any(item.value.lower().strip() == "series" for item in collection_types):
            continue
        value = _attribute(element, "content") or _element_text(element)
        source_location = f"opf.collection[{collection_index}]"
        _append_value(observations, "series", value)
        series_index += 1
        prefix = f"series.{series_index}"
        _append_candidate_value(candidates, f"{prefix}.name", value, f"{source_location}.text")
        for position_index, position in enumerate(properties.get("group-position", ()), start=1):
            suffix = (
                "" if len(properties.get("group-position", ())) == 1 else (f".{position_index}")
            )
            _append_value(observations, "series_index", position.value)
            _append_candidate_value(
                candidates,
                f"{prefix}.position{suffix}",
                position.value,
                f"{source_location}.group-position",
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


def _append_candidate_value(
    values: list[EbookMetadataCandidate],
    key: str,
    value: str,
    source_location: str,
) -> None:
    normalized = " ".join(value.split())
    if not normalized:
        return
    if len(normalized) > MAX_RESULT_VALUE_CHARS:
        raise CalibreMetadataError("calibre OPF contains an oversized metadata value")
    if len(values) >= MAX_CANDIDATE_RESULT_COUNT:
        raise CalibreMetadataError("calibre OPF produces too many metadata candidates")
    values.append(
        EbookMetadataCandidate(
            field_path=key,
            value=normalized,
            source_location=source_location,
        )
    )
