"""Unit tests for the DuckDB memory_limit applied to every manager connection."""

from pathlib import Path

import duckdb
import geopandas as gpd
import pytest
from shapely.geometry import Point
from vector_api.duckdb_manager import DEFAULT_MEMORY_LIMIT, DuckDBManager
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit

COLLECTION_ID: str = "test_collection"


def _expected_setting(memory_limit: str) -> str:
    """Return memory_limit as DuckDB reports it once normalized."""
    with duckdb.connect(config={"memory_limit": memory_limit}) as conn:
        return conn.execute("SELECT current_setting('memory_limit')").fetchone()[0]


def _setting(conn: duckdb.DuckDBPyConnection) -> str:
    return conn.execute("SELECT current_setting('memory_limit')").fetchone()[0]


@pytest.fixture
def materialized_dir(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"gid": [1, 2], "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)]},
        crs="EPSG:4326",
    )
    parquet_path = tmp_path / f"{COLLECTION_ID}.parquet"
    gdf.to_parquet(parquet_path)
    materialize_collection(parquet_path, tmp_path / f"{COLLECTION_ID}.duckdb")
    return tmp_path


def test_memory_limit_argument_applies_to_both_connection_kinds(
    materialized_dir: Path,
) -> None:
    manager = DuckDBManager(data_dir=str(materialized_dir), memory_limit="256MiB")
    try:
        materialized_conn, _ = manager._get_materialized_connection(COLLECTION_ID)
        expected = _expected_setting("256MiB")
        assert _setting(manager.conn) == expected
        assert _setting(materialized_conn) == expected
    finally:
        manager.close()


def test_memory_limit_defaults_without_argument_or_env(
    materialized_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DUCKDB_MEMORY_LIMIT", raising=False)
    manager = DuckDBManager(data_dir=str(materialized_dir))
    try:
        materialized_conn, _ = manager._get_materialized_connection(COLLECTION_ID)
        expected = _expected_setting(DEFAULT_MEMORY_LIMIT)
        assert manager.memory_limit == DEFAULT_MEMORY_LIMIT
        assert _setting(manager.conn) == expected
        assert _setting(materialized_conn) == expected
    finally:
        manager.close()


def test_memory_limit_read_from_env_without_argument(
    materialized_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "300MiB")
    manager = DuckDBManager(data_dir=str(materialized_dir))
    try:
        materialized_conn, _ = manager._get_materialized_connection(COLLECTION_ID)
        expected = _expected_setting("300MiB")
        assert _setting(manager.conn) == expected
        assert _setting(materialized_conn) == expected
    finally:
        manager.close()


def test_memory_limit_argument_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "300MiB")
    manager = DuckDBManager(data_dir=str(tmp_path), memory_limit="200MiB")
    try:
        assert _setting(manager.conn) == _expected_setting("200MiB")
    finally:
        manager.close()
