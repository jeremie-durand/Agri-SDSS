import time

import pytest
import requests
import responses


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def sample_collection_response(vector_api_url_fixture):
    """Sample collection metadata response."""
    base = vector_api_url_fixture
    return {
        "id": "public.sud_du_quebec_4326",
        "title": "public.sud_du_quebec_4326",
        "links": [
            {
                "href": f"{base}/postgis/collections/public.sud_du_quebec_4326",
                "rel": "self",
                "type": "application/json",
            },
            {
                "href": f"{base}/postgis/collections/public.sud_du_quebec_4326/items",
                "rel": "items",
                "type": "application/geo+json",
                "title": "Items",
            },
        ],
        "extent": {
            "spatial": {
                "bbox": [
                    [
                        -74.66980081171282,
                        44.99135832579372,
                        -69.62529737300314,
                        47.4119438131845,
                    ]
                ],
                "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            },
            "temporal": {
                "interval": [
                    ["2024-01-01T00:00:00+00:00", "2024-12-31T00:00:00+00:00"]
                ],
                "trs": "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian",
            },
        },
        "itemType": "feature",
        "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
    }


@pytest.fixture
def sample_feature_collection(vector_api_url_fixture):
    """Sample feature collection response."""
    base = vector_api_url_fixture
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "region-1",
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
                "properties": {
                    "name": "Montérégie",
                    "region_code": "16",
                    "area_km2": 11111.5,
                    "population": 1534000,
                },
            }
        ],
        "links": [
            {
                "href": f"{base}/postgis/collections/public.sud_du_quebec_4326/items",
                "rel": "self",
                "type": "application/geo+json",
            }
        ],
        "numberMatched": 1,
        "numberReturned": 1,
    }


@pytest.fixture
def collections_list_response(vector_api_url_fixture):
    """Sample collections list response."""
    base = vector_api_url_fixture
    return {
        "collections": [
            {
                "id": "public.sud_du_quebec_4326",
                "title": "Southern Quebec Administrative Boundaries",
                "links": [
                    {
                        "href": f"{base}/postgis/collections/public.sud_du_quebec_4326",
                        "rel": "self",
                        "type": "application/json",
                    }
                ],
            },
            {
                "id": "public.bdppad_2024_4326_sample_stac",
                "title": "Agricultural Parcels Sample",
                "links": [
                    {
                        "href": f"{base}/postgis/collections/public.bdppad_2024_4326_sample_stac",
                        "rel": "self",
                        "type": "application/json",
                    }
                ],
            },
        ],
        "links": [
            {
                "href": f"{base}/postgis/collections",
                "rel": "self",
                "type": "application/json",
            }
        ],
    }


# ------------------------------------------
# Mocked vector API tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_postgis_responds(vector_api_url_fixture):
    """Test if the PostGIS endpoint responds with a 200 status code."""
    responses.add(responses.GET, vector_api_url_fixture, status=200)
    resp = requests.get(vector_api_url_fixture)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_all_collections(collections_list_response, vector_api_url_fixture):
    """Test GET /postgis/collections endpoint."""
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections",
        json=collections_list_response,
        status=200,
    )

    resp = requests.get(f"{vector_api_url_fixture}/postgis/collections")

    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    assert len(data["collections"]) == 2
    assert data["collections"][0]["id"] == "public.sud_du_quebec_4326"
    assert data["collections"][1]["id"] == "public.bdppad_2024_4326_sample_stac"


