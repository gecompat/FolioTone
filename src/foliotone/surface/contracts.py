"""Stable contracts for the local-single-operator surface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SURFACE_PROFILE: Final = "local-single-operator/v1"
OPENAPI_VERSION: Final = "3.1.0"
MAX_REQUEST_BYTES: Final = 1_048_576
SESSION_COOKIE_NAME: Final = "foliotone_session"
CSRF_HEADER_NAME: Final = "X-FolioTone-CSRF"


class ProcessRole(StrEnum):
    """Runtime roles that must not share source-media authority."""

    SURFACE_API = "surface-api"
    ANALYSIS_WORKER = "analysis-worker"
    OPERATOR_WORKER = "operator-worker"


class Scope(StrEnum):
    """Endpoint authorisation scopes."""

    READ = "READ"
    PRIVATE_READ = "PRIVATE_READ"
    REVIEW = "REVIEW"
    OPERATE = "OPERATE"
    ADMIN = "ADMIN"


class JobStatus(StrEnum):
    """Persisted queue states visible without private job input."""

    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True, slots=True)
class SurfaceRuntimeConfig:
    """Loopback-only runtime configuration for one same-origin surface."""

    bind_host: str = "127.0.0.1"
    port: int = 8765
    secure_cookie: bool = False

    def __post_init__(self) -> None:
        if self.bind_host not in {"127.0.0.1", "::1"}:
            raise ValueError("surface binding must be an explicit loopback address")
        if not 1 <= self.port <= 65535:
            raise ValueError("surface port is invalid")

    @property
    def origin(self) -> str:
        host = f"[{self.bind_host}]" if self.bind_host == "::1" else self.bind_host
        return f"http{'s' if self.secure_cookie else ''}://{host}:{self.port}"
