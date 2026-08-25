from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text, update

from foliotone.application.contracts import (
    EbookFixityAnalysisJobProfile,
    EbookFixityReviewCommand,
)
from foliotone.application.services import FolioToneApplication
from foliotone.core import EntityId, MediaType
from foliotone.fixity import EbookFixityBaselineEntry, expected_fixity_baseline_confirmation
from foliotone.fixity.verification_contracts import (
    EbookFixityVerificationResult,
    EbookFixityVerificationResultRecord,
)
from foliotone.persistence import schema
from foliotone.persistence.fixity import SQLiteEbookFixityBaselineStore
from foliotone.persistence.fixity_commands import SQLiteEbookFixityCommandOperation
from foliotone.persistence.fixity_surface import SQLiteEbookFixityBaselineActivationOperation
from foliotone.persistence.fixity_verification import SQLiteEbookFixityVerificationStore
from foliotone.persistence.resolution_review import SQLiteResolutionReviewStore
from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import EbookFixityAnalysisJobBinder, SQLiteSurfaceStore
from foliotone.persistence.surface_schema import surface_grants
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import SurfaceRuntimeConfig
from foliotone.surface.service import LocalSurfaceService

ORIGIN = "http://127.0.0.1:8765"
_FIXITY_ROOT_ID = "00000000-0000-4000-8000-000000000001"


def _add_fixity_root(database: Path) -> None:
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots).values(
                id=_FIXITY_ROOT_ID,
                name="synthetic-ebooks",
                media_type=MediaType.EBOOK.value,
                enabled=True,
            )
        )


class _SyntheticEbookReadModel:
    """A path-bearing fake proves the HTTP allowlist does not serialize its extras."""

    def scan_status(self, scan_root_id: EntityId) -> dict[str, object] | None:
        return {"scan_root_id": str(scan_root_id), "status": "COMPLETED"}

    def inventory(self, scan_root_id: EntityId) -> dict[str, object] | None:
        return {"scan_root_id": str(scan_root_id), "formats": [{"format": "EPUB"}]}

    def collection_analysis(self, run_id: EntityId) -> dict[str, object] | None:
        return {"collection_run_id": str(run_id), "analysis_coverage": {"SUCCEEDED": 1}}

    def review_queue(self, run_id: EntityId, *, after_id: str | None, limit: int):
        return (
            ({"observation_id": "00000000-0000-0000-0000-000000000001", "priority": "REVIEW"},),
            None,
        )

    def candidate_evidence(self, run_id: EntityId) -> dict[str, object] | None:
        return {"collection_run_id": str(run_id), "exact_duplicates": {"groups": 0}}

    def list_plans(self, *, after_id: str | None, limit: int):
        return (
            (
                {
                    "plan_id": "00000000-0000-0000-0000-000000000002",
                    "execution_state": "NOT_EXECUTABLE",
                },
            ),
            None,
        )

    def plan_report(self, plan_id: EntityId) -> dict[str, object] | None:
        return {"plan_id": str(plan_id), "execution_state": "NOT_EXECUTABLE"}