@pytest.mark.mocked
@responses.activate
def test_mocked_get_collection_info(sample_collection_response, vector_api_url_fixture):
    """Test GET /postgis/collections/{collectionId} endpoint."""
    collection_id = "public.sud_du_quebec_4326"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}",
        json=sample_collection_response,
        status=200,
    )

    resp = requests.get(f"{vector_api_url_fixture}/postgis/collections/{collection_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == collection_id
    assert "extent" in data
    assert "spatial" in data["extent"]
    assert "temporal" in data["extent"]
    assert data["itemType"] == "feature"


@pytest.mark.mocked
@responses.activate
def test_mocked_vector_api_collection_items(
    sample_feature_collection, vector_api_url_fixture
):
    """Test GET /postgis/collections/{collectionId}/items endpoint."""
    collection_id = "public.sud_du_quebec_4326"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=sample_feature_collection,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert len(data["features"]) == 1
    assert data["numberReturned"] == 1


@pytest.mark.mocked
@responses.activate
def test_mocked_get_specific_feature(
    single_feature_polygon_fixture, vector_api_url_fixture
):
    """Test GET /postgis/collections/{collectionId}/items/{featureId} endpoint."""
    collection_id = "public.sud_du_quebec_4326"
    feature_id = "region-1"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/{feature_id}",
        json=single_feature_polygon_fixture,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/{feature_id}"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == feature_id
    assert "geometry" in data
    assert "properties" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_items_with_limit(vector_api_url_fixture):
    """Test collection items endpoint with limit parameter."""
    collection_id = "public.sud_du_quebec_4326"
    limited_response = {
        "type": "FeatureCollection",
        "features": [],
        "numberMatched": 100,
        "numberReturned": 5,
    }

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=limited_response,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?limit=5"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["numberReturned"] == 5
    assert data["numberMatched"] == 100


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_items_with_bbox(vector_api_url_fixture):
    """Test collection items endpoint with bbox parameter."""
    collection_id = "public.sud_du_quebec_4326"
    bbox_response = {
        "type": "FeatureCollection",
        "features": [],
        "numberMatched": 2,
        "numberReturned": 2,
    }

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=bbox_response,
        status=200,
    )

    bbox = "-75,45,-74,46"
    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?bbox={bbox}"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_items_with_pagination(vector_api_url_fixture):
    """Test collection items endpoint with pagination parameters."""
    collection_id = "public.bdppad_2024_4326_sample_stac"
    paginated_response = {
        "type": "FeatureCollection",
        "features": [],
        "numberMatched": 100,
        "numberReturned": 10,
        "links": [
            {
                "href": f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?offset=30&limit=10",
                "rel": "next",
                "type": "application/geo+json",
            }
        ],
    }

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=paginated_response,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?limit=10&offset=20"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["numberReturned"] == 10
    assert "links" in data


# ------------------------------------------
# Error Handling Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_collection_not_found(vector_api_url_fixture):
    """Test handling of non-existent collection."""
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/nonexistent",
        json={"detail": "Collection not found"},
        status=404,
    )

    resp = requests.get(f"{vector_api_url_fixture}/postgis/collections/nonexistent")

    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.mocked
@responses.activate
def test_mocked_feature_not_found(vector_api_url_fixture):
    """Test handling of non-existent feature."""
    collection_id = "public.sud_du_quebec_4326"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/nonexistent",
        json={"detail": "Feature not found"},
        status=404,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/nonexistent"
    )

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_invalid_bbox(vector_api_url_fixture):
    """Test handling of invalid bbox parameter."""
    collection_id = "public.sud_du_quebec_4326"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json={"detail": "Invalid bbox format"},
        status=400,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?bbox=invalid"
    )

    assert resp.status_code == 400


@pytest.mark.mocked
@responses.activate
def test_mocked_server_error(vector_api_url_fixture):
    """Test handling of server errors."""
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections",
        json={"detail": "Internal server error"},
        status=500,
    )

    resp = requests.get(f"{vector_api_url_fixture}/postgis/collections")

    assert resp.status_code == 500


# ------------------------------------------
# Content Type and Format Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_geojson_content_type(vector_api_url_fixture):
    """Test that responses have correct content type for GeoJSON."""
    collection_id = "public.sud_du_quebec_4326"
    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json={"type": "FeatureCollection", "features": []},
        status=200,
        headers={"Content-Type": "application/geo+json"},
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items"
    )

    assert resp.status_code == 200
    assert "application/geo+json" in resp.headers.get("Content-Type", "")


@pytest.mark.mocked
@responses.activate
def test_mocked_geojsonseq_format(vector_api_url_fixture):
    """Test GeoJSON Sequence format support."""
    collection_id = "public.sud_du_quebec_4326"
    geojsonseq_data = '{"type":"Feature","id":"region-1","geometry":{"type":"Point","coordinates":[-73,45]},"properties":{"name":"Test"}}\n'

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        body=geojsonseq_data,
        status=200,
        headers={"Content-Type": "application/geo+json-seq"},
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?f=geojsonseq"
    )

    assert resp.status_code == 200
    assert "application/geo+json-seq" in resp.headers.get("Content-Type", "")


