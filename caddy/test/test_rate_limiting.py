"""Integration tests for Caddy rate limiting on PyGeoAPI routes.

Two zones are tested:
- pygeoapi_exec : POST /mos-pygeoapi/processes/*/execution  (heavy compute)
- pygeoapi_browse: GET  /mos-pygeoapi/*                     (lightweight reads)

Run the stack with short windows before executing these tests:
    RATE_LIMIT_PYGEOAPI_EXEC_EVENTS=3   RATE_LIMIT_PYGEOAPI_EXEC_WINDOW=5s
    RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS=5 RATE_LIMIT_PYGEOAPI_BROWSE_WINDOW=5s
"""

import os
import time

import pytest

CADDY_BASE_URL = os.getenv("CADDY_BASE_URL", "https://localhost")
EXEC_URL = f"{CADDY_BASE_URL}/mos-pygeoapi/processes/eo-sentinel-fetch/execution"
BROWSE_URL = f"{CADDY_BASE_URL}/mos-pygeoapi/processes"
OTHER_URL = f"{CADDY_BASE_URL}/services"

EXEC_LIMIT = int(os.getenv("RATE_LIMIT_PYGEOAPI_EXEC_EVENTS", "3"))
BROWSE_LIMIT = int(os.getenv("RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS", "5"))
WINDOW_SECONDS = 6  # safe margin above the 5s test window


# ---------------------------------------------------------------------------
# Execution zone — POST /mos-pygeoapi/processes/*/execution
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_execution_within_limit_not_blocked(caddy_session):
    """Every request up to the limit must reach PyGeoAPI (not return 429)."""
    for i in range(EXEC_LIMIT):
        r = caddy_session.post(EXEC_URL, json={})
        assert (
            r.status_code != 429
        ), f"Request {i + 1}/{EXEC_LIMIT} was blocked (429) before reaching the limit"


@pytest.mark.integration
def test_execution_over_limit_returns_429(caddy_session):
    """The (limit + 1)th POST must be rejected with 429."""
    for _ in range(EXEC_LIMIT):
        caddy_session.post(EXEC_URL, json={})
    r = caddy_session.post(EXEC_URL, json={})
    assert r.status_code == 429


@pytest.mark.integration
def test_execution_429_has_retry_after_header(caddy_session):
    """A 429 response must carry a Retry-After header so clients can back off."""
    for _ in range(EXEC_LIMIT + 1):
        r = caddy_session.post(EXEC_URL, json={})
    assert r.status_code == 429
    assert "retry-after" in r.headers, "429 missing Retry-After header"
    assert int(r.headers["retry-after"]) > 0


@pytest.mark.integration
def test_execution_limit_resets_after_window(caddy_session):
    """After the window expires the counter resets and requests pass again."""
    for _ in range(EXEC_LIMIT + 1):
        caddy_session.post(EXEC_URL, json={})
    time.sleep(WINDOW_SECONDS)
    r = caddy_session.post(EXEC_URL, json={})
    assert r.status_code != 429, "Rate limit was not reset after the window expired"


# ---------------------------------------------------------------------------
# Browse zone — GET /mos-pygeoapi/*
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_browse_within_limit_not_blocked(caddy_session):
    """Every GET up to the browse limit must return a non-429 status."""
    for i in range(BROWSE_LIMIT):
        r = caddy_session.get(BROWSE_URL)
        assert (
            r.status_code != 429
        ), f"Browse request {i + 1}/{BROWSE_LIMIT} blocked before limit"


@pytest.mark.integration
def test_browse_over_limit_returns_429(caddy_session):
    """The (limit + 1)th GET must be rejected with 429."""
    for _ in range(BROWSE_LIMIT):
        caddy_session.get(BROWSE_URL)
    r = caddy_session.get(BROWSE_URL)
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# Zone isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_exec_zone_does_not_bleed_into_browse_zone(caddy_session):
    """Exhausting the exec quota must not block browse requests."""
    time.sleep(
        WINDOW_SECONDS
    )  # ensure a clean window — previous tests may have exhausted browse
    for _ in range(EXEC_LIMIT + 1):
        caddy_session.post(EXEC_URL, json={})
    r = caddy_session.get(BROWSE_URL)
    assert (
        r.status_code != 429
    ), "Browse zone was incorrectly blocked by exec zone exhaustion"


@pytest.mark.integration
def test_browse_zone_does_not_bleed_into_exec_zone(caddy_session):
    """Exhausting the browse quota must not block execution requests."""
    time.sleep(
        WINDOW_SECONDS
    )  # ensure a clean window — previous tests may have exhausted exec
    for _ in range(BROWSE_LIMIT + 1):
        caddy_session.get(BROWSE_URL)
    r = caddy_session.post(EXEC_URL, json={})
    assert (
        r.status_code != 429
    ), "Exec zone was incorrectly blocked by browse zone exhaustion"


# ---------------------------------------------------------------------------
# Non-PyGeoAPI routes — must never be rate limited
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_non_pygeoapi_path_not_rate_limited(caddy_session):
    """Paths outside /mos-pygeoapi/ must never receive 429 regardless of volume."""
    for _ in range(EXEC_LIMIT + BROWSE_LIMIT + 5):
        r = caddy_session.get(OTHER_URL)
        assert (
            r.status_code != 429
        ), "/services returned 429 — rate limit leaked outside pygeoapi zone"
