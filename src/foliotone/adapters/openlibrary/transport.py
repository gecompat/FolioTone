"""Bounded, privacy-safe HTTP transport for the Open Library adapter.

The transport owns only the ADR-0036 wire boundary.  Source DTO parsing and
provider-cache projection deliberately remain in their respective modules.
"""

from __future__ import annotations

import json
import re
import ssl
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Final, Protocol
from urllib.parse import urlsplit

from foliotone.adapters.openlibrary.query import (
    OPENLIBRARY_HOST,
    OPENLIBRARY_PORT,
    OPENLIBRARY_SCHEME,
    OpenLibraryRequest,
    OpenLibraryRouteKind,
)
from foliotone.enrichment.provider_cache_contracts import ProviderCacheResultStatus

CONNECT_TIMEOUT_SECONDS: Final = 3
READ_TIMEOUT_SECONDS: Final = 10
MAX_RESPONSE_BYTES: Final = 524_288
REQUEST_START_INTERVAL_SECONDS: Final = 1
RETRY_AFTER_FALLBACK_SECONDS: Final = 60
RETRY_AFTER_MAX_SECONDS: Final = 86_400
_CONTACT_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_APPLICATION_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class OpenLibraryTransportFinding(StrEnum):
    """Fixed, redacted diagnostics emitted by the transport boundary."""

    REQUEST_REJECTED = "REQUEST_REJECTED"
    TIMEOUT = "TIMEOUT"
    TLS = "TLS"
    NETWORK = "NETWORK"
    CONTENT_LENGTH = "CONTENT_LENGTH"
    BODY_LIMIT = "BODY_LIMIT"
    CONTENT_TYPE = "CONTENT_TYPE"
    UTF8 = "UTF8"
    JSON = "JSON"
    HTTP_404 = "HTTP_404"
    HTTP_429 = "HTTP_429"
    HTTP_3XX = "HTTP_3XX"
    HTTP_TEMPORARY = "HTTP_TEMPORARY"
    HTTP_PERMANENT = "HTTP_PERMANENT"
    HTTP_OTHER = "HTTP_OTHER"
    RETRY_AFTER_CAPPED = "RETRY_AFTER_CAPPED"


@dataclass(frozen=True, slots=True)
class OpenLibraryHttpResponse:
    """Minimal response shape supplied by a concrete or fake HTTP client."""

    status_code: int
    headers: Mapping[str, str]
    body_chunks: Iterable[bytes]

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be between 100 and 599")
        if not isinstance(self.headers, Mapping) or len(self.headers) > 64:
            raise ValueError("headers must be a bounded mapping")
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > 128
            or len(value) > 8192
            or any(character in key + value for character in "\x00\r\n")
            for key, value in self.headers.items()
        ):
            raise ValueError("headers contain an invalid field")
        if not isinstance(self.body_chunks, Iterable):
            raise ValueError("body_chunks must be iterable")

    def __repr__(self) -> str:
        return f"OpenLibraryHttpResponse(status_code={self.status_code!r}, <redacted>)"


