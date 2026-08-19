from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pytest import CaptureFixture
from sqlalchemy import Engine, delete, select

from foliotone.cli.main import main
from foliotone.core import (
    EntityId,
    EntityKind,
    FileObservation,
    FileRecord,
    Fingerprint,
    MediaType,
    PresenceState,
    ScanRoot,
    ScanRun,
    ScanRunStatus,
    ToolCapability,
    ToolExecutionStatus,
)
from foliotone.persistence import (
    EbookCollectionReportStoreError,
    SQLiteEbookCollectionReportStore,
    SQLiteEbookCollectionStore,
    create_sqlite_engine,
    repository,
    w3_schema,
)
from foliotone.tooling import ToolExecution
from foliotone.workflows import (
    EbookAnalysisOutcome,
    EbookAnalysisStepOutcome,
    EbookCollectionReportLimits,
    EbookCollectionReportService,
    EbookCollectionService,
    EbookQualityAssessment,
    EbookQualityDimension,
    EbookQualityDimensionName,
    EbookQualityDimensionStatus,
    EbookQualityFinding,
    EbookQualityFindingSeverity,
)

NOW = datetime(2026, 8, 15, 21, 0, tzinfo=UTC)
TEXT_PROFILE = "synthetic-normalized-text/v1"


def test_collection_report_is_actionable_bounded_private_and_deterministic(
    tmp_path: Path,
    head_database: Path,
    capsys: CaptureFixture[str],
) -> None:
    media = tmp_path / "private-media"
    media.mkdir()
    database = head_database
    engine, root, observations = _environment(
        database,
        media,
        (
            "+00-a.epub",
            "02-b.epub",
            "03-c.epub",
            "04-d.epub",
            "05-e.epub",
            "06-f.epub",
            "07-g.mobi",
        ),
    )
    file_hashes = {
        "+00-a.epub": "a" * 64,
        "02-b.epub": "a" * 64,
        "03-c.epub": "a" * 64,
        "04-d.epub": "b" * 64,
        "05-e.epub": "b" * 64,
        "06-f.epub": "d" * 64,
        "07-g.mobi": "c" * 64,
    }
    text_hashes = {
        "+00-a.epub": "1" * 64,
        "02-b.epub": "1" * 64,
        "03-c.epub": "1" * 64,
        "04-d.epub": "1" * 64,
        "05-e.epub": "2" * 64,
        "07-g.mobi": "2" * 64,
    }
    quality_states = {
        "+00-a.epub": "OK",
        "02-b.epub": "REVIEW",
        "03-c.epub": "ACTION_REQUIRED",
        "04-d.epub": "INCOMPLETE",
        "05-e.epub": "OK",
        "07-g.mobi": "OK",
    }
    for relative_path, observation in observations.items():
        repository(engine, Fingerprint).save(
            Fingerprint(
                id=EntityId.new(),
                target_kind=EntityKind.FILE_OBSERVATION,
                target_id=observation.id,
                kind="FILE_SHA256",
                algorithm="sha256",
                algorithm_version="1",
                value=file_hashes[relative_path],
                created_at=NOW,
            )
        )

    def analyze(observation: FileObservation, _fresh: bool) -> EbookAnalysisOutcome:
        relative_path = observation.relative_path
        if relative_path == "06-f.epub":
            raise RuntimeError(r"private analyzer detail at Q:\synthetic\06-f.epub")
        return _outcome(
            engine,
            observation,
            quality_states[relative_path],
            text_hashes[relative_path],
        )

    batch = EbookCollectionService(
        SQLiteEbookCollectionStore(engine),
        analyze,
        clock=lambda: NOW,
    ).start(root.id)
    source_bytes = {
        path: path.read_bytes() for path in sorted(media.iterdir()) if path.is_file()
    }

    report_root = tmp_path / "reports"
    service = EbookCollectionReportService(SQLiteEbookCollectionReportStore(engine))
    limits = EbookCollectionReportLimits(
        review_items=3,
        candidate_groups=1,
        members_per_group=2,
    )
    first = service.generate(batch.run.id, report_root, limits=limits)
    second = service.generate(batch.run.id, report_root, limits=limits)

    assert first.report_directory == second.report_directory
    assert first.report_sha256 == second.report_sha256
    assert len(first.files) == 5
    report_path = first.report_directory / "collection-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["profile"] == "ebook-collection-report/v1"
    assert payload["aggregate"]["planned"] == 7
    assert payload["aggregate"]["formats"] == {
        "AZW": 0,
        "AZW3": 0,
        "EPUB": 6,
        "MOBI": 1,
        "PDF": 0,
    }
    assert payload["aggregate"]["analysis_statuses"]["SUCCEEDED"] == 6
    assert payload["aggregate"]["analysis_statuses"]["ERROR"] == 1
    assert payload["aggregate"]["quality_statuses"]["UNAVAILABLE"] == 1
    assert payload["aggregate"]["findings"] == 3
    assert [item["priority"] for item in payload["review"]["items"]] == [
        "ANALYSIS_ERROR",
        "ACTION_REQUIRED",
        "INCOMPLETE",
    ]
    assert payload["review"]["total_items"] == 4
    assert payload["review"]["truncated"] is True
    action_finding = payload["review"]["items"][1]["findings"][0]
    assert action_finding["code"] == "TEXT_NOT_AVAILABLE"
    assert len(action_finding["source_execution_ids"]) == 1
    EntityId.parse(action_finding["source_execution_ids"][0])

    duplicates = payload["candidate_sets"]["exact_duplicates"]
    assert duplicates["total_groups"] == 2
    assert duplicates["emitted_groups"] == 1
    assert duplicates["groups"][0]["member_count"] == 3
    assert duplicates["groups"][0]["emitted_members"] == 2
    assert duplicates["groups_truncated"] is True
    assert duplicates["members_truncated"] is True

    variants = payload["candidate_sets"]["content_variants"]
    assert variants["total_groups"] == 2
    assert variants["emitted_groups"] == 1
    assert variants["groups"][0]["member_count"] == 4
    assert variants["groups"][0]["emitted_members"] == 2
    assert variants["groups_truncated"] is True
    assert variants["members_truncated"] is True
    assert payload["identity_verdict"] == "NOT_PRODUCED"
    assert payload["relation_records_written"] == 0

    report_text = report_path.read_text(encoding="utf-8")
    assert "+00-a.epub" in report_text
    assert "'+00-a.epub" in (
        first.report_directory / "exact-duplicates.csv"
    ).read_text(encoding="utf-8")
    assert all(value not in report_text for value in set(file_hashes.values()))
    assert all(value not in report_text for value in set(text_hashes.values()))
    _verify_checksums(first.report_directory)
    assert all(path.read_bytes() == content for path, content in source_bytes.items())

    cli_report_root = tmp_path / "cli-reports"
    result = main(
        [
            "ebook-collection-report",
            "--run",
            str(batch.run.id),
            "--source-root",
            str(media),
            "--database",
            str(database),
            "--report-root",
            str(cli_report_root),
            "--review-limit",
            "3",
            "--group-limit",
            "1",
            "--group-member-limit",
            "2",
        ]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert "Report profile: ebook-collection-report/v1" in output
    assert "Review items: 4" in output
    assert "Exact duplicate groups: 2" in output
    assert "Content variant groups: 2" in output
    assert "Identity verdict: NOT_PRODUCED" in output
    assert str(media) not in output
    assert all(relative_path not in output for relative_path in observations)

    rejected = main(
        [
            "ebook-collection-report",
            "--run",
            str(batch.run.id),
            "--source-root",
            str(media),
            "--database",
            str(database),
            "--report-root",
            str(media / "reports"),
        ]
    )
    assert rejected == 2
    assert "must be outside source root" in capsys.readouterr().out
    assert not (media / "reports").exists()

    active = SQLiteEbookCollectionStore(engine).create_run(
        root.id,
        profile="ebook-collection-analysis/v1",
        analysis_profile="ebook-analysis-workflow/v3",
        fresh=False,
        worker_count=1,
        started_at=NOW,
        lease_token="active-report-test",
        lease_expires_at=NOW + timedelta(minutes=30),
        plan_limit=1,
    )
    with pytest.raises(EbookCollectionReportStoreError, match="running"):
        SQLiteEbookCollectionReportStore(engine).snapshot(
            active.run.id,
            review_item_limit=1,
            candidate_group_limit=1,
            candidate_member_limit=1,
        )

    with engine.begin() as connection:
        connection.execute(
            delete(w3_schema.ebook_collection_item_executions).where(
                w3_schema.ebook_collection_item_executions.c.item_id.in_(
                    select(w3_schema.ebook_collection_items.c.id).where(
                        w3_schema.ebook_collection_items.c.run_id
                        == str(batch.run.id)
                    )
                )
            )
        )
    with pytest.raises(EbookCollectionReportStoreError, match="execution projection"):
        SQLiteEbookCollectionReportStore(engine).snapshot(
            batch.run.id,
            review_item_limit=1,
            candidate_group_limit=1,
            candidate_member_limit=1,
        )


def _environment(
    database: Path,
    media: Path,
    paths: tuple[str, ...],
) -> tuple[Engine, ScanRoot, dict[str, FileObservation]]:
    engine = create_sqlite_engine(database)
    root = ScanRoot(id=EntityId.new(), name="synthetic-report", media_type=MediaType.EBOOK)
    scan = ScanRun(
        id=EntityId.new(),
        scan_root_id=root.id,
        started_at=NOW,
        completed_at=NOW,
        status=ScanRunStatus.COMPLETED,
    )
    repository(engine, ScanRoot).save(root)
    repository(engine, ScanRun).save(scan)
    observations: dict[str, FileObservation] = {}
    for relative_path in paths:
        source = media / relative_path
        content = f"synthetic-{relative_path}".encode()
        source.write_bytes(content)
        record = FileRecord(
            id=EntityId.new(),
            scan_root_id=root.id,
            relative_path=relative_path,
            size_bytes=len(content),
            modified_at=NOW,
            media_type=MediaType.EBOOK,
            presence_state=PresenceState.PRESENT,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        observation = FileObservation(
            id=EntityId.new(),
            file_id=record.id,
            scan_run_id=scan.id,
            relative_path=relative_path,
            size_bytes=len(content),
            modified_at=NOW,
            observed_at=NOW,
        )
        repository(engine, FileRecord).save(record)
        repository(engine, FileObservation).save(observation)
        observations[relative_path] = observation
    return engine, root, observations


def _outcome(
    engine: Engine,
    observation: FileObservation,
    quality_state: str,
    text_hash: str,
) -> EbookAnalysisOutcome:
    execution = ToolExecution(
        id=EntityId.new(),
        provider_id="synthetic-report",
        tool_version="1",
        adapter_version="1",
        capability=ToolCapability.EXTRACT_TEXT,
        input_identity=f"file-observation:{observation.id}",
        started_at=NOW,
        finished_at=NOW,
        status=ToolExecutionStatus.SUCCEEDED,
        exit_code=0,
    )
    repository(engine, ToolExecution).save(execution)
    repository(engine, Fingerprint).save(
        Fingerprint(
            id=EntityId.new(),
            target_kind=EntityKind.FILE_OBSERVATION,
            target_id=observation.id,
            kind="EBOOK_NORMALIZED_TEXT",
            algorithm="sha256",
            algorithm_version=TEXT_PROFILE,
            value=text_hash,
            created_at=NOW,
            tool_execution_id=execution.id,
        )
    )
    dimensions = [
        EbookQualityDimension(name, EbookQualityDimensionStatus.OK)
        for name in EbookQualityDimensionName
    ]
    findings: tuple[EbookQualityFinding, ...] = ()
    if quality_state == "REVIEW":
        dimensions[2] = EbookQualityDimension(
            EbookQualityDimensionName.COVER,
            EbookQualityDimensionStatus.REVIEW,
        )
        findings = (
            EbookQualityFinding(
                "COVER_MISSING",
                EbookQualityDimensionName.COVER,
                EbookQualityFindingSeverity.WARNING,
                (execution.id,),
            ),
        )
    elif quality_state == "ACTION_REQUIRED":
        dimensions[1] = EbookQualityDimension(
            EbookQualityDimensionName.TEXT,
            EbookQualityDimensionStatus.ACTION_REQUIRED,
        )
        findings = (
            EbookQualityFinding(
                "TEXT_NOT_AVAILABLE",
                EbookQualityDimensionName.TEXT,
                EbookQualityFindingSeverity.ERROR,
                (execution.id,),
            ),
        )
    elif quality_state == "INCOMPLETE":
        dimensions[0] = EbookQualityDimension(
            EbookQualityDimensionName.METADATA,
            EbookQualityDimensionStatus.INCOMPLETE,
        )
        findings = (
            EbookQualityFinding(
                "METADATA_ANALYSIS_INCOMPLETE",
                EbookQualityDimensionName.METADATA,
                EbookQualityFindingSeverity.ERROR,
                (execution.id,),
            ),
        )
    quality = EbookQualityAssessment(
        observation_id=observation.id,
        format_name=observation.relative_path.rsplit(".", 1)[-1].upper(),
        dimensions=tuple(dimensions),
        findings=findings,
        source_execution_ids=(execution.id,),
    )
    return EbookAnalysisOutcome(
        observation_id=observation.id,
        format_name=quality.format_name,
        steps=(EbookAnalysisStepOutcome(name="synthetic", executions=(execution,)),),
        quality=quality,
    )


def _verify_checksums(report_directory: Path) -> None:
    lines = (report_directory / "checksums.sha256").read_text(
        encoding="ascii"
    ).splitlines()
    assert len(lines) == 4
    for line in lines:
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((report_directory / name).read_bytes()).hexdigest() == expected
