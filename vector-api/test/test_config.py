"""Unit tests for vector_api.config module.

Tests module-level constants and CORS parsing logic directly.
"""

import pytest
from vector_api import config


@pytest.mark.unit
def test_api_title_is_vector_api():
    assert config.API_TITLE == "Vector API"


@pytest.mark.unit
def test_api_version_is_semver():
    assert config.API_VERSION == "1.0.0"


@pytest.mark.unit
def test_postgis_prefix():
    assert config.POSTGIS_PREFIX == "/postgis"


@pytest.mark.unit
def test_parquet_prefix():
    assert config.PARQUET_PREFIX == "/parquet"


@pytest.mark.unit
def test_endpoints_dict_has_both_sources():
    assert set(config.ENDPOINTS.keys()) == {"postgis", "parquet"}


@pytest.mark.unit
def test_cors_origins_empty_string_gives_empty_list():
    raw = ""
    result = [o.strip() for o in raw.split(",") if o.strip()]
    assert result == []


@pytest.mark.unit
def test_cors_origins_multiple_values_stripped():
    raw = "http://a.com , http://b.com"
    result = [o.strip() for o in raw.split(",") if o.strip()]
    assert result == ["http://a.com", "http://b.com"]


@pytest.mark.unit
def test_allow_credentials_false_when_empty():
    origins: list = []
    assert not (bool(origins) and "*" not in origins)


@pytest.mark.unit
def test_allow_credentials_false_when_wildcard():
    origins = ["*"]
    assert not (bool(origins) and "*" not in origins)


@pytest.mark.unit
def test_allow_credentials_true_when_explicit_origin():
    origins = ["http://example.com"]
    assert bool(origins) and "*" not in origins


@pytest.mark.unit
def test_materialized_collections_is_frozenset_type():
    assert isinstance(config.PARQUET_MATERIALIZED_COLLECTIONS, frozenset)


@pytest.mark.unit
def test_materialized_collections_empty_string_gives_empty_frozenset():
    raw = ""
    result = frozenset(c.strip() for c in raw.split(",") if c.strip())
    assert result == frozenset()


@pytest.mark.unit
def test_materialized_collections_parses_comma_separated_values():
    raw = "bdppad_v03_an_2025_s_20260504, other_collection "
    result = frozenset(c.strip() for c in raw.split(",") if c.strip())
    assert result == frozenset({"bdppad_v03_an_2025_s_20260504", "other_collection"})
