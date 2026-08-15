from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import cast

from foliotone.analyzers.ebook import normalize_ebook_text
from foliotone.workflows import (
    EbookComparisonDimensionName,
    EbookComparisonState,
    EbookComparisonStatus,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "ebook_comparison" / "v2"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
SCHEMA_VERSION = "foliotone-ebook-comparison-fixture/v2"
BASE_SCHEMA_VERSION = "foliotone-ebook-comparison-fixture/v1"
SUPPORTED_FORMATS = {"EPUB", "MOBI", "AZW", "AZW3", "PDF"}

JsonObject = dict[str, object]


def test_edge_fixture_manifest_is_safe_versioned_and_reproducible() -> None:
    manifest = _manifest()

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["extends_schema_version"] == BASE_SCHEMA_VERSION
    assert _object(manifest["provenance"]) == {
        "source_kind": "synthetic",
        "source_name": "FolioTone W3-014",
        "license": "generated-for-foliotone-tests",
        "contains_real_media": False,
    }

    items = [_object(value) for value in _array(manifest["items"])]
    assert len(items) == 6
    assert {_string(item["evidence_case"]) for item in items} == {
        "COMPLETE",
        "SPARSE",
        "MALFORMED",
    }
    for item in items:
        file_data = _fixture_path(item["file_path"]).read_bytes()
        assert hashlib.sha256(file_data).hexdigest() == item["file_sha256"]
        assert _string(item["media_format"]) in SUPPORTED_FORMATS
        assert _object(item["ground_truth"])
        assert isinstance(item["metadata"], dict)

        text_path = item.get("text_path")
        if text_path is None:
            assert item["evidence_case"] == "SPARSE"
            continue
        text_data = _fixture_path(text_path).read_bytes()
        assert hashlib.sha256(text_data).hexdigest() == item["text_artifact_sha256"]
        assert normalize_ebook_text(text_data).sha256 == item["normalized_text_sha256"]


def test_edge_fixture_covers_all_formats_states_and_calibrated_distances() -> None:
    manifest = _manifest()
    base_manifest = _object(
        json.loads(
            (FIXTURE_ROOT.parent / "v1" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    )
    all_formats = {
        _string(item["media_format"])
        for source in (base_manifest, manifest)
        for item in (_object(value) for value in _array(source["items"]))
    }
    assert all_formats == SUPPORTED_FORMATS

    calibration = _object(manifest["cover_distance_calibration"])
    reference = int(_string(calibration["reference_dhash"]), 16)
    distances = {
        _integer(case["expected_distance"])
        for case in (_object(value) for value in _array(calibration["cases"]))
        if (reference ^ int(_string(case["dhash"]), 16)).bit_count()
        == _integer(case["expected_distance"])
    }
    assert distances == {0, 1, 8, 32, 64}

    scenarios = [_object(value) for value in _array(manifest["scenarios"])]
    assert len(scenarios) == 6
    observed_states: set[EbookComparisonState] = set()
    for scenario in scenarios:
        EbookComparisonStatus(_string(scenario["expected_status"]))
        states = _object(scenario["expected_states"])
        assert set(states) == {value.value for value in EbookComparisonDimensionName}
        observed_states.update(EbookComparisonState(_string(value)) for value in states.values())
    assert {
        EbookComparisonState.SAME,
        EbookComparisonState.DIFFERENT,
        EbookComparisonState.INDETERMINATE,
        EbookComparisonState.NOT_APPLICABLE,
    } <= observed_states


def _manifest() -> JsonObject:
    return _object(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def _fixture_path(value: object) -> Path:
    relative = PurePosixPath(_string(value))
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    candidate = FIXTURE_ROOT / Path(*relative.parts)
    assert not candidate.is_symlink()
    resolved = candidate.resolve(strict=True)
    assert resolved.is_relative_to(FIXTURE_ROOT.resolve(strict=True))
    assert resolved.is_file()
    return resolved


def _object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    return cast(JsonObject, value)


def _array(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _string(value: object) -> str:
    assert isinstance(value, str)
    assert value
    return value


def _integer(value: object) -> int:
    assert isinstance(value, int)
    return value
