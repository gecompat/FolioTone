from datetime import UTC, datetime

import pytest

from foliotone.adapters.openlibrary import (
    MAPPING_PROFILE_VERSION,
    OpenLibraryEvidenceProjection,
    OpenLibraryIdentifierProjection,
    OpenLibraryMappingProvenance,
    OpenLibraryMappingResult,
    map_openlibrary_record,
)
from foliotone.adapters.openlibrary.source import (
    AuthorSourceRecord,
    EditionSourceRecord,
    SearchSourceRecord,
    WorkSourceRecord,
)
from foliotone.core import EntityKind, ValueState

NOW = datetime(2026, 8, 19, tzinfo=UTC)
WORK = WorkSourceRecord("OL1W", "Synthetic Work", "2020", (), (), False)


def test_repeated_mapping_is_deterministic_and_requires_binding():
    with pytest.raises(ValueError):
        map_openlibrary_record(WORK, observed_at=NOW)
    assert map_openlibrary_record(
        WORK, observed_at=NOW, target_id="opaque-work"
    ) == map_openlibrary_record(WORK, observed_at=NOW, target_id="opaque-work")


def test_work_edition_and_agent_are_separate_and_external():
    edition = EditionSourceRecord(
        "OL2M", ("OL1W",), "Synthetic Edition", None, None, (), (), (), (), (), (), (), False
    )
    work = map_openlibrary_record(WORK, observed_at=NOW, target_id="w")
    mapped_edition = map_openlibrary_record(
        edition, observed_at=NOW, target_id="e", target_bindings={"openlibrary.work:OL1W": "w"}
    )
    author = map_openlibrary_record(
        AuthorSourceRecord("OL3A", "Synthetic Author", (), None, None, False),
        observed_at=NOW,
        target_id="a",
    )
    assert work.identifiers[0].target_kind is EntityKind.WORK
    assert mapped_edition.identifiers[0].target_kind is EntityKind.EDITION
    assert mapped_edition.work_candidates[0].target_ref == "w"
    assert not hasattr(author.agent_candidates[0], "agent_id")
    assert all(
        v.state is ValueState.EXTERNAL for v in work.values + mapped_edition.values + author.values
    )
    assert all(
        x.provenance.mapping_profile_version == MAPPING_PROFILE_VERSION
        for x in work.identifiers + work.values
    )


def test_invalid_public_projection_and_provenance_are_rejected():
    p = OpenLibraryMappingProvenance(
        "openlibrary",
        "openlibrary-web-api-docs-2026-08-19",
        "openlibrary-book-adapter/v1",
        "openlibrary-source-record/v1",
        MAPPING_PROFILE_VERSION,
        NOW,
    )
    with pytest.raises(ValueError):
        OpenLibraryEvidenceProjection(EntityKind.WORK, "x", "title", "v", ValueState.CANONICAL, p)
    with pytest.raises(ValueError):
        OpenLibraryMappingProvenance(
            "other",
            p.provider_source_version,
            p.provider_adapter_version,
            p.source_profile_version,
            p.mapping_profile_version,
            NOW,
        )


@pytest.mark.parametrize(
    ("target_ref", "value"),
    [
        ("C:/private", "Synthetic"),
        ("opaque", "Not NFD e\u0301"),
    ],
)
def test_public_dtos_reject_private_or_noncanonical_text(target_ref: str, value: str):
    p = OpenLibraryMappingProvenance(
        "openlibrary",
        "openlibrary-web-api-docs-2026-08-19",
        "openlibrary-book-adapter/v1",
        "openlibrary-source-record/v1",
        MAPPING_PROFILE_VERSION,
        NOW,
    )
    with pytest.raises(ValueError):
        OpenLibraryEvidenceProjection(
            EntityKind.WORK, target_ref, "title", value, ValueState.EXTERNAL, p
        )
    with pytest.raises(ValueError):
        OpenLibraryIdentifierProjection(EntityKind.WORK, "opaque", "isbn13", "bad", p)


