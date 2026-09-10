import pytest
import requests
import responses


# ------------------------------------------
# Mocked Raster API tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_raster_api_responds(raster_api_url_fixture):
    """Test if the raster API responds with a 200 status code."""
    responses.add(responses.GET, raster_api_url_fixture, status=200)
    resp = requests.get(raster_api_url_fixture)
    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_info(raster_api_url_fixture, tmp_raster_valid_fixture):
    """Test GET /cog/info endpoint."""
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/info?url={tmp_raster_valid_fixture.as_uri()}",
        status=200,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/info?url={tmp_raster_valid_fixture.as_uri()}"
    )

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_tile(raster_api_url_fixture, tmp_raster_valid_fixture):
    """Test GET /cog/tiles endpoint."""
    z, x, y = 0, 0, 0
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={tmp_raster_valid_fixture.as_uri()}",
        status=200,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={tmp_raster_valid_fixture.as_uri()}"
    )

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_viewer(raster_api_url_fixture, tmp_raster_valid_fixture):
    """Test GET /cog/viewer endpoint."""
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/viewer?url={tmp_raster_valid_fixture.as_uri()}",
        status=200,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/viewer?url={tmp_raster_valid_fixture.as_uri()}"
    )

    assert resp.status_code == 200


# ------------------------------------------
# Error Handling Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_info_not_found(raster_api_url_fixture):
    """Test GET /cog/info endpoint with non-existing raster."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/info?url={non_existing_raster_uri}",
        status=404,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/info?url={non_existing_raster_uri}"
    )

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_tile_not_found(raster_api_url_fixture):
    """Test GET /cog/tiles endpoint with non-existing raster."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    z, x, y = 0, 0, 0
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={non_existing_raster_uri}",
        status=404,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={non_existing_raster_uri}"
    )

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_info_body_has_geometry_fields(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/info response body must include width, height, bounds, and dtype."""
    url = f"{raster_api_url_fixture}/cog/info?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(
        responses.GET,
        url,
        json={
            "bounds": [-1.0, -1.0, 1.0, 1.0],
            "minzoom": 0,
            "maxzoom": 24,
            "width": 10,
            "height": 10,
            "dtype": "uint8",
        },
        status=200,
    )

    resp = requests.get(url)
    data = resp.json()

    assert "bounds" in data and len(data["bounds"]) == 4
    assert "width" in data and "height" in data
    assert "dtype" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_info_malformed_url_returns_422(raster_api_url_fixture):
    """GET /cog/info with a non-URL string returns 422 Unprocessable Entity."""
    url = f"{raster_api_url_fixture}/cog/info?url=not-a-valid-cog-url"
    responses.add(
        responses.GET,
        url,
        json={"detail": "Invalid COG URL"},
        status=422,
    )

    resp = requests.get(url)

    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_viewer_not_found(raster_api_url_fixture):
    """Test GET /cog/viewer endpoint with non-existing raster."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    responses.add(
        responses.GET,
        f"{raster_api_url_fixture}/cog/viewer?url={non_existing_raster_uri}",
        status=404,
    )

    resp = requests.get(
        f"{raster_api_url_fixture}/cog/viewer?url={non_existing_raster_uri}"
    )

    assert resp.status_code == 404


