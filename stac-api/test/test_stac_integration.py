"""Real integration tests for the stac-api (stac-fastapi.pgstac).

Uses FastAPI TestClient against the real stac-fastapi app backed by pgstac.
All tests are automatically skipped when PostgreSQL is unavailable.

Test strategy: session-scoped fixtures create a collection and item once,
run all read/search assertions against them, then clean up via DELETE.
This avoids polluting the shared database between test runs.
"""

import pytest

# ------------------------------------------
# Session-scoped fixtures — create once, clean up after
# ------------------------------------------


@pytest.fixture(scope="session")
def _created_collection(stac_integration_client, sample_stac_collection):
    """Create test collection; yield its ID; delete it after the session."""
    resp = stac_integration_client.post("/collections", json=sample_stac_collection)
    if resp.status_code not in (200, 201):
        pytest.skip(
            f"Cannot create test collection (status {resp.status_code}): {resp.text}"
        )
    collection_id = sample_stac_collection["id"]
    yield collection_id
    stac_integration_client.delete(f"/collections/{collection_id}")


@pytest.fixture(scope="session")
def _created_item(stac_integration_client, _created_collection, sample_stac_item):
    """Create test item inside the test collection; yield its ID; delete after session."""
    resp = stac_integration_client.post(
        f"/collections/{_created_collection}/items",
        json=sample_stac_item,
    )
    if resp.status_code not in (200, 201):
        pytest.skip(f"Cannot create test item (status {resp.status_code}): {resp.text}")
    item_id = sample_stac_item["id"]
    yield item_id
    stac_integration_client.delete(
        f"/collections/{_created_collection}/items/{item_id}"
    )


# ------------------------------------------
# Root and conformance
# ------------------------------------------


@pytest.mark.integration
def test_stac_root_returns_catalog(stac_integration_client):
    """GET / returns a valid STAC catalog landing page."""
    resp = stac_integration_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "links" in data
    assert "stac_version" in data


@pytest.mark.integration
def test_stac_conformance_returns_classes(stac_integration_client):
    """GET /conformance returns a conformsTo list with at least one OGC/STAC URI."""
    resp = stac_integration_client.get("/conformance")
    assert resp.status_code == 200
    data = resp.json()
    assert "conformsTo" in data
    assert isinstance(data["conformsTo"], list)
    assert len(data["conformsTo"]) > 0


# ------------------------------------------
# Collections — read
# ------------------------------------------


@pytest.mark.integration
def test_stac_collections_list_includes_created_collection(
    stac_integration_client, _created_collection
):
    """GET /collections returns a list containing the created test collection."""
    resp = stac_integration_client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    ids = [c["id"] for c in data["collections"]]
    assert _created_collection in ids, f"'{_created_collection}' not found in {ids}"


@pytest.mark.integration
def test_stac_collection_metadata_is_valid(
    stac_integration_client, _created_collection
):
    """GET /collections/{id} returns a valid STAC Collection object."""
    resp = stac_integration_client.get(f"/collections/{_created_collection}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _created_collection
    assert data["type"] == "Collection"
    assert "extent" in data
    assert "links" in data


# ------------------------------------------
# Items — read (requires _created_item)
# ------------------------------------------


@pytest.mark.integration
def test_stac_items_endpoint_returns_feature_collection(
    stac_integration_client, _created_item, _created_collection
):
    """GET /collections/{id}/items returns a FeatureCollection containing the test item."""
    resp = stac_integration_client.get(f"/collections/{_created_collection}/items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    ids = [f["id"] for f in data["features"]]
    assert _created_item in ids, f"'{_created_item}' not found in items"


@pytest.mark.integration
def test_stac_item_by_id_returns_feature(
    stac_integration_client, _created_item, _created_collection
):
    """GET /collections/{id}/items/{item_id} returns a valid STAC Feature."""
    resp = stac_integration_client.get(
        f"/collections/{_created_collection}/items/{_created_item}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == _created_item
    assert "geometry" in data
    assert "properties" in data
    assert "assets" in data


# ------------------------------------------
# Search
# ------------------------------------------


@pytest.mark.integration
def test_stac_search_finds_created_item(
    stac_integration_client, _created_item, _created_collection
):
    """POST /search with collection filter returns the created item."""
    resp = stac_integration_client.post(
        "/search",
        json={"collections": [_created_collection]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    ids = [f["id"] for f in data["features"]]
    assert _created_item in ids, f"'{_created_item}' not found in search results"


@pytest.mark.integration
def test_stac_search_bbox_filters_item(
    stac_integration_client, _created_item, _created_collection
):
    """POST /search with bbox enclosing the item returns at least one feature."""
    # item bbox is [-73.5, 45.5, -73.4, 45.6] — well inside [-74, 45, -73, 46]
    resp = stac_integration_client.post(
        "/search",
        json={
            "collections": [_created_collection],
            "bbox": [-74.0, 45.0, -73.0, 46.0],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 1
