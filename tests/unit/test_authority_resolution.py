from datetime import UTC, datetime

from foliotone.authority import (
    DEFAULT_AUTHOR_RESOLUTION_VERSION,
    generate_agent_name_candidates,
    generate_edition_candidates,
    generate_series_candidates,
    generate_work_candidates,
    is_homonym_free_merge,
    normalize_agent_name,
    normalize_identifier,
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
    assert by_field["agent.name.normalized"] == "john a. doe"
    assert by_field["agent.name.sort_name"] == "John A. Doe"
    assert by_field["agent.name.alias"] == "john a. doe"
    assert by_field["agent.name.pseudonym"] == "Mark Twain"


def test_agent_name_homonym_gate_requires_disambiguation_hint() -> None:
    left = normalize_agent_name("Doe, John")
    right = normalize_agent_name("John Doe")
    assert not is_homonym_free_merge(left, right)
    assert is_homonym_free_merge(left, right, disambiguation="isbn:12345")


def test_credited_as_candidate_is_preserved() -> None:
    candidates = generate_agent_name_candidates("Samuel Clemens as Mark Twain", observed_at=NOW)
    by_field = {candidate.field_name: candidate.value for candidate in candidates}
    assert by_field["agent.name.credited_as"] == "Mark Twain"
    assert "agent.name.sort_name" not in by_field


def test_identifier_normalization_removes_noise_for_versioning() -> None:
    assert normalize_identifier("978-3-16-148410-0") == "9783161484100"
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

    assert {candidate.field_name for candidate in series_candidates} == {
        "series.title.canonical",
        "series.title.normalized",
        "series.title.alias",
    }
