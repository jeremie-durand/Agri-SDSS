"""Paging tests for DuckDBManager.query_items on raw and materialized sources."""

import json
import random
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import MATERIALIZED_TABLE_NAME, materialize_collection

pytestmark = pytest.mark.unit

COLLECTION_ID: str = "paging_collection"
FEATURE_COUNT: int = 50
PAGE_LIMIT: int = 7
BBOX: tuple[float, float, float, float] = (-73.999, 45.0, -73.7505, 45.5)

Bbox = tuple[float, float, float, float] | None

WIDE_ROW_COUNT: int = 6000
WIDE_MEMORY_LIMIT: str = "128MB"


def _square(minx: float, miny: float, size: float = 0.005) -> Polygon:
    return Polygon(
        [
            (minx, miny),
            (minx + size, miny),
            (minx + size, miny + size),
            (minx, miny + size),
            (minx, miny),
        ]
    )


def _write_collection(directory: Path, gdf: gpd.GeoDataFrame, materialized: bool) -> None:
    parquet_path = directory / f"{COLLECTION_ID}.parquet"
    gdf.to_parquet(parquet_path)
    if materialized:
        materialize_collection(parquet_path, directory / f"{COLLECTION_ID}.duckdb")


def _unique_id_gdf() -> gpd.GeoDataFrame:
    gids = list(range(1, FEATURE_COUNT + 1))
    random.Random(279).shuffle(gids)
    return gpd.GeoDataFrame(
        {
            "gid": gids,
            "name": [f"Feature {gid}" for gid in gids],
            "value": [gid * 1.5 for gid in gids],
            "geometry": [_square(-74.0 + gid * 0.01, 45.0) for gid in gids],
        },
        crs="EPSG:4326",
    )


