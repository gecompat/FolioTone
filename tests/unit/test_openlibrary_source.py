from __future__ import annotations

import json
from pathlib import Path

import pytest

from foliotone.adapters.openlibrary import (
    OpenLibraryRequest,
    OpenLibraryRouteKind,
    OpenLibrarySourceStatus,
    parse_openlibrary_source,
)
from foliotone.adapters.openlibrary.source import (
    EditionSourceRecord,
    OpenLibrarySourceEnvelope,
    OpenLibrarySourceParseResult,
    WorkSourceRecord,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openlibrary" / "v1"


def request(kind: OpenLibraryRouteKind, fixture: str | None = None) -> OpenLibraryRequest:
    paths = {
        OpenLibraryRouteKind.WORK: "/works/OL1W.json",
        OpenLibraryRouteKind.EDITION: "/books/OL900000002M.json",
        OpenLibraryRouteKind.ISBN: "/isbn/9000000000001.json",
        OpenLibraryRouteKind.AUTHOR: "/authors/OL900000001A.json",
        OpenLibraryRouteKind.LEGACY_IDENTIFIER: "/api/books",
        OpenLibraryRouteKind.SEARCH: "/search.json",
    }
    query = (
        (
            (
                "bibkeys",
                ("LCCN:synthetic-9002" if fixture == "legacy_lccn.json" else "OCLC:900000000002"),
            ),
            ("jscmd", "data"),
            ("format", "json"),
        )
        if kind is OpenLibraryRouteKind.LEGACY_IDENTIFIER
        else (
            ("title", "Synthetic Title"),
            ("author", "Synthetic Author"),
            (
                "fields",
                "key,title,author_key,author_name,first_publish_year,edition_count,editions,editions.key,editions.title,editions.subtitle,editions.isbn,editions.language,editions.publisher,editions.publish_date",
            ),
            ("limit", "10"),
            ("offset", "0"),
        )
        if kind is OpenLibraryRouteKind.SEARCH
        else ()
    )
    if fixture == "sparse.json":
        paths[kind] = "/works/OL900000006W.json"
    elif fixture == "work.json":
        paths[kind] = "/works/OL900000001W.json"
    if fixture == "search_page_2.json":
        query = tuple((key, "10" if key == "offset" else value) for key, value in query)
    return OpenLibraryRequest(kind, paths[kind], query)


@pytest.mark.parametrize(
    ("fixture", "kind", "status"),
    (
        ("work.json", OpenLibraryRouteKind.WORK, OpenLibrarySourceStatus.SUCCESS),
        ("edition.json", OpenLibraryRouteKind.EDITION, OpenLibrarySourceStatus.SUCCESS),
        ("isbn.json", OpenLibraryRouteKind.ISBN, OpenLibrarySourceStatus.SUCCESS),
        ("author.json", OpenLibraryRouteKind.AUTHOR, OpenLibrarySourceStatus.SUCCESS),
        (
            "legacy_oclc.json",
            OpenLibraryRouteKind.LEGACY_IDENTIFIER,
            OpenLibrarySourceStatus.SUCCESS,
        ),
        (
            "legacy_lccn.json",
            OpenLibraryRouteKind.LEGACY_IDENTIFIER,
            OpenLibrarySourceStatus.SUCCESS,
        ),
        ("empty.json", OpenLibraryRouteKind.EDITION, OpenLibrarySourceStatus.NOT_FOUND),
        ("search_page_1_stop.json", OpenLibraryRouteKind.SEARCH, OpenLibrarySourceStatus.SUCCESS),
        (
            "search_page_1_stop_isbn_only.json",
            OpenLibraryRouteKind.SEARCH,
            OpenLibrarySourceStatus.SUCCESS,
        ),
        (
            "search_page_1_requires_page_2.json",
            OpenLibraryRouteKind.SEARCH,
            OpenLibrarySourceStatus.SUCCESS,
        ),
        ("search_page_2.json", OpenLibraryRouteKind.SEARCH, OpenLibrarySourceStatus.SUCCESS),
        ("sparse.json", OpenLibraryRouteKind.WORK, OpenLibrarySourceStatus.SUCCESS),
    ),
)
def test_fixtures_are_classified(
    fixture: str, kind: OpenLibraryRouteKind, status: OpenLibrarySourceStatus
) -> None:
    result = parse_openlibrary_source((FIXTURES / fixture).read_bytes(), request(kind, fixture))
    assert result.status is status
    if status is OpenLibrarySourceStatus.SUCCESS:
        assert result.payload_bytes is not None
        assert len(result.payload_bytes) <= 262144
        assert result.payload is not None


def test_invalid_json_is_path_free_and_does_not_retain_bytes() -> None:
    result = parse_openlibrary_source(
        (FIXTURES / "invalid.json").read_bytes(), request(OpenLibraryRouteKind.WORK)
    )
    assert result.status is OpenLibrarySourceStatus.INVALID_RESPONSE
    assert result.payload is None and result.payload_bytes is None
    assert "invalid.json" not in repr(result)


def test_unknown_and_excluded_fields_are_discarded() -> None:
    payload = {
        "key": "/works/OL1W",
        "title": "T",
        "bio": "private",
        "covers": [1],
        "links": [{"url": "x"}],
    }
    result = parse_openlibrary_source(
        json.dumps(payload).encode(), request(OpenLibraryRouteKind.WORK)
    )
    assert result.status is OpenLibrarySourceStatus.SUCCESS
    assert result.payload is not None
    rendered = json.dumps(result.payload.as_payload())
    assert "bio" not in rendered and "covers" not in rendered and "links" not in rendered


def test_bounds_are_visible_and_long_values_are_not_silently_cut() -> None:
    payload = {"key": "/works/OL1W", "title": "x" * 4097, "subjects": [f"s{i}" for i in range(40)]}
    result = parse_openlibrary_source(
        json.dumps(payload).encode(), request(OpenLibraryRouteKind.WORK)
    )
    assert result.status is OpenLibrarySourceStatus.SUCCESS
    assert result.payload is not None
    record = result.payload.records[0].as_payload()
    assert record["title"] is None
    assert record["truncated"] is True


def test_canonical_serialization_is_deterministic_and_nfc_normalized() -> None:
    one = b'{"title":"e\\u0301","key":"/works/OL1W"}'
    two = b'{"key":"/works/OL1W","title":"\\u00e9"}'
    first = parse_openlibrary_source(one, request(OpenLibraryRouteKind.WORK))
    second = parse_openlibrary_source(two, request(OpenLibraryRouteKind.WORK))
    assert first.status is second.status is OpenLibrarySourceStatus.SUCCESS
    assert first.payload_bytes == second.payload_bytes


@pytest.mark.parametrize("data", (b"\xff", b"[]", b"1e309", b'{"key": []}'))
def test_malformed_shapes_fail_closed(data: bytes) -> None:
    result = parse_openlibrary_source(data, request(OpenLibraryRouteKind.WORK))
    assert result.status is OpenLibrarySourceStatus.INVALID_RESPONSE
    assert result.payload is None


def test_parser_has_no_network_surface() -> None:
    import foliotone.adapters.openlibrary.source as source

    assert not hasattr(source, "socket")
    assert not hasattr(source, "urlopen")


def test_route_binding_and_search_counts_fail_closed() -> None:
    foreign = b'{"key":"/works/OL2W"}'
    assert (
        parse_openlibrary_source(foreign, request(OpenLibraryRouteKind.WORK)).status
        is OpenLibrarySourceStatus.INVALID_RESPONSE
    )
    bad_offset = b'{"numFound":1,"start":10,"docs":[{"key":"/works/OL1W"}]}'
    assert (
        parse_openlibrary_source(bad_offset, request(OpenLibraryRouteKind.SEARCH)).status
        is OpenLibrarySourceStatus.INVALID_RESPONSE
    )
    contradictory = b'{"numFound":2,"num_found":3,"start":0,"docs":[]}'
    assert (
        parse_openlibrary_source(contradictory, request(OpenLibraryRouteKind.SEARCH)).status
        is OpenLibrarySourceStatus.INVALID_RESPONSE
    )


def test_search_truncates_nested_editions_and_rejects_title_only_docs() -> None:
    editions = [{"isbn": ["9000000000001"]} for _ in range(33)]
    payload = {
        "numFound": 1,
        "start": 0,
        "docs": [{"key": "/works/OL1W", "editions": {"docs": editions}}],
    }
    result = parse_openlibrary_source(
        json.dumps(payload).encode(), request(OpenLibraryRouteKind.SEARCH)
    )
    assert result.status is OpenLibrarySourceStatus.SUCCESS
    assert result.payload is not None and result.payload.records[0].truncated is True
    title_only = b'{"numFound":1,"start":0,"docs":[{"title":"only"}]}'
    assert (
        parse_openlibrary_source(title_only, request(OpenLibraryRouteKind.SEARCH)).status
        is OpenLibrarySourceStatus.INVALID_RESPONSE
    )


def test_search_author_names_are_independent_bounded_and_canonical() -> None:
    payload = {
        "numFound": 1,
        "start": 0,
        "docs": [
            {
                "key": "/works/OL1W",
                "author_key": ["OL1A"],
                "author_name": ["Zed", "e\u0301", "é", "", 3, "x" * 513],
                "editions": {"docs": [{"key": "/books/OL2M"}]},
            }
        ],
    }
    result = parse_openlibrary_source(
        json.dumps(payload, ensure_ascii=False).encode(), request(OpenLibraryRouteKind.SEARCH)
    )
    assert result.status is OpenLibrarySourceStatus.SUCCESS
    assert result.payload is not None
    record = result.payload.records[0]
    assert record.contributor_names == ("Zed", "é")
    assert record.work is not None and record.work.author_refs == ("OL1A",)
    assert record.truncated is True
    assert "contributor_names" in record.as_payload()


def test_v2_source_profile_and_codec_are_explicit() -> None:
    from foliotone.adapters.openlibrary import PAYLOAD_CODEC, PROFILE

    assert PROFILE == "openlibrary-source-record/v2"
    assert PAYLOAD_CODEC == "json/openlibrary-source-dto-v2"


@pytest.mark.parametrize("author_name", ["wrong", {}, 1])
def test_search_author_name_wrong_topology_is_malformed(author_name: object) -> None:
    payload = {
        "numFound": 1,
        "start": 0,
        "docs": [{"key": "/works/OL1W", "author_name": author_name}],
    }
    result = parse_openlibrary_source(
        json.dumps(payload).encode(), request(OpenLibraryRouteKind.SEARCH)
    )
    assert result.status is OpenLibrarySourceStatus.INVALID_RESPONSE


@pytest.mark.parametrize(
    "payload, kind",
    (
        (b'{"key":"/books/OL2M","isbn_13":["9780306406157"]}', OpenLibraryRouteKind.ISBN),
        (b'{"wrong":{"key":"/books/OL1M"}}', OpenLibraryRouteKind.LEGACY_IDENTIFIER),
        (b'{"key":"C:OL1W"}', OpenLibraryRouteKind.WORK),
        (b'{"key":"/works/OL1W","first_publish_year":1.5}', OpenLibraryRouteKind.WORK),
        (b'{"key":"/works/OL1W","first_publish_year":true}', OpenLibraryRouteKind.WORK),
    ),
)
def test_adversarial_route_and_year_inputs_fail_closed(
    payload: bytes, kind: OpenLibraryRouteKind
) -> None:
    assert (
        parse_openlibrary_source(payload, request(kind)).status
        is OpenLibrarySourceStatus.INVALID_RESPONSE
    )


def test_public_dtos_are_immutable_canonical_and_redacted() -> None:
    refs = ["OL1A"]
    record = WorkSourceRecord("OL1W", "private title", "2020", refs, [], False)
    refs[0] = "OL2A"
    assert record.author_refs == ("OL1A",)
    assert set(record.as_payload()) == {
        "work_olid",
        "title",
        "first_publish_year",
        "author_refs",
        "subjects",
        "truncated",
    }
    assert "private title" not in repr(record) and "OL1W" not in repr(record)
    with pytest.raises(ValueError):
        EditionSourceRecord(None, (), None, None, None, (), (), (), (), (), (), (), False)
    with pytest.raises(ValueError):
        WorkSourceRecord("OL1W", None, None, ("OL2A", "OL1A"), (), False)


def test_parse_result_requires_exact_canonical_bytes_and_envelope_contract() -> None:
    record = WorkSourceRecord("OL1W", None, None, (), (), False)
    envelope = OpenLibrarySourceEnvelope("WORK", (record,), 1, 0, True)
    canonical = json.dumps(envelope.as_payload(), sort_keys=True, separators=(",", ":")).encode()
    result = OpenLibrarySourceParseResult(OpenLibrarySourceStatus.SUCCESS, envelope, canonical)
    assert result.payload_bytes == canonical
    with pytest.raises(ValueError):
        OpenLibrarySourceParseResult(OpenLibrarySourceStatus.SUCCESS, envelope, b"wrong")
    with pytest.raises(ValueError):
        OpenLibrarySourceEnvelope("WORK", (record,), 2, 0, True)
