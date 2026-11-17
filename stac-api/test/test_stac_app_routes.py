"""Route-contract tests against the real stac-fastapi app.

These build the actual application with ``create_app()`` rather than mocking
HTTP, so a renamed route, a dropped extension, or a broken import fails the
run. No database is needed: the database pool opens in the app's lifespan,
which these tests never enter.
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from stac_api.app import create_app

CORE_PATHS = {
    "/",
    "/conformance",
    "/collections",
    "/collections/{collection_id}",
    "/collections/{collection_id}/items",
    "/collections/{collection_id}/items/{item_id}",
    "/search",
    "/queryables",
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="module")
def spec(app: FastAPI) -> dict:
    return app.openapi()


@pytest.mark.unit
def test_core_stac_paths_are_exposed(spec):
    """Every STAC core path a client depends on must be published."""
    missing = CORE_PATHS - set(spec["paths"])
    assert not missing, f"missing paths: {sorted(missing)}"


@pytest.mark.unit
def test_search_supports_get_and_post(spec):
    """STAC item search is defined for both verbs."""
    assert {"get", "post"} <= set(spec["paths"]["/search"])


@pytest.mark.unit
def test_transaction_verbs_match_configured_extension(spec):
    """Write verbs appear only when transactions are enabled.

    Pins the deployment's actual setting rather than assuming one, so
    flipping ENABLE_TRANSACTIONS_EXTENSIONS shows up here instead of
    silently changing the public write surface.
    """
    enabled = os.getenv("ENABLE_TRANSACTIONS_EXTENSIONS", "").upper() == "TRUE"
    collection_verbs = set(spec["paths"]["/collections"])
    assert ("post" in collection_verbs) is enabled


@pytest.mark.unit
def test_openapi_document_builds(spec):
    """A malformed route or response model breaks generation."""
    assert spec["openapi"].startswith("3.")
    assert spec["paths"]


@pytest.mark.unit
def test_create_app_returns_a_fastapi_app(app: FastAPI) -> None:
    """uvicorn --factory serves whatever create_app() returns."""
    assert isinstance(app, FastAPI)


@pytest.mark.unit
def test_conformance_is_served_as_json(app: FastAPI) -> None:
    """Responses keep the application/json media type clients parse.

    The landing page needs the database, so it is covered by the integration
    suite; /conformance answers without it.
    """
    response = TestClient(app).get("/conformance")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
