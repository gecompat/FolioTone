from __future__ import annotations

import pytest

from foliotone.adapters.openlibrary import (
    OpenLibraryIdentifier,
    OpenLibraryQueryBuilder,
    OpenLibraryQueryRoute,
    OpenLibraryRequest,
    OpenLibraryResolvedAuthorQuery,
    OpenLibraryRouteKind,
)
from foliotone.core import EntityId
from foliotone.enrichment import BookKnowledgeQuery

DECISION_ID = EntityId.parse("00000000-0000-0000-0000-000000000001")


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    (
        ("openlibrary.edition", "OL123M", "/books/OL123M.json"),
        ("openlibrary.work", "OL123W", "/works/OL123W.json"),
        ("isbn13", "978-0-306-40615-7", "/isbn/9780306406157.json"),
        ("isbn10", "0-306-40615-2", "/isbn/0306406152.json"),
        ("oclc", "123", "/api/books?bibkeys=OCLC%3A123&jscmd=data&format=json"),
        ("lccn", "sn123", "/api/books?bibkeys=LCCN%3Asn123&jscmd=data&format=json"),
    ),
)
def test_direct_routes_have_golden_urls(kind: str, value: str, expected: str) -> None:
    route = OpenLibraryQueryBuilder().build(identifiers=((kind, value),))
    assert route is not None
    assert route.urls == (f"https://openlibrary.org{expected}",)


def test_identifier_priority_deduplicates_and_sorts() -> None:
    route = OpenLibraryQueryBuilder().build(
        identifiers=(
            ("oclc", "9"),
            ("openlibrary.work", "OL20W"),
            ("openlibrary.work", "OL10W"),
            ("openlibrary.work", "OL10W"),
        )
    )
    assert route is not None
    assert route.urls == ("https://openlibrary.org/works/OL10W.json",)


def test_search_uses_fixed_fields_and_exact_second_page_rule() -> None:
    author = OpenLibraryResolvedAuthorQuery("A title", "An Author", DECISION_ID)
    route = OpenLibraryQueryBuilder().build(resolved_author=author)
    assert route is not None
    assert "q%3D" not in route.urls[0]
    assert "offset=0" in route.urls[0]
    assert (
        len(route.with_search_page_two(num_found=21, page_one_has_strong_doc=False).requests)
        == 2
    )
    assert (
        len(route.with_search_page_two(num_found=21, page_one_has_strong_doc=True).requests)
        == 1
    )
    assert (
        len(route.with_search_page_two(num_found=10, page_one_has_strong_doc=False).requests)
        == 1
    )


def test_direct_route_can_fetch_only_one_referenced_author() -> None:
    route = OpenLibraryQueryBuilder().build(
        identifiers=(("openlibrary.edition", "OL123M"),),
        referenced_author_olid="OL777A",
    )
    assert route is not None
    assert route.urls == (
        "https://openlibrary.org/books/OL123M.json",
        "https://openlibrary.org/authors/OL777A.json",
    )


def test_unresolved_book_author_never_becomes_online_search() -> None:
    query = BookKnowledgeQuery(title="A title", authors=("An Author",))
    assert OpenLibraryQueryBuilder().build(query) is None
    with pytest.raises(ValueError):
        OpenLibraryQueryBuilder().build(query, referenced_author_olid="OL777A")


def test_query_and_explicit_resolved_title_must_match() -> None:
    query = BookKnowledgeQuery(title="One title")
    author = OpenLibraryResolvedAuthorQuery("Other title", "Author", DECISION_ID)
    with pytest.raises(ValueError):
        OpenLibraryQueryBuilder().build(query, resolved_author=author)


def test_sensitive_values_are_absent_from_representations() -> None:
    author = OpenLibraryResolvedAuthorQuery("Secret Title", "Secret Author", DECISION_ID)
    route = OpenLibraryQueryBuilder().build(resolved_author=author)
    assert route is not None
    rendered = repr(author) + repr(route) + repr(route.requests[0])
    assert all(secret not in rendered for secret in ("Secret", "decision", "openlibrary.org"))


def test_direct_request_and_route_reject_adversarial_shapes() -> None:
    with pytest.raises(ValueError):
        OpenLibraryRequest(OpenLibraryRouteKind.WORK, "/works/OL1W.json", (("q", "free"),))
    with pytest.raises(ValueError):
        OpenLibraryRequest(
            OpenLibraryRouteKind.SEARCH,
            "/search.json",
            (
                ("title", "Title"),
                ("author", "Author"),
                ("fields", "key"),
                ("limit", "10"),
                ("offset", "0"),
            ),
        )
    first = OpenLibraryRequest(OpenLibraryRouteKind.WORK, "/works/OL1W.json")
    with pytest.raises(ValueError):
        OpenLibraryQueryRoute(
            OpenLibraryRouteKind.EDITION,
            (first,),
            identifier=OpenLibraryIdentifier("openlibrary.edition", "OL1M"),
        )
    with pytest.raises(ValueError):
        OpenLibraryRequest(OpenLibraryRouteKind.WORK, "/works/OL1W.json", (("q", 1),))  # type: ignore[arg-type]


def test_page_two_arguments_are_strictly_typed() -> None:
    route = OpenLibraryQueryBuilder().build(
        resolved_author=OpenLibraryResolvedAuthorQuery("Title", "Author", DECISION_ID)
    )
    assert route is not None
    with pytest.raises(ValueError):
        route.with_search_page_two(num_found=True, page_one_has_strong_doc=False)
    with pytest.raises(ValueError):
        route.with_search_page_two(num_found=-1, page_one_has_strong_doc=False)
    with pytest.raises(ValueError):
        route.with_search_page_two(num_found=11, page_one_has_strong_doc=1)  # type: ignore[arg-type]


def test_search_route_cannot_change_query_between_pages() -> None:
    author = OpenLibraryResolvedAuthorQuery("Title", "Author", DECISION_ID)
    route = OpenLibraryQueryBuilder().build(resolved_author=author)
    assert route is not None
    first = route.requests[0]
    second = OpenLibraryRequest(
        OpenLibraryRouteKind.SEARCH,
        "/search.json",
        (
            ("title", "Other Title"),
            ("author", "Author"),
            ("fields", first.query[2][1]),
            ("limit", "10"),
            ("offset", "10"),
        ),
    )
    with pytest.raises(ValueError):
        OpenLibraryQueryRoute(OpenLibraryRouteKind.SEARCH, (first, second), search=author)


@pytest.mark.parametrize(
    ("kind", "value"),
    (
        ("openlibrary.edition", "OL123W"),
        ("openlibrary.work", "OL123M"),
        ("isbn13", "9780306406158"),
        ("isbn10", "0306406153"),
        ("oclc", "123/4"),
        ("lccn", "bad value"),
    ),
)
def test_invalid_identifiers_are_rejected(kind: str, value: str) -> None:
    with pytest.raises(ValueError):
        OpenLibraryQueryBuilder().build(identifiers=((kind, value),))


@pytest.mark.parametrize("text", ("", "C:\\book.epub", "../book", "https://x", "book.pdf"))
def test_search_rejects_path_and_filename_like_text(text: str) -> None:
    with pytest.raises(ValueError):
        OpenLibraryResolvedAuthorQuery(text, "Author", DECISION_ID)
