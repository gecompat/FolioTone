from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from pytest import CaptureFixture
from sqlalchemy import Engine

from foliotone.analyzers.ebook import (
    COVER_FINGERPRINT_KIND,
    EBOOK_METADATA_CANDIDATE_RESULT,
    TEXT_FINGERPRINT_KIND,
    TEXT_NORMALIZATION_PROFILE,
)
from foliotone.cli.main import main
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    Fingerprint,
    Relation,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import create_sqlite_engine, repository
from foliotone.tooling import ToolExecution, ToolResult
from foliotone.workflows import (
    EBOOK_COMPARISON_PROFILE,
    EbookComparisonDimension,
    EbookComparisonDimensionName,
    EbookComparisonOutcome,
    EbookComparisonService,
    EbookComparisonState,
    EbookComparisonStatus,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "ebook_comparison" / "v1"
NOW = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)

JsonObject = dict[str, object]


def test_provider_neutral_comparison_matches_synthetic_scenario_evidence(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database, observations, items = _seed_corpus(tmp_path, capsys)
    engine = create_sqlite_engine(database)
    service = EbookComparisonService(engine)

    exact = service.compare(
        observations["lantern-en-epub-a"].id,
        observations["lantern-en-epub-copy"].id,
    )
    assert exact.profile == EBOOK_COMPARISON_PROFILE
    assert exact.status is EbookComparisonStatus.COMPLETE
    assert {dimension.name: dimension.state for dimension in exact.dimensions} == {
        EbookComparisonDimensionName.FILE_BYTES: EbookComparisonState.SAME,
        EbookComparisonDimensionName.NORMALIZED_TEXT: EbookComparisonState.SAME,
        EbookComparisonDimensionName.METADATA: EbookComparisonState.SAME,
        EbookComparisonDimensionName.STRUCTURE: EbookComparisonState.SAME,
        EbookComparisonDimensionName.COVER: EbookComparisonState.SAME,
    }

    changed = service.compare(
        observations["lantern-en-epub-a"].id,
        observations["lantern-en-epub-metadata-change"].id,
    )
    assert _state(changed, EbookComparisonDimensionName.FILE_BYTES) is (
        EbookComparisonState.DIFFERENT
    )
    assert _state(changed, EbookComparisonDimensionName.NORMALIZED_TEXT) is (
        EbookComparisonState.SAME
    )
    assert _state(changed, EbookComparisonDimensionName.METADATA) is (
        EbookComparisonState.DIFFERENT
    )
    assert _facts(changed, EbookComparisonDimensionName.METADATA)[
        "different_fields"
    ] == "publisher"

    format_variant = service.compare(
        observations["lantern-en-epub-a"].id,
        observations["lantern-en-mobi"].id,
    )
    assert format_variant.left_format == "EPUB"
    assert format_variant.right_format == "MOBI"
    assert _state(format_variant, EbookComparisonDimensionName.FILE_BYTES) is (
        EbookComparisonState.DIFFERENT
    )
    assert _state(format_variant, EbookComparisonDimensionName.NORMALIZED_TEXT) is (
        EbookComparisonState.SAME
    )
    assert _state(format_variant, EbookComparisonDimensionName.METADATA) is (
        EbookComparisonState.SAME
    )
    assert _state(format_variant, EbookComparisonDimensionName.STRUCTURE) is (
        EbookComparisonState.NOT_APPLICABLE
    )
    assert _state(format_variant, EbookComparisonDimensionName.COVER) is (
        EbookComparisonState.SAME
    )

    translation = service.compare(
        observations["lantern-en-epub-a"].id,
        observations["lantern-de-epub"].id,
    )
    assert _state(translation, EbookComparisonDimensionName.FILE_BYTES) is (
        EbookComparisonState.DIFFERENT
    )
    assert _state(translation, EbookComparisonDimensionName.NORMALIZED_TEXT) is (
        EbookComparisonState.DIFFERENT
    )
    assert _facts(translation, EbookComparisonDimensionName.METADATA)[
        "different_fields"
    ] == "contributor.translator,identifier.isbn,language,publisher,title"
    assert _state(translation, EbookComparisonDimensionName.STRUCTURE) is (
        EbookComparisonState.DIFFERENT
    )
    assert _state(translation, EbookComparisonDimensionName.COVER) is (
        EbookComparisonState.DIFFERENT
    )
    assert _facts(translation, EbookComparisonDimensionName.COVER)[
        "dhash_distance"
    ] == "64"

    expected = {
        _string(item["id"]): _string(item["normalized_text_sha256"])
        for item in items
    }
    persisted = {
        observation_id: tuple(
            fingerprint.value
            for fingerprint in repository(engine, Fingerprint).list_all()
            if fingerprint.target_id == observation.id
            and fingerprint.kind == TEXT_FINGERPRINT_KIND
        )
        for observation_id, observation in observations.items()
    }
    assert persisted == {key: (value,) for key, value in expected.items()}
    assert repository(engine, Relation).list_all() == []


def test_comparison_preserves_provider_disagreement_without_canonical_value(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database, observations, _items = _seed_corpus(tmp_path, capsys)
    engine = create_sqlite_engine(database)
    subject = observations["lantern-en-epub-a"]
    execution = _execution(
        subject,
        ToolCapability.READ_METADATA,
        provider_id="fixture-tool-b",
        offset=100,
    )
    repository(engine, ToolExecution).save(execution)
    for key, value in (
        ("identifier.1.value", "9780000000999"),
        ("identifier.1.namespace", "isbn"),
    ):
        repository(engine, ToolResult).save(
            _result(
                execution,
                subject,
                EBOOK_METADATA_CANDIDATE_RESULT,
                key,
                value,
            )
        )

    outcome = EbookComparisonService(engine).compare(
        subject.id,
        observations["lantern-en-epub-copy"].id,
    )

    metadata = _dimension(outcome, EbookComparisonDimensionName.METADATA)
    assert metadata.state is EbookComparisonState.DIFFERENT
    assert dict(metadata.facts)["different_fields"] == "identifier.isbn"
    assert dict(metadata.facts)["left_multiple_candidate_fields"] == (
        "identifier.isbn"
    )
    assert len(metadata.source_execution_ids) == 3
    assert repository(engine, Relation).list_all() == []

    failed_text = _failed_execution(
        subject,
        ToolCapability.EXTRACT_TEXT,
        provider_id="fixture-text",
        offset=200,
    )
    repository(engine, ToolExecution).save(failed_text)
    after_failure = EbookComparisonService(engine).compare(
        subject.id,
        observations["lantern-en-epub-copy"].id,
    )
    assert _state(after_failure, EbookComparisonDimensionName.NORMALIZED_TEXT) is (
        EbookComparisonState.INDETERMINATE
    )
    assert _facts(after_failure, EbookComparisonDimensionName.NORMALIZED_TEXT)[
        "reason"
    ] == "NORMALIZED_TEXT_FINGERPRINT_MISSING"
    assert after_failure.status is EbookComparisonStatus.PARTIAL


def test_ebook_compare_cli_is_bounded_and_writes_no_relation(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    database, observations, _items = _seed_corpus(tmp_path, capsys)
    left = observations["lantern-en-epub-a"]
    right = observations["lantern-en-epub-copy"]

    assert main(
        [
            "ebook-compare",
            "--left-observation-id",
            str(left.id),
            "--right-observation-id",
            str(right.id),
            "--database",
            str(database),
        ]
    ) == 0

    output = capsys.readouterr().out
    assert "Comparison profile: ebook-comparison/v1" in output
    assert "Comparison status: COMPLETE" in output
    assert "Comparison dimension FILE_BYTES: SAME" in output
    assert "Comparison dimension NORMALIZED_TEXT: SAME" in output
    assert "Comparison dimension METADATA: SAME" in output
    assert "Comparison dimension STRUCTURE: SAME" in output
    assert "Comparison dimension COVER: SAME" in output
    assert "Identity verdict: NOT_PRODUCED" in output
    assert "Relation records written: 0" in output
    assert "The Lantern Archive" not in output
    assert "Northstar Press" not in output
    assert str(tmp_path) not in output
    assert repository(create_sqlite_engine(database), Relation).list_all() == []


def _seed_corpus(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> tuple[Path, dict[str, FileObservation], list[JsonObject]]:
    manifest = _object(
        json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    )
    items = [_object(value) for value in _array(manifest["items"])]
    media = tmp_path / "media"
    media.mkdir()
    filename_by_id: dict[str, str] = {}
    for item in items:
        item_id = _string(item["id"])
        suffix = _string(item["media_format"]).lower()
        filename = f"{item_id}.{suffix}"
        filename_by_id[item_id] = filename
        source = FIXTURE_ROOT / Path(_string(item["file_path"]))
        (media / filename).write_bytes(source.read_bytes())

    database = tmp_path / "foliotone.db"
    assert main(
        [
            "scan",
            "--name",
            "comparison-fixture",
            "--path",
            str(media),
            "--media-type",
            "ebook",
            "--database",
            str(database),
            "--hash",
            "full",
            "--suffix",
            "epub",
            "--suffix",
            "mobi",
        ]
    ) == 0
    capsys.readouterr()

    engine = create_sqlite_engine(database)
    by_path = {
        observation.relative_path: observation
        for observation in repository(engine, FileObservation).list_all()
    }
    observations = {
        item_id: by_path[filename] for item_id, filename in filename_by_id.items()
    }
    for index, item in enumerate(items):
        _seed_item(engine, observations[_string(item["id"])], item, offset=index * 10)
    return database, observations, items


def _seed_item(
    engine: Engine,
    observation: FileObservation,
    item: JsonObject,
    *,
    offset: int,
) -> None:
    metadata_execution = _execution(
        observation,
        ToolCapability.READ_METADATA,
        provider_id="fixture-calibre",
        offset=offset,
    )
    text_execution = _execution(
        observation,
        ToolCapability.EXTRACT_TEXT,
        provider_id="fixture-text",
        offset=offset + 1,
    )
    cover_execution = _execution(
        observation,
        ToolCapability.FINGERPRINT,
        provider_id="fixture-cover",
        offset=offset + 2,
    )
    execution_repo = repository(engine, ToolExecution)
    result_repo = repository(engine, ToolResult)
    fingerprint_repo = repository(engine, Fingerprint)
    for execution in (metadata_execution, text_execution, cover_execution):
        execution_repo.save(execution)

    metadata = {
        key: _string(value) for key, value in _object(item["metadata"]).items()
    }
    for key, value in _candidate_values(metadata):
        result_repo.save(
            _result(
                metadata_execution,
                observation,
                EBOOK_METADATA_CANDIDATE_RESULT,
                key,
                value,
            )
        )
    for key, value in (
        ("identifier.99.value", str(observation.id)),
        ("identifier.99.namespace", "calibre"),
    ):
        result_repo.save(
            _result(
                metadata_execution,
                observation,
                EBOOK_METADATA_CANDIDATE_RESULT,
                key,
                value,
            )
        )

    result_repo.save(
        _result(text_execution, observation, "fixture_text", "text_status", "TEXT_EXTRACTED")
    )
    fingerprint_repo.save(
        Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            kind=TEXT_FINGERPRINT_KIND,
            algorithm="sha256",
            algorithm_version=TEXT_NORMALIZATION_PROFILE,
            value=_string(item["normalized_text_sha256"]),
            created_at=text_execution.finished_at or NOW,
            tool_execution_id=text_execution.id,
        )
    )

    result_repo.save(
        _result(
            cover_execution,
            observation,
            "fixture_cover",
            "cover_status",
            "COVER_EXTRACTED",
        )
    )
    cover_value = (
        "ffffffffffffffff"
        if _string(item["id"]) == "lantern-de-epub"
        else "0000000000000000"
    )
    fingerprint_repo.save(
        Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            kind=COVER_FINGERPRINT_KIND,
            algorithm="dhash-64",
            algorithm_version="fixture-cover/v1",
            value=cover_value,
            created_at=cover_execution.finished_at or NOW,
            tool_execution_id=cover_execution.id,
        )
    )

    if _string(item["media_format"]) == "EPUB":
        structure_execution = _execution(
            observation,
            ToolCapability.STRUCTURAL_VALIDATION,
            provider_id="fixture-epubcheck",
            offset=offset + 3,
        )
        execution_repo.save(structure_execution)
        is_translation = _string(item["id"]) == "lantern-de-epub"
        values = (
            ("conformance_status", "NONCONFORMANT" if is_translation else "CONFORMANT"),
            ("fatal_count", "0"),
            ("error_count", "1" if is_translation else "0"),
            ("warning_count", "0"),
        )
        for key, value in values:
            result_repo.save(
                _result(
                    structure_execution,
                    observation,
                    "fixture_structure",
                    key,
                    value,
                )
            )
        if is_translation:
            result_repo.save(
                _result(
                    structure_execution,
                    observation,
                    "fixture_structure",
                    "diagnostic.ERROR.OPF-001",
                    "1",
                )
            )


def _candidate_values(metadata: dict[str, str]) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    contributor_index = 0
    identifier_index = 0
    for key, value in metadata.items():
        if key.startswith("contributor."):
            contributor_index += 1
            values.extend(
                (
                    (f"contributor.{contributor_index}.name", value),
                    (f"contributor.{contributor_index}.role", key.split(".", 1)[1]),
                )
            )
        elif key.startswith("identifier."):
            identifier_index += 1
            values.extend(
                (
                    (f"identifier.{identifier_index}.value", value),
                    (f"identifier.{identifier_index}.namespace", key.split(".", 1)[1]),
                )
            )
        else:
            values.append((key, value))
    return tuple(values)


def _execution(
    observation: FileObservation,
    capability: ToolCapability,
    *,
    provider_id: str,
    offset: int,
) -> ToolExecution:
    timestamp = NOW + timedelta(seconds=offset)
    return ToolExecution(
        id=EntityId.new(),
        provider_id=provider_id,
        tool_version="fixture 1.0",
        adapter_version=f"{provider_id}/1",
        capability=capability,
        input_identity=f"file-observation:{observation.id}",
        config_identity="fixture:v1",
        started_at=timestamp,
        finished_at=timestamp,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )


def _failed_execution(
    observation: FileObservation,
    capability: ToolCapability,
    *,
    provider_id: str,
    offset: int,
) -> ToolExecution:
    timestamp = NOW + timedelta(seconds=offset)
    return ToolExecution(
        id=EntityId.new(),
        provider_id=provider_id,
        tool_version="fixture 2.0",
        adapter_version=f"{provider_id}/2",
        capability=capability,
        input_identity=f"file-observation:{observation.id}",
        config_identity="fixture:v2",
        started_at=timestamp,
        finished_at=timestamp,
        status=ToolExecutionStatus.FAILED,
        exit_code=1,
        error_summary="synthetic failure",
    )


def _result(
    execution: ToolExecution,
    observation: FileObservation,
    result_type: str,
    key: str,
    value: str,
) -> ToolResult:
    return ToolResult(
        id=EntityId.new(),
        execution_id=execution.id,
        result_type=result_type,
        target_kind=EntityKind.FILE_OBSERVATION,
        target_id=observation.id,
        key=key,
        value=value,
    )


def _dimension(
    outcome: EbookComparisonOutcome,
    name: EbookComparisonDimensionName,
) -> EbookComparisonDimension:
    return next(dimension for dimension in outcome.dimensions if dimension.name is name)


def _state(
    outcome: EbookComparisonOutcome,
    name: EbookComparisonDimensionName,
) -> EbookComparisonState:
    return _dimension(outcome, name).state


def _facts(
    outcome: EbookComparisonOutcome,
    name: EbookComparisonDimensionName,
) -> dict[str, str]:
    return dict(_dimension(outcome, name).facts)


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
