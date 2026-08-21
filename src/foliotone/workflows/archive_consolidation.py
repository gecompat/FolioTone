"""Pure archive-dependency composition for non-executable consolidation plans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from foliotone.consolidation.archive_dependencies import (
    MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS,
    ArchiveDependencyProjectionInputs,
    ArchiveSourceDependencyBinding,
    build_archive_dependency,
)
from foliotone.consolidation.contracts import (
    ConsolidationDependencyKind,
    ConsolidationFileRole,
    ConsolidationPlan,
)
from foliotone.consolidation.planner import (
    ConsolidationPlannerInputs,
    build_consolidation_plan,
)
from foliotone.core import EntityKind, MatchStatus, RelationType


def archive_aware_planner_inputs(
    inputs: ConsolidationPlannerInputs,
    bindings: tuple[ArchiveSourceDependencyBinding, ...],
) -> ConsolidationPlannerInputs:
    """Replace only the two ARCHIVE dependencies from bounded source evidence."""

    if not isinstance(inputs, ConsolidationPlannerInputs):
        raise TypeError("inputs must be ConsolidationPlannerInputs")
    if (
        not isinstance(bindings, tuple)
        or len(bindings) > 2 * MAX_ARCHIVE_SOURCE_DEPENDENCY_BINDINGS
        or any(not isinstance(item, ArchiveSourceDependencyBinding) for item in bindings)
    ):
        raise ValueError("archive bindings are invalid or exceed the endpoint bound")
    identity = inputs.identity
    if (
        identity is None
        or identity.relation_type is not RelationType.EXACT_DUPLICATE
        or identity.left_kind is not EntityKind.FILE
        or identity.right_kind is not EntityKind.FILE
        or identity.status is not MatchStatus.CONFIRMED
        or identity.scan_root_id != inputs.scan_root_id
        or identity.source_scan_run_id != inputs.source_scan_run_id
        or len(inputs.precondition_inputs) != 2
    ):
        raise ValueError("archive-aware planning requires an actionable file identity")
    sources_by_role = {
        source.file_endpoint.role: source for source in inputs.precondition_inputs
    }
    if set(sources_by_role) != set(ConsolidationFileRole):
        raise ValueError("archive-aware planning requires both directed endpoints")
    if any(
        source.file_endpoint.scan_root_id != inputs.scan_root_id
        or source.file_endpoint.source_scan_run_id != inputs.source_scan_run_id
        for source in sources_by_role.values()
    ):
        raise ValueError("archive endpoints belong to foreign lineage")
    endpoints_by_observation = {
        source.file_endpoint.observation_id: role
        for role, source in sources_by_role.items()
    }
    if len(endpoints_by_observation) != 2 or any(
        binding.file_observation_id not in endpoints_by_observation
        or binding.scan_root_id != inputs.scan_root_id
        or binding.source_scan_run_id != inputs.source_scan_run_id
        for binding in bindings
    ):
        raise ValueError("archive bindings do not match the directed endpoints")
    expected_file_ids = {
        source.file_endpoint.file_id for source in sources_by_role.values()
    }
    if expected_file_ids != {identity.left_file_id, identity.right_file_id}:
        raise ValueError("archive endpoints do not match the exact identity")

    non_archive = tuple(
        item
        for item in inputs.dependencies
        if item.kind is not ConsolidationDependencyKind.ARCHIVE
    )
    archive_dependencies = tuple(
        build_archive_dependency(
            ArchiveDependencyProjectionInputs(
                file_role=role,
                file_observation_id=source.file_endpoint.observation_id,
                scan_root_id=inputs.scan_root_id,
                source_scan_run_id=inputs.source_scan_run_id,
                bindings=tuple(
                    item
                    for item in bindings
                    if item.file_observation_id
                    == source.file_endpoint.observation_id
                ),
            )
        )
        for role in ConsolidationFileRole
        for source in (sources_by_role[role],)
    )
    dependencies = tuple(
        sorted(
            (*non_archive, *archive_dependencies),
            key=lambda item: (item.file_role.value, item.kind.value),
        )
    )
    preconditions = tuple(
        replace(
            source,
            dependencies=tuple(
                item for item in dependencies if item.file_role is role
            ),
        )
        for role in ConsolidationFileRole
        for source in (sources_by_role[role],)
    )
    return replace(
        inputs,
        dependencies=dependencies,
        precondition_inputs=preconditions,
    )


def build_archive_aware_consolidation_plan(
    inputs: ConsolidationPlannerInputs,
    bindings: tuple[ArchiveSourceDependencyBinding, ...],
    *,
    clock: Callable[[], datetime],
) -> ConsolidationPlan:
    """Build a regular planner snapshot after the bounded archive projection."""

    return build_consolidation_plan(
        archive_aware_planner_inputs(inputs, bindings), clock=clock
    )


__all__ = [
    "archive_aware_planner_inputs",
    "build_archive_aware_consolidation_plan",
]
