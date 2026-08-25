"""Loopback-only same-origin FastAPI adapter for the local product surface."""

from __future__ import annotations

import json
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
    EbookFixityAnalysisJobCommand,
    EbookFixityAnalysisJobProfile,
    EbookFixityBaselineActivationCommand,
    EbookFixityExpectationRevisionCommand,
    EbookFixityPrivateBaselineEntryPageQuery,
    EbookFixityPrivateResultDetailQuery,
    EbookFixityResultPageQuery,
    EbookFixityReviewCommand,
    EbookProjectionQuery,
    EbookRenameOperatorJobProfile,
    EbookRenamePlanCommand,
    EbookRenamePreviewQuery,
    EbookRenameProposalCommand,
    EbookRenameReviewCommand,
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
    EbookRenamePlanningPort,
    LibraryHealthReader,
    SurfaceReadModel,
)
from foliotone.collection_state import parse_collection_query_spec
from foliotone.core import EntityId, ReviewDecisionValue
from foliotone.persistence.surface import (
    EbookRenameOperatorJobBinder,
    SurfaceSession,
)
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
from foliotone.surface.security import SurfaceSecurityError, secret_digest
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


class EbookRenameProposalRequest(BaseModel):
    observation_id: str = Field(min_length=36, max_length=36)
    dependency_scope_id: str = Field(min_length=36, max_length=36)
    target_basename: str = Field(min_length=1, max_length=255)


class EbookRenameReviewRequest(BaseModel):
    decision: str = Field(pattern="^(ACCEPT|REJECT|DEFER)$")


class EbookRenameAuthorizationRequest(BaseModel):
    plan_id: str = Field(min_length=36, max_length=36)
    plan_content_hash: str = Field(pattern="^[0-9a-f]{64}$")
    capability_id: str = Field(min_length=36, max_length=36)


class EbookRenameExecutionRequest(EbookRenameAuthorizationRequest):
    authorization_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(min_length=1, max_length=256)


class EbookRenameRecoveryRequest(BaseModel):
    run_id: str = Field(min_length=36, max_length=36)


class EbookFixityJobRequest(BaseModel):
    scan_root_id: str = Field(min_length=36, max_length=36)
    worker_count: int = Field(default=1, ge=1, le=2)


class EbookFixityActivationRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=256)


class EbookFixityReviewRequest(BaseModel):
    decision: str = Field(pattern="^(ACCEPT|REJECT|DEFER)$")


