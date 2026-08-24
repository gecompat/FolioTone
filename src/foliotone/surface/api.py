"""Loopback-only same-origin FastAPI adapter for the local product surface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, cast

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from foliotone.application import (
    ApplicationJobDetailQuery,
    CollectionSearchQuery,
    CollectionStateQuery,
    EbookProjectionQuery,
    EbookToolchainReadinessQuery,
    FolioToneApplication,
    LibraryHealthQuery,
    SurfacePageQuery,
    create_application,
)
from foliotone.application.services import (
    CollectionSearchReader,
    CollectionStateReader,
    EbookReadModel,
    LibraryHealthReader,
    SurfaceReadModel,
)
from foliotone.collection_state import parse_collection_query_spec
from foliotone.core import EntityId
from foliotone.persistence.surface import SurfaceSession
from foliotone.surface.contracts import (
    CSRF_HEADER_NAME,
    MAX_REQUEST_BYTES,
    OPENAPI_VERSION,
    SESSION_COOKIE_NAME,
    SURFACE_PROFILE,
    Scope,
    SurfaceRuntimeConfig,
)
from foliotone.surface.read import CursorCodec, CursorError
from foliotone.surface.security import SurfaceSecurityError
from foliotone.surface.service import LocalSurfaceService

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; style-src 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_STATIC_ROOT = Path(__file__).with_name("static")


class SetupRequest(BaseModel):
    bootstrap_code: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=15, max_length=4096)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=15, max_length=4096)


class ReauthRequest(BaseModel):
    password: str = Field(min_length=15, max_length=4096)


class SurfaceSecurityMiddleware(BaseHTTPMiddleware):
    """Reject non-local origins, oversized bodies, and unsafe mutating requests."""

    def __init__(self, app: ASGIApp, config: SurfaceRuntimeConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        host = request.headers.get("host", "")
        host_name = (
            f"[{self._config.bind_host}]"
            if self._config.bind_host == "::1"
            else self._config.bind_host
        )
        expected_host = f"{host_name}:{self._config.port}"
        if host != expected_host:
            return _security_problem(400, "SURFACE_HOST_REJECTED", request=request)
        length = request.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_REQUEST_BYTES):
            return _security_problem(413, "REQUEST_TOO_LARGE", request=request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("origin") != self._config.origin:
                return _security_problem(403, "SURFACE_ORIGIN_REJECTED", request=request)
            content_type = request.headers.get("content-type", "")
            if not content_type.startswith("application/json"):
                return _security_problem(415, "JSON_REQUIRED", request=request)
            if length is None and len(await request.body()) > MAX_REQUEST_BYTES:
                return _security_problem(413, "REQUEST_TOO_LARGE", request=request)
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


def problem(status: int, code: str) -> JSONResponse:
    """Return the public RFC 9457-compatible problem shape without internal detail."""
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://foliotone.invalid/problems/{code}",
            "title": code,
            "status": status,
            "code": code,
        },
        media_type="application/problem+json",
    )


def _security_problem(status: int, code: str, *, request: Request) -> JSONResponse:
    response = problem(status, code)
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    if request.url.path.startswith("/api/v1/private/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def create_surface_app(
    service: LocalSurfaceService,
    *,
    config: SurfaceRuntimeConfig | None = None,
    application: FolioToneApplication | None = None,
    collection_state_reader: CollectionStateReader | None = None,
    library_health_reader: LibraryHealthReader | None = None,
    collection_search_reader: CollectionSearchReader | None = None,
    surface_read_model: SurfaceReadModel | None = None,
    ebook_read_model: EbookReadModel | None = None,
) -> FastAPI:
    """Create a transport adapter that exposes no source-media authority."""
    config = config or SurfaceRuntimeConfig()
    application = application or create_application()
    cursor_codec = CursorCodec()
    app = FastAPI(
        title="FolioTone local surface",
        version=SURFACE_PROFILE,
        openapi_version=OPENAPI_VERSION,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(SurfaceSecurityMiddleware, config=config)

    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, error: HTTPException) -> JSONResponse:
        response = problem(error.status_code, str(error.detail))
        if request.url.path.startswith("/api/v1/private/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(
        request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        response = problem(400, "REQUEST_INVALID")
        if request.url.path.startswith("/api/v1/private/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session_dependency(
        token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> SurfaceSession:
        if token is None:
            raise HTTPException(401, "SESSION_REQUIRED")
        session = service.authenticate(token)
        if session is None:
            raise HTTPException(401, "SESSION_REQUIRED")
        return session

    def csrf_dependency(
        request: Request,
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
        csrf: Annotated[str | None, Header(alias=CSRF_HEADER_NAME)] = None,
    ) -> SurfaceSession:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            csrf is None or not service.csrf_valid(session, csrf)
        ):
            raise HTTPException(403, "CSRF_REJECTED")
        return session

    def private_read_dependency(
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> SurfaceSession:
        if not service.has_active_grant(session, Scope.PRIVATE_READ):
            raise HTTPException(403, "PRIVATE_READ_GRANT_REQUIRED")
        return session

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def shell() -> FileResponse:
        return FileResponse(_STATIC_ROOT / "index.html", media_type="text/html")

    @app.get("/assets/{asset_name}", include_in_schema=False)
    async def asset(asset_name: str) -> FileResponse:
        if asset_name not in {"app.css", "app.js"}:
            raise HTTPException(404, "ASSET_NOT_FOUND")
        media_type = "text/css" if asset_name.endswith(".css") else "application/javascript"
        return FileResponse(_STATIC_ROOT / asset_name, media_type=media_type)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"profile": SURFACE_PROFILE, "status": "READY"}

    @app.get("/api/v1/setup-status")
    async def setup_status() -> dict[str, bool]:
        return {"setup_required": service.setup_required()}

    @app.get("/api/v1/media-lines")
    async def media_lines(
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        """Expose only the bounded product-entry registry after authentication."""
        return {
            "profile": application.media_lines.profile,
            "items": [
                {"media_line": entry.media_line.value, "enabled": entry.enabled}
                for entry in application.media_lines.entries
            ],
        }

    @app.get("/api/v1/ebooks/collection-states/{snapshot_id}")
    async def collection_state(
        snapshot_id: str,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        if collection_state_reader is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        try:
            report = application.collection_state_report(
                collection_state_reader,
                CollectionStateQuery(snapshot_id=EntityId.parse(snapshot_id)),
            )
        except (ValueError, RuntimeError):
            raise HTTPException(404, "COLLECTION_STATE_UNAVAILABLE") from None
        snapshot = report.snapshot
        return {
            "profile": report.profile,
            "snapshot_id": str(snapshot.id),
            "scan_root_id": str(snapshot.scan_root_id),
            "source_scan_run_id": str(snapshot.source_scan_run_id),
            "created_at": snapshot.created_at.isoformat(),
            "counts": {count.key: count.value for count in snapshot.counts},
            "truncated": any(
                component.truncation_state.value != "NONE" for component in snapshot.components
            ),
        }

    @app.get("/api/v1/ebooks/collection-states/{snapshot_id}/library-health")
    async def library_health(
        snapshot_id: str,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        if library_health_reader is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        try:
            report = application.library_health_report(
                library_health_reader,
                LibraryHealthQuery(snapshot_id=EntityId.parse(snapshot_id)),
            )
        except (ValueError, RuntimeError):
            raise HTTPException(404, "LIBRARY_HEALTH_UNAVAILABLE") from None
        snapshot = report.snapshot
        return {
            "profile": report.profile,
            "health_snapshot_id": str(snapshot.id),
            "collection_state_snapshot_id": str(snapshot.collection_state_snapshot_id),
            "created_at": snapshot.created_at.isoformat(),
            "item_count": snapshot.item_count,
            "finding_count": snapshot.finding_count,
            "dimensions": [
                {
                    "dimension": dimension.dimension.value,
                    "status": dimension.status.value,
                    "coverage": dimension.coverage_state.value,
                    "assessed_item_count": dimension.assessed_item_count,
                    "covered_item_count": dimension.covered_item_count,
                    "affected_item_count": dimension.affected_item_count,
                }
                for dimension in snapshot.dimensions
            ],
        }

    @app.get("/api/v1/private/session")
    async def private_session(
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            private_read_dependency
        ),
    ) -> JSONResponse:
        """Prove the bounded private route boundary without returning collection data."""
        return JSONResponse(
            content={"status": "PRIVATE_READ_ACTIVE"},
            headers={"Cache-Control": "no-store"},
        )

    def collection_search_response(
        *,
        snapshot_id: str,
        query: str,
        cursor: str | None,
        private_details: bool,
    ) -> dict[str, object]:
        if collection_search_reader is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        try:
            parsed_snapshot_id = EntityId.parse(snapshot_id)
            base_spec = replace(parse_collection_query_spec(query), after_file_id=None)
            resource = f"collection-search/v1:{snapshot_id}:{base_spec.query_digest}"
            spec = base_spec
            if cursor is not None:
                decoded = cursor_codec.decode(
                    cursor,
                    resource=resource,
                    sort="FILE_ID_ASC",
                )
                spec = replace(base_spec, after_file_id=EntityId.parse(decoded.last_id))
            report = application.collection_search(
                collection_search_reader,
                CollectionSearchQuery(
                    snapshot_id=parsed_snapshot_id,
                    spec=spec,
                    private_details=private_details,
                ),
            )
        except CursorError:
            raise HTTPException(400, "CURSOR_INVALID") from None
        except (ValueError, RuntimeError):
            raise HTTPException(400, "COLLECTION_SEARCH_INVALID") from None
        payload = report.payload()
        next_after = payload.pop("next_after_file_id")
        payload["next_cursor"] = (
            None
            if next_after is None
            else cursor_codec.encode(
                resource=resource,
                sort="FILE_ID_ASC",
                last_id=str(next_after),
            )
        )
        if private_details:
            payload["private_details"] = True
            payload["private_hits"] = [
                {
                    "file_id": str(hit.file_id),
                    "observation_id": str(hit.observation_id),
                    "metadata": [
                        {"field": value.field.value, "value": value.value}
                        for value in report.private_values(hit)
                    ],
                }
                for hit in report.page.hits
            ]
        return payload

    def surface_page_response(
        *,
        resource: str,
        cursor: str | None,
        fetch: Callable[[SurfacePageQuery], tuple[tuple[dict[str, object], ...], str | None]],
    ) -> dict[str, object]:
        if surface_read_model is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        after_id = None
        if cursor is not None:
            try:
                after_id = cursor_codec.decode(cursor, resource=resource, sort="ID_ASC").last_id
            except CursorError:
                raise HTTPException(400, "CURSOR_INVALID") from None
        items, next_after = fetch(SurfacePageQuery(after_id=after_id))
        return {
            "items": items,
            "next_cursor": None
            if next_after is None
            else cursor_codec.encode(resource=resource, sort="ID_ASC", last_id=next_after),
        }

    def ebook_projection_response(projection_id: str, kind: str) -> dict[str, object]:
        if ebook_read_model is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        try:
            payload = application.ebook_projection(
                ebook_read_model,
                EbookProjectionQuery(projection_id=EntityId.parse(projection_id)),
                kind,
            )
        except ValueError:
            raise HTTPException(404, "EBOOK_PROJECTION_UNAVAILABLE") from None
        if payload is None:
            raise HTTPException(404, "EBOOK_PROJECTION_UNAVAILABLE")
        return payload

    def ebook_page_response(
        *, resource: str, run_id: str | None, cursor: str | None, plans: bool = False
    ) -> dict[str, object]:
        if ebook_read_model is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        after_id = None
        if cursor is not None:
            try:
                after_id = cursor_codec.decode(cursor, resource=resource, sort="ID_ASC").last_id
            except CursorError:
                raise HTTPException(400, "CURSOR_INVALID") from None
        page = SurfacePageQuery(after_id=after_id)
        if plans:
            items, next_after = application.ebook_plans(ebook_read_model, page)
        else:
            try:
                items, next_after = application.ebook_review_queue(
                    ebook_read_model,
                    EbookProjectionQuery(projection_id=EntityId.parse(run_id or "")),
                    page,
                )
            except ValueError:
                raise HTTPException(404, "EBOOK_PROJECTION_UNAVAILABLE") from None
        return {
            "items": items,
            "next_cursor": None
            if next_after is None
            else cursor_codec.encode(resource=resource, sort="ID_ASC", last_id=next_after),
        }

    @app.get("/api/v1/ebooks/collection-states/{snapshot_id}/search")
    async def collection_search(
        snapshot_id: str,
        query: str,
        cursor: str | None = None,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        return collection_search_response(
            snapshot_id=snapshot_id,
            query=query,
            cursor=cursor,
            private_details=False,
        )

    @app.get("/api/v1/private/ebooks/collection-states/{snapshot_id}/search")
    async def private_collection_search(
        snapshot_id: str,
        query: str,
        cursor: str | None = None,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            private_read_dependency
        ),
    ) -> JSONResponse:
        return JSONResponse(
            content=collection_search_response(
                snapshot_id=snapshot_id,
                query=query,
                cursor=cursor,
                private_details=True,
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/ebooks/scan-roots/{scan_root_id}/status")
    async def scan_status(
        scan_root_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_projection_response(scan_root_id, "scan-status")

    @app.get("/api/v1/ebooks/readiness")
    async def toolchain_readiness(
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        """Run the existing bounded Doctor without opening source media."""
        report = application.ebook_toolchain_readiness(
            EbookToolchainReadinessQuery(
                ebook_meta_executable="ebook-meta",
                ebook_convert_executable="ebook-convert",
                calibre_debug_executable="calibre-debug",
                pdfinfo_executable="pdfinfo",
                pdftotext_executable="pdftotext",
                java_executable="java",
                epubcheck_jar=Path("epubcheck.jar"),
            )
        )
        return report.as_dict()

    @app.get("/api/v1/ebooks/scan-roots/{scan_root_id}/inventory")
    async def inventory(
        scan_root_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_projection_response(scan_root_id, "inventory")

    @app.get("/api/v1/ebooks/collection-runs/{run_id}/analysis")
    async def collection_analysis(
        run_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_projection_response(run_id, "collection-analysis")

    @app.get("/api/v1/ebooks/collection-runs/{run_id}/reviews")
    async def review_queue(
        run_id: str,
        cursor: str | None = None,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_page_response(
            resource=f"ebook-review-queue/v1:{run_id}", run_id=run_id, cursor=cursor
        )

    @app.get("/api/v1/ebooks/collection-runs/{run_id}/evidence")
    async def candidate_evidence(
        run_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_projection_response(run_id, "candidate-evidence")

    @app.get("/api/v1/ebooks/plans")
    async def plans(
        cursor: str | None = None,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_page_response(
            resource="ebook-plans/v1", run_id=None, cursor=cursor, plans=True
        )

    @app.get("/api/v1/ebooks/plans/{plan_id}")
    async def plan_report(
        plan_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_projection_response(plan_id, "plan-report")

    @app.get("/api/v1/jobs")
    async def jobs(
        cursor: str | None = None,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        return surface_page_response(
            resource="application-jobs/v1",
            cursor=cursor,
            fetch=lambda query: application.jobs(cast(SurfaceReadModel, surface_read_model), query),
        )

    @app.get("/api/v1/jobs/{job_id}")
    async def job_detail(
        job_id: str,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        if surface_read_model is None:
            raise HTTPException(503, "READ_PROJECTION_UNAVAILABLE")
        detail = application.job_detail(
            surface_read_model, ApplicationJobDetailQuery(job_id=job_id)
        )
        if detail is None:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return detail

    @app.get("/api/v1/audit-events")
    async def audit_events(
        cursor: str | None = None,
        _session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, object]:
        return surface_page_response(
            resource="surface-audit-events/v1",
            cursor=cursor,
            fetch=lambda query: application.audit_events(
                cast(SurfaceReadModel, surface_read_model), query
            ),
        )

    @app.post("/api/v1/setup", status_code=201)
    async def setup(payload: SetupRequest) -> dict[str, str]:
        try:
            user = service.setup(
                bootstrap_code=payload.bootstrap_code,
                username=payload.username,
                password=payload.password,
            )
        except SurfaceSecurityError:
            raise HTTPException(400, "SETUP_REJECTED") from None
        if user is None:
            raise HTTPException(403, "SETUP_REJECTED")
        return {"status": "SETUP_COMPLETED"}

    @app.post("/api/v1/session")
    async def login(payload: LoginRequest, response: Response) -> dict[str, str]:
        try:
            authenticated = service.login(username=payload.username, password=payload.password)
        except SurfaceSecurityError:
            authenticated = None
        if authenticated is None:
            raise HTTPException(401, "LOGIN_REJECTED")
        token, csrf, _session = authenticated
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=config.secure_cookie,
            path="/",
            max_age=None,
        )
        return {"csrf": csrf}

    @app.get("/api/v1/session")
    async def current_session(
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            session_dependency
        ),
    ) -> dict[str, str]:
        return {"status": "AUTHENTICATED", "scope": "ADMIN", "session_id": session.id}

    @app.delete("/api/v1/session", status_code=204)
    async def logout(
        response: Response,
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> None:
        service.logout(session)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return None

    @app.post("/api/v1/session/reauth")
    async def reauth(
        payload: ReauthRequest,
        response: Response,
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> dict[str, str]:
        rotated = service.reauthenticate(session, payload.password)
        if rotated is None:
            raise HTTPException(401, "REAUTH_REJECTED")
        token, csrf, _session = rotated
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            httponly=True,
            samesite="strict",
            secure=config.secure_cookie,
            path="/",
            max_age=None,
        )
        response.headers["Cache-Control"] = "no-store"
        return {"status": "PRIVATE_READ_GRANT_ISSUED", "csrf": csrf}

    return app
