"""
Tests for location_utils.py shared location-resolution utilities.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (psycopg DB)
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from processes.backend_utils import LocationType
from processes.location_utils import (
    calc_bbox_from_geojson,
    get_geometry_from_db,
    resolve_location,
)
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_POLYGON_QC = {
    "type": "Polygon",
    "coordinates": [
        [
            [-71.5, 45.5],
            [-71.4, 45.5],
            [-71.4, 45.6],
            [-71.5, 45.6],
            [-71.5, 45.5],
        ]
    ],
}


@pytest.fixture
def mock_db_connection():
    """Mock psycopg connection returning a valid geometry JSON string."""
    json_string = json.dumps(_POLYGON_QC)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json_string,)
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ---------------------------------------------------------------------------
# TestCalcBboxFromGeoJSON
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalcBboxFromGeoJSON:
    def test_polygon_returns_correct_bbox(self) -> None:
        bbox = calc_bbox_from_geojson(_POLYGON_QC)
        assert bbox == (-71.5, 45.5, -71.4, 45.6)

    def test_multipolygon_returns_union_bbox(self) -> None:
        geojson: Dict[str, Any] = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [-71.5, 45.5],
                        [-71.4, 45.5],
                        [-71.4, 45.6],
                        [-71.5, 45.6],
                        [-71.5, 45.5],
                    ]
                ],
                [
                    [
                        [-72.0, 46.0],
                        [-71.9, 46.0],
                        [-71.9, 46.1],
                        [-72.0, 46.1],
                        [-72.0, 46.0],
                    ]
                ],
            ],
        }
        minx, miny, maxx, maxy = calc_bbox_from_geojson(geojson)
        assert minx == -72.0
        assert miny == 45.5
        assert maxx == -71.4
        assert maxy == 46.1

    def test_invalid_geojson_raises(self) -> None:
        with pytest.raises(ProcessorExecuteError, match="Invalid GeoJSON"):
            calc_bbox_from_geojson({"type": "NotAType", "coordinates": "bad"})

    def test_empty_geometry_raises(self) -> None:
        empty_poly = {"type": "Polygon", "coordinates": []}
        with pytest.raises(ProcessorExecuteError):
            calc_bbox_from_geojson(empty_poly)


# ---------------------------------------------------------------------------
# TestResolveLocationPoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLocationPoint:
    def test_point_returns_collapsed_bbox(self) -> None:
        bbox, poly = resolve_location(
            LocationType.POINT, None, [-73.5, 45.5], None, None
        )
        assert bbox == (-73.5, 45.5, -73.5, 45.5)

    def test_point_polygon_is_none(self) -> None:
        _, poly = resolve_location(LocationType.POINT, None, [-73.5, 45.5], None, None)
        assert poly is None

    def test_point_float_coercion(self) -> None:
        bbox, _ = resolve_location(LocationType.POINT, None, ["-73.5", "45.5"], None, None)  # type: ignore[list-item]
        assert bbox == (-73.5, 45.5, -73.5, 45.5)


# ---------------------------------------------------------------------------
# TestResolveLocationBbox
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLocationBbox:
    def test_bbox_returns_tuple(self) -> None:
        bbox, poly = resolve_location(
            LocationType.BBOX, None, None, [-74.0, 45.0, -73.0, 46.0], None
        )
        assert bbox == (-74.0, 45.0, -73.0, 46.0)

    def test_bbox_polygon_is_none(self) -> None:
        _, poly = resolve_location(
            LocationType.BBOX, None, None, [-74.0, 45.0, -73.0, 46.0], None
        )
        assert poly is None

    def test_bbox_float_coercion(self) -> None:
        bbox, _ = resolve_location(
            LocationType.BBOX, None, None, ["-74.0", "45.0", "-73.0", "46.0"], None  # type: ignore[list-item]
        )
        assert bbox == (-74.0, 45.0, -73.0, 46.0)


# ---------------------------------------------------------------------------
# TestResolveLocationPolygon
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLocationPolygon:
    def test_polygon_returns_bbox_and_geojson(self) -> None:
        bbox, poly = resolve_location(
            LocationType.POLYGON, None, None, None, _POLYGON_QC
        )
        assert bbox == (-71.5, 45.5, -71.4, 45.6)
        assert poly is _POLYGON_QC

    def test_polygon_geojson_passed_through_unchanged(self) -> None:
        _, poly = resolve_location(LocationType.POLYGON, None, None, None, _POLYGON_QC)
        assert poly == _POLYGON_QC


# ---------------------------------------------------------------------------
# TestGetGeometryFromDb
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestGetGeometryFromDb:
    def test_valid_farm_id_returns_geometry(self, mock_db_connection) -> None:
        with patch(
            "processes.location_utils.psycopg.connect", return_value=mock_db_connection
        ):
            geom = get_geometry_from_db("1")
        assert geom["type"] == "Polygon"

    def test_non_integer_farm_id_raises(self) -> None:
        with pytest.raises(ProcessorExecuteError, match="valid integer"):
            get_geometry_from_db("abc")

    def test_zero_farm_id_raises(self) -> None:
        with pytest.raises(ProcessorExecuteError, match="positive integer"):
            get_geometry_from_db("0")

    def test_negative_farm_id_raises(self) -> None:
        with pytest.raises(ProcessorExecuteError, match="positive integer"):
            get_geometry_from_db("-5")

    def test_farm_not_found_raises(self, mock_db_connection) -> None:
        mock_db_connection.cursor.return_value.fetchone.return_value = None
        with patch(
            "processes.location_utils.psycopg.connect", return_value=mock_db_connection
        ):
            with pytest.raises(ProcessorExecuteError, match="not found"):
                get_geometry_from_db("999")

    def test_db_error_raises(self, mock_db_connection) -> None:
        import psycopg as _psycopg

        mock_db_connection.__enter__.side_effect = _psycopg.OperationalError(
            "conn refused"
        )
        with patch(
            "processes.location_utils.psycopg.connect", return_value=mock_db_connection
        ):
            with pytest.raises(ProcessorExecuteError, match="Database error"):
                get_geometry_from_db("1")

    def test_invalid_table_name_env_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("FARM_TABLE_NAME", "public.table; DROP TABLE users--")
        with pytest.raises(ProcessorExecuteError, match="disallowed characters"):
            get_geometry_from_db("1")


# ---------------------------------------------------------------------------
# TestResolveLocationFarmId
# ---------------------------------------------------------------------------


@pytest.mark.mocked
class TestResolveLocationFarmId:
    def test_farm_id_calls_db_and_returns_bbox(self) -> None:
        with patch(
            "processes.location_utils.get_geometry_from_db", return_value=_POLYGON_QC
        ):
            bbox, poly = resolve_location(LocationType.FARM_ID, "1", None, None, None)
        assert bbox == (-71.5, 45.5, -71.4, 45.6)
        assert poly == _POLYGON_QC