class OpenLibraryHttpClient(Protocol):
    """Injectable HTTP boundary; implementations must not perform retries."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        follow_redirects: bool,
    ) -> OpenLibraryHttpResponse: ...


@dataclass(frozen=True, slots=True)
class OpenLibraryTransportConfig:
    """Local identifying configuration required before online use is possible."""

    application_version: str
    contact_email: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.application_version, str)
            or _APPLICATION_VERSION.fullmatch(self.application_version) is None
        ):
            raise ValueError("application_version must be a bounded technical version")
        if (
            not isinstance(self.contact_email, str)
            or not self.contact_email.isascii()
            or len(self.contact_email) > 254
            or _CONTACT_EMAIL.fullmatch(self.contact_email) is None
        ):
            raise ValueError("contact_email must be a syntactically valid address")

    @property
    def user_agent(self) -> str:
        return (
            f"FolioTone/{self.application_version} "
            f"(+https://github.com/gecompat/FolioTone; mailto:{self.contact_email})"
        )

    def __repr__(self) -> str:
        return (
            "OpenLibraryTransportConfig(application_version=<redacted>, contact_email=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class OpenLibraryTransportResult:
    """One classified response.  Body bytes are transient and never logged."""

    status: ProviderCacheResultStatus
    endpoint_kind: str | None = None
    http_status: int | None = None
    body: bytes | None = None
    retry_after_at: datetime | None = None
    finding: OpenLibraryTransportFinding | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ProviderCacheResultStatus:
            raise ValueError("status must be a ProviderCacheResultStatus")
        if self.endpoint_kind is not None and self.endpoint_kind not in {
            route_kind.value for route_kind in OpenLibraryRouteKind
        }:
            raise ValueError("endpoint_kind must be an Open Library route kind")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("http_status must be between 100 and 599")
        if self.status is ProviderCacheResultStatus.SUCCESS:
            if (
                not isinstance(self.body, bytes)
                or not self.body
                or len(self.body) > MAX_RESPONSE_BYTES
                or self.finding is not None
            ):
                raise ValueError("SUCCESS requires non-empty body bytes")
        elif self.body is not None:
            raise ValueError("only SUCCESS may include body bytes")
        if self.retry_after_at is not None:
            if self.status is not ProviderCacheResultStatus.RATE_LIMITED:
                raise ValueError("retry_after_at is only valid for RATE_LIMITED")
            if self.retry_after_at.tzinfo is None or self.retry_after_at.utcoffset() != timedelta(
                0
            ):
                raise ValueError("retry_after_at must be UTC")
            object.__setattr__(self, "retry_after_at", self.retry_after_at.astimezone(UTC))
        if self.finding is not None and not isinstance(self.finding, OpenLibraryTransportFinding):
            raise ValueError("finding must be an OpenLibraryTransportFinding")

    def __repr__(self) -> str:
        return (
            "OpenLibraryTransportResult("
            f"status={self.status!r}, endpoint_kind={self.endpoint_kind!r}, "
            f"http_status={self.http_status!r}, "
            f"retry_after_at={self.retry_after_at!r}, finding={self.finding!r})"
        )


class OpenLibraryTransport:
    """Serialize Open Library fetches and apply the ADR-0036 failure matrix."""

    def __init__(
        self,
        config: OpenLibraryTransportConfig,
        http_client: OpenLibraryHttpClient,
        *,
        clock: Callable[[], datetime],
        sleeper: Callable[[float], None],
    ) -> None:
        if not isinstance(config, OpenLibraryTransportConfig):
            raise ValueError("config must be an OpenLibraryTransportConfig")
        self._config = config
        self._http_client = http_client
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_started_at: datetime | None = None

    def fetch(self, request: OpenLibraryRequest) -> OpenLibraryTransportResult:
        """Fetch one already-approved request, without redirects or retries."""
        try:
            request = _revalidate_request(request)
        except ValueError:
            return _failure(
                ProviderCacheResultStatus.PERMANENT_FAILURE,
                OpenLibraryTransportFinding.REQUEST_REJECTED,
            )

        with self._lock:
            self._pace()
            try:
                response = self._http_client.get(
                    request.url,
                    headers={"Accept": "application/json", "User-Agent": self._config.user_agent},
                    connect_timeout_seconds=CONNECT_TIMEOUT_SECONDS,
                    read_timeout_seconds=READ_TIMEOUT_SECONDS,
                    follow_redirects=False,
                )
            except TimeoutError:
                return _failure(
                    ProviderCacheResultStatus.TEMPORARY_FAILURE, OpenLibraryTransportFinding.TIMEOUT
                )
            except ssl.SSLError:
                return _failure(
                    ProviderCacheResultStatus.TEMPORARY_FAILURE, OpenLibraryTransportFinding.TLS
                )
            except OSError:
                return _failure(
                    ProviderCacheResultStatus.TEMPORARY_FAILURE, OpenLibraryTransportFinding.NETWORK
                )

            if not isinstance(response, OpenLibraryHttpResponse):
                return _failure(
                    ProviderCacheResultStatus.INVALID_RESPONSE,
                    OpenLibraryTransportFinding.HTTP_OTHER,
                )
            return replace(self._classify(response), endpoint_kind=request.route_kind.value)

    def _pace(self) -> None:
        now = _utc_now(self._clock)
        if self._last_started_at is not None:
            elapsed = (now - self._last_started_at).total_seconds()
            remaining = REQUEST_START_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = _utc_now(self._clock)
        self._last_started_at = now

    def _classify(self, response: OpenLibraryHttpResponse) -> OpenLibraryTransportResult:
        status = response.status_code
        if type(status) is not int or not 100 <= status <= 599:
            return _failure(
                ProviderCacheResultStatus.INVALID_RESPONSE, OpenLibraryTransportFinding.HTTP_OTHER
            )
        if status == 429:
            retry_after_at, capped = _retry_after(response.headers, _utc_now(self._clock))
            finding = (
                OpenLibraryTransportFinding.RETRY_AFTER_CAPPED
                if capped
                else OpenLibraryTransportFinding.HTTP_429
            )
            return OpenLibraryTransportResult(
                ProviderCacheResultStatus.RATE_LIMITED,
                http_status=status,
                retry_after_at=retry_after_at,
                finding=finding,
            )
        if status == 404:
            return OpenLibraryTransportResult(
                ProviderCacheResultStatus.NOT_FOUND,
                http_status=status,
                finding=OpenLibraryTransportFinding.HTTP_404,
            )
        if 300 <= status <= 399:
            return _failure(
                ProviderCacheResultStatus.PERMANENT_FAILURE,
                OpenLibraryTransportFinding.HTTP_3XX,
                status,
            )
        if status in {400, 401, 403, 405, 410}:
            return _failure(
                ProviderCacheResultStatus.PERMANENT_FAILURE,
                OpenLibraryTransportFinding.HTTP_PERMANENT,
                status,
            )
        if status in {408, 425} or 500 <= status <= 599:
            return _failure(
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                OpenLibraryTransportFinding.HTTP_TEMPORARY,
                status,
            )
        if status != 200:
            return _failure(
                ProviderCacheResultStatus.INVALID_RESPONSE,
                OpenLibraryTransportFinding.HTTP_OTHER,
                status,
            )
        if not _is_json_content_type(response.headers):
            return _failure(
                ProviderCacheResultStatus.INVALID_RESPONSE,
                OpenLibraryTransportFinding.CONTENT_TYPE,
                status,
            )
        try:
            body, failure = _bounded_body(response.headers, response.body_chunks)
        except TimeoutError:
            return _failure(
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                OpenLibraryTransportFinding.TIMEOUT,
                status,
            )
        except ssl.SSLError:
            return _failure(
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                OpenLibraryTransportFinding.TLS,
                status,
            )
        except OSError:
            return _failure(
                ProviderCacheResultStatus.TEMPORARY_FAILURE,
                OpenLibraryTransportFinding.NETWORK,
                status,
            )
        if failure is not None:
            return _failure(ProviderCacheResultStatus.INVALID_RESPONSE, failure, status)
        assert body is not None
        try:
            json.loads(body.decode("utf-8"))
        except UnicodeDecodeError:
            return _failure(
                ProviderCacheResultStatus.INVALID_RESPONSE, OpenLibraryTransportFinding.UTF8, status
            )
        except (json.JSONDecodeError, ValueError):
            return _failure(
                ProviderCacheResultStatus.INVALID_RESPONSE, OpenLibraryTransportFinding.JSON, status
            )
        return OpenLibraryTransportResult(
            ProviderCacheResultStatus.SUCCESS, http_status=status, body=body
        )


def _revalidate_request(request: object) -> OpenLibraryRequest:
    if not isinstance(request, OpenLibraryRequest):
        raise ValueError("request")
    approved = OpenLibraryRequest(request.route_kind, request.path, request.query)
    parsed = urlsplit(approved.url)
    if (
        approved.method != "GET"
        or approved.scheme != OPENLIBRARY_SCHEME
        or approved.host != OPENLIBRARY_HOST
        or approved.port != OPENLIBRARY_PORT
        or parsed.scheme != OPENLIBRARY_SCHEME
        or parsed.hostname != OPENLIBRARY_HOST
        or parsed.port not in {None, OPENLIBRARY_PORT}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("request")
    return approved


def _utc_now(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("clock must return an aware UTC datetime")
    return now.astimezone(UTC)


def _failure(
    status: ProviderCacheResultStatus,
    finding: OpenLibraryTransportFinding,
    http_status: int | None = None,
) -> OpenLibraryTransportResult:
    return OpenLibraryTransportResult(status, http_status=http_status, finding=finding)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name.lower() and isinstance(value, str):
            return value
    return None


def _is_json_content_type(headers: Mapping[str, str]) -> bool:
    content_type = _header(headers, "content-type")
    if content_type is None:
        return False
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def _bounded_body(
    headers: Mapping[str, str], chunks: Iterable[bytes]
) -> tuple[bytes | None, OpenLibraryTransportFinding | None]:
    content_length = _header(headers, "content-length")
    if content_length is not None:
        try:
            length = int(content_length, 10)
        except ValueError:
            return None, OpenLibraryTransportFinding.CONTENT_LENGTH
        if length < 0 or length > MAX_RESPONSE_BYTES:
            return None, OpenLibraryTransportFinding.CONTENT_LENGTH
    if not isinstance(chunks, Iterable):
        return None, OpenLibraryTransportFinding.BODY_LIMIT
    output = bytearray()
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            return None, OpenLibraryTransportFinding.BODY_LIMIT
        output.extend(chunk)
        if len(output) > MAX_RESPONSE_BYTES:
            return None, OpenLibraryTransportFinding.BODY_LIMIT
    return bytes(output), None


def _retry_after(headers: Mapping[str, str], now: datetime) -> tuple[datetime, bool]:
    value = _header(headers, "retry-after")
    seconds: int | None = None
    if value is not None and value.isascii() and value.isdecimal():
        seconds = int(value, 10)
    elif value is not None:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is not None:
                seconds = max(0, int((parsed.astimezone(UTC) - now).total_seconds()))
        except (TypeError, ValueError, IndexError, OverflowError):
            seconds = None
    if seconds is None:
        seconds = RETRY_AFTER_FALLBACK_SECONDS
    capped = seconds > RETRY_AFTER_MAX_SECONDS
    return now + timedelta(seconds=min(seconds, RETRY_AFTER_MAX_SECONDS)), capped


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BYTES",
    "READ_TIMEOUT_SECONDS",
    "REQUEST_START_INTERVAL_SECONDS",
    "OpenLibraryHttpClient",
    "OpenLibraryHttpResponse",
    "OpenLibraryTransport",
    "OpenLibraryTransportConfig",
    "OpenLibraryTransportFinding",
    "OpenLibraryTransportResult",
]
