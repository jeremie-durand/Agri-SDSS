"""Parquet collections with a TIMESTAMP WITH TIME ZONE column serve their items.

DuckDB needs pytz to return timezone-aware timestamps as Python datetimes;
without it, items answered 500 and items/{id} 404 (#287). The values are
rendered as ISO 8601 strings in UTC, the session time zone of the container.
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

COLLECTION_ID: str = "timestamptz_case"
UPDATE_TIMES: pd.Series = pd.Series(
    pd.to_datetime(["2024-06-01T08:30:00-04:00", None], utc=True)
)
EXPECTED_UPDATE_TIMES: dict[int, str | None] = {1: "2024-06-01T12:30:00Z", 2: None}


def _write_collection(data_dir: Path, materialized: bool) -> None:
    gdf = gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "update_time": UPDATE_TIMES,
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
def timestamptz_client(
    temp_parquet_dir: Path, request: pytest.FixtureRequest
) -> Iterator[TestClient]:
    _write_collection(temp_parquet_dir, materialized=request.param)
    with _serve(temp_parquet_dir) as (client, manager):
        yield client
        _assert_backend(manager, materialized=request.param)


def test_items_render_timestamptz_as_utc_iso(timestamptz_client: TestClient) -> None:
    features = _items(timestamptz_client, COLLECTION_ID)

    assert {
        f["properties"]["gid"]: f["properties"]["update_time"] for f in features
    } == EXPECTED_UPDATE_TIMES


def test_single_item_renders_timestamptz_as_utc_iso(
    timestamptz_client: TestClient,
) -> None:
    resp = timestamptz_client.get(f"/parquet/collections/{COLLECTION_ID}/items/1")

    assert resp.status_code == 200, resp.text
    assert resp.json()["properties"]["update_time"] == EXPECTED_UPDATE_TIMES[1]


def test_raw_and_materialized_render_the_same_timestamps(
    temp_parquet_dir: Path,
) -> None:
    features: dict[str, list[dict[str, Any]]] = {}
    for backend, materialized in (("raw", False), ("materialized", True)):
        data_dir = temp_parquet_dir / backend
        data_dir.mkdir()
        _write_collection(data_dir, materialized=materialized)
        with _serve(data_dir) as (client, manager):
            features[backend] = _items(client, COLLECTION_ID)
            _assert_backend(manager, materialized=materialized)

    assert features["raw"] == features["materialized"]


def test_collection_without_geometry_serves_timestamptz(
    temp_parquet_dir: Path,
) -> None:
    pd.DataFrame({"id": [1, 2], "update_time": UPDATE_TIMES}).to_parquet(
        temp_parquet_dir / "layer_styles.parquet"
    )

    with _serve(temp_parquet_dir) as (client, _):
        resp = client.get("/parquet/collections/layer_styles/items?limit=1")

    assert resp.status_code == 200, resp.text
    properties = resp.json()["features"][0]["properties"]
    assert properties["update_time"] == EXPECTED_UPDATE_TIMES[1]


def test_naive_timestamp_is_rendered_without_offset(temp_parquet_dir: Path) -> None:
    gpd.GeoDataFrame(
        {
            "gid": [1],
            "observed_at": pd.to_datetime(["2024-06-01T08:30:00"]),
            "geometry": [Point(-73.5, 45.5)],
        },
        crs="EPSG:4326",
    ).to_parquet(temp_parquet_dir / "naive_case.parquet")

    with _serve(temp_parquet_dir) as (client, _):
        features = _items(client, "naive_case")

    assert features[0]["properties"]["observed_at"] == "2024-06-01T08:30:00"
