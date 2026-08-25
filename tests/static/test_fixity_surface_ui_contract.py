from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "foliotone" / "surface" / "static"


def test_fixity_ui_is_german_bounded_and_uses_the_existing_rest_surface() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "app.css").read_text(encoding="utf-8")

    for marker in (
        'id="fixity"',
        "Fixity-Monitoring",
        'id="fixity-baseline-build-form"',
        'id="fixity-baseline-status-form"',
        'id="fixity-baseline-activation-form"',
        'id="fixity-verification-build-form"',
        'id="fixity-verification-status-form"',
        'id="fixity-results-form"',
        'id="fixity-review-queue"',
        'id="fixity-review-form"',
        'id="fixity-expectation-form"',
        'id="fixity-private-panel"',
        'type="password"',
        'maxlength="256"',
    ):
        assert marker in html

    for route in (
        "/api/v1/ebooks/fixity/baselines",
        "/api/v1/ebooks/fixity/baselines/${encodeURIComponent(data.manifest_id)}/activation",
        "/api/v1/ebooks/fixity/verifications",
        "/api/v1/ebooks/fixity/verifications/${encodeURIComponent(run_id)}/results?limit=50",
        "/api/v1/ebooks/fixity/reviews?limit=50",
        "/api/v1/ebooks/fixity/results/${encodeURIComponent(data.result_id)}/reviews",
        "/api/v1/ebooks/fixity/results/${encodeURIComponent(data.result_id)}/expectations",
        "/api/v1/private/ebooks/fixity/baselines/${encodeURIComponent(manifest_id)}/entries?limit=50",
        "/api/v1/private/ebooks/fixity/results/${encodeURIComponent(result_id)}",
        "/api/v1/session/reauth",
        "/api/v1/session/reauth-review",
    ):
        assert route in script

    assert "Nächste Seite" in script
    assert "ACCEPT FIXITY BASELINE ${manifestId}" in script
    assert "worker_count: Number(data.worker_count)" in script
    assert "crypto.randomUUID" in script
    assert "actionKeys" in script
    assert "next_cursor" in script
    assert "clearFixityPrivateValues" in script
    assert "PRIVATE_READ-Freigabe" in script
    assert "UNEXPECTED_BYTE_CHANGE" in script
    assert "RETIRE_MISSING" in script
    assert "ACCEPT_CURRENT" in script
    assert "renderPrivateResult" in script
    assert "JSON.stringify(value)" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "console." not in script
    assert "eval(" not in script
    assert "innerHTML" not in script
    assert "<script" not in html.replace('<script src="/assets/app.js"></script>', "")
    assert "http://" not in html
    assert "https://" not in html
    assert ".fixity-card" in styles
    assert "@media (max-width: 40rem)" in styles


def test_fixity_public_rendering_does_not_project_private_locators_or_hashes() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    public_renderer = script.split("function renderFixityResults", 1)[1].split(
        "function renderPrivateBaselineEntries", 1
    )[0]

    assert "item.result_id" in public_renderer
    assert "item.file_id" in public_renderer
    assert "item.result" in public_renderer
    assert "item.failure_code" in public_renderer
    assert "relative_locator" not in public_renderer
    assert "sha256" not in public_renderer.lower()
    assert "window.csrf" in script
    assert 'headers["Idempotency-Key"]' in script

    fixity_handlers = script.split('document.querySelector("#fixity-baseline-build-form")', 1)[1]
    for forbidden in ("/rename/", "/authorizations", "/executions", "/recoveries", "capability"):
        assert forbidden not in fixity_handlers


def test_fixity_private_dom_is_cleared_for_every_session_401_or_403() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    response_handler = script.split("async function responseJson", 1)[1].split(
        "async function request", 1
    )[0]

    assert "privateValue" not in script
    assert "response.status === 401 || response.status === 403" in response_handler
    assert "clearFixityPrivateValues" in response_handler


def test_initialise_has_no_direct_fetch_bypass_for_session_responses() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    initialise = script.split("async function initialise", 1)[1].split(
        'document.querySelector("#setup-form")', 1
    )[0]

    assert "fetch(" not in initialise
    for route in (
        'getJson("/api/v1/setup-status")',
        'getJson("/api/v1/session")',
        'getJson("/api/v1/media-lines")',
    ):
        assert route in initialise
