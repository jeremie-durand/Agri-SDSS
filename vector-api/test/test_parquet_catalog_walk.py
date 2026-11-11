"""Every collection the Parquet catalog lists must serve its items page.

Each case writes one GeoParquet file with a given column type into its own
data dir, then walks /parquet/collections and opens items?limit=1 for every
listed id. The xfail cases are known bugs; strict=True turns the run red once
a fix lands and the marker has to go.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection
from vector_api.parquet_router import router as parquet_router


def _plain_columns() -> dict[str, Any]:
    return {}


def _timestamptz_columns() -> dict[str, Any]:
    return {
        "update_time": pd.to_datetime(
            ["2024-01-01T12:00:00Z", "2024-06-01T08:30:00Z"], utc=True
        )
    }


def _blob_columns() -> dict[str, Any]:
    return {"pageblob": [b"\xaa\x00\x01", b"\xbd\xff"]}


COLUMN_CASES: list[Any] = [
    pytest.param(_plain_columns, id="plain"),
    pytest.param(_timestamptz_columns, id="timestamptz"),
    pytest.param(
        _blob_columns,
        id="blob",
        marks=pytest.mark.xfail(
            strict=True,
            reason="#289: BLOB columns answer 500 (UnicodeDecodeError)",
        ),
    ),
]


@pytest.fixture
def catalog_client(
    temp_parquet_dir: Path, request: pytest.FixtureRequest
) -> Iterator[TestClient]:
    """Parquet-router client over a data dir holding one collection of the case.

    Not built on sample_geoparquet / parquet_app_client: their schema is fixed,
    and each case here needs its own column types.
    """
    extra_columns: Callable[[], dict[str, Any]] = request.param
    gdf = gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "name": ["A", "B"],
            **extra_columns(),
            "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
        },
        crs="EPSG:4326",
    )
    gdf.to_parquet(temp_parquet_dir / "walk_case.parquet")

    manager = DuckDBManager(data_dir=str(temp_parquet_dir))
    app = FastAPI()
    app.include_router(parquet_router)
    with patch("vector_api.parquet_router.get_shared_manager", return_value=manager):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    manager.close()


@pytest.mark.integration
@pytest.mark.parametrize("catalog_client", COLUMN_CASES, indirect=True)
def test_every_listed_collection_serves_items(catalog_client: TestClient) -> None:
    resp = catalog_client.get("/parquet/collections")
    assert resp.status_code == 200
    collection_ids = [c["id"] for c in resp.json()["collections"]]
    assert collection_ids

    failures: list[str] = []
    for collection_id in collection_ids:
        items = catalog_client.get(
            f"/parquet/collections/{collection_id}/items?limit=1"
        )
        if items.status_code != 200 or items.json().get("type") != "FeatureCollection":
            failures.append(f"{collection_id}: {items.status_code}")
    assert failures == []


WALK_COLLECTIONS: int = 6
WALK_MAX_OPEN: int = 2


@pytest.mark.integration
def test_catalog_walk_keeps_open_materialized_collections_under_the_cap(
    temp_parquet_dir: Path,
) -> None:
    """#288: walking more collections than the cap must not keep them all open.

    Every materialized connection is its own DuckDB instance with its own
    block cache, so an unbounded cache grows until the container is
    OOM-killed. The walk asserts the cap after every request, and that
    connections dropped from the cache were really closed.
    """
    for index in range(WALK_COLLECTIONS):
        gdf = gpd.GeoDataFrame(
            {"gid": [1, 2], "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)]},
            crs="EPSG:4326",
        )
        parquet_path = temp_parquet_dir / f"walk_{index}.parquet"
        gdf.to_parquet(parquet_path)
        materialize_collection(parquet_path, temp_parquet_dir / f"walk_{index}.duckdb")

    manager = DuckDBManager(data_dir=str(temp_parquet_dir), max_open=WALK_MAX_OPEN)
    app = FastAPI()
    app.include_router(parquet_router)
    seen: dict[int, duckdb.DuckDBPyConnection] = {}
    try:
        with patch(
            "vector_api.parquet_router.get_shared_manager", return_value=manager
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                listed = client.get("/parquet/collections").json()["collections"]
                assert len(listed) == WALK_COLLECTIONS
                for collection in listed:
                    resp = client.get(
                        f"/parquet/collections/{collection['id']}/items?limit=1"
                    )
                    assert resp.status_code == 200, collection["id"]
                    open_now = manager._materialized_conns
                    assert len(open_now) <= WALK_MAX_OPEN, sorted(open_now)
                    for conn, _ in open_now.values():
                        seen[id(conn)] = conn

        still_open = {id(conn) for conn, _ in manager._materialized_conns.values()}
        dropped = [conn for key, conn in seen.items() if key not in still_open]
        assert len(dropped) == WALK_COLLECTIONS - WALK_MAX_OPEN
        for conn in dropped:
            with pytest.raises(duckdb.ConnectionException):
                conn.execute("SELECT 1")
    finally:
        manager.close()
