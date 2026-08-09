from datetime import UTC, datetime

import pytest

from foliotone.parsing import (
    FilenameParser,
    FilenameParsingProfile,
    FilenameParsingRule,
    PathContextAnalyzer,
    RuleBasedFilenameParser,
)

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def test_filename_parser_emits_versioned_derived_candidate():
    (candidate,) = FilenameParser("1").parse("Title.epub", observed_at=NOW)

    assert (candidate.field_name, candidate.value, candidate.source_location) == (
        "title",
        "Title",
        "filename.stem",
    )
    assert (
        candidate.provenance.source_kind,
        candidate.provenance.source_name,
        candidate.provenance.source_version,
        candidate.provenance.observed_at,
        candidate.confidence,
    ) == ("derived", "FilenameParser", "1", NOW, 0.2)


@pytest.mark.parametrize("filename", ("", "  ", "Author/Title.epub", r"Author\Title.epub"))
def test_filename_parser_rejects_empty_values_and_paths(filename: str):
    with pytest.raises(ValueError):
        FilenameParser("1").parse(filename, observed_at=NOW)


def test_filename_parser_rejects_an_empty_version():
    with pytest.raises(ValueError, match="version must not be empty"):
        FilenameParser(" ")


def test_path_analyzer_emits_parent_context_from_windows_or_posix_relative_path():
    analyzer = PathContextAnalyzer("1")

    (posix_candidate,) = analyzer.analyze("Author/Title.epub", observed_at=NOW)
    (windows_candidate,) = analyzer.analyze(r"Author\Title.epub", observed_at=NOW)

    assert (posix_candidate.field_name, posix_candidate.value, posix_candidate.source_location) == (
        "path_context",
        "Author",
        "path.parent",
    )
    assert windows_candidate == posix_candidate


def test_path_analyzer_returns_no_candidate_for_a_filename_without_parent():
    assert PathContextAnalyzer("1").analyze("Title.epub", observed_at=NOW) == ()


@pytest.mark.parametrize("relative_path", ("/private/Author/Title.epub", "../Author/Title.epub"))
def test_path_analyzer_rejects_absolute_and_traversal_paths(relative_path: str):
    with pytest.raises(ValueError, match="relative_path must be a safe scan-root-relative path"):
        PathContextAnalyzer("1").analyze(relative_path, observed_at=NOW)


def test_parsers_require_an_aware_observation_timestamp():
    naive_now = datetime(2026, 8, 9)

    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        FilenameParser("1").parse("Title.epub", observed_at=naive_now)


def test_rule_based_parser_emits_versioned_candidates_from_a_configured_rule():
    parser = RuleBasedFilenameParser(
        FilenameParsingProfile(
            version="collection-a/1",
            rules=(
                FilenameParsingRule(
                    name="book",
                    pattern=(
                        r"(?P<author>.+?) - (?P<series>.+?) #(?P<volume>\d+) - "
                        r"(?P<title>.+?) \((?P<year>\d{4})\) \[(?P<language>[a-z]{2})\]"
                    ),
                    confidence=0.7,
                ),
            ),
        )
    )

    candidates = parser.parse(
        "Ursula Le Guin - Earthsea #03 - The Farthest Shore (1972) [en].epub",
        observed_at=NOW,
    )

    assert [(item.field_name, item.value) for item in candidates] == [
        ("author", "Ursula Le Guin"),
        ("series", "Earthsea"),
        ("volume", "03"),
        ("title", "The Farthest Shore"),
        ("year", "1972"),
        ("language", "en"),
    ]
    assert all(item.provenance.source_version == "collection-a/1" for item in candidates)
    assert all(item.confidence == 0.7 for item in candidates)


def test_rule_based_parser_supports_track_and_optional_disc_conventions():
    parser = RuleBasedFilenameParser(
        FilenameParsingProfile(
            version="music/1",
            rules=(
                FilenameParsingRule(
                    name="track",
                    pattern=r"(?:D(?P<disc>\d+) )?(?P<track>\d+) - (?P<title>.+)",
                ),
            ),
        )
    )

    candidates = parser.parse("D2 07 - Allegro.flac", observed_at=NOW)

    assert [(item.field_name, item.value) for item in candidates] == [
        ("disc", "2"),
        ("track", "07"),
        ("title", "Allegro"),
    ]


def test_rule_based_parser_uses_the_first_matching_rule_and_returns_no_guess():
    parser = RuleBasedFilenameParser(
        FilenameParsingProfile(
            version="1",
            rules=(
                FilenameParsingRule(
                    name="specific",
                    pattern=r"(?P<title>.+) \[(?P<language>[a-z]{2})\]",
                ),
                FilenameParsingRule(name="fallback", pattern=r"(?P<title>.+)"),
            ),
        )
    )

    candidates = parser.parse("Title [de].epub", observed_at=NOW)

    assert [(item.field_name, item.value) for item in candidates] == [
        ("title", "Title"),
        ("language", "de"),
    ]
    no_match_parser = RuleBasedFilenameParser(
        FilenameParsingProfile(
            version="1",
            rules=(FilenameParsingRule(name="language", pattern=r"(?P<title>.+) \[[a-z]{2}\]"),),
        )
    )
    assert no_match_parser.parse("Untitled.epub", observed_at=NOW) == ()


@pytest.mark.parametrize("pattern", (r"(?P<title>", r".+"))
def test_rule_requires_a_valid_named_capture_pattern(pattern: str):
    with pytest.raises(ValueError):
        FilenameParsingRule(name="invalid", pattern=pattern)


def test_profile_requires_unique_rule_names():
    rule = FilenameParsingRule(name="duplicate", pattern=r"(?P<title>.+)")
    with pytest.raises(ValueError, match="rule names must be unique"):
        FilenameParsingProfile(version="1", rules=(rule, rule))