def _client(
    database: Path,
    *,
    ebook_read_model: object | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    engine = create_sqlite_engine(database)
    store = SQLiteSurfaceStore(engine)
    service = LocalSurfaceService(
        store,
        fixity_baseline_store=SQLiteEbookFixityBaselineStore(engine),
        fixity_verification_store=SQLiteEbookFixityVerificationStore(engine),
        fixity_activation_operation=SQLiteEbookFixityBaselineActivationOperation(engine),
        fixity_review_store=SQLiteResolutionReviewStore(engine),
        fixity_command_operation=SQLiteEbookFixityCommandOperation(engine),
    )
    app = create_surface_app(
        service,
        config=SurfaceRuntimeConfig(),
        surface_read_model=store,
        ebook_read_model=ebook_read_model,
    )
    return TestClient(
        app,
        base_url=ORIGIN,
        raise_server_exceptions=raise_server_exceptions,
    )


def _ready_fixity_manifest(database: Path, *, reuse_root: bool = False) -> EntityId:
    now = datetime.now(UTC).replace(microsecond=0)
    manifest_id = EntityId.new()
    engine = create_sqlite_engine(database)
    if reuse_root:
        with engine.connect() as connection:
            root_id = EntityId.parse(
                str(connection.execute(select(schema.scan_roots.c.id)).scalar_one())
            )
            scan_id = EntityId.parse(
                str(
                    connection.execute(
                        select(schema.scan_runs.c.id).where(
                            schema.scan_runs.c.scan_root_id == str(root_id)
                        )
                    ).scalar_one()
                )
            )
    else:
        root_id = EntityId.new()
        scan_id = EntityId.new()
        with engine.begin() as connection:
            connection.execute(
                insert(schema.scan_roots).values(
                    id=str(root_id),
                    name=f"synthetic-ebooks-{root_id}",
                    media_type=MediaType.EBOOK.value,
                    enabled=True,
                )
            )
            connection.execute(
                insert(schema.scan_runs).values(
                    id=str(scan_id),
                    scan_root_id=str(root_id),
                    started_at=now - timedelta(minutes=2),
                    status="COMPLETED",
                    completed_at=now - timedelta(minutes=1),
                )
            )
    store = SQLiteEbookFixityBaselineStore(engine)
    lease = store.acquire_lease(root_id, manifest_id, acquired_at=now)
    store.start_build(manifest_id, scan_id, started_at=now, lease=lease)
    store.finalize_manifest(
        manifest_id,
        prepared_at=now,
        expires_at=now + timedelta(minutes=15),
        lease=lease,
    )
    store.release(lease, released_at=now)
    return manifest_id


def _actionable_fixity_results(
    database: Path,
    *,
    count: int = 2,
) -> tuple[EntityId, EntityId, tuple[EntityId, ...]]:
    """Seed only synthetic immutable Fixity evidence for surface tests."""

    now = datetime.now(UTC).replace(microsecond=0)
    root_id, scan_id, manifest_id = EntityId.new(), EntityId.new(), EntityId.new()
    expected_sha = "1" * 64
    current_sha = "2" * 64
    rows: list[tuple[EntityId, EntityId, str]] = []
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            insert(schema.scan_roots).values(
                id=str(root_id),
                name="synthetic-fixity-surface",
                media_type=MediaType.EBOOK.value,
                enabled=True,
            )
        )
        connection.execute(
            insert(schema.scan_runs).values(
                id=str(scan_id),
                scan_root_id=str(root_id),
                started_at=now - timedelta(minutes=4),
                status="COMPLETED",
                completed_at=now - timedelta(minutes=3),
            )
        )
        for index in range(count):
            file_id, observation_id = EntityId.new(), EntityId.new()
            locator = f"synthetic-{index}.epub"
            connection.execute(
                insert(schema.file_records).values(
                    id=str(file_id),
                    scan_root_id=str(root_id),
                    relative_path=locator,
                    size_bytes=16,
                    modified_at=now - timedelta(minutes=5),
                    media_type=MediaType.EBOOK.value,
                    presence_state="PRESENT",
                    first_seen_at=now - timedelta(minutes=4),
                    last_seen_at=now - timedelta(minutes=3),
                    missing_since_at=None,
                    consecutive_missing_scans=0,
                )
            )
            connection.execute(
                insert(schema.file_observations).values(
                    id=str(observation_id),
                    file_id=str(file_id),
                    scan_run_id=str(scan_id),
                    relative_path=locator,
                    size_bytes=16,
                    modified_at=now - timedelta(minutes=5),
                    observed_at=now - timedelta(minutes=3),
                )
            )
            rows.append((file_id, observation_id, locator))
    baseline = SQLiteEbookFixityBaselineStore(engine)
    lease = baseline.acquire_lease(
        root_id,
        manifest_id,
        acquired_at=now - timedelta(minutes=2),
        lease_duration=timedelta(minutes=5),
    )
    baseline.start_build(
        manifest_id,
        scan_id,
        started_at=now - timedelta(minutes=2),
        lease=lease,
    )
    baseline.append_entries(
        manifest_id,
        tuple(
            EbookFixityBaselineEntry(
                ordinal=index,
                file_id=file_id,
                observation_id=observation_id,
                expected_size_bytes=16,
                expected_sha256=expected_sha,
                relative_locator=locator,
            )
            for index, (file_id, observation_id, locator) in enumerate(rows)
        ),
        lease=lease,
        committed_at=now - timedelta(seconds=110),
    )
    baseline.finalize_manifest(
        manifest_id,
        prepared_at=now - timedelta(seconds=100),
        expires_at=now + timedelta(minutes=10),
        lease=lease,
    )
    baseline.release(lease, released_at=now - timedelta(seconds=90))
    baseline.activate(
        manifest_id,
        expected_fixity_baseline_confirmation(manifest_id),
        activated_at=now - timedelta(seconds=80),
    )
    verification = SQLiteEbookFixityVerificationStore(engine)
    owned = verification.start_run(
        EntityId.new(),
        root_id,
        started_at=now - timedelta(seconds=60),
        lease_token="synthetic-surface-verification",
        lease_expires_at=now + timedelta(minutes=2),
    )
    work = verification.read_workset_batch(
        owned,
        observed_at=now - timedelta(seconds=50),
        batch_size=count,
    )
    results = tuple(
        EbookFixityVerificationResultRecord(
            result_id=EntityId.new(),
            run_id=owned.run.run_id,
            file_id=item.file_id,
            result=EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
            expected_observation_id=item.expected_observation_id,
            expected_size_bytes=item.expected_size_bytes,
            expected_sha256=item.expected_sha256,
            expected_relative_locator=item.expected_relative_locator,
            current_observation_id=item.current_observation_id,
            current_size_bytes=item.current_size_bytes,
            current_sha256=current_sha,
            current_relative_locator=item.current_relative_locator,
        )
        for item in work
    )
    verification.append_results(
        owned,
        results,
        recorded_at=now - timedelta(seconds=40),
    )
    verification.complete_run(owned, completed_at=now - timedelta(seconds=30))
    engine.dispose()
    return manifest_id, owned.run.run_id, tuple(result.result_id for result in results)


