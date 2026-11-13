"""A page's geometry stays within the vertex budget; a larger feature is refused.

`limit` used to count features whatever their geometry weighed, so one page
could take vector-api past its 1 GiB limit (#292). A page now holds the
leading features whose vertices fit the budget, its `next` link continues from
the first feature left out, and a feature that alone exceeds the budget answers
413.
"""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection
from vector_api.parquet_router import router as parquet_router

from agri_i18n.middleware import LocaleASGIMiddleware

pytestmark = pytest.mark.integration

BUDGET: int = 100
SMALL: int = 40
LARGE: int = 500
COLLECTION_ID: str = "budget_case"
BBOX_FIVE: str = "-74.0,44.9,-73.5,45.1"


def _polygon(index: int, vertices: int | None) -> Polygon | None:
    """Return a polygon whose ring holds exactly `vertices` points, closing one included."""
    if vertices is None:
        return None
    centre_x, centre_y = -73.95 + index * 0.1, 45.0
    points = [
        (
            centre_x + 0.01 * math.cos(2 * math.pi * k / (vertices - 1)),
            centre_y + 0.01 * math.sin(2 * math.pi * k / (vertices - 1)),
        )
        for k in range(vertices - 1)
    ]
    return Polygon([*points, points[0]])


def _write(
    data_dir: Path,
    vertex_counts: list[int | None],
    materialized: bool = False,
    collection_id: str = COLLECTION_ID,
) -> None:
    gdf = gpd.GeoDataFrame(
        {
            "gid": list(range(1, len(vertex_counts) + 1)),
            "geometry": [_polygon(i, n) for i, n in enumerate(vertex_counts)],
        },
        crs="EPSG:4326",
    )
    parquet_path = data_dir / f"{collection_id}.parquet"
    gdf.to_parquet(parquet_path)
    if materialized:
        materialize_collection(parquet_path, data_dir / f"{collection_id}.duckdb")


def _assert_vertex_counts(
    manager: DuckDBManager, expected: list[int | None], collection_id: str
) -> None:
    rows = manager.query_rows(
        "SELECT ST_NPoints(geometry) AS n FROM "
        f"{manager.parquet_source(collection_id)} ORDER BY gid"
    )
    assert [row["n"] for row in rows] == expected


