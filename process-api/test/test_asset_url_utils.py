"""Unit tests for public STAC asset URL construction."""

import pytest

from processes.asset_url_utils import cog_href, preview_href, tilejson_href


@pytest.fixture
def public_host(monkeypatch):
    """Point the URL builders at a known public origin."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")


@pytest.mark.unit
def test_cog_href_is_absolute(public_host):
    assert (
        cog_href("/data/lidar_dtm_geom_095dc21f.tif")
        == "https://agri-sdss.duckdns.org/cog/lidar_dtm_geom_095dc21f.tif"
    )


@pytest.mark.unit
def test_cog_href_keeps_only_the_basename(public_host):
    assert (
        cog_href("/some/nested/dir/x.tif") == "https://agri-sdss.duckdns.org/cog/x.tif"
    )


@pytest.mark.unit
def test_preview_href_points_at_titiler(public_host):
    assert preview_href("/data/x.tif") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png?url=/data/x.tif"
    )


@pytest.mark.unit
def test_preview_href_appends_rescale(public_host):
    assert preview_href("/data/x.tif", rescale="0,1") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png"
        "?url=/data/x.tif&rescale=0,1"
    )


@pytest.mark.unit
def test_tilejson_href_carries_the_tile_matrix_set(public_host):
    assert tilejson_href("/data/x.tif") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/WebMercatorQuad"
        "/tilejson.json?url=/data/x.tif"
    )


@pytest.mark.unit
def test_tilejson_href_appends_rescale(public_host):
    assert tilejson_href("/data/x.tif", rescale="0,1") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/WebMercatorQuad"
        "/tilejson.json?url=/data/x.tif&rescale=0,1"
    )


@pytest.mark.unit
def test_defaults_to_localhost_when_host_is_unset(monkeypatch):
    monkeypatch.delenv("HOST_PROTOCOL", raising=False)
    monkeypatch.delenv("HOST_URL", raising=False)
    assert cog_href("/data/x.tif") == "http://localhost/cog/x.tif"


@pytest.mark.unit
def test_cog_href_encodes_unsafe_characters(public_host):
    assert cog_href("/data/relevé 1.tif") == (
        "https://agri-sdss.duckdns.org/cog/relev%C3%A9%201.tif"
    )


@pytest.mark.unit
def test_cog_href_does_not_double_encode_an_already_public_url(public_host):
    once = cog_href("/data/relevé 1.tif")
    assert cog_href(once) == once


@pytest.mark.unit
def test_preview_href_selects_a_band(public_host):
    assert preview_href("/data/x.tif", bidx=1) == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png"
        "?url=/data/x.tif&bidx=1"
    )


@pytest.mark.unit
def test_preview_href_combines_band_and_rescale(public_host):
    assert preview_href("/data/x.tif", rescale="0,1", bidx=2) == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png"
        "?url=/data/x.tif&bidx=2&rescale=0,1"
    )


@pytest.mark.unit
def test_tilejson_href_selects_a_band(public_host):
    assert tilejson_href("/data/x.tif", rescale="0,1", bidx=1) == (
        "https://agri-sdss.duckdns.org/raster-api/cog/WebMercatorQuad"
        "/tilejson.json?url=/data/x.tif&bidx=1&rescale=0,1"
    )
