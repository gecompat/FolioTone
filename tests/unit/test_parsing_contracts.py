from datetime import UTC, datetime

import pytest

from foliotone.parsing import FilenameParser, PathContextAnalyzer

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
