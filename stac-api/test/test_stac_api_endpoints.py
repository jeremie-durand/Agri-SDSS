import time
from urllib.parse import urlparse

import pytest
import requests
import responses


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def sample_stac_catalog(stac_api_url_fixture):
    """Sample STAC catalog root response."""
    base = stac_api_url_fixture
    return {
        "type": "Catalog",
        "stac_version": "1.0.0",
        "id": "agri-sdss-catalog",
        "title": "Agri-SDSS STAC Catalog",
        "description": "STAC catalog for Agri-SDSS project",
        "links": [
            {
                "rel": "self",
                "type": "application/json",
                "href": f"{base}/",
            },
            {
                "rel": "root",
                "type": "application/json",
                "href": f"{base}/",
            },
            {
                "rel": "collections",
                "type": "application/json",
                "href": f"{base}/collections",
            },
            {
                "rel": "search",
                "type": "application/geo+json",
                "href": f"{base}/search",
            },
        ],
    }


@pytest.fixture
def sample_collections_response(stac_api_url_fixture):
    """Sample collections list response."""
    base = stac_api_url_fixture
    return {
        "collections": [
            {
                "type": "Collection",
                "id": "sentinel-2-l2a",
                "title": "Sentinel-2 Level-2A",
                "description": "Sentinel-2 Level-2A Surface Reflectance",
                "stac_version": "1.0.0",
                "license": "proprietary",
                "extent": {
                    "spatial": {"bbox": [[-74.66, 44.99, -69.62, 47.41]]},
                    "temporal": {
                        "interval": [["2023-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
                    },
                },
                "links": [
                    {
                        "rel": "self",
                        "type": "application/json",
                        "href": f"{base}/collections/sentinel-2-l2a",
                    },
                    {
                        "rel": "items",
                        "type": "application/geo+json",
                        "href": f"{base}/collections/sentinel-2-l2a/items",
                    },
                ],
            },
            {
                "type": "Collection",
                "id": "landsat-c2-l2",
                "title": "Landsat Collection 2 Level-2",
                "description": "Landsat Collection 2 Level-2 Surface Reflectance",
                "stac_version": "1.0.0",
                "license": "public-domain",
                "extent": {
                    "spatial": {"bbox": [[-75.0, 45.0, -70.0, 47.0]]},
                    "temporal": {
                        "interval": [["2022-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
                    },
                },
            },
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/json",
                "href": f"{base}/collections",
            }
        ],
    }


@pytest.fixture
def sample_collection_detail():
    """Sample individual collection response."""
    return {
        "type": "Collection",
        "id": "sentinel-2-l2a",
        "title": "Sentinel-2 Level-2A",
        "description": "Sentinel-2 Level-2A Surface Reflectance",
        "stac_version": "1.0.0",
        "license": "proprietary",
        "providers": [
            {
                "name": "ESA",
                "roles": ["producer"],
                "url": "https://scihub.copernicus.eu/",
            }
        ],
        "extent": {
            "spatial": {"bbox": [[-74.66, 44.99, -69.62, 47.41]]},
            "temporal": {
                "interval": [["2023-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]
            },
        },
        "item_assets": {
            "red": {
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "title": "Red Band",
            },
            "green": {
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "title": "Green Band",
            },
        },
        "summaries": {
            "platform": ["sentinel-2a", "sentinel-2b"],
            "instruments": ["msi"],
            "gsd": [10, 20, 60],
        },
    }


@pytest.fixture
def sample_items_response(stac_api_url_fixture):
    """Sample items (features) response."""
    base = stac_api_url_fixture
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "stac_version": "1.0.0",
                "id": "S2A_MSIL2A_20240115T153631_N0510_R068_T18TYM_20240115T201450",
                "collection": "sentinel-2-l2a",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-73.123, 45.456],
                            [-73.124, 45.457],
                            [-73.125, 45.456],
                            [-73.123, 45.456],
                        ]
                    ],
                },
                "bbox": [-73.125, 45.456, -73.123, 45.457],
                "properties": {
                    "datetime": "2024-01-15T15:36:31.000Z",
                    "platform": "sentinel-2a",
                    "instruments": ["msi"],
                    "constellation": "sentinel-2",
                    "mission": "sentinel-2a",
                    "gsd": 10,
                    "proj:epsg": 32618,
                    "eo:cloud_cover": 12.5,
                },
                "assets": {
                    "red": {
                        "href": "https://example.com/data/red.tif",
                        "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                        "roles": ["data"],
                        "title": "Red Band",
                    },
                    "thumbnail": {
                        "href": "https://example.com/thumbnails/thumb.jpg",
                        "type": "image/jpeg",
                        "roles": ["thumbnail"],
                        "title": "Thumbnail",
                    },
                },
                "links": [
                    {
                        "rel": "self",
                        "type": "application/geo+json",
                        "href": f"{base}/collections/sentinel-2-l2a/items/S2A_MSIL2A_20240115T153631_N0510_R068_T18TYM_20240115T201450",
                    }
                ],
            }
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/geo+json",
                "href": f"{base}/collections/sentinel-2-l2a/items",
            }
        ],
        "context": {"page": 1, "limit": 10, "matched": 1, "returned": 1},
    }


