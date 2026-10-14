"""Route-contract tests against the real stac-fastapi app.

These import the actual application rather than mocking HTTP, so a renamed
route, a dropped extension, or a broken import fails the run. No database is
needed: only the generated OpenAPI document is inspected.
"""
import os

import pytest

from stac_api.app import app

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
def spec() -> dict:
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
def test_orjson_response_class_is_patched():
    """stac_api.app swaps in _OrjsonResponse to avoid the deprecated one.

    The patch sits in a try/except ImportError, so losing orjson would
    revert it silently.
    """
    import stac_fastapi.api.models as models

    assert models.JSONResponse.__name__ == "_OrjsonResponse"
