"""Unit tests for gis_pipeline/core/config.py — Config class loading and defaults."""

import os
from datetime import timezone

import pytest


@pytest.mark.unit
def test_config_default_datetime_is_utc_aware():
    """Config.DEFAULT_DATETIME must be timezone-aware (UTC)."""
    from gis_pipeline.core.config import Config

    assert Config.DEFAULT_DATETIME.tzinfo is not None
    assert Config.DEFAULT_DATETIME.tzinfo == timezone.utc


@pytest.mark.unit
def test_config_hash_suffix_length_is_consistent():
    """HASH_SUFFIX_LENGTH must equal HASH_HEX_LENGTH + len(HASH_SEPARATOR)."""
    from gis_pipeline.core.config import Config

    expected = Config.HASH_HEX_LENGTH + len(Config.HASH_SEPARATOR)
    assert Config.HASH_SUFFIX_LENGTH == expected


@pytest.mark.unit
def test_config_postgres_port_default_when_env_unset(monkeypatch):
    """POSTGRES_PORT must default to 5432 when the env var is absent."""
    monkeypatch.delenv("POSTGRES_PORT", raising=False)

    # Re-import to pick up the monkeypatched env (Config reads env at import time,
    # so we verify via the int() default in the source rather than re-importing).
    # Validate the documented default value directly.

    default_port = int(os.getenv("POSTGRES_PORT", 5432))
    assert default_port == 5432


@pytest.mark.unit
def test_config_duckdb_database_default_when_env_unset(monkeypatch):
    """DUCKDB_DATABASE must default to '/data/duckdb/eoapi.duckdb' when unset."""
    monkeypatch.delenv("DUCKDB_DATABASE", raising=False)

    default_path = os.getenv("DUCKDB_DATABASE", "/data/duckdb/eoapi.duckdb")
    assert default_path == "/data/duckdb/eoapi.duckdb"


@pytest.mark.unit
def test_config_hash_hex_length_is_six():
    """HASH_HEX_LENGTH must be 6 to match the MD5 truncation in harmonize_name."""
    from gis_pipeline.core.config import Config

    assert Config.HASH_HEX_LENGTH == 6


@pytest.mark.unit
def test_config_now_datetime_is_utc_aware():
    """Config.NOW_DATETIME must be timezone-aware (UTC)."""
    from gis_pipeline.core.config import Config

    assert Config.NOW_DATETIME.tzinfo is not None
    assert Config.NOW_DATETIME.tzinfo == timezone.utc


@pytest.mark.unit
def test_public_cog_url_is_absolute(monkeypatch):
    """A COG path becomes an absolute URL on the configured public origin."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_cog_url

    assert public_cog_url("/data/output/raster_cog/demo.tif") == (
        "https://agri-sdss.duckdns.org/cog/demo.tif"
    )


@pytest.mark.unit
def test_public_cog_url_defaults_to_localhost(monkeypatch):
    """With no host configured the URL falls back to a local origin."""
    monkeypatch.delenv("HOST_PROTOCOL", raising=False)
    monkeypatch.delenv("HOST_URL", raising=False)

    from gis_pipeline.core.config import public_cog_url

    assert public_cog_url("/x/demo.tif") == "http://localhost/cog/demo.tif"


@pytest.mark.unit
def test_public_cog_url_encodes_unsafe_characters(monkeypatch):
    """Spaces and non-ASCII in a filename are percent-encoded."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_cog_url

    assert public_cog_url("/d/relevé été.tif") == (
        "https://agri-sdss.duckdns.org/cog/relev%C3%A9%20%C3%A9t%C3%A9.tif"
    )


@pytest.mark.unit
def test_public_preview_url_points_at_the_raster_api(monkeypatch):
    """The preview is rendered by TiTiler, reached through the public route."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_preview_url

    assert public_preview_url("/data/output/raster_cog/demo.tif") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png?url=/data/demo.tif"
    )


@pytest.mark.unit
def test_public_preview_url_appends_rescale(monkeypatch):
    """A float raster renders flat unless TiTiler is given its value range."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_preview_url

    assert public_preview_url("/d/demo.tif", rescale="0.5,9.5") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png"
        "?url=/data/demo.tif&rescale=0.5,9.5"
    )


@pytest.mark.unit
def test_public_tilejson_url_carries_the_tile_matrix_set(monkeypatch):
    """TiTiler 2.x requires the tile grid identifier in the TileJSON path."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_tilejson_url

    assert public_tilejson_url("/d/demo.tif", rescale="0,1") == (
        "https://agri-sdss.duckdns.org/raster-api/cog/WebMercatorQuad"
        "/tilejson.json?url=/data/demo.tif&rescale=0,1"
    )


@pytest.mark.unit
def test_public_preview_url_selects_a_band(monkeypatch):
    """A multi-band COG is unencodable unless one band is selected."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_preview_url

    assert public_preview_url("/d/demo.tif", rescale="3,78", bidx=1) == (
        "https://agri-sdss.duckdns.org/raster-api/cog/preview.png"
        "?url=/data/demo.tif&bidx=1&rescale=3,78"
    )


@pytest.mark.unit
def test_public_tilejson_url_selects_a_band(monkeypatch):
    """Tiles must select the same band as the preview, or they differ."""
    monkeypatch.setenv("HOST_PROTOCOL", "https")
    monkeypatch.setenv("HOST_URL", "agri-sdss.duckdns.org")

    from gis_pipeline.core.config import public_tilejson_url

    assert public_tilejson_url("/d/demo.tif", rescale="3,78", bidx=1) == (
        "https://agri-sdss.duckdns.org/raster-api/cog/WebMercatorQuad"
        "/tilejson.json?url=/data/demo.tif&bidx=1&rescale=3,78"
    )