@pytest.fixture
def sample_search_response(stac_api_url_fixture):
    """Sample search endpoint response."""
    base = stac_api_url_fixture
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "stac_version": "1.0.0",
                "id": "search-result-1",
                "collection": "sentinel-2-l2a",
                "geometry": {"type": "Point", "coordinates": [-73.0, 45.5]},
                "properties": {
                    "datetime": "2024-01-15T15:36:31.000Z",
                    "eo:cloud_cover": 5.2,
                },
            }
        ],
        "links": [
            {
                "rel": "self",
                "type": "application/geo+json",
                "href": f"{base}/search?collections=sentinel-2-l2a",
            }
        ],
        "context": {"page": 1, "limit": 10, "matched": 1, "returned": 1},
    }


# ------------------------------------------
# Basic STAC API Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_catalog_root(stac_api_url_fixture, sample_stac_catalog):
    """Test STAC catalog root endpoint."""
    responses.add(
        responses.GET, stac_api_url_fixture, json=sample_stac_catalog, status=200
    )

    resp = requests.get(stac_api_url_fixture)

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Catalog"
    assert data["stac_version"] == "1.0.0"
    assert "links" in data

    # Verify required links
    link_rels = [link["rel"] for link in data["links"]]
    assert "self" in link_rels
    assert "root" in link_rels


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_collections_list(
    stac_api_url_fixture, sample_collections_response
):
    """Test STAC collections endpoint."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections",
        json=sample_collections_response,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/collections")

    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    assert len(data["collections"]) == 2

    # Verify collection structure
    for collection in data["collections"]:
        assert collection["type"] == "Collection"
        assert "id" in collection
        assert "extent" in collection
        assert "spatial" in collection["extent"]
        assert "temporal" in collection["extent"]


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_collection_detail(stac_api_url_fixture, sample_collection_detail):
    """Test individual STAC collection endpoint."""
    collection_id = "sentinel-2-l2a"
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/{collection_id}",
        json=sample_collection_detail,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/collections/{collection_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Collection"
    assert data["id"] == collection_id
    assert "extent" in data
    assert "item_assets" in data
    assert "summaries" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_collection_items(stac_api_url_fixture, sample_items_response):
    """Test STAC collection items endpoint."""
    collection_id = "sentinel-2-l2a"
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/{collection_id}/items",
        json=sample_items_response,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/collections/{collection_id}/items")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert len(data["features"]) == 1

    # Verify STAC item structure
    item = data["features"][0]
    assert item["type"] == "Feature"
    assert "stac_version" in item
    assert "collection" in item
    assert "geometry" in item
    assert "properties" in item
    assert "assets" in item


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_search_get(stac_api_url_fixture, sample_search_response):
    """Test STAC search endpoint with GET."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json=sample_search_response,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/search?collections=sentinel-2-l2a")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert "context" in data
    assert data["context"]["returned"] == 1


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_search_post(stac_api_url_fixture, sample_search_response):
    """Test STAC search endpoint with POST."""
    responses.add(
        responses.POST,
        f"{stac_api_url_fixture}/search",
        json=sample_search_response,
        status=200,
    )

    search_body = {
        "collections": ["sentinel-2-l2a"],
        "bbox": [-74, 45, -70, 47],
        "datetime": "2024-01-01T00:00:00Z/2024-12-31T23:59:59Z",
        "limit": 10,
    }

    resp = requests.post(f"{stac_api_url_fixture}/search", json=search_body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data


# ------------------------------------------
# Search Parameter Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_search_with_bbox(stac_api_url_fixture):
    """Test STAC search with bbox parameter."""
    filtered_response = {
        "type": "FeatureCollection",
        "features": [],
        "context": {"matched": 0, "returned": 0},
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json=filtered_response,
        status=200,
    )

    bbox = "-74,45,-70,47"
    resp = requests.get(f"{stac_api_url_fixture}/search?bbox={bbox}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_search_with_datetime(stac_api_url_fixture):
    """Test STAC search with datetime parameter."""
    time_filtered_response = {
        "type": "FeatureCollection",
        "features": [],
        "context": {"matched": 0, "returned": 0},
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json=time_filtered_response,
        status=200,
    )

    datetime_param = "2024-01-01T00:00:00Z/2024-01-31T23:59:59Z"
    resp = requests.get(f"{stac_api_url_fixture}/search?datetime={datetime_param}")

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_search_with_query(stac_api_url_fixture):
    """Test STAC search with query parameters."""
    query_response = {
        "type": "FeatureCollection",
        "features": [],
        "context": {"matched": 0, "returned": 0},
    }

    responses.add(
        responses.POST,
        f"{stac_api_url_fixture}/search",
        json=query_response,
        status=200,
    )

    search_body = {
        "collections": ["sentinel-2-l2a"],
        "query": {"eo:cloud_cover": {"lt": 10}, "platform": {"eq": "sentinel-2a"}},
    }

    resp = requests.post(f"{stac_api_url_fixture}/search", json=search_body)

    assert resp.status_code == 200


# ------------------------------------------
# Pagination Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_pagination(stac_api_url_fixture):
    """Test STAC API pagination."""
    paginated_response = {
        "type": "FeatureCollection",
        "features": [],
        "links": [
            {
                "rel": "next",
                "type": "application/geo+json",
                "href": f"{stac_api_url_fixture}/search?page=2",
            }
        ],
        "context": {"page": 1, "limit": 10, "matched": 25, "returned": 10},
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json=paginated_response,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/search?limit=10")

    assert resp.status_code == 200
    data = resp.json()
    assert data["context"]["limit"] == 10
    assert data["context"]["matched"] == 25

    # Check for next link
    next_link = next((link for link in data["links"] if link["rel"] == "next"), None)
    assert next_link is not None


# ------------------------------------------
# Error Handling Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_collection_not_found(stac_api_url_fixture):
    """Test 404 for non-existent collection."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/nonexistent",
        json={"detail": "Collection not found"},
        status=404,
    )

    resp = requests.get(f"{stac_api_url_fixture}/collections/nonexistent")
    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_item_not_found(stac_api_url_fixture):
    """Test 404 for non-existent item."""
    collection_id = "sentinel-2-l2a"
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/{collection_id}/items/nonexistent",
        json={"detail": "Item not found"},
        status=404,
    )

    resp = requests.get(
        f"{stac_api_url_fixture}/collections/{collection_id}/items/nonexistent"
    )
    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_invalid_search_parameters(stac_api_url_fixture):
    """Test 400 for invalid search parameters."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json={"detail": "Invalid bbox format"},
        status=400,
    )

    resp = requests.get(f"{stac_api_url_fixture}/search?bbox=invalid")
    assert resp.status_code == 400


# ------------------------------------------
# STAC Extensions Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_projection_extension(stac_api_url_fixture):
    """Test STAC Projection extension."""
    proj_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/projection/v1.1.0/schema.json"
        ],
        "id": "proj-test-item",
        "properties": {
            "datetime": "2024-01-15T15:36:31.000Z",
            "proj:epsg": 32618,
            "proj:transform": [10, 0, 300000, 0, -10, 5900000],
        },
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/sentinel-2-l2a/items/proj-test-item",
        json=proj_item,
        status=200,
    )

    resp = requests.get(
        f"{stac_api_url_fixture}/collections/sentinel-2-l2a/items/proj-test-item"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "proj:epsg" in data["properties"]


# ------------------------------------------
# Content Negotiation Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_content_type_json(stac_api_url_fixture):
    """Test JSON content type."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections",
        json={"collections": []},
        status=200,
        headers={"Content-Type": "application/json"},
    )

    resp = requests.get(
        f"{stac_api_url_fixture}/collections", headers={"Accept": "application/json"}
    )

    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("Content-Type", "")


@pytest.mark.mocked
@responses.activate
def test_mocked_content_type_geojson(stac_api_url_fixture):
    """Test GeoJSON content type for search."""
    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/search",
        json={"type": "FeatureCollection", "features": []},
        status=200,
        headers={"Content-Type": "application/geo+json"},
    )

    resp = requests.get(
        f"{stac_api_url_fixture}/search", headers={"Accept": "application/geo+json"}
    )

    assert resp.status_code == 200
    assert "application/geo+json" in resp.headers.get("Content-Type", "")


# ------------------------------------------
# Performance Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_search_response_time(stac_api_url_fixture):
    """Test STAC search response time."""
    large_response = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "id": f"item-{i}"} for i in range(100)],
        "context": {"matched": 100, "returned": 100},
    }

    responses.add(
        responses.GET, f"{stac_api_url_fixture}/search", json=large_response, status=200
    )

    start_time = time.time()
    resp = requests.get(f"{stac_api_url_fixture}/search?limit=100")
    response_time = time.time() - start_time

    assert resp.status_code == 200
    assert response_time < 3.0  # Should respond within 3 seconds
    assert len(resp.json()["features"]) == 100


# ------------------------------------------
# STAC Validation Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_item_validation(stac_api_url_fixture):
    """Test STAC item structure validation."""
    valid_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": "validation-test",
        "collection": "test-collection",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
        },
        "bbox": [-1, -1, 1, 1],
        "properties": {"datetime": "2024-01-15T15:36:31.000Z"},
        "assets": {
            "data": {
                "href": "https://example.com/data.tif",
                "type": "image/tiff",
                "roles": ["data"],
            }
        },
        "links": [
            {
                "rel": "self",
                "type": "application/geo+json",
                "href": f"{stac_api_url_fixture}/collections/test/items/validation-test",
            }
        ],
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/collections/test-collection/items/validation-test",
        json=valid_item,
        status=200,
    )

    resp = requests.get(
        f"{stac_api_url_fixture}/collections/test-collection/items/validation-test"
    )

    assert resp.status_code == 200
    item = resp.json()

    # Validate required STAC item fields
    required_fields = [
        "type",
        "stac_version",
        "id",
        "geometry",
        "properties",
        "assets",
        "links",
    ]
    for field in required_fields:
        assert field in item, f"Missing required field: {field}"

    assert item["type"] == "Feature"
    assert "datetime" in item["properties"]
    assert len(item["assets"]) > 0
    assert len(item["links"]) > 0


# ------------------------------------------
# Conformance Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_conformance(stac_api_url_fixture):
    """Test STAC API conformance classes."""
    conformance_response = {
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/collections",
            "https://api.stacspec.org/v1.0.0/ogcapi-features",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
        ]
    }

    responses.add(
        responses.GET,
        f"{stac_api_url_fixture}/conformance",
        json=conformance_response,
        status=200,
    )

    resp = requests.get(f"{stac_api_url_fixture}/conformance")

    assert resp.status_code == 200
    data = resp.json()
    assert "conformsTo" in data
    assert len(data["conformsTo"]) > 0

    # Check for core STAC conformance
    stac_core_found = any(
        (
            urlparse(conf).hostname == "stacspec.org"
            or (
                urlparse(conf).hostname is not None
                and urlparse(conf).hostname.endswith(".stacspec.org")
            )
        )
        for conf in data["conformsTo"]
    )
    assert stac_core_found, "STAC core conformance class not found"
