"""Unit and mocked tests for vector_api.app module.

Tests the landing page endpoints, lifespan startup/shutdown sequence,
and MountRootPathMiddleware ASGI middleware.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from tipg.main import app as tipg_app
from vector_api.app import MountRootPathMiddleware, app

PARQUET_OPENAPI_SNAPSHOT: Path = Path(__file__).parent / "data" / "parquet_openapi.json"
PARQUET_SPEC_PATHS: set[str] = {
    "/parquet/collections",
    "/parquet/collections/{collection_id}",
    "/parquet/collections/{collection_id}/items",
    "/parquet/collections/{collection_id}/items/{item_id}",
    "/parquet/collections/{collection_id}/queryables",
    "/parquet/collections/{collection_id}/invalidate",
}


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
@pytest.mark.parametrize("path", ["/", "/parquet"])
def test_landing_page_links_carry_the_external_prefix(app_client, path):
    """Root-relative /postgis or /parquet hrefs 404 behind the /vector-api proxy."""
    with patch("vector_api.config.EXTERNAL_ROOT", "/vector-api"):
        resp = app_client.get(path)

    hrefs = [link["href"] for link in resp.json()["links"]]
    assert hrefs
    for href in hrefs:
        assert href.startswith("http://testserver/vector-api/"), href


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


@pytest.mark.unit
def test_parquet_openapi_spec_lists_parquet_paths_only(app_client):
    """An empty spec leaves /parquet/api.html with no endpoints (issue #276)."""
    resp = app_client.get("/parquet/openapi.json")

    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert PARQUET_SPEC_PATHS <= set(paths), PARQUET_SPEC_PATHS - set(paths)
    assert "/" not in paths
    assert "/pedo-properties" not in paths
    for path in paths:
        assert path.startswith("/parquet"), path


@pytest.mark.unit
def test_parquet_openapi_spec_resolves_every_schema_reference(app_client):
    """Swagger UI fails to render an operation whose $ref points nowhere."""
    spec = app_client.get("/parquet/openapi.json").json()

    refs = set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(spec)))
    defined = set(spec.get("components", {}).get("schemas", {}))
    assert refs
    assert refs <= defined, refs - defined


@pytest.mark.unit
def test_parquet_openapi_spec_matches_snapshot(app_client: TestClient) -> None:
    """Paths, response schemas and descriptions stay as pinned for #280.

    After an intended change (a FastAPI or Pydantic upgrade included),
    regenerate the snapshot with json.dump(spec, f, indent=2, sort_keys=True,
    ensure_ascii=False) and review the diff.
    """
    with patch("vector_api.app.EXTERNAL_ROOT", "/vector-api"):
        spec = app_client.get("/parquet/openapi.json").json()

    assert spec == json.loads(PARQUET_OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))


# --- Main docs pages ---


@pytest.mark.unit
def test_docs_page_loads_the_spec_under_the_external_prefix(app_client):
    """/docs must fetch /vector-api/openapi.json; /openapi.json 404s behind home."""
    with patch("vector_api.app.EXTERNAL_ROOT", "/vector-api"):
        resp = app_client.get("/docs")

    assert resp.status_code == 200
    assert "url: '/vector-api/openapi.json'" in resp.text


@pytest.mark.unit
def test_redoc_page_loads_the_spec_under_the_external_prefix(app_client):
    """/redoc must fetch the prefixed spec and skip the CSP-blocked Google Fonts."""
    with patch("vector_api.app.EXTERNAL_ROOT", "/vector-api"):
        resp = app_client.get("/redoc")

    assert resp.status_code == 200
    assert 'spec-url="/vector-api/openapi.json"' in resp.text
    assert "fonts.googleapis.com" not in resp.text


@pytest.mark.unit
def test_main_openapi_spec_declares_the_external_prefix_as_server(app_client):
    """Without servers, "Try it out" on /docs calls the domain root and 404s."""
    external = os.getenv("APP_ROOT_PATH", "").rstrip("/")
    assert external, "APP_ROOT_PATH must be set for this test to mean anything"

    resp = app_client.get("/openapi.json")

    assert resp.status_code == 200
    assert resp.json().get("servers") == [{"url": external}]


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
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", b"999"),
                ],
            }
        )
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
def test_external_prefix_is_inserted_into_html_pages():
    """TiPg's HTML pages link with absolute URLs, which must carry the prefix."""
    middleware = MountRootPathMiddleware(None, "/postgis", "/vector-api")
    body = (
        b'<a href="https://example.org/postgis/collections">Collections</a>'
        b'<script>var currentURL = "https://example.org/postgis/items"</script>'
    )

    sent = _run_middleware(middleware, body, content_type=b"text/html; charset=utf-8")

    assert b'href="https://example.org/vector-api/postgis/collections"' in (
        sent[-1]["body"]
    )
    assert b'"https://example.org/vector-api/postgis/items"' in sent[-1]["body"]
    assert b'"https://example.org/postgis/' not in sent[-1]["body"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "content_type",
    [b"image/png", b"application/vnd.mapbox-vector-tile"],
)
def test_binary_responses_are_not_rewritten(content_type):
    """Tiles and images pass through byte for byte."""
    middleware = MountRootPathMiddleware(None, "/postgis", "/vector-api")
    body = b"\x89PNG\r\nhttps://example.org/postgis/not-a-link"

    sent = _run_middleware(middleware, body, content_type=content_type)

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
def test_mount_root_path_middleware_routes_url_for_to_the_sub_app():
    """request.url_for inside TiPg must resolve TiPg's own route names."""
    captured = []

    async def capture_app(scope, receive, send):
        captured.append(scope)

    capture_app.router = tipg_app.router
    middleware = MountRootPathMiddleware(capture_app, "/postgis")
    scope = {"type": "http", "router": app.router, "headers": []}
    asyncio.run(middleware(scope, None, None))

    assert captured[0]["router"] is tipg_app.router


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


@pytest.mark.unit
def test_tipg_sub_app_has_no_cors_middleware_of_its_own():
    """The parent app must be the only CORS layer on /postgis/*.

    TiPg ships its own CORSMiddleware (allow_origins=*, allow_credentials=True).
    Left in place, it reflects any Origin the parent refuses, so
    VECTOR_API_CORS_ORIGINS has no effect on PostGIS routes.
    """
    assert not any(m.cls is CORSMiddleware for m in tipg_app.user_middleware)
