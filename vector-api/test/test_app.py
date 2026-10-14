"""Unit and mocked tests for vector_api.app module.

Tests the landing page endpoints, lifespan startup/shutdown sequence,
and MountRootPathMiddleware ASGI middleware.
"""

import asyncio
import os
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


# --- Parquet OpenAPI spec ---


@pytest.mark.unit
def test_parquet_openapi_spec_includes_external_root_as_server(app_client):
    """GET /parquet/openapi.json declares APP_ROOT_PATH as the server URL.

    Without a "servers" entry, Swagger UI's "Try it out" defaults request
    URLs to the domain root, stripping the reverse-proxy prefix
    (e.g. /vector-api) and producing 404s against the proxy.
    """
    with patch("vector_api.app.EXTERNAL_ROOT", "/vector-api"):
        resp = app_client.get("/parquet/openapi.json")
    assert resp.status_code == 200
    assert resp.json().get("servers") == [{"url": "/vector-api"}]


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


def _run_middleware(middleware, body: bytes, content_type: bytes = b"application/json"):
    """Drive the middleware with a stub app and capture the emitted body."""
    sent = []

    async def stub_app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", content_type), (b"content-length", b"999")],
        })
        await send({"type": "http.response.body", "body": body})

    async def capture(message):
        sent.append(message)

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/collections",
        "headers": [(b"host", b"example.org"), (b"x-forwarded-proto", b"https")],
    }
    middleware.app = stub_app
    asyncio.run(middleware(scope, None, capture))
    return sent


@pytest.mark.unit
def test_external_prefix_is_inserted_into_emitted_hrefs():
    """Hrefs must carry the proxy prefix, or they 404 when followed."""
    middleware = MountRootPathMiddleware(None, "/postgis", "/vector-api")
    body = b'{"links":[{"href":"https://example.org/postgis/collections"}]}'

    sent = _run_middleware(middleware, body)

    assert b"https://example.org/vector-api/postgis/collections" in sent[-1]["body"]


@pytest.mark.unit
def test_rewrite_is_a_no_op_without_an_external_prefix():
    """With APP_ROOT_PATH unset the body must pass through untouched."""
    middleware = MountRootPathMiddleware(None, "/postgis", "")
    body = b'{"links":[{"href":"https://example.org/postgis/collections"}]}'

    sent = _run_middleware(middleware, body)

    assert sent[-1]["body"] == body


@pytest.mark.unit
def test_non_json_responses_are_not_rewritten():
    """Only JSON bodies are touched; tiles and HTML pass through."""
    middleware = MountRootPathMiddleware(None, "/postgis", "/vector-api")
    body = b"\x89PNG\r\n/postgis/not-a-link"

    sent = _run_middleware(middleware, body, content_type=b"image/png")

    assert sent[-1]["body"] == body


@pytest.mark.unit
def test_stale_content_length_is_dropped():
    """Rewriting lengthens the body, so a stale Content-Length must not survive."""
    middleware = MountRootPathMiddleware(None, "/postgis", "/vector-api")

    sent = _run_middleware(middleware, b'{"href":"https://example.org/postgis/x"}')

    header_names = [k.lower() for k, _ in sent[0]["headers"]]
    assert b"content-length" not in header_names


@pytest.mark.unit
def test_request_path_is_never_altered_by_the_rewrite():
    """Routing must be untouched.

    Widening root_path to include the external prefix fixed the links and
    broke the sub-app's own route resolution (/postgis/* returned 404).
    The prefix is applied to the response instead, so scope['path'] and
    root_path must stay exactly as Starlette's Mount set them.
    """
    captured = []

    async def capture_app(scope, receive, send):
        captured.append(scope)

    middleware = MountRootPathMiddleware(capture_app, "/postgis", "/vector-api")
    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/collections",
        "headers": [(b"host", b"example.org")],
    }
    asyncio.run(middleware(scope, None, lambda m: asyncio.sleep(0)))

    assert captured[0]["path"] == "/collections"
    assert captured[0]["root_path"] == "/postgis"


@pytest.mark.unit
def test_postgis_mount_is_wired_with_the_external_prefix():
    """The mount must pass APP_ROOT_PATH through to the middleware.

    The middleware's own rewrite logic is tested above, but that passes even
    if app.mount() forgets to supply the prefix -- which is the actual bug
    this guards: links were emitted without /vector-api and 404'd.
    """
    external = os.getenv("APP_ROOT_PATH", "").rstrip("/")
    mount = next(r for r in app.routes if getattr(r, "path", None) == "/postgis")

    assert mount.app.external_root == external


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
