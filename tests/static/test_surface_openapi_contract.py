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
        "/api/v1/ebooks/rename/candidates",
        "/api/v1/ebooks/rename/candidates/{candidate_id}",
        "/api/v1/ebooks/rename/candidates/{candidate_id}/reviews",
        "/api/v1/ebooks/rename/candidates/{candidate_id}/plans",
        "/api/v1/ebooks/rename/authorizations",
        "/api/v1/ebooks/rename/executions",
        "/api/v1/ebooks/rename/recoveries",
        "/api/v1/media-lines",
        "/api/v1/setup-status",
        "/api/v1/setup",
        "/api/v1/session",
        "/api/v1/session/reauth",
        "/api/v1/session/reauth-operate",
        "/api/v1/session/reauth-review",
        "/api/v1/private/ebooks/collection-states/{snapshot_id}/search",
        "/api/v1/private/ebooks/rename/candidates/{candidate_id}",
        "/api/v1/private/session",
    }
    assert (
        hashlib.sha256(payload).hexdigest()
        == "1cb2d81c7a4de1df3633cd6ac2b8d0107d60cf1e8fcd411b8314683044a46ce1"
    )


def test_local_ui_has_german_accessible_read_only_workflows() -> None:
    root = Path("src/foliotone/surface/static")
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    styles = (root / "app.css").read_text(encoding="utf-8")

    for marker in (
        'lang="de"',
        'class="skip-link"',
        'id="setup-form"',
        'id="login-form"',
        'id="reauth-form"',
        'id="rename-proposal-form"',
        'id="rename-execute-form"',
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
    assert "next_cursor" in script
    assert "Nächste Seite" in script
    assert "/api/v1/ebooks/readiness" in script
    assert "/api/v1/ebooks/collection-runs/" in script
    assert "renderTable" in script
    assert 'value == null ? "—"' in script
    assert "Array.isArray(payload.hits)" in script
    assert "Object.entries(hit.statuses || {})" in script
    assert "innerHTML" not in script
    assert '"Idempotency-Key"' in script
    assert "/api/v1/ebooks/rename/executions" in script
    assert "#search-results table { table-layout: fixed; }" in styles
    assert "#search-results th:nth-child(4)" in styles


def test_local_surface_workers_wait_for_the_schema_owner() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    rename_compose = Path("compose.rename.yaml").read_text(encoding="utf-8")

    assert compose.count("condition: service_healthy") == 1
    assert "urlopen('http://127.0.0.1:8765/api/v1/health')" in compose
    assert "analysis-worker:\n    profiles: [\"local-surface\"]" in compose
    assert "--container-loopback-publish" in compose
    assert 'ports:\n      - "127.0.0.1:8765:8765"' in compose
    assert "FOLIOTONE_MUSIC_DIR" not in compose
    assert "operator-worker:" not in compose
    assert "operator-worker:\n    profiles: [\"ebook-rename\"]" in rename_compose
    assert rename_compose.count("condition: service_healthy") == 1
    assert "FOLIOTONE_EBOOK_RENAME_CAPABILITIES_FILE:?" in rename_compose
    assert "FOLIOTONE_EBOOK_RENAME_DEPENDENCY_SCOPES_FILE:?" in rename_compose
    assert "FOLIOTONE_EBOOK_RENAME_WRITABLE_ROOT:?" in rename_compose
    assert "network_mode: none" in rename_compose
    assert 'source: "${FOLIOTONE_EBOOKS_DIR:-./media/ebooks}"' not in rename_compose
