"""
Verify mos-chatbot backend is correctly connected to its four internal services.
All tests are @pytest.mark.mocked — no live services required.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi_app import app


def _aiohttp_mock(get_json=None, post_json=None, status: int = 200) -> MagicMock:
    """Return a mock aiohttp.ClientSession for a single GET or POST call."""

    def _make_response(json_data):
        resp = MagicMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data or {})
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        return resp

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = MagicMock(return_value=_make_response(get_json))
    session.post = MagicMock(return_value=_make_response(post_json))
    return session


@pytest.mark.mocked
def test_health_check_reaches_internal_stac_api():
    """GET /api/health must call STAC_API_URL (http://stac-api:8080) to verify connectivity."""
    mock_session = _aiohttp_mock(status=200)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    stac_calls = [
        c for c in mock_session.get.call_args_list if "stac-api:8080" in str(c)
    ]
    assert len(stac_calls) >= 1


@pytest.mark.mocked
def test_stac_collections_calls_internal_stac_api():
    """GET /api/stac/collections must call http://stac-api:8080/collections."""
    fake_collections = {
        "collections": [{"id": "soil-om", "title": "Soil Organic Matter"}]
    }
    mock_session = _aiohttp_mock(get_json=fake_collections, status=200)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        response = TestClient(app).get("/api/stac/collections")
    assert response.status_code == 200
    stac_calls = [
        c for c in mock_session.get.call_args_list if "stac-api:8080" in str(c)
    ]
    assert len(stac_calls) >= 1
    assert "/collections" in str(stac_calls[0])


@pytest.mark.mocked
def test_stac_search_proxies_to_internal_stac_api():
    """POST /api/stac-search must POST to http://stac-api:8080/search."""
    fake_geojson = {"type": "FeatureCollection", "features": []}
    mock_session = _aiohttp_mock(post_json=fake_geojson, status=200)
    payload = {
        "collections": ["sentinel2_eo_products"],
        "bbox": [-73.0, 45.0, -72.0, 46.0],
        "limit": 10,
    }
    with patch("aiohttp.ClientSession", return_value=mock_session):
        response = TestClient(app).post("/api/stac-search", json=payload)
    assert response.status_code == 200
    stac_calls = [
        c for c in mock_session.post.call_args_list if "stac-api:8080" in str(c)
    ]
    assert len(stac_calls) >= 1
    assert "/search" in str(stac_calls[0])


@pytest.mark.mocked
def test_internal_service_env_vars_match_docker_hostnames():
    """Env vars for raster-api, vector-api, mos-pygeoapi must use correct Docker network hostnames."""
    assert os.getenv("RASTER_API_INTERNAL_URL") == "http://raster-api:8080"
    assert os.getenv("VECTOR_API_INTERNAL_URL") == "http://vector-api:8080"
    assert os.getenv("PYGEOAPI_INTERNAL_URL") == "http://mos-pygeoapi:5000"