# ------------------------------------------
# Query Parameters Validation Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_query_parameters_validation(vector_api_url_fixture):
    """Test various query parameter combinations."""
    collection_id = "public.sud_du_quebec_4326"

    test_cases = [
        {"limit": 50, "expected_returned": 50},
        {"limit": 1000, "expected_returned": 1000},  # Max limit test
        {"offset": 100, "expected_returned": 10},
        {"limit": 25, "offset": 50, "expected_returned": 25},
    ]

    for case in test_cases:
        query_params = "&".join(
            [f"{k}={v}" for k, v in case.items() if k != "expected_returned"]
        )

        responses.add(
            responses.GET,
            f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
            json={
                "type": "FeatureCollection",
                "features": [],
                "numberReturned": case["expected_returned"],
            },
            status=200,
        )

        resp = requests.get(
            f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?{query_params}"
        )

        assert resp.status_code == 200
        assert resp.json()["numberReturned"] == case["expected_returned"]

        responses.reset()


# ------------------------------------------
# Performance Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_large_collection_response_time(vector_api_url_fixture):
    """Test response time for large collections."""
    collection_id = "public.bdppad_2024_4326_sample_stac"
    large_response = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"feature-{i}",
                "geometry": None,
                "properties": {},
            }
            for i in range(1000)
        ],
        "numberReturned": 1000,
    }

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=large_response,
        status=200,
    )

    start_time = time.time()
    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items?limit=1000"
    )
    response_time = time.time() - start_time

    assert resp.status_code == 200
    assert response_time < 5.0  # Should respond within 5 seconds
    assert len(resp.json()["features"]) == 1000


# ------------------------------------------
# Standards Compliance Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_ogc_api_features_compliance(vector_api_url_fixture):
    """Test OGC API - Features standard compliance."""
    # Test required endpoints exist
    endpoints = [
        "/postgis/collections",
        "/postgis/collections/public.sud_du_quebec_4326",
        "/postgis/collections/public.sud_du_quebec_4326/items",
    ]

    for endpoint in endpoints:
        responses.add(
            responses.GET,
            f"{vector_api_url_fixture}{endpoint}",
            json={"status": "ok"},
            status=200,
        )

        resp = requests.get(f"{vector_api_url_fixture}{endpoint}")
        assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_crs_support(vector_api_url_fixture):
    """Test coordinate reference system support."""
    collection_response = {
        "id": "public.sud_du_quebec_4326",
        "crs": ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"],
    }

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/public.sud_du_quebec_4326",
        json=collection_response,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/public.sud_du_quebec_4326"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "crs" in data
    assert "http://www.opengis.net/def/crs/OGC/1.3/CRS84" in data["crs"]


# ------------------------------------------
# Data Validation Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_geojson_feature_validation(
    single_feature_polygon_fixture, vector_api_url_fixture
):
    """Test that returned features are valid GeoJSON."""
    collection_id = "public.sud_du_quebec_4326"
    feature_id = "region-1"

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/{feature_id}",
        json=single_feature_polygon_fixture,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items/{feature_id}"
    )

    assert resp.status_code == 200
    feature = resp.json()

    # Validate GeoJSON Feature structure
    assert feature["type"] == "Feature"
    assert "id" in feature
    assert "geometry" in feature
    assert "properties" in feature
    assert feature["geometry"]["type"] in [
        "Point",
        "LineString",
        "Polygon",
        "MultiPoint",
        "MultiLineString",
        "MultiPolygon",
    ]
    assert isinstance(feature["properties"], dict)


@pytest.mark.mocked
@responses.activate
def test_feature_collection_validation(
    sample_feature_collection, vector_api_url_fixture
):
    """Test that returned feature collections are valid GeoJSON."""
    collection_id = "public.sud_du_quebec_4326"

    responses.add(
        responses.GET,
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items",
        json=sample_feature_collection,
        status=200,
    )

    resp = requests.get(
        f"{vector_api_url_fixture}/postgis/collections/{collection_id}/items"
    )

    assert resp.status_code == 200
    feature_collection = resp.json()

    # Validate GeoJSON FeatureCollection structure
    assert feature_collection["type"] == "FeatureCollection"
    assert "features" in feature_collection
    assert isinstance(feature_collection["features"], list)

    # Validate each feature
    for feature in feature_collection["features"]:
        assert feature["type"] == "Feature"
        assert "geometry" in feature
        assert "properties" in feature