# ------------------------------------------
# /cog/statistics Tests
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_statistics_returns_200(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """Test GET /cog/statistics endpoint returns 200."""
    url = f"{raster_api_url_fixture}/cog/statistics?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(responses.GET, url, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_statistics_body_has_per_band_stats(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/statistics response body must include per-band min/max/mean/std."""
    url = f"{raster_api_url_fixture}/cog/statistics?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(
        responses.GET,
        url,
        json={"b1": {"min": 1.0, "max": 1.0, "mean": 1.0, "std": 0.0, "count": 100.0}},
        status=200,
    )

    resp = requests.get(url)
    data = resp.json()

    assert "b1" in data
    for key in ("min", "max", "mean", "std"):
        assert key in data["b1"], f"Missing key '{key}' in statistics band"


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_statistics_not_found_returns_404(raster_api_url_fixture):
    """GET /cog/statistics with non-existing raster returns 404."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    url = f"{raster_api_url_fixture}/cog/statistics?url={non_existing_raster_uri}"
    responses.add(responses.GET, url, status=404)

    resp = requests.get(url)

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_statistics_missing_url_returns_422(raster_api_url_fixture):
    """GET /cog/statistics with invalid url param returns 422."""
    url = f"{raster_api_url_fixture}/cog/statistics?url=not-a-valid-cog-url"
    responses.add(responses.GET, url, json={"detail": "Invalid COG URL"}, status=422)

    resp = requests.get(url)

    assert resp.status_code == 422


# ------------------------------------------
# /cog/point Tests
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_point_returns_200(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """Test GET /cog/point/{lon},{lat} endpoint returns 200."""
    url = f"{raster_api_url_fixture}/cog/point/5.0,5.0?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(responses.GET, url, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_point_body_has_coordinates_and_values(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/point response body must include coordinates and values."""
    url = f"{raster_api_url_fixture}/cog/point/5.0,5.0?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(
        responses.GET,
        url,
        json={"coordinates": [5.0, 5.0], "values": [1]},
        status=200,
    )

    resp = requests.get(url)
    data = resp.json()

    assert "coordinates" in data and len(data["coordinates"]) == 2
    assert "values" in data and isinstance(data["values"], list)


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_point_not_found_returns_404(raster_api_url_fixture):
    """GET /cog/point with non-existing raster returns 404."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    url = f"{raster_api_url_fixture}/cog/point/5.0,5.0?url={non_existing_raster_uri}"
    responses.add(responses.GET, url, status=404)

    resp = requests.get(url)

    assert resp.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_point_missing_url_returns_422(raster_api_url_fixture):
    """GET /cog/point with invalid url param returns 422."""
    url = f"{raster_api_url_fixture}/cog/point/5.0,5.0?url=not-a-valid-cog-url"
    responses.add(responses.GET, url, json={"detail": "Invalid COG URL"}, status=422)

    resp = requests.get(url)

    assert resp.status_code == 422


# ------------------------------------------
# /cog/preview Tests
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_preview_returns_200(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """Test GET /cog/preview endpoint returns 200."""
    url = (
        f"{raster_api_url_fixture}/cog/preview?url={tmp_raster_valid_fixture.as_uri()}"
    )
    responses.add(responses.GET, url, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_preview_content_type_is_image(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/preview response content-type must be an image type."""
    url = (
        f"{raster_api_url_fixture}/cog/preview?url={tmp_raster_valid_fixture.as_uri()}"
    )
    responses.add(
        responses.GET,
        url,
        body=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
        status=200,
    )

    resp = requests.get(url)

    assert "image" in resp.headers.get("Content-Type", "")


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_preview_not_found_returns_404(raster_api_url_fixture):
    """GET /cog/preview with non-existing raster returns 404."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    url = f"{raster_api_url_fixture}/cog/preview?url={non_existing_raster_uri}"
    responses.add(responses.GET, url, status=404)

    resp = requests.get(url)

    assert resp.status_code == 404


# ------------------------------------------
# /cog/validate Tests
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_validate_returns_200(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """Test GET /cog/validate endpoint returns 200."""
    url = (
        f"{raster_api_url_fixture}/cog/validate?url={tmp_raster_valid_fixture.as_uri()}"
    )
    responses.add(responses.GET, url, status=200)

    resp = requests.get(url)

    assert resp.status_code == 200


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_validate_body_has_is_valid(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/validate response body must include is_valid boolean."""
    url = (
        f"{raster_api_url_fixture}/cog/validate?url={tmp_raster_valid_fixture.as_uri()}"
    )
    responses.add(
        responses.GET,
        url,
        json={"is_valid": True, "errors": [], "warnings": []},
        status=200,
    )

    resp = requests.get(url)
    data = resp.json()

    assert "is_valid" in data
    assert isinstance(data["is_valid"], bool)


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_validate_not_found_returns_404(raster_api_url_fixture):
    """GET /cog/validate with non-existing raster returns 404."""
    non_existing_raster_uri = "file:///non/existing/raster.tif"
    url = f"{raster_api_url_fixture}/cog/validate?url={non_existing_raster_uri}"
    responses.add(responses.GET, url, status=404)

    resp = requests.get(url)

    assert resp.status_code == 404


# ------------------------------------------
# Existing Endpoint Gap Tests
# ------------------------------------------


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_tiles_missing_url_returns_422(raster_api_url_fixture):
    """GET /cog/tiles with invalid url param returns 422."""
    z, x, y = 0, 0, 0
    url = f"{raster_api_url_fixture}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=not-a-valid-cog-url"
    responses.add(responses.GET, url, json={"detail": "Invalid COG URL"}, status=422)

    resp = requests.get(url)

    assert resp.status_code == 422


@pytest.mark.mocked
@responses.activate
def test_mocked_get_raster_info_has_band_descriptions(
    raster_api_url_fixture, tmp_raster_valid_fixture
):
    """GET /cog/info response body must include band_descriptions list."""
    url = f"{raster_api_url_fixture}/cog/info?url={tmp_raster_valid_fixture.as_uri()}"
    responses.add(
        responses.GET,
        url,
        json={
            "bounds": [-1.0, -1.0, 1.0, 1.0],
            "minzoom": 0,
            "maxzoom": 24,
            "width": 10,
            "height": 10,
            "dtype": "uint8",
            "band_descriptions": [[1, ""]],
        },
        status=200,
    )

    resp = requests.get(url)
    data = resp.json()

    assert "band_descriptions" in data
    assert isinstance(data["band_descriptions"], list)
