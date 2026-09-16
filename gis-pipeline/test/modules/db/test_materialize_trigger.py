"""Unit tests for gis_pipeline.modules.db.materialize_trigger."""

import geopandas as gpd
import pytest
import responses
from gis_pipeline.core.config import Config
from gis_pipeline.modules.db.materialize_trigger import trigger_materialize_and_notify
from shapely.geometry import Point


@pytest.fixture(autouse=True)
def patch_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gis_pipeline.modules.db.materialize_trigger.Config.DUCKDB_DATA_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "gis_pipeline.modules.db.materialize_trigger.Config.VECTOR_API_URL",
        "http://vector-api:8083",
    )


@pytest.fixture
def written_parquet(tmp_path):
    """Simulates save_gdf_to_geoparquet() having already written this file."""
    data = {
        "gid": [1, 2],
        "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    path = tmp_path / "test_table.parquet"
    gdf.to_parquet(path)
    return path


@responses.activate
def test_trigger_builds_index_and_notifies_vector_api(tmp_path, written_parquet):
    responses.add(
        responses.POST,
        "http://vector-api:8083/parquet/collections/test_table/invalidate",
        json={"collection_id": "test_table", "invalidated": True},
        status=200,
    )

    trigger_materialize_and_notify("test_table")

    assert (tmp_path / "test_table.duckdb").exists()
    assert not (tmp_path / "test_table.duckdb.new").exists()
    assert len(responses.calls) == 1


@responses.activate
def test_trigger_is_non_fatal_when_vector_api_unreachable(tmp_path, written_parquet):
    responses.add(
        responses.POST,
        "http://vector-api:8083/parquet/collections/test_table/invalidate",
        body=ConnectionError("connection refused"),
    )

    trigger_materialize_and_notify("test_table")  # must not raise

    assert (tmp_path / "test_table.duckdb").exists()


def test_trigger_is_non_fatal_when_parquet_missing(tmp_path):
    trigger_materialize_and_notify("does_not_exist")  # must not raise
    assert not (tmp_path / "does_not_exist.duckdb").exists()


def test_trigger_is_non_fatal_when_materialize_raises(tmp_path, monkeypatch):
    (tmp_path / "broken_table.parquet").write_text("not a real parquet file")

    trigger_materialize_and_notify("broken_table")  # must not raise

    assert not (tmp_path / "broken_table.duckdb").exists()


def test_trigger_skips_when_vector_api_url_not_configured(
    tmp_path, written_parquet, monkeypatch
):
    monkeypatch.setattr(
        "gis_pipeline.modules.db.materialize_trigger.Config.VECTOR_API_URL", None
    )

    trigger_materialize_and_notify("test_table")  # must not raise

    assert not (tmp_path / "test_table.duckdb").exists()


@responses.activate
def test_trigger_recovers_from_stale_new_file_on_next_call(tmp_path, written_parquet):
    (tmp_path / "test_table.duckdb.new").write_text("stale leftover from a crashed run")
    responses.add(
        responses.POST,
        "http://vector-api:8083/parquet/collections/test_table/invalidate",
        json={"collection_id": "test_table", "invalidated": True},
        status=200,
    )

    trigger_materialize_and_notify("test_table")

    assert (tmp_path / "test_table.duckdb").exists()
    assert not (tmp_path / "test_table.duckdb.new").exists()