def test_surface_requires_owner_bootstrap_and_fences_origin(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()

    rejected = client.post("/api/v1/setup", json={})
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "SURFACE_ORIGIN_REJECTED"
    assert rejected.headers["content-security-policy"].startswith("default-src 'self'")

    setup = client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    assert setup.status_code == 201
    assert client.get("/api/v1/setup-status").json() == {"setup_required": False}


def test_session_cookie_csrf_and_host_checks(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )

    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    assert login.status_code == 200
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert client.get("/api/v1/session").status_code == 200
    assert client.get("/api/v1/media-lines").json() == {
        "profile": "application-contracts/v1",
        "items": [
            {"media_line": "EBOOK", "enabled": True},
            {"media_line": "MUSIC", "enabled": False},
            {"media_line": "IMAGE", "enabled": False},
        ],
    }
    assert (
        client.delete(
            "/api/v1/session",
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        ).json()["code"]
        == "CSRF_REJECTED"
    )
    assert (
        client.delete(
            "/api/v1/session",
            headers={
                "Origin": ORIGIN,
                "Content-Type": "application/json",
                "X-FolioTone-CSRF": login.json()["csrf"],
            },
        ).status_code
        == 204
    )
    assert (
        client.get("/api/v1/health", headers={"Host": "localhost:8765"}).json()["code"]
        == "SURFACE_HOST_REJECTED"
    )


def test_reauthentication_rotates_session_and_serves_only_local_assets(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    original_session = client.get("/api/v1/session").json()["session_id"]

    reauth = client.post(
        "/api/v1/session/reauth",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": login.json()["csrf"],
        },
        json={"password": "ein sehr langes Passwort"},
    )

    assert reauth.status_code == 200
    assert reauth.json()["status"] == "PRIVATE_READ_GRANT_ISSUED"
    assert reauth.headers["cache-control"] == "no-store"
    assert reauth.json()["csrf"] != login.json()["csrf"]
    assert client.get("/api/v1/session").json()["session_id"] != original_session
    assert client.get("/api/v1/private/session").headers["cache-control"] == "no-store"
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.css").headers["content-type"].startswith("text/css")
    assert client.get("/assets/not-found.js").json()["code"] == "ASSET_NOT_FOUND"


def test_operate_reauthentication_rotates_the_session(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth-operate",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )

    assert reauth.status_code == 200
    assert reauth.json()["status"] == "OPERATE_GRANT_ISSUED"
    assert reauth.headers["cache-control"] == "no-store"
    queued = client.post(
        "/api/v1/ebooks/rename/authorizations",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "synthetic-authorize-1",
        },
        json={
            "plan_id": str(uuid4()),
            "plan_content_hash": "a" * 64,
            "capability_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    detail = client.get(f"/api/v1/jobs/{queued.json()['job_id']}")
    assert detail.status_code == 200
    assert "capability" not in str(detail.json()).lower()


def test_rename_planning_requires_a_fresh_review_grant(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    request = {
        "observation_id": str(uuid4()),
        "dependency_scope_id": str(uuid4()),
        "target_basename": "synthetic.epub",
    }
    denied = client.post(
        "/api/v1/ebooks/rename/candidates",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": login.json()["csrf"],
            "Idempotency-Key": "synthetic-proposal-1",
        },
        json=request,
    )
    assert denied.json()["code"] == "REVIEW_GRANT_REQUIRED"
    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    assert reauth.status_code == 200
    assert reauth.json()["status"] == "REVIEW_GRANT_ISSUED"
    csrf_denied = client.post(
        "/api/v1/ebooks/rename/candidates",
        headers={"Origin": ORIGIN, "Idempotency-Key": "synthetic-proposal-csrf"},
        json=request,
    )
    assert csrf_denied.json()["code"] == "CSRF_REJECTED"
    unavailable = client.post(
        "/api/v1/ebooks/rename/candidates",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "synthetic-proposal-2",
        },
        json=request,
    )
    assert unavailable.json()["code"] == "EBOOK_RENAME_UNAVAILABLE"


def test_private_boundary_requires_a_fresh_rotated_grant(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )

    denied = client.get("/api/v1/private/session")
    assert denied.status_code == 403
    assert denied.headers["cache-control"] == "no-store"

    reauth = client.post(
        "/api/v1/session/reauth",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    assert reauth.status_code == 200
    unavailable = client.get(
        f"/api/v1/private/ebooks/collection-states/{uuid4()}/search",
        params={"query": '{"where":{"field":"FORMAT","operator":"EQ","value":"EPUB"}}'},
    )
    assert unavailable.status_code == 503
    assert unavailable.headers["cache-control"] == "no-store"


def test_private_boundary_hides_unexpected_errors_and_disables_caching(
    head_database_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database, raise_server_exceptions=False)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Marta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Marta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    assert reauth.status_code == 200

    def fail_private_read(*_args: object, **_kwargs: object) -> None:
        raise OSError("C:/private/synthetic-library.sqlite")

    monkeypatch.setattr(
        FolioToneApplication,
        "private_ebook_fixity_result_detail",
        fail_private_read,
    )
    response = client.get(f"/api/v1/private/ebooks/fixity/results/{EntityId.new()}")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "private" not in response.text.lower()


def test_jobs_and_audit_are_bounded_public_application_projections(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    _add_fixity_root(database)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    service = LocalSurfaceService(store)
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    user = store.only_user()
    assert user is not None
    job_id = store.enqueue_ebook_fixity_analysis_job(
        actor_id=user.id,
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        binder=EbookFixityAnalysisJobBinder(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            scan_root_id=_FIXITY_ROOT_ID,
        ),
    )

    jobs = client.get("/api/v1/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["items"] == [
        {
            "job_id": job_id,
            "command_profile": "ebook-fixity-baseline-build/v1",
            "created_at": jobs.json()["items"][0]["created_at"],
            "status": "WAITING",
            "worker_role": "analysis-worker",
        }
    ]
    assert "input_digest" not in jobs.text
    assert client.get(f"/api/v1/jobs/{job_id}").json()["events"][0]["status"] == "WAITING"
    audit = client.get("/api/v1/audit-events")
    assert audit.status_code == 200
    assert any(item["event_type"] == "JOB_ACCEPTED" for item in audit.json()["items"])
    assert client.get("/api/v1/jobs", params={"cursor": "wrong"}).json()["code"] == "CURSOR_INVALID"
    assert login.status_code == 200


def test_fixity_enqueue_is_csrf_idempotent_and_path_free(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    _add_fixity_root(database)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    payload = {"scan_root_id": _FIXITY_ROOT_ID, "worker_count": 2}
    denied = client.post(
        "/api/v1/ebooks/fixity/baselines",
        headers={"Origin": ORIGIN, "Idempotency-Key": "fixity-baseline-1"},
        json=payload,
    )
    assert denied.json()["code"] == "CSRF_REJECTED"
    headers = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": login.json()["csrf"],
        "Idempotency-Key": "fixity-baseline-1",
    }
    accepted = client.post("/api/v1/ebooks/fixity/baselines", headers=headers, json=payload)
    repeated = client.post("/api/v1/ebooks/fixity/baselines", headers=headers, json=payload)
    assert accepted.status_code == repeated.status_code == 201
    assert accepted.json() == repeated.json()
    assert accepted.json()["profile"] == "ebook-fixity-baseline-build/v1"
    assert "path" not in accepted.text.lower()
    assert "hash" not in accepted.text.lower()
    assert client.get("/api/v1/ebooks/fixity/baselines/not-an-id").status_code == 404


def test_fixity_activation_is_grant_bound_atomic_idempotent_and_secret_free(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    manifest_id = _ready_fixity_manifest(database)
    divergent_manifest_id = _ready_fixity_manifest(database, reuse_root=True)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    confirmation = expected_fixity_baseline_confirmation(manifest_id)
    route = f"/api/v1/ebooks/fixity/baselines/{manifest_id}/activation"
    base_headers = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": login.json()["csrf"],
        "Idempotency-Key": "fixity-activation-1",
    }

    missing_grant = client.post(route, headers=base_headers, json={"confirmation": confirmation})
    assert missing_grant.status_code == 403
    assert missing_grant.json()["code"] == "REVIEW_GRANT_REQUIRED"

    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    assert reauth.status_code == 200
    headers = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": reauth.json()["csrf"],
        "Idempotency-Key": "fixity-activation-1",
    }
    csrf_denied = client.post(
        route,
        headers={"Origin": ORIGIN, "Idempotency-Key": "fixity-activation-csrf"},
        json={"confirmation": confirmation},
    )
    assert csrf_denied.status_code == 403
    assert csrf_denied.json()["code"] == "CSRF_REJECTED"
    wrong = client.post(route, headers=headers, json={"confirmation": "wrong"})
    assert wrong.status_code == 409
    assert wrong.json()["code"] == "FIXITY_BASELINE_ACTIVATION_REJECTED"

    accepted = client.post(route, headers=headers, json={"confirmation": confirmation})
    replay = client.post(route, headers=headers, json={"confirmation": confirmation})
    assert accepted.status_code == replay.status_code == 200
    assert accepted.json() == replay.json()
    assert accepted.json()["status"] == "ACTIVE"

    divergent = client.post(
        f"/api/v1/ebooks/fixity/baselines/{divergent_manifest_id}/activation",
        headers=headers,
        json={"confirmation": expected_fixity_baseline_confirmation(divergent_manifest_id)},
    )
    assert divergent.status_code == 409
    assert divergent.json()["code"] == "FIXITY_BASELINE_ACTIVATION_REJECTED"
    dump = "\n".join(sqlite3.connect(database).iterdump())
    assert confirmation not in dump


def test_fixity_activation_rejects_expired_review_grant(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    manifest_id = _ready_fixity_manifest(database)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            update(surface_grants)
            .where(surface_grants.c.scope == "REVIEW")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    response = client.post(
        f"/api/v1/ebooks/fixity/baselines/{manifest_id}/activation",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "fixity-activation-expired",
        },
        json={"confirmation": expected_fixity_baseline_confirmation(manifest_id)},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "REVIEW_GRANT_REQUIRED"


def test_fixity_activation_receipt_failure_rolls_back_the_activation(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    manifest_id = _ready_fixity_manifest(database)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER synthetic_fixity_receipt_failure BEFORE UPDATE OF response_json "
                "ON surface_command_receipts WHEN OLD.command_profile="
                "'ebook-fixity-baseline-activation/v1' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END"
            )
        )
    confirmation = expected_fixity_baseline_confirmation(manifest_id)
    response = client.post(
        f"/api/v1/ebooks/fixity/baselines/{manifest_id}/activation",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "fixity-activation-crash",
        },
        json={"confirmation": confirmation},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "FIXITY_BASELINE_ACTIVATION_REJECTED"
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_fixity_baseline_activations")
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM surface_command_receipts WHERE command_profile="
                "'ebook-fixity-baseline-activation/v1'"
            )
        ).scalar_one() == 0
    assert confirmation not in "\n".join(sqlite3.connect(database).iterdump())


def test_fixity_review_and_expectation_surface_is_atomic_bounded_and_private(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    manifest_id, run_id, result_ids = _actionable_fixity_results(database)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    result_route = f"/api/v1/ebooks/fixity/results/{result_ids[0]}"
    review_route = f"{result_route}/reviews"
    expectation_route = f"{result_route}/expectations"
    csrf_only = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": login.json()["csrf"],
        "Idempotency-Key": "fixity-review-1",
    }
    no_csrf = client.post(
        review_route,
        headers={"Origin": ORIGIN, "Idempotency-Key": "fixity-review-csrf"},
        json={"decision": "DEFER"},
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_REJECTED"
    no_grant = client.post(review_route, headers=csrf_only, json={"decision": "DEFER"})
    assert no_grant.status_code == 403
    assert no_grant.json()["code"] == "REVIEW_GRANT_REQUIRED"

    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    headers = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": reauth.json()["csrf"],
        "Idempotency-Key": "fixity-review-1",
    }
    deferred = client.post(review_route, headers=headers, json={"decision": "DEFER"})
    replay = client.post(review_route, headers=headers, json={"decision": "DEFER"})
    divergent = client.post(review_route, headers=headers, json={"decision": "ACCEPT"})
    assert deferred.status_code == replay.status_code == 201
    assert deferred.json() == replay.json()
    assert deferred.json()["decision"] == "DEFER"
    assert divergent.status_code == 409
    assert divergent.json()["code"] == "FIXITY_REVIEW_REJECTED"
    assert "path" not in deferred.text.lower()
    assert "hash" not in deferred.text.lower()

    result_page = client.get(
        f"/api/v1/ebooks/fixity/verifications/{run_id}/results",
        params={"limit": 1},
    )
    assert result_page.status_code == 200
    assert result_page.json()["next_cursor"] is not None
    assert "sha256" not in result_page.text
    assert "locator" not in result_page.text
    cross_resource = client.get(
        "/api/v1/ebooks/fixity/reviews",
        params={"cursor": result_page.json()["next_cursor"]},
    )
    assert cross_resource.status_code == 400
    assert cross_resource.json()["code"] == "CURSOR_INVALID"
    queue = client.get("/api/v1/ebooks/fixity/reviews")
    assert queue.status_code == 200
    assert queue.json()["reviews"][0]["result_id"] == str(result_ids[0])
    assert "fingerprint" not in queue.text

    accepted_headers = dict(headers, **{"Idempotency-Key": "fixity-review-accept"})
    accepted = client.post(review_route, headers=accepted_headers, json={"decision": "ACCEPT"})
    assert accepted.status_code == 201
    assert accepted.json()["sequence_no"] == 2

    engine = create_sqlite_engine(database)
    with engine.begin() as connection:
        original_fingerprint = str(
            connection.execute(
                text("SELECT evidence_fingerprint FROM review_decisions WHERE id=:id"),
                {"id": accepted.json()["decision_id"]},
            ).scalar_one()
        )
        connection.execute(
            text("UPDATE review_decisions SET evidence_fingerprint=:value WHERE id=:id"),
            {"value": "f" * 64, "id": accepted.json()["decision_id"]},
        )
    stale_fingerprint = client.post(
        expectation_route,
        headers=dict(headers, **{"Idempotency-Key": "fixity-expectation-fingerprint"}),
        json={"action": "ACCEPT_CURRENT"},
    )
    assert stale_fingerprint.status_code == 409
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE review_decisions SET evidence_fingerprint=:value WHERE id=:id"),
            {"value": original_fingerprint, "id": accepted.json()["decision_id"]},
        )

    wrong_action = client.post(
        expectation_route,
        headers=dict(headers, **{"Idempotency-Key": "fixity-expectation-wrong"}),
        json={"action": "RETIRE_MISSING"},
    )
    assert wrong_action.status_code == 409
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER synthetic_fixity_expectation_receipt_failure "
                "BEFORE UPDATE OF response_json ON surface_command_receipts "
                "WHEN OLD.command_profile='ebook-fixity-expectation-revision/v1' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END"
            )
        )
    failed = client.post(
        expectation_route,
        headers=dict(headers, **{"Idempotency-Key": "fixity-expectation-crash"}),
        json={"action": "ACCEPT_CURRENT"},
    )
    assert failed.status_code == 409
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_fixity_expectation_revisions")
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM surface_command_receipts "
                "WHERE command_profile='ebook-fixity-expectation-revision/v1'"
            )
        ).scalar_one() == 0
        connection.execute(text("DROP TRIGGER synthetic_fixity_expectation_receipt_failure"))

    expectation_headers = dict(headers, **{"Idempotency-Key": "fixity-expectation-1"})
    revised = client.post(
        expectation_route,
        headers=expectation_headers,
        json={"action": "ACCEPT_CURRENT"},
    )
    revised_replay = client.post(
        expectation_route,
        headers=expectation_headers,
        json={"action": "ACCEPT_CURRENT"},
    )
    assert revised.status_code == revised_replay.status_code == 201
    assert revised.json() == revised_replay.json()
    assert revised.json()["revision_no"] == 1
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_fixity_expectation_revisions")
        ).scalar_one() == 1
        receipt_material = "\n".join(
            str(value)
            for row in connection.execute(
                text(
                    "SELECT input_digest,idempotency_digest,response_json "
                    "FROM surface_command_receipts "
                    "WHERE command_profile LIKE 'ebook-fixity-%'"
                )
            )
            for value in row
        )
    assert "synthetic-0.epub" not in receipt_material
    assert "1" * 64 not in receipt_material
    assert "2" * 64 not in receipt_material
    stale = client.post(
        expectation_route,
        headers=dict(headers, **{"Idempotency-Key": "fixity-expectation-stale"}),
        json={"action": "ACCEPT_CURRENT"},
    )
    assert stale.status_code == 409

    private_denied = client.get(
        f"/api/v1/private/ebooks/fixity/results/{result_ids[0]}"
    )
    assert private_denied.status_code == 403
    assert private_denied.headers["cache-control"] == "no-store"
    private_reauth = client.post(
        "/api/v1/session/reauth",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": reauth.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    private_entry = client.get(
        f"/api/v1/private/ebooks/fixity/baselines/{manifest_id}/entries",
        params={"limit": 1},
    )
    assert private_reauth.status_code == 200
    assert private_entry.status_code == 200
    assert private_entry.headers["cache-control"] == "no-store"
    assert private_entry.json()["entries"][0]["relative_locator"] == "synthetic-0.epub"
    private_result = client.get(
        f"/api/v1/private/ebooks/fixity/results/{result_ids[0]}"
    )
    assert private_result.status_code == 200
    assert private_result.headers["cache-control"] == "no-store"
    assert private_result.json()["current"]["relative_locator"] in {
        "synthetic-0.epub",
        "synthetic-1.epub",
    }
    missing_private = client.get(
        f"/api/v1/private/ebooks/fixity/results/{EntityId.new()}"
    )
    assert missing_private.status_code == 404
    assert missing_private.headers["cache-control"] == "no-store"
    missing_baseline = client.get(
        f"/api/v1/private/ebooks/fixity/baselines/{EntityId.new()}/entries"
    )
    assert missing_baseline.status_code == 404
    assert missing_baseline.headers["cache-control"] == "no-store"

    with engine.begin() as connection:
        connection.execute(
            text("DROP TRIGGER ebook_fixity_verification_results_no_update")
        )
        connection.execute(
            text(
                "UPDATE ebook_fixity_verification_results "
                "SET current_relative_locator='C:/private/book.epub' WHERE id=:id"
            ),
            {"id": str(result_ids[0])},
        )
    absolute_rejected = client.get(
        f"/api/v1/private/ebooks/fixity/results/{result_ids[0]}"
    )
    assert absolute_rejected.status_code == 404
    assert absolute_rejected.headers["cache-control"] == "no-store"


