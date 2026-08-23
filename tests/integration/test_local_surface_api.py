from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import SurfaceRuntimeConfig
from foliotone.surface.service import LocalSurfaceService

ORIGIN = "http://127.0.0.1:8765"


def _client(database: Path) -> TestClient:
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    app = create_surface_app(service, config=SurfaceRuntimeConfig())
    return TestClient(app, base_url=ORIGIN)


def test_surface_requires_owner_bootstrap_and_fences_origin(head_database_factory) -> None:
    database = head_database_factory("surface.sqlite")
    client = _client(database)
    service = LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database)))
    bootstrap = service.bootstrap()

    rejected = client.post("/api/v1/setup", json={})
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "SURFACE_ORIGIN_REJECTED"

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
