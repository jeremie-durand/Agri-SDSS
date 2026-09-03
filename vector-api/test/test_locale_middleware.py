"""Integration tests for locale binding through the real vector_api app.

The unit tests in agri_i18n cover the raw ASGI protocol. These assert the
middleware is actually installed on the shipped app and that Starlette's
middleware stack preserves the ContextVar into an endpoint -- the property
that BaseHTTPMiddleware would have broken.
"""

import pytest
from agri_i18n import DEFAULT, get_locale
from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.app import app


@pytest.fixture
def locale_probe_client():
    """A FastAPI app wired exactly like vector_api, exposing the bound locale."""
    probe = FastAPI()
    probe.add_middleware(LocaleASGIMiddleware)

    @probe.get("/probe")
    async def _probe():
        return {"locale": get_locale()}

    with TestClient(probe) as client:
        yield client


@pytest.mark.unit
def test_middleware_is_installed_on_vector_api():
    """The shipped app carries the locale middleware."""
    installed = [m.cls for m in app.user_middleware]
    assert LocaleASGIMiddleware in installed


@pytest.mark.integration
@pytest.mark.parametrize(
    "header,expected",
    [
        ("fr-CA,fr;q=0.9", "fr"),
        ("en-US,en;q=0.9", "en"),
        ("de", DEFAULT),
    ],
)
def test_endpoint_sees_negotiated_locale(locale_probe_client, header, expected):
    """Accept-Language reaches the endpoint through the middleware stack."""
    resp = locale_probe_client.get("/probe", headers={"Accept-Language": header})
    assert resp.status_code == 200
    assert resp.json()["locale"] == expected


@pytest.mark.integration
def test_endpoint_defaults_without_header(locale_probe_client):
    """A request with no Accept-Language falls back to the platform default."""
    assert locale_probe_client.get("/probe").json()["locale"] == DEFAULT


@pytest.mark.integration
def test_query_param_overrides_header(locale_probe_client):
    """?lang= wins over Accept-Language end to end."""
    resp = locale_probe_client.get(
        "/probe?lang=en", headers={"Accept-Language": "fr-CA,fr;q=0.9"}
    )
    assert resp.json()["locale"] == "en"
