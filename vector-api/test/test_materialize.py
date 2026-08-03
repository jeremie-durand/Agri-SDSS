"""Unit tests for vector_api.materialize."""

import duckdb
import geopandas as gpd
import pytest
from shapely.geometry import Point
from vector_api.materialize import MATERIALIZED_TABLE_NAME, materialize_collection

pytestmark = pytest.mark.unit


@pytest.fixture
def sample_geoparquet_path(tmp_path):
    """GeoParquet file with 3 Point features and an explicit CRS.

    The explicit CRS matters: DuckDB's spatial extension reads it back as a
    CRS-annotated GEOMETRY('EPSG:4326') type -- the same shape RTree indexing
    rejects on the real BDPPAD data (see materialize.py docstring).
    """
    data = {
        "gid": [1, 2, 3],
        "name": ["Feature A", "Feature B", "Feature C"],
        "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6), Point(-73.7, 45.7)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    path = tmp_path / "sample.parquet"
    gdf.to_parquet(path)
    return path


def test_materialize_collection_returns_row_count(tmp_path, sample_geoparquet_path):
    db_path = tmp_path / "sample.duckdb"
    row_count = materialize_collection(sample_geoparquet_path, db_path)
    assert row_count == 3


def test_materialize_collection_builds_queryable_rtree_index(
    tmp_path, sample_geoparquet_path
):
    db_path = tmp_path / "sample.duckdb"
    materialize_collection(sample_geoparquet_path, db_path)

    conn = duckdb.connect(database=str(db_path), read_only=True)
    conn.execute("INSTALL spatial")
    conn.execute("LOAD spatial")
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {MATERIALIZED_TABLE_NAME} "
            "WHERE ST_Intersects(geometry, "
            "ST_MakeEnvelope(-73.65, 45.55, -73.55, 45.65))"
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_materialize_collection_casts_away_crs_annotation(
    tmp_path, sample_geoparquet_path
):
    """Regression test: CRS-annotated GEOMETRY('EPSG:4326') cannot be RTree-indexed.

    materialize_collection must CAST the geometry column to plain GEOMETRY
    before indexing, or CREATE INDEX ... USING RTREE raises a BinderException.
    """
    db_path = tmp_path / "sample.duckdb"
    materialize_collection(sample_geoparquet_path, db_path)

    conn = duckdb.connect(database=str(db_path), read_only=True)
    conn.execute("INSTALL spatial")
    conn.execute("LOAD spatial")
    try:
        column_type = conn.execute(
            f"SELECT typeof(geometry) FROM {MATERIALIZED_TABLE_NAME} LIMIT 1"
        ).fetchone()[0]
        assert column_type == "GEOMETRY"
    finally:
        conn.close()


def test_materialize_collection_is_idempotent(tmp_path, sample_geoparquet_path):
    db_path = tmp_path / "sample.duckdb"
    materialize_collection(sample_geoparquet_path, db_path)
    row_count = materialize_collection(sample_geoparquet_path, db_path)
    assert row_count == 3
