"""Fixtures for Caddy rate limiting integration tests.

Requires the full stack running with short rate limit windows:
    RATE_LIMIT_PYGEOAPI_EXEC_EVENTS=3
    RATE_LIMIT_PYGEOAPI_EXEC_WINDOW=5s
    RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS=5
    RATE_LIMIT_PYGEOAPI_BROWSE_WINDOW=5s

Run with:
    docker compose run --rm -e RATE_LIMIT_PYGEOAPI_EXEC_EVENTS=3 \\
        -e RATE_LIMIT_PYGEOAPI_EXEC_WINDOW=5s \\
        -e RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS=5 \\
        -e RATE_LIMIT_PYGEOAPI_BROWSE_WINDOW=5s \\
        caddy pytest caddy/test/ -v -m integration
"""

import os

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CADDY_BASE_URL = os.getenv("CADDY_BASE_URL", "https://localhost")


@pytest.fixture(scope="function")
def caddy_session():
    """Requests session that skips TLS verification (self-signed cert)."""
    with requests.Session() as session:
        session.verify = False
        try:
            resp = session.get(f"{CADDY_BASE_URL}/", timeout=5)
            if resp.status_code >= 500:
                pytest.skip("Caddy not reachable")
        except requests.exceptions.ConnectionError:
            pytest.skip("Caddy not reachable — start the stack first")
        yield session
