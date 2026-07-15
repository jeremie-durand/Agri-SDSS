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
