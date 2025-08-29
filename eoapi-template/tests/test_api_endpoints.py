# tests/test_api_endpoints.py
import pytest
import requests
import responses

from .conftest import (
    duckdb_api_url,
    pygeoapi_api_url,
    raster_api_url,
    stac_api_url,
    stacbrowser_api_url,
    vector_api_url,
)


# ------------------------------------------
# Mocked STAC API
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_api_stac_responds():
    """
    Test if the STAC API responds with a 200 status code and correct mock content.
    """
    responses.add(responses.GET, stac_api_url, json={"title": "STAC mock"}, status=200)
    resp = requests.get(stac_api_url)
    assert resp.status_code == 200
    assert resp.json()["title"] == "STAC mock"


@pytest.mark.mocked
@responses.activate
def test_mocked_api_stac_collections():
    """
    Test if the STAC API collections endpoint returns a list of collections.
    """
    responses.add(
        responses.GET,
        f"{stac_api_url}/collections",
        json={"collections": []},
        status=200,
    )
    resp = requests.get(f"{stac_api_url}/collections")
    assert resp.status_code == 200
    assert "collections" in resp.json()


@pytest.mark.mocked
@responses.activate
def test_mocked_api_stac_search():
    """
    Test if the STAC API search endpoint returns a valid response.
    """
    responses.add(
        responses.GET,
        f"{stac_api_url}/search",
        json={"features": [{"id": "item1"}]},
        status=200,
    )
    resp = requests.get(f"{stac_api_url}/search")
    assert resp.status_code == 200
    assert "features" in resp.json()
    assert len(resp.json()["features"]) > 0


# ------------------------------------------
# Mocked raster API (TiTiler)
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_raster_api_responds():
    """
    Test if the raster API responds with a 200 status code.
    """
    responses.add(responses.GET, raster_api_url, status=200)
    resp = requests.get(raster_api_url)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_raster_api_info_endpoint():
    """
    Test if the raster API info endpoint returns a valid response.
    """
    responses.add(
        responses.GET,
        f"{raster_api_url}/cog/info",
        json={"bounds": [0, 0, 1, 1]},
        status=200,
    )
    resp = requests.get(f"{raster_api_url}/cog/info")
    assert resp.status_code == 200
    assert "bounds" in resp.json()


# ------------------------------------------
# Mocked vector API (TiPg)
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_vector_api_responds():
    """
    Test if the vector API responds with a 200 status code.
    """
    responses.add(responses.GET, vector_api_url, status=200)
    resp = requests.get(vector_api_url)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_vector_api_collection_items():
    """
    Test if the vector API collection items endpoint returns a valid response.
    """
    responses.add(
        responses.GET,
        f"{vector_api_url}/collections/public.sud_du_quebec_4326/items",
        json={"features": []},
        status=200,
    )
    resp = requests.get(f"{vector_api_url}/collections/public.sud_du_quebec_4326/items")
    assert resp.status_code == 200
    assert "features" in resp.json()


# ------------------------------------------
# Mocked STAC Browser
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_stac_browser_responds():
    """
    Test if the STAC Browser responds with a 200 status code.
    """
    responses.add(responses.GET, stacbrowser_api_url, status=200)
    resp = requests.get(stacbrowser_api_url)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_stac_browser_search_endpoint():
    """
    Test if the STAC Browser search endpoint returns a valid response.
    """
    responses.add(responses.GET, f"{stacbrowser_api_url}/search", status=200)
    resp = requests.get(f"{stacbrowser_api_url}/search")
    assert resp.status_code == 200


# ------------------------------------------
# Mocked pygeoapi
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_pygeoapi_responds():
    """
    Test if the pygeoapi responds with a 200 status code.
    """
    responses.add(responses.GET, pygeoapi_api_url, status=200)
    resp = requests.get(pygeoapi_api_url)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_pygeoapi_processes_endpoint():
    """
    Test if the pygeoapi processes endpoint returns a valid response.
    """
    responses.add(responses.GET, f"{pygeoapi_api_url}/processes", status=200)
    resp = requests.get(f"{pygeoapi_api_url}/processes")
    assert resp.status_code == 200


# ------------------------------------------
# Mocked duckDB
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_duckdb_responds():
    responses.add(responses.GET, duckdb_api_url, status=200)
    resp = requests.get(duckdb_api_url)
    assert resp.status_code == 200
