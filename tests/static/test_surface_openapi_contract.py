from __future__ import annotations

import hashlib
import json

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
        "/api/v1/setup-status",
        "/api/v1/setup",
        "/api/v1/session",
        "/api/v1/session/reauth",
    }
    assert (
        hashlib.sha256(payload).hexdigest()
        == "4e598d4981356e6ce4c3ca0802d241e29113a0c12db0a0533a5db478b755b938"
    )