class EbookFixityExpectationRequest(BaseModel):
    action: str = Field(pattern="^(ACCEPT_CURRENT|RETIRE_MISSING)$")


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
    ebook_rename_planning: EbookRenamePlanningPort | None = None,
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

    @app.exception_handler(Exception)
    async def _unexpected_exception(request: Request, _error: Exception) -> JSONResponse:
        response = problem(500, "INTERNAL_ERROR")
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

    def review_dependency(
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> SurfaceSession:
        if not service.has_active_grant(session, Scope.REVIEW):
            raise HTTPException(403, "REVIEW_GRANT_REQUIRED")
        return session

    def operate_dependency(
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> SurfaceSession:
        if not service.has_active_grant(session, Scope.OPERATE):
            raise HTTPException(403, "OPERATE_GRANT_REQUIRED")
        return session

    def rename_planning() -> EbookRenamePlanningPort:
        if ebook_rename_planning is None:
            raise HTTPException(503, "EBOOK_RENAME_UNAVAILABLE")
        return ebook_rename_planning

    def require_idempotency(value: str | None) -> str:
        if value is None or not 1 <= len(value) <= 128:
            raise HTTPException(400, "IDEMPOTENCY_KEY_REQUIRED")
        return value

    def job_digests(
        profile: EbookRenameOperatorJobProfile,
        binder: EbookRenameOperatorJobBinder,
        key: str,
    ) -> tuple[str, str]:
        material = json.dumps(
            {
                "profile": profile.value,
                "plan_id": binder.plan_id,
                "plan_content_hash": binder.plan_content_hash,
                "capability_id": binder.capability_id,
                "authorization_id": binder.authorization_id,
                "run_id": binder.run_id,
                "confirmation_digest": binder.confirmation_digest,
                "operate_grant_id": binder.operate_grant_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            secret_digest(material, purpose="ebook-rename-job-input"),
            secret_digest(key, purpose="ebook-rename-job-idempotency"),
        )

    def planning_receipt(
        *,
        profile: str,
        session: SurfaceSession,
        idempotency_key: str | None,
        semantic_input: dict[str, str],
    ) -> tuple[dict[str, object] | None, dict[str, str]]:
        """Replay one actor-bound planning response; never retain raw transport input."""
        key = require_idempotency(idempotency_key)
        material = json.dumps(semantic_input, sort_keys=True, separators=(",", ":"))
        arguments = {
            "actor_id": session.user_id,
            "command_profile": profile,
            "input_digest": secret_digest(material, purpose="ebook-rename-planning-input"),
            "idempotency_digest": secret_digest(key, purpose="ebook-rename-planning-idempotency"),
        }
        return service.claim_command_receipt(**arguments), arguments

    def enqueue_fixity_job(
        *,
        profile: EbookFixityAnalysisJobProfile,
        payload: EbookFixityJobRequest,
        session: SurfaceSession,
        key: str | None,
    ) -> dict[str, object]:
        idempotency_key = require_idempotency(key)
        try:
            scan_root_id = EntityId.parse(payload.scan_root_id)
        except ValueError:
            raise HTTPException(400, "FIXITY_JOB_REJECTED") from None
        material = json.dumps(
            {
                "profile": profile.value,
                "scan_root_id": str(scan_root_id),
                "worker_count": payload.worker_count,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            job_id = application.enqueue_ebook_fixity_job(
                service,
                EbookFixityAnalysisJobCommand(
                    profile=profile,
                    scan_root_id=scan_root_id,
                    worker_count=payload.worker_count,
                ),
                actor_id=session.user_id,
                input_digest=secret_digest(material, purpose="ebook-fixity-job-input"),
                idempotency_digest=secret_digest(
                    idempotency_key, purpose="ebook-fixity-job-idempotency"
                ),
            )
        except (RuntimeError, ValueError):
            raise HTTPException(409, "FIXITY_JOB_REJECTED") from None
        return {"job_id": job_id, "profile": profile.value, "status": "WAITING"}

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

    @app.post("/api/v1/ebooks/fixity/baselines", status_code=201)
    async def enqueue_fixity_baseline(
        payload: EbookFixityJobRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(csrf_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return enqueue_fixity_job(
            profile=EbookFixityAnalysisJobProfile.BASELINE_BUILD,
            payload=payload,
            session=session,
            key=idempotency_key,
        )

    @app.get("/api/v1/ebooks/fixity/baselines/{manifest_id}")
    async def fixity_baseline_status(
        manifest_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        try:
            status = application.ebook_fixity_baseline_status(service, EntityId.parse(manifest_id))
        except (RuntimeError, ValueError):
            status = None
        if status is None:
            raise HTTPException(404, "FIXITY_BASELINE_UNAVAILABLE")
        return {
            "manifest_id": str(status.manifest_id),
            "scan_root_id": str(status.scan_root_id),
            "source_scan_run_id": str(status.source_scan_run_id),
            "status": status.status,
            "started_at": status.started_at,
            "prepared_at": status.prepared_at,
            "expires_at": status.expires_at,
            "item_count": status.item_count,
            "activated_at": None if status.activated_at is None else status.activated_at,
        }

    @app.post("/api/v1/ebooks/fixity/baselines/{manifest_id}/activation")
    async def activate_fixity_baseline(
        manifest_id: str,
        payload: EbookFixityActivationRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        try:
            parsed_manifest_id = EntityId.parse(manifest_id)
            command = EbookFixityBaselineActivationCommand(
                manifest_id=parsed_manifest_id,
                confirmation=payload.confirmation,
            )
            key = require_idempotency(idempotency_key)
            material = json.dumps(
                {"manifest_id": manifest_id, "confirmation": payload.confirmation},
                sort_keys=True,
                separators=(",", ":"),
            )
            activation = application.activate_ebook_fixity_baseline(
                service,
                command,
                actor_id=session.user_id,
                session_id=session.id,
                input_digest=secret_digest(
                    material, purpose="ebook-fixity-activation-input"
                ),
                idempotency_digest=secret_digest(
                    key, purpose="ebook-fixity-activation-idempotency"
                ),
            )
        except (RuntimeError, TypeError, ValueError):
            raise HTTPException(409, "FIXITY_BASELINE_ACTIVATION_REJECTED") from None
        return {
            "activation_id": str(activation.activation_id),
            "manifest_id": str(activation.manifest_id),
            "status": "ACTIVE",
        }

    @app.post("/api/v1/ebooks/fixity/verifications", status_code=201)
    async def enqueue_fixity_verification(
        payload: EbookFixityJobRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(csrf_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return enqueue_fixity_job(
            profile=EbookFixityAnalysisJobProfile.VERIFICATION,
            payload=payload,
            session=session,
            key=idempotency_key,
        )

    @app.get("/api/v1/ebooks/fixity/verifications/{run_id}")
    async def fixity_verification_status(
        run_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        try:
            status = application.ebook_fixity_verification_status(service, EntityId.parse(run_id))
        except (RuntimeError, ValueError):
            status = None
        if status is None:
            raise HTTPException(404, "FIXITY_VERIFICATION_UNAVAILABLE")
        return {
            "run_id": str(status.run_id),
            "scan_root_id": str(status.scan_root_id),
            "baseline_activation_id": str(status.baseline_activation_id),
            "source_scan_run_id": str(status.source_scan_run_id),
            "expectation_revision_no": status.expectation_revision_no,
            "status": status.status,
            "started_at": status.started_at,
            "completed_at": status.completed_at,
            "expected_result_count": status.expected_result_count,
            "result_count": status.result_count,
            "failure_code": status.failure_code,
        }

    @app.get("/api/v1/private/ebooks/fixity/baselines/{manifest_id}/entries")
    async def fixity_baseline_entries(
        manifest_id: str,
        cursor: str | None = None,
        limit: int = 50,
        _session: SurfaceSession = Depends(private_read_dependency),  # noqa: B008
    ) -> JSONResponse:
        try:
            after = None
            if cursor is not None:
                after = int(cursor_codec.decode(
                    cursor, resource=f"fixity-baseline-entry/v1:{manifest_id}", sort="ORDINAL_ASC"
                ).last_id)
            page = application.private_ebook_fixity_baseline_entries(
                service,
                EbookFixityPrivateBaselineEntryPageQuery(
                    manifest_id=EntityId.parse(manifest_id),
                    after_ordinal=after,
                    limit=limit,
                ),
            )
        except CursorError:
            raise HTTPException(400, "CURSOR_INVALID") from None
        except (RuntimeError, ValueError):
            raise HTTPException(404, "FIXITY_BASELINE_ENTRIES_UNAVAILABLE") from None
        return JSONResponse(
            content={
                "manifest_id": str(page.manifest_id),
                "entries": [
                    {
                        "file_id": str(item.file_id),
                        "relative_locator": item.relative_locator,
                        "size_bytes": item.size_bytes,
                        "sha256": item.sha256,
                    }
                    for item in page.entries
                ],
                "next_cursor": None
                if page.next_after_ordinal is None
                else cursor_codec.encode(
                    resource=f"fixity-baseline-entry/v1:{manifest_id}", sort="ORDINAL_ASC",
                    last_id=str(page.next_after_ordinal)
                ),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/ebooks/fixity/verifications/{run_id}/results")
    async def fixity_result_summaries(
        run_id: str,
        cursor: str | None = None,
        limit: int = 50,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        try:
            after = None if cursor is None else EntityId.parse(cursor_codec.decode(
                cursor, resource=f"fixity-result-summary/v1:{run_id}", sort="ID_ASC"
            ).last_id)
            items, next_after = application.ebook_fixity_results(
                service,
                EbookFixityResultPageQuery(
                    run_id=EntityId.parse(run_id),
                    after_id=after,
                    limit=limit,
                ),
            )
        except CursorError:
            raise HTTPException(400, "CURSOR_INVALID") from None
        except (RuntimeError, ValueError):
            raise HTTPException(404, "FIXITY_RESULTS_UNAVAILABLE") from None
        return {
            "run_id": run_id,
            "results": [
                {"result_id": str(item.result_id), "file_id": str(item.file_id),
                 "result": item.result, "failure_code": item.failure_code}
                for item in items
            ],
            "next_cursor": None if next_after is None else cursor_codec.encode(
                resource=f"fixity-result-summary/v1:{run_id}",
                sort="ID_ASC",
                last_id=str(next_after),
            ),
        }

    @app.get("/api/v1/private/ebooks/fixity/results/{result_id}")
    async def fixity_result_detail(
        result_id: str,
        _session: SurfaceSession = Depends(private_read_dependency),  # noqa: B008
    ) -> JSONResponse:
        try:
            item = application.private_ebook_fixity_result_detail(
                service,
                EbookFixityPrivateResultDetailQuery(result_id=EntityId.parse(result_id)),
            )
        except (RuntimeError, ValueError):
            item = None
        if item is None:
            raise HTTPException(404, "FIXITY_RESULT_UNAVAILABLE")
        return JSONResponse(
            content={
                "result_id": str(item.result_id),
                "run_id": str(item.run_id),
                "file_id": str(item.file_id),
                "result": item.result,
                "expected": {
                    "observation_id": None
                    if item.expected.observation_id is None
                    else str(item.expected.observation_id),
                    "relative_locator": item.expected.relative_locator,
                    "size_bytes": item.expected.size_bytes,
                    "sha256": item.expected.sha256,
                },
                "current": {
                    "observation_id": None
                    if item.current.observation_id is None
                    else str(item.current.observation_id),
                    "relative_locator": item.current.relative_locator,
                    "size_bytes": item.current.size_bytes,
                    "sha256": item.current.sha256,
                },
                "failure_code": item.failure_code,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/ebooks/fixity/reviews")
    async def fixity_review_queue(
        cursor: str | None = None,
        limit: int = 50,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        try:
            after_id = None
            if cursor is not None:
                after_id = cursor_codec.decode(
                    cursor,
                    resource="fixity-review-queue/v1",
                    sort="ID_ASC",
                ).last_id
            items, next_after = application.ebook_fixity_review_queue(
                service,
                SurfacePageQuery(after_id=after_id, limit=limit),
            )
        except CursorError:
            raise HTTPException(400, "CURSOR_INVALID") from None
        except (RuntimeError, ValueError):
            raise HTTPException(404, "FIXITY_REVIEWS_UNAVAILABLE") from None
        return {
            "reviews": [
                {
                    "review_item_id": str(item.review_item_id),
                    "result_id": str(item.result_id),
                    "file_id": str(item.file_id),
                    "state": item.state,
                    "created_at": item.created_at,
                }
                for item in items
            ],
            "next_cursor": None
            if next_after is None
            else cursor_codec.encode(
                resource="fixity-review-queue/v1",
                sort="ID_ASC",
                last_id=str(next_after),
            ),
        }

    @app.post("/api/v1/ebooks/fixity/results/{result_id}/reviews", status_code=201)
    async def review_fixity_result(
        result_id: str,
        payload: EbookFixityReviewRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        key = require_idempotency(idempotency_key)
        try:
            parsed_result_id = EntityId.parse(result_id)
            material = json.dumps(
                {"result_id": str(parsed_result_id), "decision": payload.decision},
                sort_keys=True,
                separators=(",", ":"),
            )
            result = application.review_ebook_fixity_result(
                service,
                EbookFixityReviewCommand(
                    result_id=parsed_result_id,
                    decision=payload.decision,
                ),
                actor_id=session.user_id,
                session_id=session.id,
                input_digest=secret_digest(
                    material,
                    purpose="ebook-fixity-review-input",
                ),
                idempotency_digest=secret_digest(
                    key,
                    purpose="ebook-fixity-review-idempotency",
                ),
            )
        except (RuntimeError, ValueError):
            raise HTTPException(409, "FIXITY_REVIEW_REJECTED") from None
        return {
            "result_id": str(result.result_id),
            "review_item_id": str(result.review_item_id),
            "decision_id": str(result.decision_id),
            "decision": result.decision,
            "sequence_no": result.sequence_no,
        }

    @app.post("/api/v1/ebooks/fixity/results/{result_id}/expectations", status_code=201)
    async def revise_fixity_expectation(
        result_id: str,
        payload: EbookFixityExpectationRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        key = require_idempotency(idempotency_key)
        try:
            parsed_result_id = EntityId.parse(result_id)
            material = json.dumps(
                {"result_id": str(parsed_result_id), "action": payload.action},
                sort_keys=True,
                separators=(",", ":"),
            )
            result = application.revise_ebook_fixity_expectation(
                service,
                EbookFixityExpectationRevisionCommand(
                    result_id=parsed_result_id,
                    action=payload.action,
                ),
                actor_id=session.user_id,
                session_id=session.id,
                input_digest=secret_digest(
                    material,
                    purpose="ebook-fixity-expectation-input",
                ),
                idempotency_digest=secret_digest(
                    key,
                    purpose="ebook-fixity-expectation-idempotency",
                ),
            )
        except (RuntimeError, ValueError):
            raise HTTPException(409, "FIXITY_EXPECTATION_REJECTED") from None
        return {
            "result_id": str(result.result_id),
            "revision_id": str(result.revision_id),
            "action": result.action,
            "revision_no": result.revision_no,
        }

    @app.post("/api/v1/ebooks/rename/candidates", status_code=201)
    async def ebook_rename_propose(
        payload: EbookRenameProposalRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        existing, receipt = planning_receipt(
            profile="ebook-rename-proposal/v1",
            session=session,
            idempotency_key=idempotency_key,
            semantic_input={
                "observation_id": payload.observation_id,
                "dependency_scope_id": payload.dependency_scope_id,
                "target_basename": payload.target_basename,
            },
        )
        if existing is not None:
            return existing
        try:
            result = application.ebook_rename_proposal(
                rename_planning(),
                EbookRenameProposalCommand(
                    observation_id=EntityId.parse(payload.observation_id),
                    dependency_scope_id=EntityId.parse(payload.dependency_scope_id),
                    target_basename=payload.target_basename,
                ),
            )
        except (ValueError, RuntimeError):
            raise HTTPException(400, "EBOOK_RENAME_PROPOSAL_REJECTED") from None
        response: dict[str, object] = {
            "candidate_id": str(result.candidate_id),
            "review_item_id": str(result.review_item_id),
            "review_state": result.review_state.value,
            "dependency_states": [value.value for value in result.dependency_states],
        }
        return service.complete_command_receipt(**receipt, response=response)

    def ebook_rename_preview_response(
        candidate_id: str, *, private_details: bool
    ) -> dict[str, object]:
        try:
            preview = application.ebook_rename_preview(
                rename_planning(),
                EbookRenamePreviewQuery(candidate_id=EntityId.parse(candidate_id)),
            )
        except (ValueError, RuntimeError):
            raise HTTPException(404, "EBOOK_RENAME_CANDIDATE_UNAVAILABLE") from None
        result: dict[str, object] = {
            "candidate_id": str(preview.candidate_id),
            "candidate_profile": preview.candidate_profile,
            "operation_kind": preview.operation_kind.value,
            "status": preview.status.value,
            "execution_state": "NOT_EXECUTABLE",
            "review_state": preview.review_state.value,
            "counts": {
                "sources": preview.source_count,
                "dependencies": preview.dependency_count,
                "evidence_refs": preview.evidence_count,
                "blockers": len(preview.blocker_codes),
            },
            "blocker_codes": list(preview.blocker_codes),
        }
        if private_details:
            result["private_details"] = {
                "source_relative_locator": preview.source_relative_locator,
                "target_relative_locator": preview.target_relative_locator,
            }
        return result

    @app.get("/api/v1/ebooks/rename/candidates/{candidate_id}")
    async def ebook_rename_preview(
        candidate_id: str,
        _session: SurfaceSession = Depends(session_dependency),  # noqa: B008
    ) -> dict[str, object]:
        return ebook_rename_preview_response(candidate_id, private_details=False)

    @app.get("/api/v1/private/ebooks/rename/candidates/{candidate_id}")
    async def ebook_rename_private_preview(
        candidate_id: str,
        _session: SurfaceSession = Depends(private_read_dependency),  # noqa: B008
    ) -> JSONResponse:
        return JSONResponse(
            content=ebook_rename_preview_response(candidate_id, private_details=True),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/v1/ebooks/rename/candidates/{candidate_id}/reviews", status_code=201)
    async def ebook_rename_review(
        candidate_id: str,
        payload: EbookRenameReviewRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        existing, receipt = planning_receipt(
            profile="ebook-rename-review/v1",
            session=session,
            idempotency_key=idempotency_key,
            semantic_input={"candidate_id": candidate_id, "decision": payload.decision},
        )
        if existing is not None:
            return existing
        try:
            result = application.ebook_rename_review(
                rename_planning(),
                EbookRenameReviewCommand(
                    candidate_id=EntityId.parse(candidate_id),
                    decision=ReviewDecisionValue(payload.decision),
                ),
            )
        except (ValueError, RuntimeError):
            raise HTTPException(400, "EBOOK_RENAME_REVIEW_REJECTED") from None
        response: dict[str, object] = {
            "candidate_id": str(result.candidate_id),
            "review_item_id": str(result.review_item_id),
            "decision_id": str(result.decision_id),
            "decision": result.decision.value,
            "sequence_no": result.sequence_no,
        }
        return service.complete_command_receipt(**receipt, response=response)

    @app.post("/api/v1/ebooks/rename/candidates/{candidate_id}/plans", status_code=201)
    async def ebook_rename_plan(
        candidate_id: str,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(review_dependency),  # noqa: B008
    ) -> dict[str, object]:
        existing, receipt = planning_receipt(
            profile="ebook-rename-plan/v1",
            session=session,
            idempotency_key=idempotency_key,
            semantic_input={"candidate_id": candidate_id},
        )
        if existing is not None:
            return existing
        try:
            result = application.ebook_rename_plan(
                rename_planning(), EbookRenamePlanCommand(candidate_id=EntityId.parse(candidate_id))
            )
        except (ValueError, RuntimeError):
            raise HTTPException(400, "EBOOK_RENAME_PLAN_REJECTED") from None
        response: dict[str, object] = {
            "plan_id": str(result.plan_id),
            "candidate_id": str(result.candidate_id),
            "status": result.status.value,
            "execution_state": "NOT_EXECUTABLE",
            "review_state": result.review_state.value,
            "blocker_codes": list(result.blocker_codes),
        }
        return service.complete_command_receipt(**receipt, response=response)

    def enqueue_rename_job(
        *,
        profile: EbookRenameOperatorJobProfile,
        binder: EbookRenameOperatorJobBinder,
        session: SurfaceSession,
        idempotency_key: str | None,
    ) -> dict[str, str]:
        key = require_idempotency(idempotency_key)
        input_digest, idempotency_digest = job_digests(profile, binder, key)
        try:
            job_id = service.enqueue_ebook_rename_operator_job(
                actor_id=session.user_id,
                input_digest=input_digest,
                idempotency_digest=idempotency_digest,
                binder=binder,
            )
        except ValueError:
            raise HTTPException(409, "EBOOK_RENAME_JOB_REJECTED") from None
        return {"job_id": job_id, "status": "WAITING"}

    @app.post("/api/v1/ebooks/rename/authorizations", status_code=202)
    async def ebook_rename_authorize(
        payload: EbookRenameAuthorizationRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(operate_dependency),  # noqa: B008
    ) -> dict[str, str]:
        grant_id = service.active_operate_grant_id(session)
        if grant_id is None:
            raise HTTPException(403, "OPERATE_GRANT_REQUIRED")
        return enqueue_rename_job(
            profile=EbookRenameOperatorJobProfile.AUTHORIZE,
            binder=EbookRenameOperatorJobBinder(
                profile=EbookRenameOperatorJobProfile.AUTHORIZE,
                plan_id=payload.plan_id,
                plan_content_hash=payload.plan_content_hash,
                capability_id=payload.capability_id,
                operate_grant_id=grant_id,
            ),
            session=session,
            idempotency_key=idempotency_key,
        )

    @app.post("/api/v1/ebooks/rename/executions", status_code=202)
    async def ebook_rename_execute(
        payload: EbookRenameExecutionRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(operate_dependency),  # noqa: B008
    ) -> dict[str, str]:
        grant_id = service.active_operate_grant_id(session)
        if grant_id is None:
            raise HTTPException(403, "OPERATE_GRANT_REQUIRED")
        try:
            confirmation_digest = service.ebook_rename_confirmation_digest(
                plan_id=payload.plan_id,
                plan_content_hash=payload.plan_content_hash,
                capability_id=payload.capability_id,
                authorization_id=payload.authorization_id,
                confirmation_text=payload.confirmation,
            )
        except ValueError:
            raise HTTPException(400, "EBOOK_RENAME_CONFIRMATION_REJECTED") from None
        return enqueue_rename_job(
            profile=EbookRenameOperatorJobProfile.EXECUTE,
            binder=EbookRenameOperatorJobBinder(
                profile=EbookRenameOperatorJobProfile.EXECUTE,
                plan_id=payload.plan_id,
                plan_content_hash=payload.plan_content_hash,
                capability_id=payload.capability_id,
                operate_grant_id=grant_id,
                authorization_id=payload.authorization_id,
                confirmation_digest=confirmation_digest,
            ),
            session=session,
            idempotency_key=idempotency_key,
        )

    @app.post("/api/v1/ebooks/rename/recoveries", status_code=202)
    async def ebook_rename_recover(
        payload: EbookRenameRecoveryRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        session: SurfaceSession = Depends(operate_dependency),  # noqa: B008
    ) -> dict[str, str]:
        grant_id = service.active_operate_grant_id(session)
        if grant_id is None:
            raise HTTPException(403, "OPERATE_GRANT_REQUIRED")
        return enqueue_rename_job(
            profile=EbookRenameOperatorJobProfile.RECOVER,
            binder=EbookRenameOperatorJobBinder(
                profile=EbookRenameOperatorJobProfile.RECOVER,
                plan_id=None,
                plan_content_hash=None,
                capability_id=None,
                operate_grant_id=grant_id,
                run_id=payload.run_id,
            ),
            session=session,
            idempotency_key=idempotency_key,
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

    @app.post("/api/v1/session/reauth-operate")
    async def reauth_operate(
        payload: ReauthRequest,
        response: Response,
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> dict[str, str]:
        """Rotate the session before the bounded first-writer commands are accepted."""
        rotated = service.reauthenticate(session, payload.password, scope=Scope.OPERATE)
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
        return {"status": "OPERATE_GRANT_ISSUED", "csrf": csrf}

    @app.post("/api/v1/session/reauth-review")
    async def reauth_review(
        payload: ReauthRequest,
        response: Response,
        session: SurfaceSession = Depends(  # noqa: B008 - FastAPI dependency declaration
            csrf_dependency
        ),
    ) -> dict[str, str]:
        rotated = service.reauthenticate(session, payload.password, scope=Scope.REVIEW)
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
        return {"status": "REVIEW_GRANT_ISSUED", "csrf": csrf}

    return app
