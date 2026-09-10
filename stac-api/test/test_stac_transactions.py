"""Mocked contract tests for the STAC Transaction Extension and extra query params.

Covers the POST/PUT/DELETE paths on /collections and /collections/{id}/items,
plus CQL2 filter, fields, and sortby query parameters — all via HTTP mocking
with the `responses` library, following the pattern in test_stac_api_endpoints.py.
"""

import pytest
import requests
import responses

_COLLECTION_ID = "sentinel-2-l2a"
_ITEM_ID = "S2A_MSIL2A_20240115T153631_N0510_R068_T18TYM_20240115T201450"

_COLLECTION_BODY = {
    "type": "Collection",
    "id": _COLLECTION_ID,
    "stac_version": "1.0.0",
    "description": "Sentinel-2 Level-2A Surface Reflectance",
    "links": [],
    "title": "Sentinel-2 Level-2A",
    "extent": {
        "spatial": {"bbox": [[-74.66, 44.99, -69.62, 47.41]]},
        "temporal": {"interval": [["2023-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]]},
    },
    "license": "proprietary",
}

_ITEM_BODY = {
    "type": "Feature",
    "stac_version": "1.0.0",
    "id": _ITEM_ID,
    "collection": _COLLECTION_ID,
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
    "properties": {"datetime": "2024-01-15T15:36:31.000Z"},
    "links": [],
    "assets": {},
}

_SEARCH_RESPONSE = {
    "type": "FeatureCollection",
    "features": [_ITEM_BODY],
    "links": [],
    "context": {"returned": 1, "matched": 1},
}


# ------------------------------------------
# POST /collections — create collection
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_post_collection_returns_201(stac_api_url_fixture):
    """POST /collections returns 201 with the created collection body."""
    url = f"{stac_api_url_fixture}/collections"
    responses.add(responses.POST, url, json=_COLLECTION_BODY, status=201)

    resp = requests.post(url, json=_COLLECTION_BODY)

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == _COLLECTION_ID
    assert body["type"] == "Collection"


@pytest.mark.mocked
@responses.activate
def test_mocked_post_collection_response_has_stac_fields(stac_api_url_fixture):
    """Created collection body has all required STAC Collection fields."""
    url = f"{stac_api_url_fixture}/collections"
    responses.add(responses.POST, url, json=_COLLECTION_BODY, status=201)

    body = requests.post(url, json=_COLLECTION_BODY).json()

    for field in ("id", "type", "stac_version", "description", "extent", "links"):
        assert field in body, f"Missing field '{field}' in collection response"


# ------------------------------------------
# PUT /collections/{id} — update collection
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_put_collection_returns_200(stac_api_url_fixture):
    """PUT /collections/{id} returns 200 with the updated collection."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}"
    responses.add(responses.PUT, url, json=_COLLECTION_BODY, status=200)

    resp = requests.put(url, json=_COLLECTION_BODY)

    assert resp.status_code == 200
    assert resp.json()["id"] == _COLLECTION_ID


# ------------------------------------------
# DELETE /collections/{id}
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_delete_collection_returns_200(stac_api_url_fixture):
    """DELETE /collections/{id} returns 200."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}"
    responses.add(responses.DELETE, url, status=200)

    resp = requests.delete(url)

    assert resp.status_code == 200


# ------------------------------------------
# POST /collections/{id}/items — create item
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_post_item_returns_201(stac_api_url_fixture):
    """POST /collections/{id}/items returns 201 with the created item body."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}/items"
    responses.add(responses.POST, url, json=_ITEM_BODY, status=201)

    resp = requests.post(url, json=_ITEM_BODY)

    assert resp.status_code == 201
    assert resp.json()["id"] == _ITEM_ID


@pytest.mark.mocked
@responses.activate
def test_mocked_post_item_response_has_stac_item_fields(stac_api_url_fixture):
    """Created item body has all required STAC Feature fields."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}/items"
    responses.add(responses.POST, url, json=_ITEM_BODY, status=201)

    body = requests.post(url, json=_ITEM_BODY).json()

    assert body["type"] == "Feature"
    for field in ("stac_version", "id", "geometry", "properties", "links", "assets"):
        assert field in body, f"Missing field '{field}' in item response"


# ------------------------------------------
# PUT /collections/{id}/items/{item_id}
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_put_item_returns_200(stac_api_url_fixture):
    """PUT /collections/{id}/items/{item_id} returns 200."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}/items/{_ITEM_ID}"
    responses.add(responses.PUT, url, json=_ITEM_BODY, status=200)

    resp = requests.put(url, json=_ITEM_BODY)

    assert resp.status_code == 200
    assert resp.json()["id"] == _ITEM_ID


# ------------------------------------------
# DELETE /collections/{id}/items/{item_id}
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_delete_item_returns_200(stac_api_url_fixture):
    """DELETE /collections/{id}/items/{item_id} returns 200."""
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}/items/{_ITEM_ID}"
    responses.add(responses.DELETE, url, status=200)

    resp = requests.delete(url)

    assert resp.status_code == 200


# ------------------------------------------
# CQL2 filter — POST /search
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_search_with_cql2_filter_returns_200(stac_api_url_fixture):
    """POST /search with CQL2-JSON filter body returns 200 FeatureCollection."""
    url = f"{stac_api_url_fixture}/search"
    responses.add(responses.POST, url, json=_SEARCH_RESPONSE, status=200)

    body = {
        "filter": {
            "op": "=",
            "args": [{"property": "collection"}, _COLLECTION_ID],
        },
        "filter-lang": "cql2-json",
    }
    resp = requests.post(url, json=body)

    assert resp.status_code == 200
    assert resp.json()["type"] == "FeatureCollection"


# ------------------------------------------
# fields extension — GET /search
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_search_with_fields_param_returns_200(stac_api_url_fixture):
    """GET /search?fields=... returns 200 with features."""
    url = f"{stac_api_url_fixture}/search?fields=properties.datetime,id"
    responses.add(responses.GET, url, json=_SEARCH_RESPONSE, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200
    assert len(resp.json()["features"]) > 0


# ------------------------------------------
# sortby — GET /search
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_search_with_sortby_returns_200(stac_api_url_fixture):
    """GET /search?sortby=... returns 200 with features."""
    url = f"{stac_api_url_fixture}/search?sortby=-properties.datetime"
    responses.add(responses.GET, url, json=_SEARCH_RESPONSE, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200
    assert len(resp.json()["features"]) > 0


# ------------------------------------------
# /collections/{id}/items with bbox
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_collection_items_with_bbox_filter_returns_200(stac_api_url_fixture):
    """GET /collections/{id}/items?bbox=... returns 200 FeatureCollection."""
    bbox = "-73.5,45.5,-73.4,45.6"
    url = f"{stac_api_url_fixture}/collections/{_COLLECTION_ID}/items?bbox={bbox}"
    responses.add(
        responses.GET,
        url,
        json={"type": "FeatureCollection", "features": [_ITEM_BODY], "links": []},
        status=200,
    )

    resp = requests.get(url)

    assert resp.status_code == 200
    assert resp.json()["type"] == "FeatureCollection"
