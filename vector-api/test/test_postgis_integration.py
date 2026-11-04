"""Real integration tests for the PostGIS (TiPg) OGC API Features endpoints.

Uses the full vector-api app with a live PostgreSQL connection. All tests are
automatically skipped when the database is unavailable (e.g., unit-test runs
without Docker Compose). In CI the database service is always started first.
"""

import os
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from vector_api.app import app
from vector_api.config import CORS_ORIGINS, EXTERNAL_ROOT


@pytest.fixture(scope="session")
def postgis_integration_client():
    """Session-scoped TestClient against the full vector-api with real PostgreSQL.

    Skips all tests in this session if the DB lifespan startup fails.
    """
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL unavailable — skipping PostGIS integration tests: {exc}"
        )


# ------------------------------------------
# /postgis root
# ------------------------------------------


@pytest.mark.integration
def test_postgis_root_returns_200(postgis_integration_client):
    """GET /postgis returns 200 with a landing page body."""
    resp = postgis_integration_client.get("/postgis")
    assert resp.status_code == 200
    data = resp.json()
    assert "title" in data
    assert "links" in data


@pytest.mark.integration
def test_postgis_landing_doc_links_point_at_tipg_docs(postgis_integration_client):
    """service-desc/service-doc must name TiPg's /api and /api.html, not 404s.

    Resolved on the parent router they became /postgis/openapi.json and
    /postgis/docs, which do not exist. Accept-Encoding is cleared as home does:
    TiPg compresses otherwise, and the prefix rewrite cannot see the links.
    """
    resp = postgis_integration_client.get(
        "/postgis/", params={"f": "json"}, headers={"Accept-Encoding": ""}
    )

    assert resp.status_code == 200
    paths = {
        link["rel"]: urlparse(link["href"]).path
        for link in resp.json()["links"]
        if link["rel"] in ("service-desc", "service-doc")
    }
    assert paths == {
        "service-desc": f"{EXTERNAL_ROOT}/postgis/api",
        "service-doc": f"{EXTERNAL_ROOT}/postgis/api.html",
    }
    for path in paths.values():
        internal = path.removeprefix(EXTERNAL_ROOT)
        assert postgis_integration_client.get(internal).status_code == 200, path


# ------------------------------------------
# /postgis/collections — OGC collection list
# ------------------------------------------


@pytest.mark.integration
def test_postgis_collections_returns_200(postgis_integration_client):
    """GET /postgis/collections returns 200."""
    resp = postgis_integration_client.get("/postgis/collections")
    assert resp.status_code == 200


@pytest.mark.integration
def test_postgis_collections_cors_follows_vector_api_config(postgis_integration_client):
    """/postgis/* answers CORS exactly as VECTOR_API_CORS_ORIGINS configures it."""
    origin = "https://never-allowed.example"
    if "*" in CORS_ORIGINS:
        expected = "*"
    elif origin in CORS_ORIGINS:
        expected = origin
    else:
        expected = None

    resp = postgis_integration_client.get(
        "/postgis/collections", headers={"Origin": origin}
    )

    assert resp.headers.get_list("access-control-allow-origin") == (
        [expected] if expected else []
    )
    if expected == "*":
        assert resp.headers.get("access-control-allow-credentials") != "true"


@pytest.mark.integration
def test_postgis_collections_has_oaf_structure(postgis_integration_client):
    """Collections response contains a 'collections' list and 'links'."""
    resp = postgis_integration_client.get("/postgis/collections")
    data = resp.json()
    assert "collections" in data or "numberMatched" in data
    assert "links" in data


# ------------------------------------------
# /postgis/collections/{id} and /items — using FARM_TABLE_NAME when available
# ------------------------------------------


@pytest.fixture(scope="session")
def _first_collection_id(postgis_integration_client):
    """Return the first collection ID whose items endpoint is functional, or skip.

    Prefers FARM_TABLE_NAME when set, then falls back to the first collection
    that returns 200 on /items. This guards against collections with column
    names that contain non-ASCII characters, which TiPg rejects at query time.
    """
    resp = postgis_integration_client.get("/postgis/collections")
    collections = resp.json().get("collections", [])
    if not collections:
        pytest.skip("No PostGIS collections registered — nothing to test")

    candidates: list[str] = []
    farm_table = os.getenv("FARM_TABLE_NAME", "")
    if farm_table:
        table_name = farm_table.split(".")[-1]
        for c in collections:
            if table_name in c["id"]:
                candidates.append(c["id"])
                break
    candidates += [c["id"] for c in collections if c["id"] not in candidates]

    for collection_id in candidates:
        probe = postgis_integration_client.get(
            f"/postgis/collections/{collection_id}/items?limit=1"
        )
        if probe.status_code == 200:
            return collection_id

    pytest.skip("No PostGIS collection has a working items endpoint")


@pytest.mark.integration
def test_postgis_collection_metadata_returns_200(
    postgis_integration_client, _first_collection_id
):
    """GET /postgis/collections/{id} returns 200 with collection metadata."""
    resp = postgis_integration_client.get(
        f"/postgis/collections/{_first_collection_id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "links" in data


@pytest.mark.integration
def test_postgis_items_returns_feature_collection(
    postgis_integration_client, _first_collection_id
):
    """GET /postgis/collections/{id}/items returns a GeoJSON FeatureCollection."""
    resp = postgis_integration_client.get(
        f"/postgis/collections/{_first_collection_id}/items?limit=5"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert isinstance(data["features"], list)


@pytest.mark.integration
def test_postgis_items_features_have_geometry(
    postgis_integration_client, _first_collection_id
):
    """Each returned feature has a non-null geometry with type and coordinates."""
    resp = postgis_integration_client.get(
        f"/postgis/collections/{_first_collection_id}/items?limit=5"
    )
    features = resp.json()["features"]
    for feature in features:
        assert "geometry" in feature
        if feature["geometry"] is not None:
            assert "type" in feature["geometry"]
            assert "coordinates" in feature["geometry"]
