"""Unit tests for DuckDBManager's materialized-collection query routing."""

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
    result = manager.query_items("test_collection")
    manager.close()

    assert result["numberMatched"] == 3
    assert result["numberReturned"] == 3


def test_query_items_bbox_matches_between_materialized_and_raw_parquet(
    tmp_path, sample_geoparquet_path
):
    """numberMatched must be identical whether or not a .duckdb file exists."""
    bbox = (-73.65, 45.55, -73.55, 45.65)

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "test_collection.parquet").write_bytes(
        sample_geoparquet_path.read_bytes()
    )

    raw_manager = DuckDBManager(data_dir=str(raw_dir))
    raw_result = raw_manager.query_items("test_collection", bbox=bbox)
    raw_manager.close()

    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")
    manager = DuckDBManager(data_dir=str(tmp_path))
    materialized_result = manager.query_items("test_collection", bbox=bbox)
    manager.close()

    assert materialized_result["numberMatched"] == raw_result["numberMatched"] == 1


def test_query_items_falls_back_to_parquet_when_duckdb_file_missing(
    tmp_path, sample_geoparquet_path
):
    """No .duckdb file yet -> falls back to read_parquet(), same result."""
    manager = DuckDBManager(data_dir=str(tmp_path))
    result = manager.query_items("test_collection")
    manager.close()

    assert result["numberMatched"] == 3


def test_get_item_by_id_uses_materialized_table_when_available(
    tmp_path, sample_geoparquet_path
):
    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")

    manager = DuckDBManager(data_dir=str(tmp_path))
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
    feature = manager.get_item_by_id("no_id_collection", 2)
    manager.close()

    assert feature is not None
    assert feature["properties"]["name"] == "Feature B"


def test_materialized_connection_open_failure_is_cached_not_retried(
    tmp_path, sample_geoparquet_path
):
    """A .duckdb file that fails to open (corrupt/invalid) is remembered in
    _failed_materialized so it isn't retried on every subsequent request."""
    bad_db_path = tmp_path / "test_collection.duckdb"
    bad_db_path.write_text("not a real duckdb file")

    manager = DuckDBManager(data_dir=str(tmp_path))

    first_result = manager.query_items("test_collection")
    assert "test_collection" in manager._failed_materialized

    second_result = manager.query_items("test_collection")
    manager.close()

    assert first_result["numberMatched"] == second_result["numberMatched"] == 3


def test_invalidate_materialized_drops_cached_connection(
    tmp_path, sample_geoparquet_path
):
    materialize_collection(sample_geoparquet_path, tmp_path / "test_collection.duckdb")
    manager = DuckDBManager(data_dir=str(tmp_path))
    manager.query_items("test_collection")
    assert "test_collection" in manager._materialized_conns

    invalidated = manager.invalidate_materialized("test_collection")
    manager.close()

    assert invalidated is True


def test_invalidate_materialized_returns_false_when_nothing_cached(tmp_path):
    manager = DuckDBManager(data_dir=str(tmp_path))
    invalidated = manager.invalidate_materialized("never_queried_collection")
    manager.close()

    assert invalidated is False


def test_invalidate_materialized_clears_failed_cache_for_retry(
    tmp_path, sample_geoparquet_path
):
    """After invalidate, a previously-failed collection gets a fresh attempt
    to open -- e.g. because the file was just rebuilt correctly."""
    db_path = tmp_path / "test_collection.duckdb"
    db_path.write_text("not a real duckdb file")

    manager = DuckDBManager(data_dir=str(tmp_path))
    manager.query_items("test_collection")
    assert "test_collection" in manager._failed_materialized

    manager.invalidate_materialized("test_collection")
    assert "test_collection" not in manager._failed_materialized

    db_path.unlink()
    materialize_collection(sample_geoparquet_path, db_path)
    result = manager.query_items("test_collection")

    assert "test_collection" in manager._materialized_conns
    manager.close()

    assert result["numberMatched"] == 3
