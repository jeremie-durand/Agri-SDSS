"""Unit tests for DuckDBManager's materialized-collection query routing."""

from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit


@pytest.fixture
def sample_geoparquet_path(tmp_path):
    data = {
        "gid": [1, 2, 3],
        "name": ["Feature A", "Feature B", "Feature C"],
        "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6), Point(-73.7, 45.7)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    path = tmp_path / "test_collection.parquet"
    gdf.to_parquet(path)
    return path


@pytest.fixture
def sample_geoparquet_no_id_path(tmp_path):
    data = {
        "name": ["Feature A", "Feature B", "Feature C"],
        "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6), Point(-73.7, 45.7)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    path = tmp_path / "no_id_collection.parquet"
    gdf.to_parquet(path)
    return path


def test_query_items_uses_materialized_table_when_available(
    tmp_path, sample_geoparquet_path
):
    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")

    manager = DuckDBManager(data_dir=str(tmp_path))
    with patch(
        "vector_api.duckdb_manager.PARQUET_MATERIALIZED_COLLECTIONS",
        frozenset({"test_collection"}),
    ):
        result = manager.query_items("test_collection")
    manager.close()

    assert result["numberMatched"] == 3
    assert result["numberReturned"] == 3


def test_query_items_bbox_matches_between_materialized_and_raw_parquet(
    tmp_path, sample_geoparquet_path
):
    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")
    bbox = (-73.65, 45.55, -73.55, 45.65)

    manager = DuckDBManager(data_dir=str(tmp_path))
    raw_result = manager.query_items("test_collection", bbox=bbox)

    with patch(
        "vector_api.duckdb_manager.PARQUET_MATERIALIZED_COLLECTIONS",
        frozenset({"test_collection"}),
    ):
        materialized_result = manager.query_items("test_collection", bbox=bbox)
    manager.close()

    assert materialized_result["numberMatched"] == raw_result["numberMatched"] == 1


def test_query_items_falls_back_to_parquet_when_duckdb_file_missing(
    tmp_path, sample_geoparquet_path
):
    """Collection listed as materialized but .duckdb not built yet -> fallback."""
    manager = DuckDBManager(data_dir=str(tmp_path))
    with patch(
        "vector_api.duckdb_manager.PARQUET_MATERIALIZED_COLLECTIONS",
        frozenset({"test_collection"}),
    ):
        result = manager.query_items("test_collection")
    manager.close()

    assert result["numberMatched"] == 3


def test_get_item_by_id_uses_materialized_table_when_available(
    tmp_path, sample_geoparquet_path
):
    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")

    manager = DuckDBManager(data_dir=str(tmp_path))
    with patch(
        "vector_api.duckdb_manager.PARQUET_MATERIALIZED_COLLECTIONS",
        frozenset({"test_collection"}),
    ):
        feature = manager.get_item_by_id("test_collection", 2)
    manager.close()

    assert feature is not None
    assert feature["properties"]["gid"] == 2


def test_get_item_by_id_row_offset_fallback_uses_materialized_table(
    tmp_path, sample_geoparquet_no_id_path
):
    """BDPPAD has no id column -- get_item_by_id falls back to row-offset
    lookup (LIMIT 1 OFFSET n-1). This must work identically against the
    materialized table."""
    materialize_collection(
        sample_geoparquet_no_id_path, tmp_path / "no_id_collection.duckdb"
    )

    manager = DuckDBManager(data_dir=str(tmp_path))
    with patch(
        "vector_api.duckdb_manager.PARQUET_MATERIALIZED_COLLECTIONS",
        frozenset({"no_id_collection"}),
    ):
        feature = manager.get_item_by_id("no_id_collection", 2)
    manager.close()

    assert feature is not None
    assert feature["properties"]["name"] == "Feature B"
