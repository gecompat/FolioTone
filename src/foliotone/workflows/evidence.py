"""Observation-bound lookup of exact reusable external-tool evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import Engine

from foliotone.core import EntityId, EntityKind, Fingerprint
from foliotone.persistence import repository
from foliotone.tooling import ToolArtifact, ToolExecution, ToolResult
from foliotone.tooling.reanalysis import (
    ToolArtifactRequirement,
    ToolReuseRequest,
    requires_reanalysis,
)
from foliotone.tooling.runtime import ToolRunOutcome, ToolRuntime
from foliotone.tooling.structured import StructuredOutputError


@dataclass(frozen=True, slots=True)
class ToolEvidenceSnapshot:
    """Persisted exact run plus observation-bound derived evidence."""

    run: ToolRunOutcome
    results: tuple[ToolResult, ...]
    fingerprints: tuple[Fingerprint, ...]

    def matches_results(self, expected: tuple[ToolResult, ...]) -> bool:
        """Compare derived result content while ignoring generated entity IDs."""
        return Counter(_result_signature(value) for value in self.results) == Counter(
            _result_signature(value) for value in expected
        )

    def matches_fingerprints(self, expected: tuple[Fingerprint, ...]) -> bool:
        """Compare fingerprint content while ignoring generated entity IDs."""
        return Counter(
            _fingerprint_signature(value) for value in self.fingerprints
        ) == Counter(_fingerprint_signature(value) for value in expected)


class ToolEvidenceReader:
    """Resolve only the latest exact successful run with intact required artifacts."""

    def __init__(self, engine: Engine, runtime: ToolRuntime) -> None:
        self._execution_repo = repository(engine, ToolExecution)
        self._artifact_repo = repository(engine, ToolArtifact)
        self._result_repo = repository(engine, ToolResult)
        self._fingerprint_repo = repository(engine, Fingerprint)
        self._runtime = runtime

    def find_reusable(
        self,
        request: ToolReuseRequest | None,
        *,
        target_kind: EntityKind,
        target_id: EntityId,
    ) -> ToolEvidenceSnapshot | None:
        """Return exact evidence or ``None`` so the caller safely re-runs the tool."""
        if request is None:
            return None
        candidates = tuple(
            execution
            for execution in self._execution_repo.list_all()
            if execution.provider_id == request.descriptor.provider_id
            and execution.capability is request.capability
            and execution.tool_version == request.tool_version
            and execution.adapter_version == request.descriptor.adapter_version
            and execution.input_identity == request.input_identity
            and execution.config_identity == request.config_identity
        )
        previous = max(
            candidates,
            key=lambda execution: (execution.started_at, str(execution.id)),
            default=None,
        )
        if requires_reanalysis(
            previous,
            request.descriptor,
            request.capability,
            tool_version=request.tool_version,
            input_identity=request.input_identity,
            config_identity=request.config_identity,
        ):
            return None
        assert previous is not None

        artifacts = tuple(
            artifact
            for artifact in self._artifact_repo.list_all()
            if artifact.execution_id == previous.id
        )
        for requirement in request.required_artifacts:
            if not self._artifact_is_intact(artifacts, requirement):
                return None

        results = tuple(
            result
            for result in self._result_repo.list_all()
            if result.execution_id == previous.id
            and result.target_kind is target_kind
            and result.target_id == target_id
        )
        fingerprints = tuple(
            fingerprint
            for fingerprint in self._fingerprint_repo.list_all()
            if fingerprint.tool_execution_id == previous.id
            and fingerprint.target_kind is target_kind
            and fingerprint.target_id == target_id
        )
        return ToolEvidenceSnapshot(
            run=ToolRunOutcome(previous, artifacts, "", ""),
            results=results,
            fingerprints=fingerprints,
        )

    def has_intact_artifact(
        self,
        snapshot: ToolEvidenceSnapshot,
        requirement: ToolArtifactRequirement,
    ) -> bool:
        """Verify one conditional artifact that depends on projected evidence."""
        return self._artifact_is_intact(snapshot.run.artifacts, requirement)

    def _artifact_is_intact(
        self,
        artifacts: tuple[ToolArtifact, ...],
        requirement: ToolArtifactRequirement,
    ) -> bool:
        matches = tuple(
            artifact
            for artifact in artifacts
            if artifact.artifact_type == requirement.artifact_type
        )
        if len(matches) != 1:
            return False
        try:
            self._runtime.verify_artifact(matches[0], max_bytes=requirement.max_bytes)
        except StructuredOutputError:
            return False
        return True


def _result_signature(result: ToolResult) -> tuple[object, ...]:
    return (
        result.execution_id,
        result.result_type,
        result.target_kind,
        result.target_id,
        result.key,
        result.value,
        result.confidence,
        result.explanation,
    )


def _fingerprint_signature(fingerprint: Fingerprint) -> tuple[object, ...]:
    return (
        fingerprint.target_kind,
        fingerprint.target_id,
        fingerprint.kind,
        fingerprint.algorithm,
        fingerprint.algorithm_version,
        fingerprint.value,
        fingerprint.created_at,
        fingerprint.tool_execution_id,
    )