def test_bibliographic_punctuation_is_evidence_but_never_leaks_through_repr():
    p = OpenLibraryMappingProvenance(
        "openlibrary",
        "openlibrary-web-api-docs-2026-08-19",
        "openlibrary-book-adapter/v1",
        "openlibrary-source-record/v1",
        MAPPING_PROFILE_VERSION,
        NOW,
    )
    value = OpenLibraryEvidenceProjection(
        EntityKind.WORK,
        "opaque",
        "title",
        "Synthetic A/B: A Study",
        ValueState.EXTERNAL,
        p,
    )
    assert value.value == "Synthetic A/B: A Study"
    assert value.value not in repr(value)


def test_target_binding_keys_are_typed_and_not_string_coerced():
    with pytest.raises((TypeError, ValueError)):
        map_openlibrary_record(WORK, observed_at=NOW, target_bindings={1: "opaque"})
    with pytest.raises(ValueError):
        map_openlibrary_record(
            WORK,
            observed_at=NOW,
            target_bindings={"openlibrary.work:OL1M": "opaque"},
        )


def test_mapping_is_redacted_typed_and_requires_all_candidate_bindings():
    p = OpenLibraryMappingProvenance(
        "openlibrary",
        "openlibrary-web-api-docs-2026-08-19",
        "openlibrary-book-adapter/v1",
        "openlibrary-source-record/v1",
        MAPPING_PROFILE_VERSION,
        NOW,
    )
    value = OpenLibraryEvidenceProjection(
        EntityKind.WORK, "work-ref", "title", "Synthetic Title", ValueState.EXTERNAL, p
    )
    identifier = OpenLibraryIdentifierProjection(
        EntityKind.WORK, "work-ref", "openlibrary.work", "OL1W", p
    )
    result = OpenLibraryMappingResult((identifier,), (value,), (), (), p)
    assert "Synthetic" not in repr(result)
    assert "OL1W" not in repr(identifier)
    with pytest.raises(ValueError):
        OpenLibraryMappingResult((identifier, identifier), (value,), (), (), p)
    edition = EditionSourceRecord(
        "OL2M", ("OL1W",), "Synthetic Edition", None, None, (), (), (), (), (), (), (), False
    )
    with pytest.raises(ValueError):
        map_openlibrary_record(edition, observed_at=NOW, target_id="edition-ref")
    referenced_author_work = WorkSourceRecord("OL4W", None, None, ("OL3A",), (), False)
    with pytest.raises(ValueError):
        map_openlibrary_record(referenced_author_work, observed_at=NOW, target_id="work-ref")
    mapped = map_openlibrary_record(
        referenced_author_work,
        observed_at=NOW,
        target_id="work-ref",
        target_bindings={"openlibrary.author:OL3A": "agent-ref"},
    )
    assert mapped.agent_candidates[0].target_ref == "agent-ref"
    search = SearchSourceRecord(WORK, (edition,), False)
    with pytest.raises(ValueError):
        map_openlibrary_record(
            search,
            observed_at=NOW,
            target_bindings={"openlibrary.work:OL1W": "work-ref"},
        )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            AuthorSourceRecord("OL10A", "Synthetic Alias", ("Synthetic Name",), None, None, False),
            AuthorSourceRecord("OL11A", "Synthetic Alias", ("Synthetic Name",), None, None, False),
        ),
        (
            AuthorSourceRecord("OL12A", "Synthetic Person", (), None, None, False),
            AuthorSourceRecord("OL13A", "Synthetic Person", (), None, None, False),
        ),
        (
            AuthorSourceRecord("OL14A", "Synthetic Name A", (), None, None, False),
            AuthorSourceRecord("OL14A", "Synthetic Name B", (), None, None, False),
        ),
    ],
)
def test_author_candidates_keep_olid_alias_homonym_and_name_conflict_boundaries(left, right):
    first = map_openlibrary_record(left, observed_at=NOW, target_id="agent-a")
    second = map_openlibrary_record(right, observed_at=NOW, target_id="agent-b")

    assert first.agent_candidates[0].author_olid != second.agent_candidates[0].author_olid or (
        first.agent_candidates[0].values != second.agent_candidates[0].values
    )
    assert all(
        value.state is ValueState.EXTERNAL
        for value in first.values + second.values
    )
    assert all(not hasattr(candidate, "resolution") for candidate in first.agent_candidates)


def test_missing_author_id_is_not_invented_by_mapping():
    with pytest.raises(ValueError):
        AuthorSourceRecord("", "Synthetic Name", (), None, None, False)
