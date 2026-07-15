"""Unit and mocked tests for vector_api.app module.

Tests the landing page endpoints, lifespan startup/shutdown sequence,
and MountRootPathMiddleware ASGI middleware.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from vector_api.app import MountRootPathMiddleware, app


@pytest.fixture
def app_client():
    """TestClient for the full app with all TiPg DB calls mocked."""
    with (
        patch("vector_api.app.connect_to_db", new=AsyncMock()),
        patch("vector_api.app.register_collection_catalog", new=AsyncMock()),
        patch("vector_api.app.close_db_connection", new=AsyncMock()),
    ):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


# --- Landing pages ---


@pytest.mark.unit
def test_root_landing_page_returns_200(app_client):
    """GET / returns 200 with title, description, and links."""
    resp = app_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("title", "description", "links"):
        assert key in body, f"Missing key '{key}' in landing page response"


@pytest.mark.unit
def test_root_landing_page_links_include_postgis_and_parquet(app_client):
    """GET / links reference both /postgis and /parquet namespaces."""
    resp = app_client.get("/")
    hrefs = [link["href"] for link in resp.json()["links"]]
    assert any("/postgis" in h for h in hrefs), "No /postgis link in root landing"
    assert any("/parquet" in h for h in hrefs), "No /parquet link in root landing"


@pytest.mark.unit
def test_parquet_landing_page_returns_200(app_client):
    """GET /parquet returns 200 with title, description, and links."""
    resp = app_client.get("/parquet")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("title", "description", "links"):
        assert key in body, f"Missing key '{key}' in parquet landing page response"


@pytest.mark.unit
def test_parquet_landing_page_links_include_collections(app_client):
    """GET /parquet links include the /parquet/collections endpoint."""
    resp = app_client.get("/parquet")
    hrefs = [link["href"] for link in resp.json()["links"]]
    assert any("/parquet/collections" in h for h in hrefs)


# --- Lifespan ---


@pytest.mark.mocked
def test_lifespan_calls_connect_to_db_on_startup():
    """connect_to_db is awaited exactly once during app startup."""
    mock_connect = AsyncMock()
    with (
        patch("vector_api.app.connect_to_db", mock_connect),
        patch("vector_api.app.register_collection_catalog", new=AsyncMock()),
        patch("vector_api.app.close_db_connection", new=AsyncMock()),
    ):
        with TestClient(app):
            pass
    mock_connect.assert_awaited_once()


@pytest.mark.mocked
def test_lifespan_calls_close_db_on_shutdown():
    """close_db_connection is awaited exactly once during app shutdown."""
    mock_close = AsyncMock()
    with (
        patch("vector_api.app.connect_to_db", new=AsyncMock()),
        patch("vector_api.app.register_collection_catalog", new=AsyncMock()),
        patch("vector_api.app.close_db_connection", mock_close),
    ):
        with TestClient(app):
            pass
    mock_close.assert_awaited_once()


# --- MountRootPathMiddleware ---


@pytest.mark.unit
def test_mount_root_path_middleware_injects_root_path():
    """HTTP scopes get root_path and app_root_path set to the mount prefix."""
    captured = []

    async def capture_app(scope, receive, send):
        captured.append(scope)

    middleware = MountRootPathMiddleware(capture_app, "/postgis")
    scope = {"type": "http", "root_path": "", "app_root_path": ""}
    asyncio.run(middleware(scope, None, None))

    assert captured[0]["root_path"] == "/postgis"
    assert captured[0]["app_root_path"] == "/postgis"


@pytest.mark.unit
def test_mount_root_path_middleware_passes_non_http_scope_unchanged():
    """Non-HTTP scopes (e.g. lifespan) are forwarded without modification."""
    captured = []

    async def capture_app(scope, receive, send):
        captured.append(scope)

    middleware = MountRootPathMiddleware(capture_app, "/postgis")
    scope = {"type": "lifespan", "root_path": ""}
    asyncio.run(middleware(scope, None, None))

    assert captured[0]["root_path"] == ""
