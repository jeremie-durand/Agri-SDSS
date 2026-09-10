"""OGC API Features compliance tests for the parquet router.

Uses real DuckDB reads via the parquet_app_client fixture (TestClient backed
by a real DuckDBManager against fixture GeoParquet files). Tests assert the
full OGC API Features GeoJSON contract, not just HTTP status codes.

Fixture data (sample_geoparquet): 3 Point features, EPSG:4326,
coords near Montreal, properties: gid, name, value, category.
"""

import pytest

# ------------------------------------------
# /parquet/collections — OGC collection list
# ------------------------------------------


@pytest.mark.integration
def test_collections_list_has_oaf_required_fields(parquet_app_client):
    """GET /parquet/collections returns numberMatched, numberReturned, and collections."""
    resp = parquet_app_client.get("/parquet/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    assert "numberMatched" in data
    assert "links" in data


@pytest.mark.integration
def test_collections_list_includes_test_collection(parquet_app_client):
    """The test_collection (derived from fixture filename) appears in the list."""
    resp = parquet_app_client.get("/parquet/collections")
    collection_ids = [c["id"] for c in resp.json()["collections"]]
    assert "test_collection" in collection_ids


# ------------------------------------------
# /parquet/collections/{id}/items — OGC FeatureCollection
# ------------------------------------------


@pytest.mark.integration
def test_items_response_is_geojson_feature_collection(parquet_app_client):
    """GET /parquet/collections/test_collection/items returns a GeoJSON FeatureCollection."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert isinstance(data["features"], list)


@pytest.mark.integration
def test_items_feature_count_matches_fixture(parquet_app_client):
    """Default response includes all 3 features from the fixture file."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    features = resp.json()["features"]
    assert len(features) == 3


@pytest.mark.integration
def test_items_each_feature_has_oaf_required_fields(parquet_app_client):
    """Every feature has the OGC-required fields: type, id, geometry, properties."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    for feature in resp.json()["features"]:
        assert feature["type"] == "Feature", "feature.type must be 'Feature'"
        assert "id" in feature, "feature must have 'id'"
        assert "geometry" in feature, "feature must have 'geometry'"
        assert "properties" in feature, "feature must have 'properties'"


@pytest.mark.integration
def test_items_geometry_is_point_with_two_coordinates(parquet_app_client):
    """Fixture points produce Point geometries with [lon, lat] coordinate pairs."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    for feature in resp.json()["features"]:
        geom = feature["geometry"]
        assert geom["type"] == "Point", f"Expected Point, got {geom['type']}"
        assert len(geom["coordinates"]) == 2, "Point coordinates must be [lon, lat]"


@pytest.mark.integration
def test_items_properties_include_all_fixture_fields(parquet_app_client):
    """Parquet properties (name, value, category) are all present on each feature."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    for feature in resp.json()["features"]:
        props = feature["properties"]
        for field in ("name", "value", "category"):
            assert field in props, f"Missing property '{field}'"


# ------------------------------------------
# Pagination
# ------------------------------------------


@pytest.mark.integration
def test_items_limit_restricts_returned_count(parquet_app_client):
    """?limit=2 returns exactly 2 features from the 3-feature fixture."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()["features"]) == 2


@pytest.mark.integration
def test_items_offset_skips_first_feature(parquet_app_client):
    """?offset=1 skips the first feature; the remaining IDs match the tail of the full list."""
    all_features = parquet_app_client.get(
        "/parquet/collections/test_collection/items"
    ).json()["features"]
    offset_features = parquet_app_client.get(
        "/parquet/collections/test_collection/items?offset=1"
    ).json()["features"]

    all_ids = [f["id"] for f in all_features]
    offset_ids = [f["id"] for f in offset_features]
    assert offset_ids == all_ids[1:]


# ------------------------------------------
# Single feature by ID
# ------------------------------------------


@pytest.mark.integration
def test_single_feature_endpoint_returns_one_feature(parquet_app_client):
    """GET /parquet/collections/test_collection/items/{id} returns a single Feature."""
    features = parquet_app_client.get(
        "/parquet/collections/test_collection/items"
    ).json()["features"]
    first_id = str(features[0]["id"])

    resp = parquet_app_client.get(
        f"/parquet/collections/test_collection/items/{first_id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert str(data["id"]) == first_id
