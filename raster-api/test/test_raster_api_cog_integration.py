"""Real integration tests for raster-api COG endpoints.

Uses FastAPI TestClient against the real TiTiler app (no HTTP mocking).
All tests operate on a real in-memory GeoTIFF created by the session fixture,
exercising actual rasterio/GDAL rendering and processing.
"""

import pytest
from fastapi.testclient import TestClient
from titiler.application.main import app as titiler_app


@pytest.fixture(scope="session")
def tiler_client():
    """Session-scoped TestClient backed by the real TiTiler ASGI app."""
    with TestClient(titiler_app) as client:
        yield client


# ------------------------------------------
# /cog/info — real rasterio metadata read
# ------------------------------------------


@pytest.mark.integration
def test_real_cog_info_returns_actual_metadata(tiler_client, tmp_raster_valid_fixture):
    """TiTiler reads the fixture GeoTIFF and returns correct raster metadata."""
    resp = tiler_client.get(f"/cog/info?url={tmp_raster_valid_fixture.as_uri()}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["width"] == 10
    assert data["height"] == 10
    assert data["dtype"] == "uint8"


@pytest.mark.integration
def test_real_cog_info_bounds_match_fixture(tiler_client, tmp_raster_valid_fixture):
    """Returned bounds match the fixture COG geographic extent (0–10°, EPSG:4326)."""
    resp = tiler_client.get(f"/cog/info?url={tmp_raster_valid_fixture.as_uri()}")
    assert resp.status_code == 200
    bounds = resp.json()["bounds"]  # [minx, miny, maxx, maxy]
    assert len(bounds) == 4
    assert abs(bounds[0] - 0.0) < 1e-3, f"minx expected ~0.0, got {bounds[0]}"
    assert abs(bounds[1] - 0.0) < 1e-3, f"miny expected ~0.0, got {bounds[1]}"
    assert abs(bounds[2] - 10.0) < 1e-3, f"maxx expected ~10.0, got {bounds[2]}"
    assert abs(bounds[3] - 10.0) < 1e-3, f"maxy expected ~10.0, got {bounds[3]}"


# ------------------------------------------
# /cog/tiles — real GDAL tile rendering
# ------------------------------------------


@pytest.mark.integration
def test_real_cog_tile_returns_png_bytes(tiler_client, tmp_raster_valid_fixture):
    """z=0/x=0/y=0 covers the entire world; TiTiler renders a non-empty PNG."""
    resp = tiler_client.get(
        f"/cog/tiles/WebMercatorQuad/0/0/0.png?url={tmp_raster_valid_fixture.as_uri()}"
    )
    assert resp.status_code == 200
    assert "image" in resp.headers["content-type"]
    assert len(resp.content) > 0


@pytest.mark.integration
def test_real_cog_tile_png_has_valid_header(tiler_client, tmp_raster_valid_fixture):
    """Rendered tile bytes start with the PNG magic byte sequence."""
    resp = tiler_client.get(
        f"/cog/tiles/WebMercatorQuad/0/0/0.png?url={tmp_raster_valid_fixture.as_uri()}"
    )
    assert resp.status_code == 200
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------
# /cog/statistics — real pixel value computation
# ------------------------------------------


@pytest.mark.integration
def test_real_cog_statistics_returns_all_ones(tiler_client, tmp_raster_valid_fixture):
    """Fixture has all pixels=1; statistics must report min=max=mean=1, std=0."""
    resp = tiler_client.get(f"/cog/statistics?url={tmp_raster_valid_fixture.as_uri()}")
    assert resp.status_code == 200
    data = resp.json()
    assert "b1" in data, "Expected band key 'b1' in statistics response"
    b1 = data["b1"]
    assert b1["min"] == pytest.approx(1.0), f"min expected 1.0, got {b1['min']}"
    assert b1["max"] == pytest.approx(1.0), f"max expected 1.0, got {b1['max']}"
    assert b1["mean"] == pytest.approx(1.0), f"mean expected 1.0, got {b1['mean']}"


# ------------------------------------------
# /cog/point — real pixel sampling
# ------------------------------------------


@pytest.mark.integration
def test_real_cog_point_returns_pixel_value(tiler_client, tmp_raster_valid_fixture):
    """Sampling at lon=5°, lat=5° (centre of fixture) returns the pixel value 1."""
    resp = tiler_client.get(
        f"/cog/point/5.0,5.0?url={tmp_raster_valid_fixture.as_uri()}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "values" in data
    assert data["values"] == [1]


# ------------------------------------------
# /cog/validate — COG structure check
# ------------------------------------------


@pytest.mark.integration
def test_real_cog_validate_response_has_is_valid_field(
    tiler_client, tmp_raster_valid_fixture
):
    """Validate endpoint returns a boolean is_valid field (value not asserted —
    fixture is a plain GeoTIFF, not necessarily a Cloud-Optimized GeoTIFF)."""
    resp = tiler_client.get(f"/cog/validate?url={tmp_raster_valid_fixture.as_uri()}")
    assert resp.status_code == 200
    data = resp.json()
    # TiTiler 2.x validate returns "COG" (bool) not "is_valid"
    assert "COG" in data
    assert isinstance(data["COG"], bool)
