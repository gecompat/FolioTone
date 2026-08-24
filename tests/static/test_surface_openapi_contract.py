from __future__ import annotations

import hashlib
import json
from pathlib import Path

from foliotone.persistence.sqlite import create_sqlite_engine
from foliotone.persistence.surface import SQLiteSurfaceStore
from foliotone.surface.api import create_surface_app
from foliotone.surface.contracts import OPENAPI_VERSION, SurfaceRuntimeConfig
from foliotone.surface.service import LocalSurfaceService


def test_openapi_contract_is_pinned_and_has_no_unregistered_media_crud(
    head_database_factory,
) -> None:
    database = head_database_factory("surface.sqlite")
    app = create_surface_app(
        LocalSurfaceService(SQLiteSurfaceStore(create_sqlite_engine(database))),
        config=SurfaceRuntimeConfig(),
    )
    schema = app.openapi()
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()

    assert schema["openapi"] == OPENAPI_VERSION
    assert set(schema["paths"]) == {
        "/api/v1/health",
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/audit-events",
        "/api/v1/ebooks/collection-states/{snapshot_id}",
        "/api/v1/ebooks/collection-states/{snapshot_id}/library-health",
        "/api/v1/ebooks/collection-states/{snapshot_id}/search",
        "/api/v1/ebooks/scan-roots/{scan_root_id}/status",
        "/api/v1/ebooks/scan-roots/{scan_root_id}/inventory",
        "/api/v1/ebooks/readiness",
        "/api/v1/ebooks/collection-runs/{run_id}/analysis",
        "/api/v1/ebooks/collection-runs/{run_id}/reviews",
        "/api/v1/ebooks/collection-runs/{run_id}/evidence",
        "/api/v1/ebooks/plans",
        "/api/v1/ebooks/plans/{plan_id}",
        "/api/v1/media-lines",
        "/api/v1/setup-status",
        "/api/v1/setup",
        "/api/v1/session",
        "/api/v1/session/reauth",
        "/api/v1/private/ebooks/collection-states/{snapshot_id}/search",
        "/api/v1/private/session",
    }
    assert (
        hashlib.sha256(payload).hexdigest()
        == "ca02b4075701a368b532f7d0c471726cb96e566d164373fbe717f883d3fc9498"
    )


def test_local_ui_has_german_accessible_read_only_workflows() -> None:
    root = Path("src/foliotone/surface/static")
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")

    for marker in (
        'lang="de"',
        'class="skip-link"',
        'id="setup-form"',
        'id="login-form"',
        'id="reauth-form"',
        'id="search-form"',
        'aria-live="polite"',
        "Jobs",
        "Audit",
    ):
        assert marker in html
    assert "http://" not in html
    assert "https://" not in html
    assert "JSON.stringify" in script
    assert "textContent" in script
    assert "/api/v1/ebooks/collection-states/" in script
    assert "innerHTML" not in script
