from __future__ import annotations

from dataclasses import replace

import pytest

from foliotone.collection_state import (
    MAX_COLLECTION_QUERY_PREDICATES,
    CollectionQueryField,
    CollectionQueryOperator,
    CollectionQueryPredicate,
    CollectionStateDiffCategory,
    CollectionStateDiffEntry,
    CollectionStateDiffRequest,
    CollectionStateItem,
    CollectionStateItemState,
    collection_query_fts_expression,
    collection_state_item_diff_categories,
    parse_collection_query_spec,
)
from foliotone.collection_state.contracts import sha256_digest
from foliotone.core import EntityId


def _item(
    *,
    observation: int = 1,
    size_bytes: int = 100,
    technical_marker: str = "base",
) -> CollectionStateItem:
    missing = CollectionStateItemState.MISSING
    return CollectionStateItem(
        ordinal=0,
        file_id=EntityId.parse("10000000-0000-0000-0000-000000000001"),
        observation_id=EntityId.parse(f"20000000-0000-0000-0000-{observation:012d}"),
        format_name="EPUB",
        size_bytes=size_bytes,
        technical_digest=sha256_digest({"technical": technical_marker}),
        analysis_state=missing,
        analysis_digest=None,
        resolution_state=missing,
        resolution_digest=None,
        classification_state=missing,
        classification_digest=None,
        matching_state=missing,
        matching_digest=None,
        review_state=missing,
        review_digest=None,
        calibre_state=missing,
        calibre_digest=None,
        archive_state=missing,
        archive_digest=None,
        consolidation_state=missing,
        consolidation_digest=None,
        quarantine_state=missing,
        quarantine_digest=None,
        item_digest="",
    )


def test_query_ast_is_normalized_bounded_and_deterministic() -> None:
    raw = {
        "where": {
            "and": [
                {"field": "title", "operator": "MATCH", "value": "  Café  Lantern "},
                {"field": "format", "operator": "EQ", "value": "epub"},
            ]
        },
        "sort": "FILE_ID_ASC",
        "limit": 25,
    }
    first = parse_collection_query_spec(raw)
    repeated = parse_collection_query_spec(raw)

    assert first == repeated
    assert parse_collection_query_spec(first.canonical_payload()) == first
    assert first.query_digest == repeated.query_digest
    assert first.fields == (CollectionQueryField.FORMAT, CollectionQueryField.TITLE)
    assert "café" in first.canonical_payload()["where"]["and"][0]["value"]  # type: ignore[index]
    assert "Café" not in repr(first)


@pytest.mark.parametrize(
    "raw",
    (
        {"where": {"field": "title; DROP TABLE files", "operator": "EQ", "value": "x"}},
        {"where": {"field": "format", "operator": "PREFIX", "value": "EP"}},
        {"where": {"field": "format", "operator": "EQ", "value": "EXE"}},
        {"where": {"field": "title", "operator": "SQL", "value": "x"}},
        {"where": {"field": "title", "operator": "EQ", "value": "x"}, "sql": "1=1"},
        {
            "profile": "collection-query/v2",
            "where": {"field": "title", "operator": "EQ", "value": "x"},
        },
        {"where": {"or": []}},
        {"where": {"field": "title", "operator": "EQ", "value": "x"}, "limit": 101},
    ),
)
def test_query_ast_rejects_unknown_unbounded_or_free_sql_shapes(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        parse_collection_query_spec(raw)


def test_query_ast_rejects_excess_predicates_and_depth() -> None:
    leaf = {"field": "title", "operator": "EQ", "value": "x"}
    with pytest.raises(ValueError, match="oversized|predicate"):
        parse_collection_query_spec(
            {"where": {"and": [leaf] * (MAX_COLLECTION_QUERY_PREDICATES + 1)}}
        )

    nested: dict[str, object] = leaf
    for _ in range(5):
        nested = {"and": [nested]}
    with pytest.raises(ValueError, match="depth"):
        parse_collection_query_spec({"where": nested})

    with pytest.raises(ValueError, match="valid JSON"):
        parse_collection_query_spec(
            '{"where":{"field":"title","operator":"EQ","value":"x"},'
            '"where":{"field":"title","operator":"EQ","value":"y"}}'
        )


def test_fts_expression_does_not_forward_query_syntax() -> None:
    expression = collection_query_fts_expression('Lantern" OR secret*')
    assert expression == '"lantern" AND "or" AND "secret"'
    assert "*" not in expression
    predicate = CollectionQueryPredicate(
        CollectionQueryField.TITLE,
        CollectionQueryOperator.MATCH,
        'Lantern" OR secret*',
    )
    assert "secret" not in repr(predicate)


def test_diff_categories_separate_lineage_from_supported_changes() -> None:
    before = _item()
    new_observation_same_facts = _item(observation=2)
    assert collection_state_item_diff_categories(before, new_observation_same_facts) == ()

    technically_changed = _item(observation=2, size_bytes=101)
    assert collection_state_item_diff_categories(before, technically_changed) == (
        CollectionStateDiffCategory.TECHNICALLY_CHANGED,
    )

    current = CollectionStateItemState.CURRENT
    current_conflict = CollectionStateItemState.CURRENT_CONFLICT
    advanced = replace(
        new_observation_same_facts,
        analysis_state=current,
        analysis_digest="a" * 64,
        resolution_state=current,
        resolution_digest="b" * 64,
        review_state=current,
        review_digest="c" * 64,
        consolidation_state=current_conflict,
        consolidation_digest="d" * 64,
        item_digest="",
    )
    assert collection_state_item_diff_categories(before, advanced) == (
        CollectionStateDiffCategory.NEWLY_ANALYZED,
        CollectionStateDiffCategory.NEWLY_RESOLVED,
        CollectionStateDiffCategory.NEWLY_REVIEWED,
        CollectionStateDiffCategory.NEWLY_BLOCKED,
    )


def test_diff_request_requires_distinct_snapshots_and_bounded_page() -> None:
    snapshot = EntityId.parse("30000000-0000-0000-0000-000000000001")
    with pytest.raises(ValueError, match="distinct"):
        CollectionStateDiffRequest(snapshot, snapshot)
    with pytest.raises(ValueError, match="limit"):
        CollectionStateDiffRequest(
            snapshot,
            EntityId.parse("30000000-0000-0000-0000-000000000002"),
            limit=1001,
        )


def test_diff_entries_reject_mixed_presence_and_transition_shapes() -> None:
    file_id = EntityId.parse("10000000-0000-0000-0000-000000000001")
    observation_id = EntityId.parse("20000000-0000-0000-0000-000000000001")
    with pytest.raises(ValueError, match="only an after"):
        CollectionStateDiffEntry(
            file_id,
            (
                CollectionStateDiffCategory.ADDED,
                CollectionStateDiffCategory.NEWLY_ANALYZED,
            ),
            None,
            observation_id,
        )
    with pytest.raises(ValueError, match="both observations"):
        CollectionStateDiffEntry(
            file_id,
            (CollectionStateDiffCategory.NEWLY_ANALYZED,),
            None,
            observation_id,
        )
