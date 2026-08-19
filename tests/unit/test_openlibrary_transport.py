from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from foliotone.adapters.openlibrary import (
    OpenLibraryHttpResponse,
    OpenLibraryQueryBuilder,
    OpenLibraryTransport,
    OpenLibraryTransportConfig,
    OpenLibraryTransportFinding,
)
from foliotone.enrichment import ProviderCacheResultStatus


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 20, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeHttp:
    def __init__(self, response: OpenLibraryHttpResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], int, int, bool]] = []

    def get(self, url: str, **kwargs: object) -> OpenLibraryHttpResponse:
        self.calls.append(
            (
                url,
                dict(kwargs["headers"]),
                kwargs["connect_timeout_seconds"],
                kwargs["read_timeout_seconds"],
                kwargs["follow_redirects"],
            )
        )  # type: ignore[arg-type]
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_transport(
    response: OpenLibraryHttpResponse | Exception,
) -> tuple[OpenLibraryTransport, FakeHttp, FakeClock]:
    clock = FakeClock()
    http = FakeHttp(response)
    return (
        OpenLibraryTransport(
            OpenLibraryTransportConfig("1.2.3", "ops@example.test"),
            http,
            clock=clock,
            sleeper=clock.sleep,
        ),
        http,
        clock,
    )


def request():
    route = OpenLibraryQueryBuilder().build(identifiers=(("openlibrary.work", "OL1W"),))
    assert route is not None
    return route.requests[0]


def response(
    status: int = 200, body: bytes = b'{"key":"/works/OL1W"}', **headers: str
) -> OpenLibraryHttpResponse:
    return OpenLibraryHttpResponse(status, {"content-type": "application/json", **headers}, [body])


def test_https_only_request_and_user_agent_are_fixed_and_redacted() -> None:
    transport, http, _ = make_transport(response())
    result = transport.fetch(request())
    assert result.status is ProviderCacheResultStatus.SUCCESS
    assert result.endpoint_kind == "WORK"
    assert http.calls == [
        (
            "https://openlibrary.org/works/OL1W.json",
            {
                "Accept": "application/json",
                "User-Agent": (
                    "FolioTone/1.2.3 "
                    "(+https://github.com/gecompat/FolioTone; mailto:ops@example.test)"
                ),
            },
            3,
            10,
            False,
        )
    ]
    assert "ops@example.test" not in repr(transport._config)  # noqa: SLF001
    assert "/works/OL1W" not in repr(response())


@pytest.mark.parametrize(
    ("application_version", "contact_email"),
    (
        ("1.0\r\nInjected", "ops@example.test"),
        ("1.0", "ops\r\n@example.test"),
        ("1.0", "x" * 255 + "@example.test"),
    ),
)
def test_user_agent_configuration_rejects_header_injection_and_unbounded_values(
    application_version: str, contact_email: str
) -> None:
    with pytest.raises(ValueError):
        OpenLibraryTransportConfig(application_version, contact_email)


def test_response_dto_rejects_malformed_headers_without_exposing_them() -> None:
    with pytest.raises(ValueError):
        OpenLibraryHttpResponse(200, {"X-Test": "private\r\nInjected: value"}, [b"{}"])
    value = OpenLibraryHttpResponse(
        200,
        {"content-type": "application/json", "X-Private": "private-value"},
        [b'{"private":"value"}'],
    )
    assert "private" not in repr(value)


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (404, ProviderCacheResultStatus.NOT_FOUND),
        (429, ProviderCacheResultStatus.RATE_LIMITED),
        (301, ProviderCacheResultStatus.PERMANENT_FAILURE),
        (400, ProviderCacheResultStatus.PERMANENT_FAILURE),
        (408, ProviderCacheResultStatus.TEMPORARY_FAILURE),
        (425, ProviderCacheResultStatus.TEMPORARY_FAILURE),
        (500, ProviderCacheResultStatus.TEMPORARY_FAILURE),
        (418, ProviderCacheResultStatus.INVALID_RESPONSE),
    ),
)
def test_status_matrix(status: int, expected: ProviderCacheResultStatus) -> None:
    transport, _, _ = make_transport(response(status))
    assert transport.fetch(request()).status is expected


@pytest.mark.parametrize(
    "bad_response",
    (
        response(body=b"{}", **{"content-type": "text/html"}),
        response(body=b"\xff"),
        response(body=b"{"),
        response(body=b"{}", **{"content-length": "524289"}),
        OpenLibraryHttpResponse(200, {"content-type": "application/json"}, [b"x" * 524288, b"x"]),
    ),
)
def test_invalid_content_and_bounded_streams_fail_closed(
    bad_response: OpenLibraryHttpResponse,
) -> None:
    transport, _, _ = make_transport(bad_response)
    assert transport.fetch(request()).status is ProviderCacheResultStatus.INVALID_RESPONSE


def test_pacing_is_one_second_and_never_retries() -> None:
    transport, http, clock = make_transport(response())
    transport.fetch(request())
    transport.fetch(request())
    assert len(http.calls) == 2
    assert clock.now == datetime(2026, 8, 20, 0, 0, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("header", "seconds"),
    (("12", 12), ("Wed, 20 Aug 2026 00:00:20 GMT", 20), ("nonsense", 60), ("999999", 86400)),
)
def test_retry_after_seconds_date_fallback_and_cap(header: str, seconds: int) -> None:
    transport, _, clock = make_transport(response(429, **{"retry-after": header}))
    result = transport.fetch(request())
    assert result.retry_after_at == clock.now + timedelta(seconds=seconds)
    if seconds == 86400:
        assert result.finding is OpenLibraryTransportFinding.RETRY_AFTER_CAPPED


def test_network_timeout_and_tls_are_temporary_and_path_free() -> None:
    for exc in (TimeoutError(), OSError(), __import__("ssl").SSLError()):
        transport, _, _ = make_transport(exc)
        result = transport.fetch(request())
        assert result.status is ProviderCacheResultStatus.TEMPORARY_FAILURE
        assert "OL1W" not in repr(result)
