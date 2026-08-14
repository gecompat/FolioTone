from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import cast

from foliotone.analyzers.ebook import normalize_ebook_text
from foliotone.core import MatchStatus, RelationType

FIXTURE_ROOT = (
    Path(__file__).parents[1] / "fixtures" / "ebook_comparison" / "v1"
)
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
SCHEMA_VERSION = "foliotone-ebook-comparison-fixture/v1"
EXPECTED_SCENARIO_KINDS = {
    "IDENTICAL_FILE",
    "CHANGED_METADATA",
    "SAME_EDITION",
    "DIFFERENT_EDITION_TRANSLATION",
    "TOOL_DISAGREEMENT",
}

JsonObject = dict[str, object]


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


def _boolean(value: object) -> bool:
    assert isinstance(value, bool)
    return value


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


def _items_by_id(manifest: JsonObject) -> dict[str, JsonObject]:
    items = [_object(item) for item in _array(manifest["items"])]
    indexed = {_string(item["id"]): item for item in items}
    assert len(indexed) == len(items)
    return indexed


def _metadata(item: JsonObject) -> dict[str, str]:
    metadata = _object(item["metadata"])
    values = {key: _string(value) for key, value in metadata.items()}
    assert values
    return values


def _ground_truth(item: JsonObject) -> JsonObject:
    ground_truth = _object(item["ground_truth"])
    assert _string(ground_truth["work_id"])
    assert _string(ground_truth["edition_id"])
    assert _string(ground_truth["language"])
    return ground_truth


def test_fixture_manifest_is_safe_versioned_and_reproducible() -> None:
    manifest = _manifest()

    assert manifest["schema_version"] == SCHEMA_VERSION
    provenance = _object(manifest["provenance"])
    assert provenance == {
        "source_kind": "synthetic",
        "source_name": "FolioTone W3-007",
        "license": "generated-for-foliotone-tests",
        "contains_real_media": False,
    }

    items = _items_by_id(manifest)
    assert len(items) == 5
    for item in items.values():
        file_data = _fixture_path(item["file_path"]).read_bytes()
        text_data = _fixture_path(item["text_path"]).read_bytes()
        normalized_text = normalize_ebook_text(text_data)

        assert _string(item["media_format"]) in {"EPUB", "MOBI"}
        assert hashlib.sha256(file_data).hexdigest() == item["file_sha256"]
        assert hashlib.sha256(text_data).hexdigest() == item["text_artifact_sha256"]
        assert normalized_text.sha256 == item["normalized_text_sha256"]
        assert normalized_text.text
        _ground_truth(item)
        _metadata(item)


def test_comparison_scenarios_encode_distinct_identity_levels() -> None:
    manifest = _manifest()
    items = _items_by_id(manifest)
    scenarios = [_object(value) for value in _array(manifest["scenarios"])]

    assert {_string(scenario["kind"]) for scenario in scenarios} == (
        EXPECTED_SCENARIO_KINDS
    )

    comparison_scenarios = [
        scenario for scenario in scenarios if scenario["kind"] != "TOOL_DISAGREEMENT"
    ]
    for scenario in comparison_scenarios:
        left = items[_string(scenario["left_item"])]
        right = items[_string(scenario["right_item"])]
        expected = _object(scenario["expected"])
        left_truth = _ground_truth(left)
        right_truth = _ground_truth(right)

        assert (left["file_sha256"] == right["file_sha256"]) is _boolean(
            expected["same_file_bytes"]
        )
        assert (
            left["normalized_text_sha256"] == right["normalized_text_sha256"]
        ) is _boolean(expected["same_normalized_text"])
        assert (left_truth["work_id"] == right_truth["work_id"]) is _boolean(
            expected["same_work"]
        )
        assert (left_truth["edition_id"] == right_truth["edition_id"]) is _boolean(
            expected["same_edition"]
        )
        assert (left["media_format"] == right["media_format"]) is _boolean(
            expected["same_format"]
        )

        left_metadata = _metadata(left)
        right_metadata = _metadata(right)
        actual_differences = sorted(
            key
            for key in left_metadata.keys() | right_metadata.keys()
            if left_metadata.get(key) != right_metadata.get(key)
        )
        expected_differences = [
            _string(value) for value in _array(expected["metadata_differences"])
        ]
        assert actual_differences == expected_differences

        relation_types = tuple(
            RelationType(_string(value)) for value in _array(expected["relation_types"])
        )
        assert relation_types

    relations_by_scenario = {
        _string(scenario["id"]): tuple(
            RelationType(_string(value))
            for value in _array(_object(scenario["expected"])["relation_types"])
        )
        for scenario in comparison_scenarios
    }
    assert relations_by_scenario == {
        "identical-file": (RelationType.EXACT_DUPLICATE,),
        "changed-metadata": (
            RelationType.CONTENT_DUPLICATE,
            RelationType.SAME_EDITION,
        ),
        "same-edition-format-variant": (
            RelationType.FORMAT_VARIANT,
            RelationType.SAME_EDITION,
        ),
        "different-edition-translation": (
            RelationType.SAME_WORK,
            RelationType.DIFFERENT_EDITION,
        ),
    }


def test_tool_disagreement_preserves_both_versioned_values_without_canonicalization() -> None:
    manifest = _manifest()
    items = _items_by_id(manifest)
    scenario = next(
        _object(value)
        for value in _array(manifest["scenarios"])
        if _object(value)["kind"] == "TOOL_DISAGREEMENT"
    )
    subject = items[_string(scenario["subject_item"])]
    field_path = _string(scenario["field_path"])
    observations = [_object(value) for value in _array(scenario["observations"])]
    expected = _object(scenario["expected"])

    assert len(observations) >= 2
    assert len({_string(item["provider_id"]) for item in observations}) == len(observations)
    for observation in observations:
        assert _string(observation["tool_version"])
        assert _string(observation["adapter_version"])
        assert _string(observation["candidate_profile"])

    values = {_string(observation["value"]) for observation in observations}
    assert len(values) == expected["distinct_values"]
    assert _metadata(subject)[field_path] in values
    assert MatchStatus(_string(expected["status"])) is MatchStatus.REVIEW_REQUIRED
    assert expected["canonical_value"] is None
