from datetime import UTC, datetime

from foliotone.authority import (
    DEFAULT_AUTHOR_RESOLUTION_VERSION,
    NAME_NORMALIZATION_PROFILE,
    IDENTIFIER_NORMALIZATION_PROFILE,
    BibliographicEntityProfile,
    NormalizedIdentifier,
    NormalizedName,
    generate_agent_name_candidates,
    generate_bibliographic_entity_candidates,
    generate_edition_candidates,
    generate_metadata_entity_candidates,
    generate_series_candidates,
    generate_work_candidates,
    is_homonym_free_merge,
    normalize_agent_name,
    normalize_agent_name_text,
    normalize_identifier,
    normalize_identifier_text,
    normalize_identifier_for_profile,
)


NOW = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_author_name_candidate_plan_is_versioned_and_homonym_safe() -> None:
    candidates = generate_agent_name_candidates("Doe, John A. (Mark Twain)", observed_at=NOW)
    assert candidates
    assert all(candidate.provenance.source_version == DEFAULT_AUTHOR_RESOLUTION_VERSION for candidate in candidates)
    assert {candidate.field_name for candidate in candidates} == {
        "agent.name.canonical",
        "agent.name.normalized",
        "agent.name.sort_name",
        "agent.name.alias",
        "agent.name.pseudonym",
    }
    by_field = {candidate.field_name: candidate.value for candidate in candidates}
    assert by_field["agent.name.canonical"] == "Doe John A."
    assert by_field["agent.name.normalized"] == "doe john a."
    assert by_field["agent.name.sort_name"] == "John A. Doe"
    assert by_field["agent.name.alias"] == "john a. doe"
    assert by_field["agent.name.pseudonym"] == "Mark Twain"


def test_agent_name_homonym_gate_requires_disambiguation_hint() -> None:
    left = normalize_agent_name_text("Doe, John")
    right = normalize_agent_name_text("John Doe")
    assert not is_homonym_free_merge(left, right)
    assert is_homonym_free_merge(left, right, disambiguation="isbn:12345")


def test_credited_as_candidate_is_preserved() -> None:
    candidates = generate_agent_name_candidates("Samuel Clemens as Mark Twain", observed_at=NOW)
    by_field = {candidate.field_name: candidate.value for candidate in candidates}
    assert by_field["agent.name.credited_as"] == "Mark Twain"
    assert "agent.name.sort_name" not in by_field


def test_identifier_normalization_removes_noise_for_versioning() -> None:
    assert normalize_identifier_text("978-3-16-148410-0") == "9783161484100"
    assert normalize_identifier_for_profile("isbn", "978-3-16-148410-0") == "isbn:9783161484100"


def test_work_edition_and_series_candidates_emit_stable_normalized_aliases() -> None:
    work_candidates = generate_work_candidates("The Great Tale", observed_at=NOW)
    edition_candidates = generate_edition_candidates("The Great Tale: Signed Edition", observed_at=NOW)
    series_candidates = generate_series_candidates("Saga 1", observed_at=NOW)

    work_fields = {candidate.field_name for candidate in work_candidates}
    assert work_fields == {
        "work.title.canonical",
        "work.title.normalized",
        "work.title.alias",
    }

    edition_fields = {candidate.field_name for candidate in edition_candidates}
    assert "edition.title.canonical" in edition_fields
    assert "edition.title.normalized" in edition_fields
    assert "edition.title.alias" in edition_fields

    series_fields = {candidate.field_name for candidate in series_candidates}
    assert series_fields == {
        "series.title.canonical",
        "series.title.normalized",
    }


def test_name_normalization_is_versioned_and_non_destructive() -> None:
    result = normalize_agent_name("  Åsán,  Nunez  ")
    assert isinstance(result, NormalizedName)
    assert result.original == "Åsán,  Nunez"
    assert result.normalized == "nunez asan"
    assert result.changed
    assert result.profile == NAME_NORMALIZATION_PROFILE


def test_identifier_normalization_is_versioned_and_non_destructive() -> None:
    result = normalize_identifier("  urn:ISBN 978-0-00-711-711-6 ")
    assert isinstance(result, NormalizedIdentifier)
    assert result.original == "urn:ISBN 978-0-00-711-711-6"
    assert result.normalized == "urn:isbn9780007117116"
    assert result.changed
    assert result.profile == IDENTIFIER_NORMALIZATION_PROFILE


def test_metadata_entity_candidates_generate_contributor_and_identifier_rows() -> None:
    candidates = generate_metadata_entity_candidates(
        work_title="Project Babel",
        edition_title="Project Babel: First Edition",
        series_name="Babel Saga",
        language="EN US",
        translator="Jane Doe",
        contributor_names=("Alice Walker", "Béla Lugosi"),
        identifiers=(("isbn", "978-3-16-148410-0"), ("urn", "urn:ISBN-1")),
        observed_at=NOW,
    )
    fields = {candidate.field_name for candidate in candidates}

    assert "work.title.canonical" in fields
    assert "edition.title.canonical" in fields
    assert "series.title.canonical" in fields
    assert "edition.language" in fields
    assert "agent.name.canonical" in fields
    assert len([field for field in fields if field.startswith("agent.name.")]) >= 1
    assert "identifier.isbn" in fields
    assert "identifier.urn" in fields

    profile_normalized = generate_bibliographic_entity_candidates(
        work_title="Project Babel",
        translator="Jane Doe",
        contributor_names=("Alice Walker",),
        identifiers=(("isbn", "978-3-16-148410-0"),),
        observed_at=NOW,
        profile=BibliographicEntityProfile(version="metadata-resolution/v1"),
    )
    assert (
        profile_normalized == generate_metadata_entity_candidates(
            work_title="Project Babel",
            translator="Jane Doe",
            contributor_names=("Alice Walker",),
            identifiers=(("isbn", "978-3-16-148410-0"),),
            observed_at=NOW,
            profile=BibliographicEntityProfile(version="metadata-resolution/v1"),
        )
    )
