"""Loopback-only same-origin FastAPI adapter for the local product surface."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from foliotone.persistence.surface import SurfaceSession
from foliotone.surface.contracts import (
    CSRF_HEADER_NAME,
    MAX_REQUEST_BYTES,
    OPENAPI_VERSION,
    SESSION_COOKIE_NAME,
    SURFACE_PROFILE,
    SurfaceRuntimeConfig,
)
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
        expected_host = f"{self._config.bind_host}:{self._config.port}"
        if host != expected_host:
            return problem(400, "SURFACE_HOST_REJECTED")
        length = request.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_REQUEST_BYTES):
            return problem(413, "REQUEST_TOO_LARGE")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("origin") != self._config.origin:
                return problem(403, "SURFACE_ORIGIN_REJECTED")
            content_type = request.headers.get("content-type", "")
            if not content_type.startswith("application/json"):
                return problem(415, "JSON_REQUIRED")
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


def create_surface_app(
    service: LocalSurfaceService,
    *,
    config: SurfaceRuntimeConfig | None = None,
) -> FastAPI:
    """Create a transport adapter that exposes no source-media authority."""
    config = config or SurfaceRuntimeConfig()
    app = FastAPI(
        title="FolioTone local surface",
        version=SURFACE_PROFILE,
        openapi_version=OPENAPI_VERSION,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(SurfaceSecurityMiddleware, config=config)

    @app.exception_handler(HTTPException)
    async def _http_exception(_request: Request, error: HTTPException) -> JSONResponse:
        return problem(error.status_code, str(error.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return problem(400, "REQUEST_INVALID")

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

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def shell() -> str:
        return (
            '<!doctype html><html lang="de"><head><meta charset="utf-8">'
            "<title>FolioTone</title></head><body><main><h1>FolioTone</h1>"
            "<p>Lokale Oberfläche wird vorbereitet.</p></main></body></html>"
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"profile": SURFACE_PROFILE, "status": "READY"}

    @app.get("/api/v1/setup-status")
    async def setup_status() -> dict[str, bool]:
        return {"setup_required": service.setup_required()}

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
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> dict[str, str]:
        if not service.grant_after_reauth(session, payload.password):
            raise HTTPException(401, "REAUTH_REJECTED")
        return {"status": "OPERATOR_GRANT_ISSUED"}

    return app