@contextmanager
def _serve(data_dir: Path) -> Iterator[tuple[TestClient, DuckDBManager]]:
    manager = DuckDBManager(data_dir=str(data_dir), max_page_vertices=BUDGET)
    app = FastAPI()
    app.include_router(parquet_router)
    app.add_middleware(LocaleASGIMiddleware)
    try:
        with patch(
            "vector_api.parquet_router.get_shared_manager", return_value=manager
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, manager
    finally:
        manager.close()


@contextmanager
def _collection(
    data_dir: Path,
    vertex_counts: list[int | None],
    materialized: bool = False,
    collection_id: str = COLLECTION_ID,
) -> Iterator[tuple[TestClient, DuckDBManager]]:
    _write(data_dir, vertex_counts, materialized, collection_id)
    with _serve(data_dir) as (client, manager):
        _assert_vertex_counts(manager, vertex_counts, collection_id)
        yield client, manager
        assert (collection_id in manager._materialized_conns) is materialized


def _next_params(body: dict[str, Any]) -> dict[str, list[str]] | None:
    link = next((link for link in body["links"] if link["rel"] == "next"), None)
    return parse_qs(urlparse(link["href"]).query) if link else None


def _items(client: TestClient, query: str, **headers: str) -> Any:
    return client.get(
        f"/parquet/collections/{COLLECTION_ID}/items?{query}", headers=headers
    )


@pytest.fixture(params=[False, True], ids=["raw", "materialized"])
def materialized(request: pytest.FixtureRequest) -> bool:
    return request.param


def test_page_is_shortened_by_the_budget(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [SMALL] * 5, materialized) as (client, _):
        resp = _items(client, "limit=10")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [f["id"] for f in body["features"]] == [1, 2]
    assert body["numberReturned"] == 2
    assert body["numberMatched"] == 5
    assert _next_params(body) == {"limit": ["10"], "offset": ["2"]}


def test_page_that_fits_is_not_shortened(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [SMALL, SMALL], materialized) as (client, _):
        resp = _items(client, "limit=10")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["numberReturned"] == 2
    assert _next_params(body) is None


def test_shortened_page_with_bbox_keeps_bbox_in_next(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [SMALL] * 8, materialized) as (client, _):
        resp = _items(client, f"limit=10&bbox={BBOX_FIVE}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [f["id"] for f in body["features"]] == [1, 2]
    assert body["numberMatched"] == 5
    assert _next_params(body) == {
        "limit": ["10"],
        "bbox": [BBOX_FIVE],
        "offset": ["2"],
    }


def test_full_walk_across_shortened_pages(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    seen: list[int] = []
    with _collection(temp_parquet_dir, [SMALL] * 7, materialized) as (client, _):
        query = "limit=10&offset=0"
        while query:
            body = _items(client, query).json()
            seen += [f["id"] for f in body["features"]]
            params = _next_params(body)
            query = (
                f"limit={params['limit'][0]}&offset={params['offset'][0]}"
                if params
                else ""
            )

    assert seen == list(range(1, 8))


def test_null_geometries_count_as_zero(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    counts: list[int | None] = [SMALL, None, SMALL, None, SMALL]
    with _collection(temp_parquet_dir, counts, materialized) as (client, _):
        body = _items(client, "limit=10").json()

    assert [f["id"] for f in body["features"]] == [1, 2, 3, 4]
    assert _next_params(body) == {"limit": ["10"], "offset": ["4"]}


def test_next_link_of_a_full_page(temp_parquet_dir: Path, materialized: bool) -> None:
    with _collection(temp_parquet_dir, [4] * 50, materialized) as (client, _):
        body = _items(client, "offset=20&limit=10").json()

    assert body["numberReturned"] == 10
    assert _next_params(body) == {"limit": ["10"], "offset": ["30"]}


def test_both_backends_shorten_alike(temp_parquet_dir: Path) -> None:
    bodies: dict[bool, dict[str, Any]] = {}
    for materialized in (False, True):
        data_dir = temp_parquet_dir / str(materialized)
        data_dir.mkdir()
        with _collection(data_dir, [SMALL] * 5, materialized) as (client, _):
            bodies[materialized] = _items(client, "limit=10").json()

    assert bodies[False]["features"] == bodies[True]["features"]
    assert bodies[False]["numberMatched"] == bodies[True]["numberMatched"]
    assert bodies[False]["numberReturned"] == bodies[True]["numberReturned"]


def test_collection_without_geometry_is_never_shortened(
    temp_parquet_dir: Path,
) -> None:
    pd.DataFrame(
        {"gid": range(1, 21), "name": [f"n{i}" for i in range(20)]}
    ).to_parquet(temp_parquet_dir / f"{COLLECTION_ID}.parquet")
    with _serve(temp_parquet_dir) as (client, _):
        body = _items(client, "limit=10").json()

    assert body["numberReturned"] == 10


def test_oversized_first_feature_is_refused(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [LARGE, SMALL], materialized) as (client, _):
        refused = _items(client, "limit=10")
        listing = client.get("/parquet/collections")

    assert refused.status_code == 413, refused.text
    detail = refused.json()["detail"]
    assert COLLECTION_ID in detail
    assert str(LARGE) in detail
    assert str(BUDGET) in detail
    assert listing.status_code == 200


def test_oversized_feature_later_in_the_page(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [SMALL, LARGE], materialized) as (client, _):
        first = _items(client, "limit=10")
        params = _next_params(first.json())
        assert params is not None
        second = _items(
            client, f"limit={params['limit'][0]}&offset={params['offset'][0]}"
        )

    assert first.status_code == 200, first.text
    assert [f["id"] for f in first.json()["features"]] == [1]
    assert second.status_code == 413, second.text


def test_oversized_single_item_is_refused(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    with _collection(temp_parquet_dir, [SMALL, LARGE], materialized) as (client, _):
        small = client.get(f"/parquet/collections/{COLLECTION_ID}/items/1")
        large = client.get(f"/parquet/collections/{COLLECTION_ID}/items/2")

    assert small.status_code == 200, small.text
    assert large.status_code == 413, large.text
    assert str(LARGE) in large.json()["detail"]


def test_refused_detail_follows_request_locale(temp_parquet_dir: Path) -> None:
    with _collection(temp_parquet_dir, [LARGE]) as (client, _):
        english = _items(client, "limit=10", **{"Accept-Language": "en"})
        french = _items(client, "limit=10", **{"Accept-Language": "fr"})

    assert english.status_code == french.status_code == 413
    assert english.json()["detail"].startswith("Feature too large")
    assert french.json()["detail"] != english.json()["detail"]
    assert COLLECTION_ID in french.json()["detail"]


@pytest.mark.parametrize("materialized", [False, True], ids=["raw", "materialized"])
def test_single_statement_shape_is_shortened_too(
    temp_parquet_dir: Path, materialized: bool
) -> None:
    """A collection without an id column pages with one statement and row ids."""
    gdf = gpd.GeoDataFrame(
        {"geometry": [_polygon(i, SMALL) for i in range(5)]}, crs="EPSG:4326"
    )
    parquet_path = temp_parquet_dir / f"{COLLECTION_ID}.parquet"
    gdf.to_parquet(parquet_path)
    if materialized:
        materialize_collection(
            parquet_path, temp_parquet_dir / f"{COLLECTION_ID}.duckdb"
        )

    with _serve(temp_parquet_dir) as (client, manager):
        first = _items(client, "limit=10").json()
        second = _items(client, "limit=10&offset=2").json()
        assert (COLLECTION_ID in manager._materialized_conns) is materialized

    assert [f["id"] for f in first["features"]] == [1, 2]
    assert first["numberReturned"] == 2
    assert _next_params(first) == {"limit": ["10"], "offset": ["2"]}
    assert [f["id"] for f in second["features"]] == [3, 4]
