"""Tests for Parquet API endpoints.

This module tests the Parquet router functionality for exposing
GeoParquet files through OGC API Features style endpoints.
"""

import os
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pytest
import responses
from shapely.geometry import Polygon

# Import the modules to test
try:
    from src.duckdb_manager import DuckDBManager
except ImportError:
    # For running tests directly, adjust path
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from duckdb_manager import DuckDBManager


# ------------------------------------------
# Fixtures
# ------------------------------------------


@pytest.fixture
def sample_polygon_geoparquet(temp_parquet_dir):
    """Create a sample GeoParquet file with polygons."""
    polygons = [
        Polygon(
            [(-73.5, 45.5), (-73.4, 45.5), (-73.4, 45.6), (-73.5, 45.6), (-73.5, 45.5)]
        ),
        Polygon(
            [(-73.6, 45.6), (-73.5, 45.6), (-73.5, 45.7), (-73.6, 45.7), (-73.6, 45.6)]
        ),
    ]
    data = {
        "gid": [1, 2],
        "name": ["Polygon A", "Polygon B"],
        "area_ha": [10.5, 20.3],
        "geometry": polygons,
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")

    output_path = temp_parquet_dir / "polygon_collection.parquet"
    gdf.to_parquet(output_path)

    return output_path


@pytest.fixture
def duckdb_manager(temp_parquet_dir, sample_geoparquet):
    """Create a DuckDBManager with test data directory."""
    with patch.dict(os.environ, {"DUCKDB_DATA_DIR": str(temp_parquet_dir)}):
        manager = DuckDBManager(data_dir=str(temp_parquet_dir))
        yield manager
        manager.conn.close()


# ------------------------------------------
# DuckDBManager Unit Tests
# ------------------------------------------
class TestDuckDBManager:
    """Tests for DuckDBManager class."""

    pytestmark = pytest.mark.unit

    def test_init_extensions(self, duckdb_manager):
        """Test that spatial extension is loaded."""
        # Should not raise an error
        result = duckdb_manager.conn.execute("SELECT ST_Point(0, 0)").fetchone()
        assert result is not None

    def test_list_parquet_files(self, duckdb_manager, sample_geoparquet):
        """Test listing Parquet files in directory."""
        collections = duckdb_manager.list_parquet_files()

        assert len(collections) >= 1
        collection_ids = [c["id"] for c in collections]
        assert "test_collection" in collection_ids

    def test_list_parquet_files_empty_dir(self, temp_parquet_dir):
        """Test listing when directory is empty."""
        empty_dir = temp_parquet_dir / "empty"
        empty_dir.mkdir()

        manager = DuckDBManager(data_dir=str(empty_dir))
        collections = manager.list_parquet_files()

        assert collections == []
        manager.conn.close()

    def test_get_parquet_path_exists(self, duckdb_manager, sample_geoparquet):
        """Test getting path for existing collection."""
        path = duckdb_manager.get_parquet_path("test_collection")

        assert path is not None
        assert path.exists()
        assert path.suffix == ".parquet"

    def test_get_parquet_path_not_found(self, duckdb_manager):
        """Test getting path for non-existent collection."""
        path = duckdb_manager.get_parquet_path("nonexistent")

        assert path is None

    def test_get_parquet_schema(self, duckdb_manager, sample_geoparquet):
        """Test getting schema for a collection."""
        schema = duckdb_manager.get_parquet_schema("test_collection")

        assert "columns" in schema
        assert "id_column" in schema
        assert "has_geometry" in schema
        assert "feature_count" in schema

        assert schema["id_column"] == "gid"
        assert schema["has_geometry"] is True
        assert schema["feature_count"] == 3

        column_names = [c["name"] for c in schema["columns"]]
        assert "gid" in column_names
        assert "name" in column_names
        assert "geometry" in column_names

    def test_get_parquet_schema_bbox(self, duckdb_manager, sample_geoparquet):
        """Test that bbox is computed for spatial data."""
        schema = duckdb_manager.get_parquet_schema("test_collection")

        assert schema["bbox"] is not None
        assert len(schema["bbox"]) == 4
        # Check bbox order: [minx, miny, maxx, maxy]
        minx, miny, maxx, maxy = schema["bbox"]
        assert minx <= maxx
        assert miny <= maxy

    def test_query_items_default(self, duckdb_manager, sample_geoparquet):
        """Test querying items with default parameters."""
        result = duckdb_manager.query_items("test_collection")

        assert "features" in result
        assert "numberMatched" in result
        assert "numberReturned" in result

        assert result["numberMatched"] == 3
        assert len(result["features"]) <= 10  # default limit

    def test_query_items_limit_offset(self, duckdb_manager, sample_geoparquet):
        """Test querying items with limit and offset."""
        result = duckdb_manager.query_items("test_collection", limit=2, offset=0)

        assert result["numberReturned"] == 2
        assert result["numberMatched"] == 3

        result2 = duckdb_manager.query_items("test_collection", limit=2, offset=2)
        assert result2["numberReturned"] == 1

    def test_query_items_geojson_format(self, duckdb_manager, sample_geoparquet):
        """Test that items are returned as valid GeoJSON features."""
        result = duckdb_manager.query_items("test_collection", limit=1)

        feature = result["features"][0]
        assert feature["type"] == "Feature"
        assert "id" in feature
        assert "geometry" in feature
        assert "properties" in feature

        # Geometry should be GeoJSON
        assert feature["geometry"]["type"] == "Point"
        assert "coordinates" in feature["geometry"]

    def test_query_items_bbox_filter(self, temp_parquet_dir, sample_polygon_geoparquet):
        """Test bbox filtering."""
        manager = DuckDBManager(data_dir=str(temp_parquet_dir))

        # Bbox that should include only one polygon
        bbox = (-73.55, 45.55, -73.45, 45.65)
        result = manager.query_items("polygon_collection", bbox=bbox)

        # Should filter to subset
        assert result["numberMatched"] <= 2

        manager.conn.close()

    def test_get_item_by_id(self, duckdb_manager, sample_geoparquet):
        """Test getting a single item by ID."""
        feature = duckdb_manager.get_item_by_id("test_collection", 1)

        assert feature is not None
        assert feature["type"] == "Feature"
        assert feature["id"] == 1
        assert feature["properties"]["name"] == "Feature A"

    def test_get_item_by_id_not_found(self, duckdb_manager, sample_geoparquet):
        """Test getting non-existent item."""
        feature = duckdb_manager.get_item_by_id("test_collection", 999)

        assert feature is None

    def test_escape_identifier(self):
        """Test identifier escaping."""
        assert DuckDBManager.escape_identifier("table") == '"table"'
        assert DuckDBManager.escape_identifier('table"name') == '"table""name"'

        with pytest.raises(ValueError):
            DuckDBManager.escape_identifier("")


# ------------------------------------------
# Mocked API Tests
# ------------------------------------------
@pytest.fixture
def parquet_api_url_fixture():
    """Base URL for Parquet API endpoints."""
    return os.getenv("VECTOR_API_URL", "http://localhost:8083") + "/parquet"


@pytest.fixture
def sample_collections_response(parquet_api_url_fixture):
    """Sample collections list response."""
    base = parquet_api_url_fixture
    return {
        "collections": [
            {
                "id": "couverture_pedo_2022",
                "title": "Couverture Pedo 2022",
                "description": "GeoParquet collection: couverture_pedo_2022",
                "extent": {
                    "spatial": {
                        "bbox": [[-79.5, 45.0, -57.0, 62.0]],
                        "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                    }
                },
                "itemType": "feature",
                "links": [
                    {
                        "href": f"{base}/collections/couverture_pedo_2022",
                        "rel": "self",
                        "type": "application/json",
                    }
                ],
            }
        ],
        "links": [
            {
                "href": f"{base}/collections",
                "rel": "self",
                "type": "application/json",
            }
        ],
        "numberMatched": 1,
        "numberReturned": 1,
    }


@pytest.fixture
def sample_parquet_feature_collection(parquet_api_url_fixture):
    """Sample feature collection response from Parquet."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": 1,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-73.5, 45.5],
                            [-73.4, 45.5],
                            [-73.4, 45.6],
                            [-73.5, 45.6],
                            [-73.5, 45.5],
                        ]
                    ],
                },
                "properties": {
                    "gid": 1,
                    "app_cart": "EAU",
                    "description": "Étendue d'eau(EAU)",
                },
            }
        ],
        "numberMatched": 1,
        "numberReturned": 1,
    }


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_collections_endpoint(
    parquet_api_url_fixture, sample_collections_response
):
    """Test GET /parquet/collections endpoint."""
    url = f"{parquet_api_url_fixture}/collections"
    responses.add(responses.GET, url, json=sample_collections_response, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    assert len(data["collections"]) > 0


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_collection_detail(parquet_api_url_fixture):
    """Test GET /parquet/collections/{collection_id} endpoint."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}"

    response_data = {
        "id": collection_id,
        "title": "Couverture Pedo 2022",
        "description": "GeoParquet collection with 1000 features",
        "itemType": "feature",
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == collection_id


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_items_endpoint(
    parquet_api_url_fixture, sample_parquet_feature_collection
):
    """Test GET /parquet/collections/{collection_id}/items endpoint."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/items"

    responses.add(
        responses.GET, url, json=sample_parquet_feature_collection, status=200
    )

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_single_item(parquet_api_url_fixture):
    """Test GET /parquet/collections/{collection_id}/items/{item_id} endpoint."""
    collection_id = "couverture_pedo_2022"
    item_id = 1
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/items/{item_id}"

    response_data = {
        "type": "Feature",
        "id": item_id,
        "geometry": {"type": "Point", "coordinates": [-73.5, 45.5]},
        "properties": {"gid": 1, "name": "Test Feature"},
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == item_id


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_collection_not_found(parquet_api_url_fixture):
    """Test 404 response for non-existent collection."""
    url = f"{parquet_api_url_fixture}/collections/nonexistent"

    responses.add(
        responses.GET,
        url,
        json={"detail": "Collection not found: nonexistent"},
        status=404,
    )

    import requests

    resp = requests.get(url)

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_items_with_bbox(parquet_api_url_fixture):
    """Test items endpoint with bbox parameter."""
    collection_id = "couverture_pedo_2022"
    bbox = "-73.6,45.4,-73.4,45.6"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/items?bbox={bbox}"

    response_data = {
        "type": "FeatureCollection",
        "features": [],
        "numberMatched": 0,
        "numberReturned": 0,
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
@pytest.mark.parametrize(
    "bbox",
    [
        "-181,45,-73,46",  # min_lon out of range
        "-73,45,181,46",  # max_lon out of range
        "-73,-91,-72,46",  # min_lat out of range
        "-73,45,-72,91",  # max_lat out of range
        "-73,45,-74,46",  # min_lon >= max_lon
        "-73,46,-72,45",  # min_lat >= max_lat
    ],
)
def test_mocked_parquet_items_invalid_bbox(parquet_api_url_fixture, bbox):
    """Test that invalid bbox coordinates return 400."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/items?bbox={bbox}"
    responses.add(
        responses.GET, url, json={"detail": "Invalid bbox format"}, status=400
    )

    import requests

    resp = requests.get(url)
    assert resp.status_code == 400


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_items_pagination(parquet_api_url_fixture):
    """Test items endpoint with pagination parameters."""
    collection_id = "couverture_pedo_2022"
    url = (
        f"{parquet_api_url_fixture}/collections/{collection_id}/items?limit=5&offset=10"
    )

    response_data = {
        "type": "FeatureCollection",
        "features": [],
        "numberMatched": 100,
        "numberReturned": 5,
        "links": [
            {
                "rel": "next",
                "href": f"{parquet_api_url_fixture}/collections/{collection_id}/items?limit=5&offset=15",
            },
            {
                "rel": "prev",
                "href": f"{parquet_api_url_fixture}/collections/{collection_id}/items?limit=5&offset=5",
            },
        ],
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert data["numberMatched"] == 100


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_queryables(parquet_api_url_fixture):
    """Test GET /parquet/collections/{collection_id}/queryables endpoint."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/queryables"

    response_data = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": f"Queryables for {collection_id}",
        "properties": {
            "gid": {"type": "integer"},
            "app_cart": {"type": "string"},
            "description": {"type": "string"},
        },
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert "properties" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_openapi_json(parquet_api_url_fixture):
    """Test GET /parquet/openapi.json returns a valid OpenAPI schema."""
    base = os.getenv("VECTOR_API_URL", "http://localhost:8083")
    url = f"{base}/parquet/openapi.json"

    response_data = {
        "openapi": "3.1.0",
        "info": {
            "title": "Parquet Collections API",
            "version": "1.0.0",
            "description": "OGC API Features style endpoints for GeoParquet files",
        },
        "paths": {
            "/parquet/collections": {},
            "/parquet/collections/{collection_id}": {},
            "/parquet/collections/{collection_id}/items": {},
            "/parquet/collections/{collection_id}/items/{item_id}": {},
        },
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert "openapi" in data
    assert "info" in data
    assert data["info"]["title"] == "Parquet Collections API"
    assert "paths" in data


# ------------------------------------------
# FastAPI TestClient — HTTP router tests
# ------------------------------------------


@pytest.mark.unit
def test_list_collections_returns_required_keys(parquet_app_client):
    """GET /parquet/collections must include collections, numberMatched, and links."""
    resp = parquet_app_client.get("/parquet/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert "collections" in body
    assert "numberMatched" in body
    assert "links" in body


@pytest.mark.unit
def test_get_collection_missing_returns_404(parquet_app_client):
    """GET /parquet/collections/{id} for a non-existent collection returns 404."""
    resp = parquet_app_client.get("/parquet/collections/does_not_exist")
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_items_returns_feature_collection(parquet_app_client):
    """GET /parquet/collections/test_collection/items returns a GeoJSON FeatureCollection."""
    resp = parquet_app_client.get("/parquet/collections/test_collection/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert "features" in body


# ------------------------------------------
# Response body structure validation
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_collections_response_has_pagination_fields(
    parquet_api_url_fixture, sample_collections_response
):
    """GET /parquet/collections response must include OGC pagination metadata."""
    url = f"{parquet_api_url_fixture}/collections"
    responses.add(responses.GET, url, json=sample_collections_response, status=200)

    import requests

    data = requests.get(url).json()

    assert "numberMatched" in data, "OGC response must include numberMatched"
    assert "numberReturned" in data, "OGC response must include numberReturned"
    assert "links" in data, "OGC response must include links array"
    assert isinstance(data["links"], list)
    assert data["numberMatched"] == len(data["collections"])


@pytest.mark.mocked
@responses.activate
def test_mocked_collections_each_item_has_id_and_links(
    parquet_api_url_fixture, sample_collections_response
):
    """Each collection entry must have 'id' and 'links' fields."""
    url = f"{parquet_api_url_fixture}/collections"
    responses.add(responses.GET, url, json=sample_collections_response, status=200)

    import requests

    data = requests.get(url).json()

    for col in data["collections"]:
        assert "id" in col, f"Collection entry missing 'id': {col}"
        assert "links" in col, f"Collection entry missing 'links': {col}"
        assert isinstance(col["links"], list)


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_detail_has_required_fields(parquet_api_url_fixture):
    """GET /parquet/collections/{id} must return OGC-required metadata fields."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}"

    response_data = {
        "id": collection_id,
        "title": "Couverture Pedo 2022",
        "description": "GeoParquet collection with 1000 features",
        "itemType": "feature",
        "links": [{"href": url, "rel": "self", "type": "application/json"}],
        "numberMatched": 1000,
    }
    responses.add(responses.GET, url, json=response_data, status=200)

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == collection_id
    assert "title" in data
    assert "description" in data
    assert data["itemType"] == "feature"
    assert "links" in data
    assert isinstance(data["links"], list)


@pytest.mark.mocked
@responses.activate
def test_mocked_parquet_swagger_ui_html(parquet_api_url_fixture):
    """Test GET /parquet/api.html returns a Swagger UI HTML page."""
    base = os.getenv("VECTOR_API_URL", "http://localhost:8083")
    url = f"{base}/parquet/api.html"

    html_body = """<!DOCTYPE html>
<html>
  <head><title>Parquet Collections API</title></head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist/swagger-ui-bundle.js"></script>
    <script>
      SwaggerUIBundle({ url: "/parquet/openapi.json", dom_id: "#swagger-ui" });
    </script>
  </body>
</html>"""
    responses.add(
        responses.GET,
        url,
        body=html_body,
        status=200,
        content_type="text/html; charset=utf-8",
    )

    import requests

    resp = requests.get(url)

    assert resp.status_code == 200
    assert "text/html" in resp.headers["Content-Type"]
    assert "swagger-ui" in resp.text.lower()
    assert "/parquet/openapi.json" in resp.text


@pytest.mark.mocked
@responses.activate
def test_mocked_items_response_features_have_geometry(
    parquet_api_url_fixture, sample_parquet_feature_collection
):
    """Each feature in items response must have a geometry field."""
    collection_id = "couverture_pedo_2022"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}/items"
    responses.add(
        responses.GET, url, json=sample_parquet_feature_collection, status=200
    )

    import requests

    data = requests.get(url).json()

    assert data["type"] == "FeatureCollection"
    for feature in data["features"]:
        assert feature["type"] == "Feature"
        assert "geometry" in feature
        assert "properties" in feature


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_not_found_returns_detail_field(parquet_api_url_fixture):
    """404 responses must include a 'detail' field explaining what was not found."""
    collection_id = "nonexistent_collection"
    url = f"{parquet_api_url_fixture}/collections/{collection_id}"
    responses.add(
        responses.GET,
        url,
        json={"detail": f"Collection '{collection_id}' not found"},
        status=404,
    )

    import requests

    resp = requests.get(url)

    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert collection_id in data["detail"]


# ------------------------------------------
# Error propagation and edge-case tests
# ------------------------------------------


@pytest.fixture
def corrupt_parquet_dir(temp_parquet_dir, sample_geoparquet):
    """Temp dir with a valid parquet file plus a corrupt one."""
    (temp_parquet_dir / "corrupt.parquet").write_bytes(b"not a parquet file at all")
    return temp_parquet_dir


@pytest.fixture
def corrupt_parquet_client(corrupt_parquet_dir):
    """FastAPI TestClient with a corrupt parquet file in the data dir."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from vector_api.duckdb_manager import DuckDBManager as _DuckDBManager
    from vector_api.parquet_router import router

    real_manager = _DuckDBManager(data_dir=str(corrupt_parquet_dir))
    test_app = FastAPI()
    test_app.include_router(router)

    with patch(
        "vector_api.parquet_router.get_shared_manager", return_value=real_manager
    ):
        with TestClient(test_app, raise_server_exceptions=False) as client:
            yield client

    real_manager.conn.close()


@pytest.fixture
def nonspatial_parquet_dir(tmp_path):
    """Temp dir with a Parquet file that has no geometry column."""
    import pandas as pd

    df = pd.DataFrame({"gid": [1, 2], "name": ["a", "b"], "value": [10, 20]})
    df.to_parquet(tmp_path / "nonspatial.parquet", index=False)
    return tmp_path


@pytest.fixture
def nonspatial_parquet_client(nonspatial_parquet_dir):
    """FastAPI TestClient pointing at the non-spatial parquet directory."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from vector_api.duckdb_manager import DuckDBManager as _DuckDBManager
    from vector_api.parquet_router import router

    real_manager = _DuckDBManager(data_dir=str(nonspatial_parquet_dir))
    test_app = FastAPI()
    test_app.include_router(router)

    with patch(
        "vector_api.parquet_router.get_shared_manager", return_value=real_manager
    ):
        with TestClient(test_app) as client:
            yield client

    real_manager.conn.close()


@pytest.mark.unit
def test_corrupt_parquet_items_returns_500(corrupt_parquet_client):
    """Querying items from a corrupt parquet file returns 500."""
    resp = corrupt_parquet_client.get("/parquet/collections/corrupt/items")
    assert resp.status_code == 500


@pytest.mark.unit
def test_invalid_bbox_format_returns_400(parquet_app_client):
    """bbox with non-numeric values returns 400."""
    resp = parquet_app_client.get(
        "/parquet/collections/test_collection/items?bbox=abc,def,ghi,jkl"
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_bbox_too_few_values_returns_400(parquet_app_client):
    """bbox with fewer than 4 values returns 400."""
    resp = parquet_app_client.get(
        "/parquet/collections/test_collection/items?bbox=1,2,3"
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_invalid_collection_id_special_chars_returns_400(parquet_app_client):
    """Collection ID with dots or spaces returns 400."""
    resp = parquet_app_client.get("/parquet/collections/bad.collection/items")
    assert resp.status_code == 400


@pytest.mark.unit
def test_spatial_extension_failure_returns_503():
    """DuckDBSpatialExtensionError from validate_collection_exists propagates as 503."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from vector_api.duckdb_manager import DuckDBSpatialExtensionError
    from vector_api.parquet_router import router

    test_app = FastAPI()
    test_app.include_router(router)

    with patch(
        "vector_api.parquet_router.get_shared_manager",
        side_effect=DuckDBSpatialExtensionError("spatial extension failed"),
    ):
        with TestClient(test_app, raise_server_exceptions=False) as client:
            resp = client.get("/parquet/collections/any_collection")

    assert resp.status_code == 503


@pytest.mark.unit
def test_nonspatial_parquet_returns_features_with_null_geometry(
    nonspatial_parquet_client,
):
    """A parquet file without a geometry column yields features with geometry=null."""
    resp = nonspatial_parquet_client.get("/parquet/collections/nonspatial/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    for feature in body["features"]:
        assert feature["geometry"] is None


@pytest.mark.unit
def test_bbox_no_intersection_returns_empty_features(parquet_app_client):
    """A bbox that does not overlap the data returns 200 with an empty features list."""
    # Sample data lives near lon=-73, lat=45; bbox 0,0,1,1 has no overlap.
    resp = parquet_app_client.get(
        "/parquet/collections/test_collection/items?bbox=0,0,1,1"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body["features"] == []


@pytest.mark.unit
def test_query_items_duckdb_error_returns_500(parquet_app_client):
    """A DuckDB error raised inside query_items propagates as 500."""
    from unittest.mock import MagicMock

    import duckdb

    mock_manager = MagicMock()
    mock_manager.query_items.side_effect = duckdb.Error("simulated DuckDB error")

    with patch(
        "vector_api.parquet_router.get_duckdb_manager", return_value=mock_manager
    ):
        resp = parquet_app_client.get("/parquet/collections/test_collection/items")

    assert resp.status_code == 500
