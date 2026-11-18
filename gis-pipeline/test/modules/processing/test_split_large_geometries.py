"""Polygonal features above SPLIT_MAX_VERTICES are split without loss (#292).

A drainage polygon of 1.4 million vertices made one vector-api request use
more memory than its container has. gis-pipeline now cuts such a feature into
pieces of at most SPLIT_MAX_VERTICES vertices, keeping every source vertex and
the source area, and records where each piece came from.
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from gis_pipeline.modules.processing.geoprocessing import GeoprocessingVector
from gis_pipeline.services.mapping import SPLIT_MAX_VERTICES
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

SMALL_MAX: int = 1_000
TABLE: str = "split_case"


def _disc(x: float, y: float, quad_segs: int, radius: float = 1.0) -> Polygon:
    """Return a polygon of exactly 4 * quad_segs + 1 vertices."""
    return Point(x, y).buffer(radius, quad_segs=quad_segs)


def _ring(vertices: int) -> Polygon:
    """Return a polygon of exactly `vertices` points, closing one included."""
    angles = np.linspace(0, 2 * np.pi, vertices - 1, endpoint=False)
    points = np.column_stack([np.cos(angles), np.sin(angles)])
    return Polygon(np.vstack([points, points[:1]]))


def _frame(geometries: list, **columns: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({**columns, "geometry": geometries}, crs="EPSG:4326")


def _split(
    gdf: gpd.GeoDataFrame, split: bool = True
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    processor = GeoprocessingVector(gdf=gdf, target_crs="4326", collection_id="c")
    with capture_logs() as logs:
        result = processor.split_large_geometries_gdf(TABLE, split=split)
    assert result is processor.gdf
    return result, logs


def _coordinates(geometries: list) -> set[tuple[float, float]]:
    coords = np.concatenate([shapely.get_coordinates(g) for g in geometries])
    return set(map(tuple, np.round(coords, 12)))


@pytest.fixture
def small_threshold(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(
        "gis_pipeline.modules.processing.geoprocessing.SPLIT_MAX_VERTICES", SMALL_MAX
    )
    return SMALL_MAX


def test_feature_above_threshold_is_split_without_loss(small_threshold: int) -> None:
    source = _disc(0, 0, quad_segs=750)
    assert shapely.get_num_coordinates(source) == 3001

    result, _ = _split(_frame([source], gid=[1]))

    pieces = list(result.geometry)
    assert len(pieces) > 1
    assert all(shapely.get_num_coordinates(p) <= small_threshold for p in pieces)
    assert all(p.is_valid and p.geom_type == "Polygon" for p in pieces)
    union = shapely.union_all(pieces)
    assert shapely.symmetric_difference(union, source).area <= 1e-9 * source.area
    assert sum(p.area for p in pieces) == pytest.approx(source.area, rel=1e-9)
    assert _coordinates([source]) <= _coordinates(pieces)


def test_real_threshold_splits_a_quarter_million_vertex_polygon() -> None:
    source = _ring(250_001)
    assert shapely.get_num_coordinates(source) == 250_001

    result, logs = _split(_frame([source], gid=[1]))

    counts = [shapely.get_num_coordinates(p) for p in result.geometry]
    assert len(counts) >= 3
    assert max(counts) <= SPLIT_MAX_VERTICES
    split_logs = [log for log in logs if log["event"] == "feature_split"]
    assert len(split_logs) == 1
    split_log = split_logs[0]
    assert split_log["table"] == TABLE
    assert split_log["source_gid"] == 1
    assert split_log["vertices"] == 250_001
    assert split_log["parts"] == len(counts)


def test_layer_below_threshold_is_unchanged(small_threshold: int) -> None:
    gdf = _frame([_disc(0, 0, 10), _disc(5, 5, 10)], gid=[7, 8], name=["a", "b"])
    expected = gdf.copy()

    result, logs = _split(gdf)

    pd.testing.assert_frame_equal(
        pd.DataFrame(result.drop(columns="geometry")),
        pd.DataFrame(expected.drop(columns="geometry")),
    )
    assert list(result.geometry) == list(expected.geometry)
    assert "split_part" not in result.columns
    assert logs == []


def test_pieces_never_cover_a_hole(small_threshold: int) -> None:
    hole = _disc(0, 0, quad_segs=100, radius=0.3)
    source = Polygon(_disc(0, 0, quad_segs=600).exterior.coords, [hole.exterior.coords])

    result, _ = _split(_frame([source], gid=[1]))

    assert len(result) > 1
    assert all(p.intersection(hole).area <= 1e-12 for p in result.geometry)
    assert sum(p.area for p in result.geometry) == pytest.approx(source.area)


def test_pieces_of_a_multipolygon_are_multipolygons(small_threshold: int) -> None:
    source = MultiPolygon([_disc(0, 0, 300), _disc(3, 0, 300)])

    result, _ = _split(_frame([source], gid=[1]))

    assert len(result) > 1
    assert all(p.geom_type == "MultiPolygon" for p in result.geometry)
    assert sum(p.area for p in result.geometry) == pytest.approx(source.area)


@pytest.mark.parametrize(
    ("gids", "expected_source_gids"),
    [([10, 20, 30], [10, 20, 30]), (None, [1, 2, 3])],
    ids=["source-gid", "no-gid"],
)
def test_pieces_keep_their_source_and_attributes(
    small_threshold: int, gids: list[int] | None, expected_source_gids: list[int]
) -> None:
    columns: dict[str, list] = {"name": ["first", "second", "third"]}
    if gids is not None:
        columns["gid"] = gids
    gdf = _frame([_disc(0, 0, 10), _disc(5, 0, 750), _disc(10, 0, 10)], **columns)

    result, _ = _split(gdf)

    assert "gid" not in result.columns
    assert isinstance(result.index, pd.RangeIndex) and result.index.start == 0
    first, third = expected_source_gids[0], expected_source_gids[2]
    second = expected_source_gids[1]
    pieces = result[result["split_source_gid"] == second]
    assert len(pieces) > 1
    assert list(pieces["split_part"]) == list(range(1, len(pieces) + 1))
    assert set(pieces["name"]) == {"second"}
    assert list(result["split_source_gid"]) == (
        [first] + [second] * len(pieces) + [third]
    )
    unsplit = result[result["split_source_gid"].isin([first, third])]
    assert list(unsplit["split_part"]) == [1, 1]
    assert list(unsplit["name"]) == ["first", "third"]


def test_column_conflict_leaves_the_layer_unsplit(small_threshold: int) -> None:
    gdf = _frame([_disc(0, 0, 750)], gid=[1], split_part=["mine"])

    result, logs = _split(gdf)

    assert len(result) == 1
    assert list(result["split_part"]) == ["mine"]
    assert [
        (log["event"], log["reason"]) for log in logs if log["log_level"] == "warning"
    ] == [("feature_not_split", "column_conflict")]


def test_chunk_is_logged_not_split(small_threshold: int) -> None:
    gdf = _frame([_disc(0, 0, 10), _disc(5, 0, 750)], gid=[1, 2])

    result, logs = _split(gdf, split=False)

    assert len(result) == 2
    assert "split_part" not in result.columns
    warning = next(log for log in logs if log["log_level"] == "warning")
    assert warning["event"] == "feature_not_split"
    assert warning["reason"] == "chunked"
    assert warning["table"] == TABLE
    assert warning["feature"] == 2
    assert warning["vertices"] == 3001


def test_long_line_is_not_split() -> None:
    line = LineString([(i * 1e-4, 0.0) for i in range(150_000)])

    result, logs = _split(_frame([line], gid=[1]))

    assert list(result.geometry) == [line]
    assert "split_part" not in result.columns
    assert logs == []


def test_empty_layer_is_unchanged(small_threshold: int) -> None:
    gdf = _frame([], gid=[])

    result, logs = _split(gdf)

    assert result.empty
    assert "split_part" not in result.columns
    assert logs == []


def test_null_geometry_is_kept_as_an_unsplit_row(small_threshold: int) -> None:
    gdf = _frame([None, _disc(0, 0, 750)], gid=[1, 2])

    result, _ = _split(gdf)

    nulls = result[result.geometry.isna()]
    assert list(nulls["split_source_gid"]) == [1]
    assert list(nulls["split_part"]) == [1]
    assert (result["split_source_gid"] == 2).sum() > 1


def test_depth_guard_keeps_an_oversized_piece_and_warns(
    small_threshold: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "gis_pipeline.modules.processing.geoprocessing.MAX_SPLIT_DEPTH", 1
    )
    source = _ring(5_001)

    result, logs = _split(_frame([source], gid=[1]))

    assert max(shapely.get_num_coordinates(p) for p in result.geometry) > (
        small_threshold
    )
    assert sum(p.area for p in result.geometry) == pytest.approx(source.area)
    warning = next(log for log in logs if log["event"] == "feature_split_incomplete")
    assert warning["table"] == TABLE
    assert warning["source_gid"] == 1
    assert warning["max_vertices"] == small_threshold


def test_invalid_pieces_are_repaired_and_unrepairable_ones_dropped(
    small_threshold: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    flat = Polygon([(0, 0), (1, 1), (2, 2), (0, 0)])
    assert not bowtie.is_valid and not flat.is_valid
    monkeypatch.setattr(
        "gis_pipeline.modules.processing.geoprocessing._halve",
        lambda geom, depth=0: [bowtie, flat],
    )

    result, _ = _split(_frame([_disc(0, 0, 750)], gid=[1]))

    assert len(result) == 2
    assert all(p.is_valid and p.geom_type == "Polygon" for p in result.geometry)
    assert sum(p.area for p in result.geometry) == pytest.approx(0.5)


def test_feature_whose_pieces_are_all_unrepairable_is_kept_whole(
    small_threshold: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    flat = Polygon([(0, 0), (1, 1), (2, 2), (0, 0)])
    monkeypatch.setattr(
        "gis_pipeline.modules.processing.geoprocessing._halve",
        lambda geom, depth=0: [flat],
    )
    source = _disc(0, 0, 750)

    result, logs = _split(_frame([source], gid=[1]))

    assert list(result.geometry) == [source]
    assert any(log["event"] == "feature_split_incomplete" for log in logs)
