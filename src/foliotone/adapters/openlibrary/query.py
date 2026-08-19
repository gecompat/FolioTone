"""Pure, bounded query and route contracts for the Open Library adapter.

This module deliberately contains no HTTP client.  It turns already structured
local candidates into one of the fixed ADR-0036 request shapes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import quote

from foliotone.core import EntityId
from foliotone.enrichment.contracts import BookKnowledgeQuery

OPENLIBRARY_HOST: Final = "openlibrary.org"
OPENLIBRARY_SCHEME: Final = "https"
OPENLIBRARY_PORT: Final = 443
OPENLIBRARY_SEARCH_FIELDS: Final = (
    "key,title,author_key,author_name,first_publish_year,edition_count,"
    "editions,editions.key,editions.title,editions.subtitle,editions.isbn,"
    "editions.language,editions.publisher,editions.publish_date"
)
OPENLIBRARY_SEARCH_LIMIT: Final = 10
OPENLIBRARY_SEARCH_OFFSETS: Final = (0, 10)
MAX_QUERY_TEXT_CODEPOINTS: Final = 512

_OLID = re.compile(r"^OL[0-9]+(?P<kind>[MWA])$")
_ISBN13 = re.compile(r"^[0-9]{13}$")
_ISBN10 = re.compile(r"^[0-9]{9}[0-9X]$")
_OCLC = re.compile(r"^[0-9]{1,16}$")
_LCCN = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_BAD_QUERY_TEXT = re.compile(
    r"(?:\x00|[\r\n]|://|file:|\.\.|[/\\]|^[A-Za-z]:|\.(?:epub|mobi|azw|azw3|pdf)$)",
    re.IGNORECASE,
)


class OpenLibraryIdentifierKind(StrEnum):
    EDITION = "openlibrary.edition"
    WORK = "openlibrary.work"
    ISBN13 = "isbn13"
    ISBN10 = "isbn10"
    OCLC = "oclc"
    LCCN = "lccn"


class OpenLibraryRouteKind(StrEnum):
    EDITION = "EDITION"
    WORK = "WORK"
    ISBN = "ISBN"
    LEGACY_IDENTIFIER = "LEGACY_IDENTIFIER"
    SEARCH = "SEARCH"
    AUTHOR = "AUTHOR"


@dataclass(frozen=True, slots=True)
class OpenLibraryResolvedAuthorQuery:
    """A title plus exactly one locally accepted author candidate."""

    title: str
    resolved_author_name: str
    resolution_decision_id: EntityId

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _validate_query_text(self.title, "title"))
        object.__setattr__(
            self,
            "resolved_author_name",
            _validate_query_text(self.resolved_author_name, "resolved_author_name"),
        )
        if not isinstance(self.resolution_decision_id, EntityId):
            raise ValueError("resolution_decision_id must be an EntityId")

    def __repr__(self) -> str:
        return "OpenLibraryResolvedAuthorQuery(<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryIdentifier:
    kind: OpenLibraryIdentifierKind | str
    value: str

    def __post_init__(self) -> None:
        try:
            kind = OpenLibraryIdentifierKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported Open Library identifier kind") from exc
        value = _normalize_identifier(kind, self.value)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)

    def __repr__(self) -> str:
        return f"OpenLibraryIdentifier(kind={self.kind!r}, value=<redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryRequest:
    """One immutable request description; no arbitrary host/path/query fields."""

    route_kind: OpenLibraryRouteKind
    path: str
    query: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        try:
            route_kind = OpenLibraryRouteKind(self.route_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported route kind") from exc
        if not self.path.startswith("/") or any(ch in self.path for ch in "\\\x00\r\n"):
            raise ValueError("path must be an approved absolute API path")
        if not self.path.endswith(".json") and self.path != "/api/books":
            raise ValueError("path must end in .json")
        query = tuple(self.query)
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(value, str) for value in pair)
            for pair in query
        ):
            raise ValueError("query parameters must be pairs of strings")
        if len({key for key, _ in query}) != len(query):
            raise ValueError("query parameters must be unique")
        if not _approved_shape(route_kind, self.path, query):
            raise ValueError("path or query is outside the approved Open Library shapes")
        object.__setattr__(self, "route_kind", route_kind)
        object.__setattr__(self, "query", query)

    @property
    def method(self) -> str:
        return "GET"

    @property
    def scheme(self) -> str:
        return OPENLIBRARY_SCHEME

    @property
    def host(self) -> str:
        return OPENLIBRARY_HOST

    @property
    def port(self) -> int:
        return OPENLIBRARY_PORT

    @property
    def url(self) -> str:
        suffix = "" if not self.query else "?" + "&".join(
            f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in self.query
        )
        return f"{OPENLIBRARY_SCHEME}://{OPENLIBRARY_HOST}{self.path}{suffix}"

    def __repr__(self) -> str:
        return f"OpenLibraryRequest(route_kind={self.route_kind!r}, <redacted>)"


@dataclass(frozen=True, slots=True)
class OpenLibraryQueryRoute:
    route_kind: OpenLibraryRouteKind
    requests: tuple[OpenLibraryRequest, ...]
    identifier: OpenLibraryIdentifier | None = None
    search: OpenLibraryResolvedAuthorQuery | None = None

    def __post_init__(self) -> None:
        requests = tuple(self.requests)
        object.__setattr__(self, "requests", requests)
        if self.identifier is not None and not isinstance(self.identifier, OpenLibraryIdentifier):
            raise ValueError("identifier must be an OpenLibraryIdentifier")
        if self.search is not None and not isinstance(self.search, OpenLibraryResolvedAuthorQuery):
            raise ValueError("search must be an OpenLibraryResolvedAuthorQuery")
        try:
            route_kind = OpenLibraryRouteKind(self.route_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported route kind") from exc
        if not requests or len(requests) > 2:
            raise ValueError("a route must contain one or two requests")
        if any(not isinstance(request, OpenLibraryRequest) for request in requests):
            raise ValueError("requests must be OpenLibraryRequest values")
        if route_kind is OpenLibraryRouteKind.SEARCH:
            if self.identifier is not None or self.search is None:
                raise ValueError("Search routes require only search query metadata")
            if any(
                request.route_kind is not OpenLibraryRouteKind.SEARCH
                for request in requests
            ):
                raise ValueError("Search route contains a non-Search request")
            if requests[0] != _search_request(self.search, 0):
                raise ValueError("Search request does not match its query metadata")
            if requests[0].query[-1] != ("offset", "0"):
                raise ValueError("a search route starts at offset zero")
            if len(requests) == 2:
                first, second = requests
                if (
                    second.query[:-1] != first.query[:-1]
                    or second.query[-1] != ("offset", "10")
                    or second != _search_request(self.search, 10)
                ):
                    raise ValueError("Search page two must match page one except offset")
        elif route_kind is OpenLibraryRouteKind.AUTHOR:
            raise ValueError("Author is only a second direct request")
        else:
            if self.identifier is None or self.search is not None:
                raise ValueError("direct routes require one identifier")
            first, *rest = requests
            if first.route_kind is not route_kind or first != _direct_request(self.identifier):
                raise ValueError("direct route does not match its identifier")
            if rest and (len(rest) != 1 or rest[0].route_kind is not OpenLibraryRouteKind.AUTHOR):
                raise ValueError("direct routes allow only one referenced Author request")
        object.__setattr__(self, "route_kind", route_kind)

    def __repr__(self) -> str:
        return (
            f"OpenLibraryQueryRoute(route_kind={self.route_kind!r}, "
            f"request_count={len(self.requests)})"
        )

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(request.url for request in self.requests)

    def with_search_page_two(
        self, *, num_found: int, page_one_has_strong_doc: bool
    ) -> OpenLibraryQueryRoute:
        if isinstance(num_found, bool) or not isinstance(num_found, int) or num_found < 0:
            raise ValueError("num_found must be a nonnegative integer")
        if not isinstance(page_one_has_strong_doc, bool):
            raise ValueError("page_one_has_strong_doc must be boolean")
        if self.route_kind is not OpenLibraryRouteKind.SEARCH:
            raise ValueError("pagination is only valid for Search")
        if len(self.requests) != 1 or num_found <= 10 or page_one_has_strong_doc:
            return self
        first = self.requests[0]
        second = _search_request(self.search, 10) if self.search else None
        if second is None:
            raise ValueError("search route is missing its query")
        return OpenLibraryQueryRoute(self.route_kind, (first, second), search=self.search)


class OpenLibraryQueryBuilder:
    """Build exactly one deterministic route from structured local candidates."""

    def build(
        self,
        query: BookKnowledgeQuery | None = None,
        *,
        identifiers: Iterable[tuple[str, str] | OpenLibraryIdentifier] = (),
        resolved_author: OpenLibraryResolvedAuthorQuery | None = None,
        referenced_author_olid: str | None = None,
    ) -> OpenLibraryQueryRoute | None:
        values: list[OpenLibraryIdentifier] = []
        if query is not None:
            if not isinstance(query, BookKnowledgeQuery):
                raise TypeError("query must be a BookKnowledgeQuery")
            identifiers = (*query.identifiers, *identifiers)
            if (
                resolved_author is not None
                and _validate_query_text(query.title, "title") != resolved_author.title
            ):
                raise ValueError("BookKnowledgeQuery title does not match resolved author query")
        for item in identifiers:
            values.append(
                item
                if isinstance(item, OpenLibraryIdentifier)
                else OpenLibraryIdentifier(item[0], item[1])
            )
        selected = _select_identifier(values)
        if selected is not None:
            route = _direct_route(selected)
            if referenced_author_olid is not None:
                author = _author_request(referenced_author_olid)
                route = OpenLibraryQueryRoute(
                    route.route_kind, (*route.requests, author), route.identifier
                )
            return route
        if referenced_author_olid is not None:
            raise ValueError("referenced Author requires a direct book route")
        if resolved_author is None:
            return None
        return OpenLibraryQueryRoute(
            OpenLibraryRouteKind.SEARCH,
            (_search_request(resolved_author, 0),),
            search=resolved_author,
        )

def build_openlibrary_route(
    query: BookKnowledgeQuery | None = None,
    *,
    identifiers: Iterable[tuple[str, str] | OpenLibraryIdentifier] = (),
    resolved_author: OpenLibraryResolvedAuthorQuery | None = None,
    referenced_author_olid: str | None = None,
) -> OpenLibraryQueryRoute | None:
    return OpenLibraryQueryBuilder().build(
        query,
        identifiers=identifiers,
        resolved_author=resolved_author,
        referenced_author_olid=referenced_author_olid,
    )


def _select_identifier(values: Iterable[OpenLibraryIdentifier]) -> OpenLibraryIdentifier | None:
    grouped: dict[OpenLibraryIdentifierKind, set[str]] = {}
    for value in values:
        kind = OpenLibraryIdentifierKind(value.kind)
        grouped.setdefault(kind, set()).add(value.value)
    for kind in OpenLibraryIdentifierKind:
        if grouped.get(kind):
            return OpenLibraryIdentifier(kind, sorted(grouped[kind])[0])
    return None


def _direct_route(identifier: OpenLibraryIdentifier) -> OpenLibraryQueryRoute:
    request = _direct_request(identifier)
    return OpenLibraryQueryRoute(request.route_kind, (request,), identifier=identifier)


def _direct_request(identifier: OpenLibraryIdentifier) -> OpenLibraryRequest:
    identifier_kind = OpenLibraryIdentifierKind(identifier.kind)
    value = quote(identifier.value, safe="")
    if identifier_kind is OpenLibraryIdentifierKind.EDITION:
        return OpenLibraryRequest(OpenLibraryRouteKind.EDITION, f"/books/{value}.json")
    elif identifier_kind is OpenLibraryIdentifierKind.WORK:
        return OpenLibraryRequest(OpenLibraryRouteKind.WORK, f"/works/{value}.json")
    elif identifier_kind in {OpenLibraryIdentifierKind.ISBN10, OpenLibraryIdentifierKind.ISBN13}:
        return OpenLibraryRequest(OpenLibraryRouteKind.ISBN, f"/isbn/{value}.json")
    else:
        return OpenLibraryRequest(
            OpenLibraryRouteKind.LEGACY_IDENTIFIER,
            "/api/books",
            (
                ("bibkeys", f"{identifier_kind.name}:{identifier.value}"),
                ("jscmd", "data"),
                ("format", "json"),
            ),
        )


def _author_request(value: str) -> OpenLibraryRequest:
    normalized = _normalize_olid(value, "A")
    return OpenLibraryRequest(OpenLibraryRouteKind.AUTHOR, f"/authors/{normalized}.json")


def _search_request(
    search: OpenLibraryResolvedAuthorQuery | None, offset: int
) -> OpenLibraryRequest:
    if search is None or offset not in OPENLIBRARY_SEARCH_OFFSETS:
        raise ValueError("invalid Search route")
    return OpenLibraryRequest(
        OpenLibraryRouteKind.SEARCH,
        "/search.json",
        (
            ("title", search.title),
            ("author", search.resolved_author_name),
            ("fields", OPENLIBRARY_SEARCH_FIELDS),
            ("limit", str(OPENLIBRARY_SEARCH_LIMIT)),
            ("offset", str(offset)),
        ),
    )


def _approved_shape(
    route_kind: OpenLibraryRouteKind,
    path: str,
    query: tuple[tuple[str, str], ...],
) -> bool:
    if route_kind is OpenLibraryRouteKind.EDITION:
        return re.fullmatch(r"/books/OL[0-9]+M\.json", path) is not None and not query
    if route_kind is OpenLibraryRouteKind.WORK:
        return re.fullmatch(r"/works/OL[0-9]+W\.json", path) is not None and not query
    if route_kind is OpenLibraryRouteKind.AUTHOR:
        return re.fullmatch(r"/authors/OL[0-9]+A\.json", path) is not None and not query
    if route_kind is OpenLibraryRouteKind.ISBN:
        match = re.fullmatch(r"/isbn/([0-9X]+)\.json", path)
        return bool(match and _valid_isbn_path_value(match.group(1)) and not query)
    if route_kind is OpenLibraryRouteKind.LEGACY_IDENTIFIER:
        if path != "/api/books" or tuple(key for key, _ in query) != (
            "bibkeys",
            "jscmd",
            "format",
        ):
            return False
        values = dict(query)
        if values.get("jscmd") != "data" or values.get("format") != "json":
            return False
        match = re.fullmatch(r"(OCLC|LCCN):(.+)", values.get("bibkeys", ""))
        return bool(
            match
            and (
                _OCLC.fullmatch(match.group(2)) is not None
                if match.group(1) == "OCLC"
                else _LCCN.fullmatch(match.group(2)) is not None
            )
        )
    if route_kind is OpenLibraryRouteKind.SEARCH:
        if path != "/search.json" or tuple(key for key, _ in query) != (
            "title",
            "author",
            "fields",
            "limit",
            "offset",
        ):
            return False
        return (
            _valid_query_text_value(query[0][1])
            and _valid_query_text_value(query[1][1])
            and query[2][1] == OPENLIBRARY_SEARCH_FIELDS
            and query[3][1] == "10"
            and query[4][1] in {"0", "10"}
        )
    return False


def _valid_isbn_path_value(value: str) -> bool:
    if _ISBN13.fullmatch(value):
        return sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(value)) % 10 == 0
    if _ISBN10.fullmatch(value):
        return sum((10 - i) * (10 if d == "X" else int(d)) for i, d in enumerate(value)) % 11 == 0
    return False


def _valid_query_text_value(value: str) -> bool:
    try:
        _validate_query_text(value, "query")
    except ValueError:
        return False
    return True


def _normalize_identifier(kind: OpenLibraryIdentifierKind, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("identifier value must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if kind is OpenLibraryIdentifierKind.EDITION:
        return _normalize_olid(value, "M")
    if kind is OpenLibraryIdentifierKind.WORK:
        return _normalize_olid(value, "W")
    if kind is OpenLibraryIdentifierKind.ISBN13:
        compact = value.replace("-", "").replace(" ", "")
        checksum = sum(
            int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(compact)
        )
        if not _ISBN13.fullmatch(compact) or checksum % 10:
            raise ValueError("invalid ISBN-13")
        return compact
    if kind is OpenLibraryIdentifierKind.ISBN10:
        compact = value.replace("-", "").replace(" ", "").upper()
        checksum = sum(
            (10 - i) * (10 if d == "X" else int(d)) for i, d in enumerate(compact)
        )
        if not _ISBN10.fullmatch(compact) or checksum % 11:
            raise ValueError("invalid ISBN-10")
        return compact
    if kind is OpenLibraryIdentifierKind.OCLC:
        if not _OCLC.fullmatch(value):
            raise ValueError("invalid OCLC")
        return value
    if not _LCCN.fullmatch(value):
        raise ValueError("invalid LCCN")
    return value


def _normalize_olid(value: str, expected_kind: str) -> str:
    if not isinstance(value, str):
        raise ValueError("OLID must be text")
    value = unicodedata.normalize("NFC", value).strip().upper()
    match = _OLID.fullmatch(value)
    if match is None or match.group("kind") != expected_kind:
        raise ValueError(f"invalid OLID kind; expected {expected_kind}")
    return value


def _validate_query_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if not value or len(value) > MAX_QUERY_TEXT_CODEPOINTS or _BAD_QUERY_TEXT.search(value):
        raise ValueError(f"invalid {field}")
    return value


__all__ = [
    "MAX_QUERY_TEXT_CODEPOINTS",
    "OPENLIBRARY_HOST",
    "OPENLIBRARY_PORT",
    "OPENLIBRARY_SCHEME",
    "OPENLIBRARY_SEARCH_FIELDS",
    "OpenLibraryIdentifier",
    "OpenLibraryIdentifierKind",
    "OpenLibraryQueryBuilder",
    "OpenLibraryQueryRoute",
    "OpenLibraryRequest",
    "OpenLibraryResolvedAuthorQuery",
    "OpenLibraryRouteKind",
    "build_openlibrary_route",
]
