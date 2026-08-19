from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "openlibrary" / "v1"
JSON_FIXTURES = tuple(
    sorted(path for path in FIXTURE_ROOT.glob("*.json") if path.name != "invalid.json")
)
FORBIDDEN = (
    "C:\\",
    "Z:\\",
    "\\\\NAS\\",
    "/home/",
    "/Users/",
    "scanroot",
    "collection-inventory",
)


def _read(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_all_valid_fixtures_are_json_and_bounded() -> None:
    assert len(JSON_FIXTURES) == 12
    for path in JSON_FIXTURES:
        assert path.stat().st_size < 32 * 1024
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)


def test_direct_and_sparse_fixture_shapes_are_synthetic_and_distinct() -> None:
    work = _read("work.json")
    edition = _read("edition.json")
    assert work["key"] == "/works/OL900000001W"
    assert work["first_publish_date"] == "2001"
    assert work["subjects"] == ["Synthetic Subject Alpha"]
    assert edition["key"] == "/books/OL900000002M"
    assert edition["isbn_10"] == ["9000000009"]
    assert edition["isbn_13"] == ["9000000000001"]
    assert _read("author.json")["key"] == "/authors/OL900000001A"
    assert _read("isbn.json")["isbn_13"] == ["9000000000001"]
    assert set(_read("legacy_oclc.json")) == {"OCLC:900000000002"}
    assert set(_read("legacy_lccn.json")) == {"LCCN:synthetic-9002"}
    assert _read("empty.json") == {}
    assert _read("sparse.json") == {"key": "/works/OL900000006W"}


def test_search_pagination_correlates_exactly_with_adr_rule() -> None:
    page_one = _read("search_page_1_requires_page_2.json")
    page_two = _read("search_page_2.json")
    assert page_one["start"] == 0
    assert page_two["start"] == 10
    assert page_one["numFound"] > 10
    assert page_two["num_found"] == page_one["numFound"]
    assert not _has_strong_doc(page_one)

    for name in ("search_page_1_stop.json", "search_page_1_stop_isbn_only.json"):
        stopping_page = _read(name)
        assert stopping_page["numFound"] > 10
        assert _has_strong_doc(stopping_page)


def _has_strong_doc(payload: dict[str, object]) -> bool:
    docs = payload.get("docs")
    if not isinstance(docs, list):
        return False
    return any(
        isinstance(doc, dict)
        and isinstance(doc.get("key"), str)
        and re.fullmatch(r"/works/OL[0-9]+W", doc["key"]) is not None
        and isinstance(doc.get("editions"), dict)
        and (
            any(
                isinstance(edition, dict)
                and isinstance(edition.get("key"), str)
                and re.fullmatch(r"/books/OL[0-9]+M", edition["key"]) is not None
                for edition in doc["editions"].get("docs", [])
            )
            or any(
                isinstance(edition, dict)
                and any(
                    isinstance(isbn, str)
                    and (
                        re.fullmatch(r"[0-9]{10}", isbn) is not None
                        or re.fullmatch(r"[0-9]{13}", isbn) is not None
                    )
                    for field in ("isbn_10", "isbn_13")
                    for isbn in edition.get(field, [])
                )
                for edition in doc["editions"].get("docs", [])
            )
        )
        for doc in docs
    )


def test_invalid_fixture_is_the_only_intentionally_unparseable_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads((FIXTURE_ROOT / "invalid.json").read_text(encoding="utf-8"))
    for path in JSON_FIXTURES:
        if path.name != "invalid.json":
            json.loads(path.read_text(encoding="utf-8"))


def test_fixture_tree_has_no_private_paths_or_collection_data() -> None:
    for path in FIXTURE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        assert not any(marker.lower() in lowered for marker in FORBIDDEN)
        assert "password" not in lowered
        assert "token" not in lowered
