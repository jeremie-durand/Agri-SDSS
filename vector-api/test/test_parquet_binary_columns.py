"""Parquet collections with binary columns serve their items without them.

DuckDB returns BLOB values, and geometry values other than the served
geometry, as raw bytes, which the JSON rendering decoded as UTF-8: items and
items/{id} answered 500 (#289). Binary columns are left out of feature
properties and of the advertised queryables.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection
from vector_api.parquet_router import router as parquet_router

pytestmark = pytest.mark.integration

COLLECTION_ID: str = "blob_case"
PAGEBLOBS: list[bytes] = [b"\xaa\x00\x01", b"\xbd\xff"]
EXPECTED_PROPERTIES: dict[int, dict[str, Any]] = {
    1: {"gid": 1, "name": "A"},
    2: {"gid": 2, "name": "B"},
}
EXPECTED_COORDINATES: dict[int, list[float]] = {1: [-73.5, 45.5], 2: [-73.6, 45.6]}


def _write_collection(data_dir: Path, materialized: bool) -> None:
    gdf = gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "name": ["A", "B"],
            "pageblob": PAGEBLOBS,
            "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
        },
        crs="EPSG:4326",
    )
    parquet_path = data_dir / f"{COLLECTION_ID}.parquet"
    gdf.to_parquet(parquet_path)
    if materialized:
        materialize_collection(parquet_path, data_dir / f"{COLLECTION_ID}.duckdb")


@contextmanager
def _serve(data_dir: Path) -> Iterator[tuple[TestClient, DuckDBManager]]:
    manager = DuckDBManager(data_dir=str(data_dir))
    app = FastAPI()
    app.include_router(parquet_router)
    try:
        with patch(
            "vector_api.parquet_router.get_shared_manager", return_value=manager
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, manager
    finally:
        manager.close()


def _items(client: TestClient, collection_id: str) -> list[dict[str, Any]]:
    resp = client.get(f"/parquet/collections/{collection_id}/items?limit=10")
    assert resp.status_code == 200, resp.text
    return resp.json()["features"]


def _assert_backend(manager: DuckDBManager, materialized: bool) -> None:
    assert (COLLECTION_ID in manager._materialized_conns) is materialized


@pytest.fixture(params=[False, True], ids=["raw", "materialized"])
def blob_client(
    temp_parquet_dir: Path, request: pytest.FixtureRequest
) -> Iterator[TestClient]:
    _write_collection(temp_parquet_dir, materialized=request.param)
    with _serve(temp_parquet_dir) as (client, manager):
        yield client
        _assert_backend(manager, materialized=request.param)


def test_items_leave_out_blob_column(blob_client: TestClient) -> None:
    features = _items(blob_client, COLLECTION_ID)

    assert {f["properties"]["gid"]: f["properties"] for f in features} == (
        EXPECTED_PROPERTIES
    )
    assert {
        f["properties"]["gid"]: f["geometry"]["coordinates"] for f in features
    } == EXPECTED_COORDINATES


def test_single_item_leaves_out_blob_column(blob_client: TestClient) -> None:
    resp = blob_client.get(f"/parquet/collections/{COLLECTION_ID}/items/1")

    assert resp.status_code == 200, resp.text
    feature = resp.json()
    assert feature["type"] == "Feature"
    assert feature["properties"] == EXPECTED_PROPERTIES[1]
    assert feature["geometry"]["coordinates"] == EXPECTED_COORDINATES[1]


def test_raw_and_materialized_serve_the_same_features(temp_parquet_dir: Path) -> None:
    features: dict[str, list[dict[str, Any]]] = {}
    for backend, materialized in (("raw", False), ("materialized", True)):
        data_dir = temp_parquet_dir / backend
        data_dir.mkdir()
        _write_collection(data_dir, materialized=materialized)
        with _serve(data_dir) as (client, manager):
            features[backend] = _items(client, COLLECTION_ID)
            _assert_backend(manager, materialized=materialized)

    assert features["raw"] == features["materialized"]


def test_queryables_leave_out_blob_column(temp_parquet_dir: Path) -> None:
    _write_collection(temp_parquet_dir, materialized=False)

    with _serve(temp_parquet_dir) as (client, _):
        collection = client.get(f"/parquet/collections/{COLLECTION_ID}")
        queryables = client.get(f"/parquet/collections/{COLLECTION_ID}/queryables")

    assert collection.status_code == 200, collection.text
    assert queryables.status_code == 200, queryables.text
    assert [q["name"] for q in collection.json()["queryables"]] == ["gid", "name"]
    assert list(queryables.json()["properties"]) == ["gid", "name"]


def test_table_without_geometry_serves_its_other_columns(
    temp_parquet_dir: Path,
) -> None:
    pd.DataFrame({"pagenumber": [1, 2], "pageblob": PAGEBLOBS}).to_parquet(
        temp_parquet_dir / "n_1_edesc.parquet"
    )

    with _serve(temp_parquet_dir) as (client, _):
        features = _items(client, "n_1_edesc")
        single = client.get("/parquet/collections/n_1_edesc/items/1")

    assert [(f["properties"], f["geometry"]) for f in features] == [
        ({"pagenumber": 1}, None),
        ({"pagenumber": 2}, None),
    ]
    assert single.status_code == 200, single.text
    assert single.json()["properties"] == {"pagenumber": 1}
    assert single.json()["geometry"] is None


def test_geometry_collection_without_id_column_leaves_out_blob(
    temp_parquet_dir: Path,
) -> None:
    gpd.GeoDataFrame(
        {
            "name": ["A", "B"],
            "pageblob": PAGEBLOBS,
            "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
        },
        crs="EPSG:4326",
    ).to_parquet(temp_parquet_dir / "no_id_case.parquet")

    with _serve(temp_parquet_dir) as (client, _):
        features = _items(client, "no_id_case")

    assert [
        (f["id"], f["properties"], f["geometry"]["coordinates"]) for f in features
    ] == [
        (1, {"name": "A"}, EXPECTED_COORDINATES[1]),
        (2, {"name": "B"}, EXPECTED_COORDINATES[2]),
    ]


def test_second_geometry_column_is_left_out(temp_parquet_dir: Path) -> None:
    gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "centroid": gpd.GeoSeries([Point(1, 1), Point(2, 2)], crs="EPSG:4326"),
            "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
        },
        crs="EPSG:4326",
    ).to_parquet(temp_parquet_dir / "two_geometries.parquet")

    with _serve(temp_parquet_dir) as (client, _):
        features = _items(client, "two_geometries")

    assert {f["properties"]["gid"]: f["properties"] for f in features} == {
        1: {"gid": 1},
        2: {"gid": 2},
    }
    assert {
        f["properties"]["gid"]: f["geometry"]["coordinates"] for f in features
    } == EXPECTED_COORDINATES
