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

import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
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
    pytest.param(
        _timestamptz_columns,
        id="timestamptz",
        marks=pytest.mark.xfail(
            strict=True,
            reason="#287: timestamptz columns answer 500, pytz is missing",
        ),
    ),
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
