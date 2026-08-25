from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from foliotone.core import EntityId
from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import ProcessRole, SurfaceRuntimeConfig
from foliotone.surface.service import LocalSurfaceService

ORIGIN = "http://127.0.0.1:8765"


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


def _client(database: Path, *, ebook_read_model: object | None = None) -> TestClient:
    store = SQLiteSurfaceStore(create_sqlite_engine(database))
    service = LocalSurfaceService(store)
    app = create_surface_app(
        service,
        config=SurfaceRuntimeConfig(),
        surface_read_model=store,
        ebook_read_model=ebook_read_model,
    )
    return TestClient(app, base_url=ORIGIN)


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


def test_jobs_and_audit_are_bounded_public_application_projections(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
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
    job_id = store.enqueue_job(
        actor_id=user.id,
        command_profile="synthetic-read-model/v1",
        input_digest="a" * 64,
        idempotency_digest="b" * 64,
        worker_role=ProcessRole.ANALYSIS_WORKER,
    )

    jobs = client.get("/api/v1/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["items"] == [
        {
            "job_id": job_id,
            "command_profile": "synthetic-read-model/v1",
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