def _duplicate_id_gdf() -> gpd.GeoDataFrame:
    gids = [index // 3 for index in range(30)]
    random.Random(287).shuffle(gids)
    return gpd.GeoDataFrame(
        {
            "gid": gids,
            "row_key": [f"row-{index}" for index in range(30)],
            "geometry": [_square(-74.0 + index * 0.01, 45.0) for index in range(30)],
        },
        crs="EPSG:4326",
    )


def _bbox_sql(manager: DuckDBManager, bbox: Bbox) -> str:
    if bbox is None:
        return ""
    geom = manager.escape_identifier("geometry")
    minx, miny, maxx, maxy = bbox
    return f"WHERE ST_Intersects({geom}, ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}))"


def _legacy_page(
    manager: DuckDBManager, limit: int, offset: int, bbox: Bbox
) -> list[dict[str, Any]]:
    """Run the single-statement query query_items used before #279."""
    materialized = manager._get_materialized_connection(COLLECTION_ID)
    if materialized:
        conn, lock = materialized
        from_sql = manager.escape_identifier(MATERIALIZED_TABLE_NAME)
    else:
        conn, lock = None, None
        from_sql = manager.parquet_source(COLLECTION_ID)
    query = f"""
        SELECT *, ST_AsGeoJSON("geometry") AS __geojson__
        FROM {from_sql}
        {_bbox_sql(manager, bbox)}
        ORDER BY "gid"
        LIMIT {limit} OFFSET {offset}
    """
    rows, columns = manager._fetchall(query, conn=conn, lock=lock)
    features = []
    for row in rows:
        row_dict = dict(zip(columns, row))
        geometry = json.loads(row_dict.pop("__geojson__"))
        row_dict.pop("geometry")
        features.append(
            {
                "type": "Feature",
                "id": row_dict["gid"],
                "geometry": geometry,
                "properties": row_dict,
            }
        )
    return features


def _walk(manager: DuckDBManager, limit: int) -> list[dict[str, Any]]:
    """Collect every page from offset 0, asserting each non-last page is full."""
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = manager.query_items(COLLECTION_ID, limit=limit, offset=offset)
        features.extend(page["features"])
        if offset + page["numberReturned"] >= page["numberMatched"]:
            assert len(features) == page["numberMatched"]
            return features
        assert page["numberReturned"] == limit
        offset += limit


@pytest.fixture(params=[False, True], ids=["raw", "materialized"])
def unique_id_manager(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[DuckDBManager]:
    _write_collection(tmp_path, _unique_id_gdf(), materialized=request.param)
    manager = DuckDBManager(data_dir=str(tmp_path))
    yield manager
    manager.close()


@pytest.fixture(params=[False, True], ids=["raw", "materialized"])
def duplicate_id_manager(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[DuckDBManager]:
    _write_collection(tmp_path, _duplicate_id_gdf(), materialized=request.param)
    manager = DuckDBManager(data_dir=str(tmp_path))
    yield manager
    manager.close()


@pytest.mark.parametrize("bbox", [None, BBOX], ids=["no-bbox", "bbox"])
@pytest.mark.parametrize("page", ["first", "middle", "last", "past-end"])
def test_query_items_matches_legacy_query(
    unique_id_manager: DuckDBManager, bbox: Bbox, page: str
) -> None:
    matched = unique_id_manager.query_items(COLLECTION_ID, limit=1, bbox=bbox)[
        "numberMatched"
    ]
    offsets = {
        "first": 0,
        "middle": (matched // PAGE_LIMIT // 2) * PAGE_LIMIT,
        "last": (matched - 1) // PAGE_LIMIT * PAGE_LIMIT,
        "past-end": matched,
    }
    offset = offsets[page]

    result = unique_id_manager.query_items(
        COLLECTION_ID, limit=PAGE_LIMIT, offset=offset, bbox=bbox
    )

    expected = _legacy_page(unique_id_manager, PAGE_LIMIT, offset, bbox)
    assert result["features"] == expected
    assert result["numberMatched"] == matched
    assert result["numberReturned"] == len(expected)
    if bbox is not None:
        assert 0 < matched < FEATURE_COUNT


@pytest.mark.parametrize("bbox", [None, BBOX], ids=["no-bbox", "bbox"])
def test_raw_and_materialized_pages_are_identical(tmp_path: Path, bbox: Bbox) -> None:
    raw_dir = tmp_path / "raw"
    materialized_dir = tmp_path / "materialized"
    raw_dir.mkdir()
    materialized_dir.mkdir()
    _write_collection(raw_dir, _unique_id_gdf(), materialized=False)
    _write_collection(materialized_dir, _unique_id_gdf(), materialized=True)
    raw = DuckDBManager(data_dir=str(raw_dir))
    materialized = DuckDBManager(data_dir=str(materialized_dir))
    try:
        for offset in range(0, FEATURE_COUNT + PAGE_LIMIT, PAGE_LIMIT):
            assert raw.query_items(
                COLLECTION_ID, limit=PAGE_LIMIT, offset=offset, bbox=bbox
            ) == materialized.query_items(
                COLLECTION_ID, limit=PAGE_LIMIT, offset=offset, bbox=bbox
            )
    finally:
        raw.close()
        materialized.close()


def test_walk_with_duplicate_ids_returns_each_row_once(
    duplicate_id_manager: DuckDBManager,
) -> None:
    features = _walk(duplicate_id_manager, limit=4)

    row_keys = [feature["properties"]["row_key"] for feature in features]
    gids = [feature["id"] for feature in features]
    assert sorted(row_keys) == sorted(f"row-{index}" for index in range(30))
    assert gids == sorted(gids)


def test_walk_with_duplicate_ids_is_repeatable(
    duplicate_id_manager: DuckDBManager,
) -> None:
    first = [f["properties"]["row_key"] for f in _walk(duplicate_id_manager, limit=4)]
    second = [f["properties"]["row_key"] for f in _walk(duplicate_id_manager, limit=4)]
    assert first == second


@pytest.mark.parametrize(
    ("materialized", "position_column"),
    [(False, "file_row_number"), (True, "rowid")],
    ids=["raw", "materialized"],
)
def test_colliding_position_column_falls_back_to_single_statement(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    materialized: bool,
    position_column: str,
) -> None:
    gdf = _unique_id_gdf()
    gdf[position_column] = [f"source-{gid}" for gid in gdf["gid"]]
    _write_collection(tmp_path, gdf, materialized=materialized)
    manager = DuckDBManager(data_dir=str(tmp_path))
    try:
        with caplog.at_level("WARNING", logger="vector_api.duckdb_manager"):
            result = manager.query_items(COLLECTION_ID, limit=PAGE_LIMIT, offset=14)
            manager.query_items(COLLECTION_ID, limit=PAGE_LIMIT, offset=21)
        expected = _legacy_page(manager, PAGE_LIMIT, 14, None)
    finally:
        manager.close()

    assert result["features"] == expected
    assert [f["id"] for f in result["features"]] == list(range(15, 22))
    assert result["features"][0]["properties"][position_column] == "source-15"
    assert caplog.text.count(f"has a column named {position_column}") == 1


@pytest.fixture(scope="module")
def wide_geometry_gdf() -> gpd.GeoDataFrame:
    """6000 polygons of 1000 vertices: the old full-row sort needs over 128MB.

    The counter-check in the test below relies on DuckDB not late-materializing
    a deep top-N by itself. If a DuckDB upgrade makes it fail with DID NOT
    RAISE, grow this fixture or drop the counter-check; the new query is the fix.
    """
    return gpd.GeoDataFrame(
        {
            "gid": list(range(WIDE_ROW_COUNT, 0, -1)),
            "geometry": [
                Point(-73.0 + index * 1e-4, 45.0).buffer(0.01, quad_segs=250)
                for index in range(WIDE_ROW_COUNT)
            ],
        },
        crs="EPSG:4326",
    )


@pytest.mark.parametrize("materialized", [False, True], ids=["raw", "materialized"])
def test_deep_offset_on_wide_geometries_fits_small_memory_limit(
    tmp_path: Path, wide_geometry_gdf: gpd.GeoDataFrame, materialized: bool
) -> None:
    _write_collection(tmp_path, wide_geometry_gdf, materialized=materialized)
    manager = DuckDBManager(data_dir=str(tmp_path), memory_limit=WIDE_MEMORY_LIMIT)
    offset = WIDE_ROW_COUNT - 10
    try:
        result = manager.query_items(COLLECTION_ID, limit=10, offset=offset)

        with pytest.raises(duckdb.OutOfMemoryException):
            _legacy_page(manager, 10, offset, None)
    finally:
        manager.close()

    assert result["numberMatched"] == WIDE_ROW_COUNT
    assert [f["id"] for f in result["features"]] == list(
        range(offset + 1, WIDE_ROW_COUNT + 1)
    )
    assert all(f["geometry"]["type"] == "Polygon" for f in result["features"])
