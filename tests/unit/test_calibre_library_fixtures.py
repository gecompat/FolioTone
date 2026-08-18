from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "calibre_library" / "v1"
PSEUDO_ROOT = "__FOLIOTONE_CALIBRE_ROOT__/"
EXPECTED_CODES = {
    "A": "FILESYSTEM_ONLY",
    "B": "CALIBRE_RECORD_WITHOUT_FILE",
    "C": "CALIBRE_DUPLICATE_RECORD_CANDIDATE",
    "D": "CALIBRE_MULTI_FORMAT_RECORD",
    "E": "CALIBRE_METADATA_CONFLICT",
    "F": "CALIBRE_AUTHORITY_CONFLICT",
    "G": "CALIBRE_SIDECAR_DEPENDENCY",
}


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixture_inventory_is_sorted_bounded_and_path_sanitized() -> None:
    records = _json(FIXTURE_ROOT / "cases_a_g" / "list_page_1.json")
    assert isinstance(records, list)
    assert len(records) == 8
    assert [record["id"] for record in records] == list(range(101, 109))
    assert all(len(record["formats"]) <= 3 for record in records)
    assert all(
        path.startswith(PSEUDO_ROOT)
        for record in records
        for path in record["formats"]
    )
    assert _json(FIXTURE_ROOT / "cases_a_g" / "list_page_2.json") == []
    assert (FIXTURE_ROOT / "cases_a_g" / "search_106.txt").read_text(
        encoding="utf-8"
    ) == "106\n"


def test_fixture_ground_truth_covers_cases_a_through_g() -> None:
    expected = _json(FIXTURE_ROOT / "cases_a_g" / "expected.json")
    assert expected["profile"] == "calibre-library-fixture/v1"
    assert {
        case: payload["code"] for case, payload in expected["cases"].items()
    } == EXPECTED_CODES
    assert expected["cases"]["C"]["calibre_record_ids"] == [103, 104]
    assert expected["cases"]["D"]["formats"] == ["EPUB", "MOBI", "PDF"]
    assert expected["cases"]["G"]["sidecars"] == [
        "Eli Eta/Sidecar Owner (108)/cover.jpg",
        "Eli Eta/Sidecar Owner (108)/data/notes.txt",
        "Eli Eta/Sidecar Owner (108)/metadata.opf",
    ]


def test_fixture_opf_and_category_outputs_are_well_formed() -> None:
    opf_namespace = "{http://www.idpf.org/2007/opf}"
    dc_namespace = "{http://purl.org/dc/elements/1.1/}"
    for record_id in (106, 107):
        root = ElementTree.fromstring(
            (FIXTURE_ROOT / "cases_a_g" / f"show_metadata_{record_id}.opf").read_bytes()
        )
        assert root.tag == f"{opf_namespace}package"
        metadata = root.find(f"{opf_namespace}metadata")
        assert metadata is not None
        assert metadata.find(f"{dc_namespace}title") is not None
        assert metadata.find(f"{dc_namespace}creator") is not None

    with (FIXTURE_ROOT / "cases_a_g" / "list_categories.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream, strict=True))
    assert rows[0] == {"category": "authors", "name": "Ada Alpha", "count": "1"}
    assert rows[-1] == {"category": "tags", "name": "fixture", "count": "2"}


def test_empty_library_outputs_are_explicit() -> None:
    assert _json(FIXTURE_ROOT / "empty" / "list_page_1.json") == []
    with (FIXTURE_ROOT / "empty" / "list_categories.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        reader = csv.DictReader(stream, strict=True)
        assert reader.fieldnames == ["category", "name", "count"]
        assert list(reader) == []


def test_malformed_outputs_cover_syntax_and_semantic_failures() -> None:
    malformed = FIXTURE_ROOT / "malformed"
    with pytest.raises(json.JSONDecodeError):
        _json(malformed / "list_invalid_json.json")
    with pytest.raises(ElementTree.ParseError):
        ElementTree.fromstring((malformed / "show_metadata_invalid.opf").read_bytes())
    with (malformed / "list_categories_invalid.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        with pytest.raises(csv.Error):
            list(csv.reader(stream, strict=True))

    absolute_records = _json(malformed / "list_absolute_path.json")
    assert not absolute_records[0]["formats"][0].startswith(PSEUDO_ROOT)
    non_monotonic = _json(malformed / "list_non_monotonic.json")
    assert [record["id"] for record in non_monotonic] == [2, 1]


def test_fixture_tree_contains_no_real_private_path_or_media_file() -> None:
    forbidden = ("C:\\", "Z:\\", "\\\\NAS\\", "/home/", "/Users/")
    for path in FIXTURE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        assert path.suffix.lower() not in {".epub", ".mobi", ".azw", ".azw3", ".pdf"}
        text = path.read_text(encoding="utf-8")
        assert not any(marker in text for marker in forbidden)
