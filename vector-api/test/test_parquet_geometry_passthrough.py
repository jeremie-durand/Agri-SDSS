"""Items and single items carry DuckDB's GeoJSON text without re-encoding it.

Parsing each geometry with ``json.loads`` and serializing it back made a
54 MiB polygon take the container past its 1 GiB limit (#292). The HTTP routes
now splice the text into the body; the JSON value of every response stays the
one the parsed path produced.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from shapely.geometry import MultiPolygon, Polygon
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection
from vector_api.parquet_router import router as parquet_router

pytestmark = pytest.mark.integration

COLLECTION_ID: str = "passthrough_case"
FLAT_COLLECTION_ID: str = "no_geometry_case"
GIDS: list[int] = [1, 2, 3]
FEATURE_KEYS: list[str] = ["type", "id", "geometry", "properties"]
COLLECTION_KEYS: list[str] = [
    "type",
    "features",
    "links",
    "numberMatched",
    "numberReturned",
]

_JSON_ADAPTER: TypeAdapter[Any] = TypeAdapter(Any)


def _write_collection(data_dir: Path, materialized: bool) -> None:
    square = Polygon([(-73.5, 45.5), (-73.4, 45.5), (-73.4, 45.6), (-73.5, 45.5)])
    pair = MultiPolygon(
        [
            Polygon([(-72.0, 46.0), (-71.9, 46.0), (-71.9, 46.1), (-72.0, 46.0)]),
            Polygon([(-71.0, 47.0), (-70.9, 47.0), (-70.9, 47.1), (-71.0, 47.0)]),
        ]
    )
    gdf = gpd.GeoDataFrame(
        {
            "gid": GIDS,
            "amount": [Decimal("12.50"), Decimal("-3.75"), Decimal("0.01")],
            "observed_on": [
                dt.date(2024, 5, 17),
                dt.date(2025, 1, 2),
                dt.date(2025, 6, 30),
            ],
            "geometry": [square, pair, None],
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


def _as_json(value: Any) -> Any:
    """Return value as the parsed-geometry path rendered it (Pydantic JSON mode)."""
    return _JSON_ADAPTER.dump_python(_JSON_ADAPTER.validate_python(value), mode="json")


@pytest.fixture(params=[False, True], ids=["raw", "materialized"])
def served(
    temp_parquet_dir: Path, request: pytest.FixtureRequest
) -> Iterator[tuple[TestClient, DuckDBManager]]:
    _write_collection(temp_parquet_dir, materialized=request.param)
    with _serve(temp_parquet_dir) as (client, manager):
        yield client, manager
        assert (COLLECTION_ID in manager._materialized_conns) is request.param


def test_items_value_matches_parsed_geometry(
    served: tuple[TestClient, DuckDBManager],
) -> None:
    client, manager = served
    expected = manager.query_items(collection_id=COLLECTION_ID, limit=10)

    resp = client.get(f"/parquet/collections/{COLLECTION_ID}/items?limit=10")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/json"
    body = resp.json()
    assert body["features"] == _as_json(expected["features"])
    assert body["numberMatched"] == expected["numberMatched"] == 3
    assert body["numberReturned"] == expected["numberReturned"] == 3
    assert [link["rel"] for link in body["links"]] == ["self", "collection"]
    assert body["features"][2]["geometry"] is None


@pytest.mark.parametrize("gid", GIDS)
def test_single_item_value_matches_parsed_geometry(
    served: tuple[TestClient, DuckDBManager], gid: int
) -> None:
    client, manager = served
    expected = manager.get_item_by_id(COLLECTION_ID, gid)

    resp = client.get(f"/parquet/collections/{COLLECTION_ID}/items/{gid}")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/json"
    body = resp.json()
    links = body.pop("links")
    assert body == _as_json(expected)
    assert [link["rel"] for link in links] == ["self", "collection"]


def test_key_order_is_unchanged(served: tuple[TestClient, DuckDBManager]) -> None:
    client, _ = served

    page = client.get(f"/parquet/collections/{COLLECTION_ID}/items?limit=10").json()
    item = client.get(f"/parquet/collections/{COLLECTION_ID}/items/2").json()

    assert list(page) == COLLECTION_KEYS
    assert all(list(feature) == FEATURE_KEYS for feature in page["features"])
    assert list(item) == [*FEATURE_KEYS, "links"]


def test_collection_without_geometry_serves_null_geometry(
    temp_parquet_dir: Path,
) -> None:
    pd.DataFrame({"gid": [1, 2], "name": ["A", "B"]}).to_parquet(
        temp_parquet_dir / f"{FLAT_COLLECTION_ID}.parquet"
    )

    with _serve(temp_parquet_dir) as (client, _):
        page = client.get(f"/parquet/collections/{FLAT_COLLECTION_ID}/items?limit=10")
        item = client.get(f"/parquet/collections/{FLAT_COLLECTION_ID}/items/1")

    assert page.status_code == 200, page.text
    assert item.status_code == 200, item.text
    assert [f["geometry"] for f in page.json()["features"]] == [None, None]
    assert item.json()["geometry"] is None
    assert item.json()["properties"] == {"gid": 1, "name": "A"}


def test_http_routes_do_not_parse_geometry(
    served: tuple[TestClient, DuckDBManager],
) -> None:
    """No json.loads runs while the routes render a geometry.

    The patch replaces loads on the stdlib json module itself, on purpose, so
    a re-parse in the router fails too. The schema is computed first so that
    only the request path runs under the patch.
    """
    client, manager = served
    manager.get_parquet_schema(COLLECTION_ID)

    with patch(
        "vector_api.duckdb_manager.json.loads",
        side_effect=AssertionError("geometry parsed on the HTTP path"),
    ):
        page = client.get(f"/parquet/collections/{COLLECTION_ID}/items?limit=10")
        item = client.get(f"/parquet/collections/{COLLECTION_ID}/items/1")

    assert page.status_code == 200, page.text
    assert item.status_code == 200, item.text