def test_fixity_review_concurrent_retry_and_fresh_grant_fence(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    _, _, result_ids = _actionable_fixity_results(database, count=4)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        session_id, actor_id = connection.execute(
            text(
                "SELECT id,user_id FROM surface_sessions "
                "WHERE revoked_at IS NULL ORDER BY created_at DESC LIMIT 1"
            )
        ).one()
    operation = SQLiteEbookFixityCommandOperation(engine)
    with pytest.raises(ValueError, match="SHA-256"):
        operation.review_result(
            EbookFixityReviewCommand(result_id=result_ids[0], decision="DEFER"),
            actor_id=str(actor_id),
            session_id=str(session_id),
            input_digest="raw-review-input",
            idempotency_digest="d" * 64,
            decided_at=datetime.now(UTC).replace(microsecond=0),
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER synthetic_fixity_review_receipt_failure "
                "BEFORE UPDATE OF response_json ON surface_command_receipts "
                "WHEN OLD.command_profile='ebook-fixity-result-review/v1' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END"
            )
        )
    with pytest.raises(RuntimeError, match="transaction failed"):
        operation.review_result(
            EbookFixityReviewCommand(result_id=result_ids[0], decision="DEFER"),
            actor_id=str(actor_id),
            session_id=str(session_id),
            input_digest="c" * 64,
            idempotency_digest="d" * 64,
            decided_at=datetime.now(UTC).replace(microsecond=0),
        )
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM review_items WHERE candidate_id=:result"),
            {"result": str(result_ids[0])},
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM review_decisions AS decision "
                "JOIN review_items AS item ON item.id=decision.review_item_id "
                "WHERE item.candidate_id=:result"
            ),
            {"result": str(result_ids[0])},
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_fixity_expectation_revisions")
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM surface_command_receipts "
                "WHERE command_profile='ebook-fixity-result-review/v1'"
            )
        ).scalar_one() == 0
        connection.execute(text("DROP TRIGGER synthetic_fixity_review_receipt_failure"))

    command = EbookFixityReviewCommand(result_id=result_ids[1], decision="DEFER")
    decided_at = datetime.now(UTC).replace(microsecond=0)

    def run() -> object:
        return operation.review_result(
            command,
            actor_id=str(actor_id),
            session_id=str(session_id),
            input_digest="a" * 64,
            idempotency_digest="b" * 64,
            decided_at=decided_at,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(lambda _index: run(), range(2)))
    assert first == second

    def run_divergent(decision: str, input_digest: str) -> object:
        try:
            return operation.review_result(
                EbookFixityReviewCommand(result_id=result_ids[2], decision=decision),
                actor_id=str(actor_id),
                session_id=str(session_id),
                input_digest=input_digest,
                idempotency_digest="e" * 64,
                decided_at=decided_at,
            )
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        divergent = tuple(
            pool.map(
                lambda arguments: run_divergent(*arguments),
                (("ACCEPT", "f" * 64), ("REJECT", "0" * 64)),
            )
        )
    assert sum(isinstance(item, ValueError) for item in divergent) == 1
    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM review_decisions AS decision "
                "JOIN review_items AS item ON item.id=decision.review_item_id "
                "WHERE item.candidate_id=:result"
            ),
            {"result": str(result_ids[1])},
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM review_decisions AS decision "
                "JOIN review_items AS item ON item.id=decision.review_item_id "
                "WHERE item.candidate_id=:result"
            ),
            {"result": str(result_ids[2])},
        ).scalar_one() == 1
        connection.execute(
            update(surface_grants)
            .where(surface_grants.c.scope == "REVIEW")
            .values(
                created_at=decided_at - timedelta(minutes=16),
                expires_at=decided_at + timedelta(minutes=5),
            )
        )
    stale_grant = client.post(
        f"/api/v1/ebooks/fixity/results/{result_ids[3]}/reviews",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "stale-review-grant",
        },
        json={"decision": "DEFER"},
    )
    assert stale_grant.status_code == 409
    with engine.begin() as connection:
        connection.execute(
            update(surface_grants)
            .where(surface_grants.c.scope == "REVIEW")
            .values(revoked_at=decided_at)
        )
    revoked = client.post(
        f"/api/v1/ebooks/fixity/results/{result_ids[3]}/reviews",
        headers={
            "Origin": ORIGIN,
            "X-FolioTone-CSRF": reauth.json()["csrf"],
            "Idempotency-Key": "revoked-review-grant",
        },
        json={"decision": "DEFER"},
    )
    assert revoked.status_code == 403
    assert revoked.json()["code"] == "REVIEW_GRANT_REQUIRED"


