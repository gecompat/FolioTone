import json
from pathlib import Path

import pytest
from sqlalchemy import insert

from foliotone.cli.main import build_parser, main
from foliotone.persistence import (
    calibre_library_schema as calibre_schema,
)
from foliotone.persistence import (
    create_sqlite_engine,
    migrate,
    schema,
)

SNAPSHOT_ID = "00000000-0000-0000-0000-000000000003"


def _database(path: Path) -> None:
    engine = create_sqlite_engine(path)
    ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 40)]
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {"id": ids[0], "name": "synthetic-eb07", "media_type": "EBOOK", "enabled": True},
        )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": ids[1],
                "scan_root_id": ids[0],
                "started_at": "2026-08-19T00:00:00+00:00",
                "status": "COMPLETED",
                "completed_at": "2026-08-19T00:01:00+00:00",
            },
        )
        connection.execute(
            insert(calibre_schema.calibre_library_snapshots),
            {
                "id": SNAPSHOT_ID,
                "scan_root_id": ids[0],
                "source_scan_run_id": ids[1],
                "profile": "calibre-library-snapshot/v1",
                "adapter_version": "calibredb-library/1",
                "tool_version": "9.13.0",
                "parser_version": "calibre-library-parser/1",
                "library_identity_digest": "a" * 64,
                "initial_inventory_digest": "b" * 64,
                "final_inventory_digest": "b" * 64,
                "status": "COMPLETED",
                "started_at": "2026-08-19T00:00:00+00:00",
                "completed_at": "2026-08-19T00:01:00+00:00",
            },
        )
        for index, record_id in enumerate((ids[3], ids[4]), start=1):
            connection.execute(
                insert(calibre_schema.calibre_library_records),
                {
                    "id": record_id,
                    "snapshot_id": SNAPSHOT_ID,
                    "calibre_record_id": index,
                    "metadata_fingerprint": chr(98 + index) * 64,
                    "authors_json": "[]",
                    "identifiers_json": "[]",
                },
            )
        for index, (record_id, label, locator) in enumerate(
            (
                (ids[3], "EPUB", "Author/One.epub"),
                (ids[3], "PDF", "Author/One.pdf"),
                (ids[4], "MOBI", "Author/Two.mobi"),
            ),
            start=5,
        ):
            connection.execute(
                insert(calibre_schema.calibre_library_formats),
                {
                    "id": ids[index],
                    "record_snapshot_id": record_id,
                    "format_label": label,
                    "relative_locator": locator,
                },
            )
        connection.execute(
            insert(calibre_schema.calibre_library_sidecars),
            {
                "id": ids[8],
                "record_snapshot_id": ids[3],
                "kind": "COVER",
                "relative_locator": "Author/cover.jpg",
            },
        )
        for index, code in enumerate(
            (
                "FILESYSTEM_ONLY",
                "CALIBRE_RECORD_WITHOUT_FILE",
                "CALIBRE_DUPLICATE_RECORD_CANDIDATE",
                "CALIBRE_MULTI_FORMAT_RECORD",
                "CALIBRE_METADATA_CONFLICT",
                "CALIBRE_AUTHORITY_CONFLICT",
                "CALIBRE_SIDECAR_DEPENDENCY",
            ),
            start=9,
        ):
            finding_id = ids[index]
            digest_character = "abcdef0123456789"[index % 16]
            connection.execute(
                insert(calibre_schema.calibre_reconciliation_findings),
                {
                    "id": finding_id,
                    "snapshot_id": SNAPSHOT_ID,
                    "code": code,
                    "finding_fingerprint": digest_character * 64,
                    "review_required": index % 2 == 1,
                    "created_at": "2026-08-19T00:01:00+00:00",
                },
            )
            connection.execute(
                insert(calibre_schema.calibre_reconciliation_finding_refs),
                {
                    "id": ids[index + 10],
                    "finding_id": finding_id,
                    "ordinal": 0,
                    "ref_kind": "CALIBRE_RECORD",
                    "ref_id": ids[3],
                    "role": "PRIMARY",
                    "material_fingerprint": "0123456789abcdef"[index % 16] * 64,
                },
            )
    engine.dispose()


