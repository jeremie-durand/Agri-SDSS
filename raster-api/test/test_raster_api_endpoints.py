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
