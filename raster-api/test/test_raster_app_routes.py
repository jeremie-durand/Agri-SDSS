"""Route-contract tests against the real TiTiler-based raster app.

Directory-scanning logic is covered by test_collections_endpoint.py; this
file asserts only the published route surface.
"""
import pytest
from fastapi.testclient import TestClient

from raster_api.main import app

COG_PATHS = {"/cog/info", "/cog/statistics", "/cog/tiles"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
def test_cog_paths_are_exposed(spec):
    """The COG endpoints the frontend calls must be published."""
    missing = COG_PATHS - set(spec["paths"])
    assert not missing, f"missing paths: {sorted(missing)}"


@pytest.mark.unit
def test_custom_collections_route_is_mounted(spec):
    """collections_router is added on top of stock TiTiler."""
    assert "/collections" in spec["paths"]


@pytest.mark.unit
def test_collections_endpoint_returns_list(client):
    """The custom route answers rather than erroring."""
    resp = client.get("/collections")
    assert resp.status_code == 200
    assert isinstance(resp.json()["collections"], list)


@pytest.mark.unit
def test_cog_info_without_url_is_client_error(client):
    """A missing required parameter is a 422, not a 500."""
    assert client.get("/cog/info").status_code == 422


@pytest.mark.unit
def test_openapi_document_builds(client):
    """A malformed route or response model breaks generation."""
    resp = client.get("/api")
    assert resp.status_code == 200
    assert resp.json()["openapi"].startswith("3.")
