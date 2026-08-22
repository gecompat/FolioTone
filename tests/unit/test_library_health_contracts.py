from __future__ import annotations

import pytest

from foliotone.collection_state import (
    LIBRARY_HEALTH_DIMENSION_ORDER,
    LIBRARY_HEALTH_FINDING_ORDER,
    CollectionStateItemState,
    LibraryHealthCoverageState,
    LibraryHealthDimension,
    LibraryHealthFindingCode,
    LibraryHealthItemFacts,
    LibraryHealthSeverity,
    LibraryHealthStatus,
    evaluate_library_health_item,
    library_health_coverage_state,
    library_health_status,
)
from foliotone.core import EntityId


def test_item_rules_cover_all_dimensions_without_authorizing_actions() -> None:
    facts = LibraryHealthItemFacts(
        file_id=EntityId.parse("70000000-0000-0000-0000-000000000001"),
        observation_id=EntityId.parse("71000000-0000-0000-0000-000000000001"),
        full_fixity_value_count=2,
        analysis_state=CollectionStateItemState.CURRENT_CONFLICT,
        resolution_state=CollectionStateItemState.CURRENT_CONFLICT,
        classification_state=CollectionStateItemState.CURRENT_CONFLICT,
        matching_state=CollectionStateItemState.CURRENT_CONFLICT,
        calibre_state=CollectionStateItemState.CURRENT_CONFLICT,
        archive_state=CollectionStateItemState.CURRENT_CONFLICT,
        consolidation_state=CollectionStateItemState.CURRENT_CONFLICT,
        quarantine_state=CollectionStateItemState.CURRENT_CONFLICT,
        metadata_fields=("contributor", "title"),
        metadata_index_truncated=True,
        analysis_finding_present=True,
        review_states=("DEFERRED", "PENDING"),
        sidecar_dependency_present=True,
    )

    evaluation = evaluate_library_health_item(facts)

    assert evaluation.finding_codes == tuple(
        code for code in LIBRARY_HEALTH_FINDING_ORDER if code in evaluation.finding_codes
    )
    assert len(evaluation.finding_codes) == len(set(evaluation.finding_codes))
    assert set(evaluation.covered_dimensions) == set(LIBRARY_HEALTH_DIMENSION_ORDER) - {
        LibraryHealthDimension.SCAN_FIXITY,
        LibraryHealthDimension.METADATA_AUTHORITY_CLASSIFICATION,
    }
    assert {
        LibraryHealthFindingCode.FULL_FIXITY_CONFLICT,
        LibraryHealthFindingCode.ANALYSIS_CONFLICT,
        LibraryHealthFindingCode.ANALYSIS_QUALITY_FINDING_PRESENT,
        LibraryHealthFindingCode.AUTHORITY_RESOLUTION_CONFLICT,
        LibraryHealthFindingCode.CLASSIFICATION_CONFLICT,
        LibraryHealthFindingCode.PENDING_REVIEW,
        LibraryHealthFindingCode.DEFERRED_REVIEW,
        LibraryHealthFindingCode.MATCHING_CONFLICT,
        LibraryHealthFindingCode.SIDECAR_DEPENDENCY_PRESENT,
        LibraryHealthFindingCode.CONSOLIDATION_BLOCKED,
        LibraryHealthFindingCode.QUARANTINE_BLOCKED,
    } <= set(evaluation.finding_codes)


def test_coverage_and_status_reducers_are_explicit_and_non_numeric() -> None:
    assert library_health_coverage_state(0, 0) is LibraryHealthCoverageState.COMPLETE
    assert library_health_coverage_state(4, 0) is LibraryHealthCoverageState.NONE
    assert library_health_coverage_state(4, 2) is LibraryHealthCoverageState.PARTIAL
    assert library_health_coverage_state(4, 4) is LibraryHealthCoverageState.COMPLETE
    with pytest.raises(ValueError, match="coverage counts"):
        library_health_coverage_state(1, 2)

    assert library_health_status(()) is LibraryHealthStatus.CLEAR
    assert library_health_status((LibraryHealthSeverity.INFO,)) is LibraryHealthStatus.OBSERVED
    assert (
        library_health_status((LibraryHealthSeverity.INFO, LibraryHealthSeverity.ATTENTION))
        is LibraryHealthStatus.ATTENTION
    )
    assert (
        library_health_status((LibraryHealthSeverity.BLOCKED, LibraryHealthSeverity.INCOMPLETE))
        is LibraryHealthStatus.BLOCKED
    )


def test_item_facts_reject_unbounded_or_noncanonical_inputs() -> None:
    common = {
        "file_id": EntityId.new(),
        "observation_id": EntityId.new(),
        "full_fixity_value_count": 0,
        "analysis_state": CollectionStateItemState.MISSING,
        "resolution_state": CollectionStateItemState.MISSING,
        "classification_state": CollectionStateItemState.MISSING,
        "matching_state": CollectionStateItemState.MISSING,
        "calibre_state": CollectionStateItemState.MISSING,
        "archive_state": CollectionStateItemState.MISSING,
        "consolidation_state": CollectionStateItemState.MISSING,
        "quarantine_state": CollectionStateItemState.MISSING,
    }
    with pytest.raises(ValueError, match="metadata fields"):
        LibraryHealthItemFacts(**common, metadata_fields=("title", "title"))
    with pytest.raises(ValueError, match="review states"):
        LibraryHealthItemFacts(**common, review_states=("DECIDED",))
    invalid_count = {**common, "full_fixity_value_count": -1}
    with pytest.raises(ValueError, match="nonnegative"):
        LibraryHealthItemFacts(**invalid_count)
