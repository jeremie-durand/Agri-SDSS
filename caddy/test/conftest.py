"""Fixtures for Caddy rate limiting integration tests.

Run with ``make test-caddy``. It hot-reloads the running Caddy with
caddy/Caddyfile.test (the same zones with 5 s windows), runs this suite from a
python container on eoapi-network, then restores the production Caddyfile even
when a test fails. The RATE_LIMIT_* variables it passes only tell the tests
which limits Caddyfile.test sets; they do not configure Caddy.
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