@pytest.mark.parametrize("divergent", (False, True))
def test_fixity_expectation_parallel_requests_are_atomic_and_idempotent(
    head_database_factory,
    divergent: bool,
) -> None:
    database = head_database_factory(f"surface-expectation-parallel-{divergent}.sqlite")
    _, _, result_ids = _actionable_fixity_results(database, count=2)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    common_headers = {
        "Origin": ORIGIN,
        "X-FolioTone-CSRF": reauth.json()["csrf"],
    }
    for index, result_id in enumerate(result_ids):
        accepted = client.post(
            f"/api/v1/ebooks/fixity/results/{result_id}/reviews",
            headers=dict(
                common_headers,
                **{"Idempotency-Key": f"parallel-expectation-review-{index}"},
            ),
            json={"decision": "ACCEPT"},
        )
        assert accepted.status_code == 201

    routes = [
        f"/api/v1/ebooks/fixity/results/{result_ids[0]}/expectations",
        f"/api/v1/ebooks/fixity/results/{result_ids[1 if divergent else 0]}/expectations",
    ]
    start = Barrier(2)

    def post_expectation(route: str):
        with _client(database) as parallel_client:
            parallel_client.cookies.update(client.cookies)
            start.wait()
            return parallel_client.post(
                route,
                headers=dict(
                    common_headers,
                    **{"Idempotency-Key": "parallel-expectation-key"},
                ),
                json={"action": "ACCEPT_CURRENT"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = tuple(pool.map(post_expectation, routes))

    if divergent:
        assert sorted(response.status_code for response in responses) == [201, 409]
        losing_index = next(
            index for index, response in enumerate(responses) if response.status_code == 409
        )
        rejected = responses[losing_index]
        assert rejected.json()["code"] == "FIXITY_EXPECTATION_REJECTED"
        stable_rejected = client.post(
            routes[losing_index],
            headers=dict(
                common_headers,
                **{"Idempotency-Key": "parallel-expectation-key"},
            ),
            json={"action": "ACCEPT_CURRENT"},
        )
        assert stable_rejected.status_code == 409
        assert stable_rejected.json() == rejected.json()
    else:
        assert all(response.status_code == 201 for response in responses)
        assert responses[0].content == responses[1].content

    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM ebook_fixity_expectation_revisions")
        ).scalar_one() == 1
        receipt_count, statuses = connection.execute(
            text(
                "SELECT COUNT(*), group_concat(status) FROM surface_command_receipts "
                "WHERE command_profile='ebook-fixity-expectation-revision/v1'"
            )
        ).one()
    assert receipt_count == 1
    assert statuses == "COMPLETED"


def test_fixity_review_rejects_non_completed_and_stale_verification_runs(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    _, completed_run_id, completed_result_ids = _actionable_fixity_results(database, count=1)
    client = _client(database)
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    bootstrap = LocalSurfaceService(store).bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    login = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    reauth_response = client.post(
        "/api/v1/session/reauth-review",
        headers={"Origin": ORIGIN, "X-FolioTone-CSRF": login.json()["csrf"]},
        json={"password": "ein sehr langes Passwort"},
    )
    assert reauth_response.status_code == 200
    engine = create_sqlite_engine(database)
    with engine.connect() as connection:
        session_id, actor_id = connection.execute(
            text(
                "SELECT id,user_id FROM surface_sessions "
                "WHERE revoked_at IS NULL ORDER BY created_at DESC LIMIT 1"
            )
        ).one()
        root_id = EntityId.parse(
            str(
                connection.execute(
                    text(
                        "SELECT scan_root_id FROM ebook_fixity_verification_runs WHERE id=:id"
                    ),
                    {"id": str(completed_run_id)},
                ).scalar_one()
            )
        )
    now = datetime.now(UTC).replace(microsecond=0)
    verification = SQLiteEbookFixityVerificationStore(engine)
    incomplete = verification.start_run(
        EntityId.new(),
        root_id,
        started_at=now,
        lease_token="synthetic-incomplete-review",
        lease_expires_at=now + timedelta(minutes=2),
    )
    work = verification.read_workset_batch(
        incomplete,
        observed_at=now + timedelta(seconds=1),
        batch_size=1,
    )[0]
    incomplete_result = EbookFixityVerificationResultRecord(
        result_id=EntityId.new(),
        run_id=incomplete.run.run_id,
        file_id=work.file_id,
        result=EbookFixityVerificationResult.UNEXPECTED_BYTE_CHANGE,
        expected_observation_id=work.expected_observation_id,
        expected_size_bytes=work.expected_size_bytes,
        expected_sha256=work.expected_sha256,
        expected_relative_locator=work.expected_relative_locator,
        current_observation_id=work.current_observation_id,
        current_size_bytes=work.current_size_bytes,
        current_sha256="3" * 64,
        current_relative_locator=work.current_relative_locator,
    )
    verification.append_results(
        incomplete,
        (incomplete_result,),
        recorded_at=now + timedelta(seconds=2),
    )
    operation = SQLiteEbookFixityCommandOperation(engine)
    with pytest.raises(RuntimeError, match="incomplete|completed"):
        operation.review_result(
            EbookFixityReviewCommand(
                result_id=incomplete_result.result_id,
                decision="ACCEPT",
            ),
            actor_id=str(actor_id),
            session_id=str(session_id),
            input_digest="4" * 64,
            idempotency_digest="5" * 64,
            decided_at=now + timedelta(seconds=3),
        )
    verification.fail_run(
        incomplete,
        failed_at=now + timedelta(seconds=4),
        failure_code="TEST_STOP",
    )
    with pytest.raises(RuntimeError, match="latest verification run"):
        operation.review_result(
            EbookFixityReviewCommand(
                result_id=completed_result_ids[0],
                decision="ACCEPT",
            ),
            actor_id=str(actor_id),
            session_id=str(session_id),
            input_digest="6" * 64,
            idempotency_digest="7" * 64,
            decided_at=now + timedelta(seconds=5),
        )


def test_ebook_read_projections_are_application_bound_and_path_free(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database, ebook_read_model=_SyntheticEbookReadModel())
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()
    client.post(
        "/api/v1/setup",
        headers={"Origin": ORIGIN},
        json={
            "bootstrap_code": bootstrap,
            "username": "Märta",
            "password": "ein sehr langes Passwort",
        },
    )
    client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "Märta", "password": "ein sehr langes Passwort"},
    )
    sample_id = "00000000-0000-0000-0000-000000000001"
    assert (
        client.get(f"/api/v1/ebooks/scan-roots/{sample_id}/status").json()["status"] == "COMPLETED"
    )
    assert client.get(f"/api/v1/ebooks/scan-roots/{sample_id}/inventory").json()["formats"] == [
        {"format": "EPUB"}
    ]
    assert client.get(f"/api/v1/ebooks/collection-runs/{sample_id}/analysis").json()[
        "analysis_coverage"
    ] == {"SUCCEEDED": 1}
    evidence = client.get(f"/api/v1/ebooks/collection-runs/{sample_id}/evidence")
    assert evidence.status_code == 200
    reviews = client.get(f"/api/v1/ebooks/collection-runs/{sample_id}/reviews")
    assert reviews.json()["items"][0]["priority"] == "REVIEW"
    assert (
        client.get("/api/v1/ebooks/plans").json()["items"][0]["execution_state"] == "NOT_EXECUTABLE"
    )
    assert "path" not in evidence.text.lower()
