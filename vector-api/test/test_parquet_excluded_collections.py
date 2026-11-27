"""Parquet collections hidden by TIPG_DB_EXCLUDE_TABLES are neither listed nor served."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import (
    DuckDBConfigError,
    DuckDBManager,
    excluded_parquet_collections,
)
from vector_api.parquet_router import router as parquet_router

pytestmark = pytest.mark.unit

PRIVATE_ID: str = "private_samples"


@pytest.fixture
def private_geoparquet(temp_parquet_dir: Path) -> Path:
    path = temp_parquet_dir / f"{PRIVATE_ID}.parquet"
    gpd.GeoDataFrame(
        {"gid": [1], "producer": ["Ferme A"], "geometry": [Point(-73.5, 45.5)]},
        crs="EPSG:4326",
    ).to_parquet(path)
    return path


@pytest.fixture
def client(
    temp_parquet_dir: Path, sample_geoparquet: Path, private_geoparquet: Path
) -> Iterator[TestClient]:
    manager = DuckDBManager(
        data_dir=str(temp_parquet_dir), excluded_collections=frozenset({PRIVATE_ID})
    )
    app = FastAPI()
    app.include_router(parquet_router)
    with patch("vector_api.parquet_router.get_shared_manager", return_value=manager):
        with TestClient(app) as test_client:
            yield test_client
    manager.close()


def test_schema_is_dropped_from_excluded_table_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TIPG_DB_EXCLUDE_TABLES", '["public.som_soil_samples", "geo.private_layer"]'
    )
    assert excluded_parquet_collections() == {"som_soil_samples", "private_layer"}


def test_nothing_is_excluded_without_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIPG_DB_EXCLUDE_TABLES", raising=False)
    assert excluded_parquet_collections() == frozenset()


@pytest.mark.parametrize(
    "value", ["public.som_soil_samples", "[1, 2]", "", '["som_soil_samples"]']
)
def test_invalid_setting_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TIPG_DB_EXCLUDE_TABLES", value)
    with pytest.raises(DuckDBConfigError, match="TIPG_DB_"):
        excluded_parquet_collections()


def test_manager_reads_the_setting_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIPG_DB_EXCLUDE_TABLES", f'["public.{PRIVATE_ID}"]')
    manager = DuckDBManager(data_dir=str(tmp_path))
    try:
        assert manager.excluded_collections == {PRIVATE_ID}
    finally:
        manager.close()


def test_excluded_file_has_no_path(
    temp_parquet_dir: Path, private_geoparquet: Path
) -> None:
    manager = DuckDBManager(
        data_dir=str(temp_parquet_dir), excluded_collections=frozenset({PRIVATE_ID})
    )
    try:
        assert private_geoparquet.exists()
        assert manager.get_parquet_path(PRIVATE_ID) is None
        assert PRIVATE_ID not in [c["id"] for c in manager.list_parquet_files()]
    finally:
        manager.close()


def test_listing_leaves_out_the_excluded_collection(client: TestClient) -> None:
    response = client.get("/parquet/collections")

    assert response.status_code == 200
    ids = [collection["id"] for collection in response.json()["collections"]]
    assert ids == ["test_collection"]


@pytest.mark.parametrize(
    "path",
    [
        f"/parquet/collections/{PRIVATE_ID}",
        f"/parquet/collections/{PRIVATE_ID}/items",
        f"/parquet/collections/{PRIVATE_ID}/items/1",
        f"/parquet/collections/{PRIVATE_ID}/queryables",
    ],
)
def test_excluded_collection_answers_like_a_missing_one(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "Ferme A" not in response.text


def test_other_collections_are_still_served(client: TestClient) -> None:
    response = client.get("/parquet/collections/test_collection/items")

    assert response.status_code == 200
    assert response.json()["numberReturned"] == 3