def _non_completed_snapshot(path: Path, status: str) -> None:
    engine = create_sqlite_engine(path)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots),
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "synthetic-eb07",
                "media_type": "EBOOK",
                "enabled": True,
            },
        )
        connection.execute(
            insert(schema.scan_runs),
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "scan_root_id": "00000000-0000-0000-0000-000000000001",
                "started_at": "2026-08-19T00:00:00+00:00",
                "status": "COMPLETED",
                "completed_at": "2026-08-19T00:01:00+00:00",
            },
        )
        connection.execute(
            insert(calibre_schema.calibre_library_snapshots),
            {
                "id": SNAPSHOT_ID,
                "scan_root_id": "00000000-0000-0000-0000-000000000001",
                "source_scan_run_id": "00000000-0000-0000-0000-000000000002",
                "profile": "calibre-library-snapshot/v1",
                "adapter_version": "calibredb-library/1",
                "tool_version": "9.13.0",
                "parser_version": "calibre-library-parser/1",
                "library_identity_digest": "a" * 64,
                "initial_inventory_digest": "b" * 64,
                "final_inventory_digest": "b" * 64,
                "status": status,
                "started_at": "2026-08-19T00:00:00+00:00",
                "completed_at": None if status == "RUNNING" else "2026-08-19T00:01:00+00:00",
            },
        )
    engine.dispose()


def test_calibre_reconciliation_report_cli_is_read_only_and_path_free(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = head_database
    _database(database)
    before = database.read_bytes()
    monkeypatch.setattr("foliotone.cli.main.migrate", lambda _path: pytest.fail("must not migrate"))
    monkeypatch.setattr(
        "foliotone.cli.main.create_sqlite_engine",
        lambda _path: pytest.fail("must not open a writable engine"),
    )

    result = main(
        [
            "calibre-reconciliation-report",
            "--snapshot",
            SNAPSHOT_ID,
            "--database",
            str(database),
            "--output",
            "json",
        ]
    )

    assert result == 0
    assert database.read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "calibre-reconciliation-report/v1"
    assert payload["scan_root_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["source_scan_run_id"] == "00000000-0000-0000-0000-000000000002"
    assert payload["snapshot_status"] == "COMPLETED"
    assert payload["counts"] == {
        "records": 2,
        "formats": 3,
        "sidecars": 1,
        "findings": 7,
        "review_required": 4,
        "refs": 7,
    }
    assert all(value == 1 for value in payload["finding_counts"].values())
    assert str(database) not in json.dumps(payload)


@pytest.mark.parametrize(
    "token",
    [
        "add",
        "remove",
        "add_format",
        "remove_format",
        "set_metadata",
        "set_custom",
        "add_custom_column",
        "remove_custom_column",
        "backup_metadata",
        "restore_database",
        "embed_metadata",
        "export",
        "catalog",
        "clone",
        "fts_index",
        "--username",
        "--password",
        "--library-path",
        "--command",
        "--query",
        "--execute",
    ],
)
def test_calibre_reconciliation_report_rejects_calibre_mutation_tokens(token: str) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "calibre-reconciliation-report",
                "--snapshot",
                SNAPSHOT_ID,
                token,
            ]
        )


def test_calibre_reconciliation_report_rejects_invalid_snapshot_token() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["calibre-reconciliation-report", "--snapshot", "not-a-uuid"]
        )


@pytest.mark.parametrize("status", ["RUNNING", "INVALIDATED", "FAILED"])
def test_calibre_reconciliation_report_non_completed_snapshot_returns_null_counts(
    head_database: Path,
    capsys: pytest.CaptureFixture[str],
    status: str,
) -> None:
    database = head_database
    _non_completed_snapshot(database, status)

    assert main(
        [
            "calibre-reconciliation-report",
            "--snapshot",
            SNAPSHOT_ID,
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["snapshot_status"] == status
    assert payload["counts"] == {
        "records": 0,
        "formats": 0,
        "sidecars": 0,
        "findings": 0,
        "review_required": 0,
        "refs": 0,
    }
    assert all(value == 0 for value in payload["finding_counts"].values())


def test_calibre_reconciliation_report_json_is_path_free_on_older_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "older-schema.db"
    migrate(database, "0014_relation_candidates")

    assert main(
        [
            "calibre-reconciliation-report",
            "--snapshot",
            SNAPSHOT_ID,
            "--database",
            str(database),
            "--output",
            "json",
        ]
    ) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "calibre-reconciliation-report",
        "ok": False,
        "error": {"code": "SCHEMA_UNAVAILABLE"},
    }
