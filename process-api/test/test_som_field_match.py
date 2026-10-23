"""
Tests for the som-field-match process and its PostGIS backend.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (psycopg DB)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest
from processes.som_field_match import SomFieldMatchProcessor
from processes.som_field_match_metadata import PROCESS_METADATA
from processes.spatial_backend.som_fields import match
from pygeoapi.process.base import ProcessorExecuteError

import agri_i18n

_SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 45.0], [-71.99, 45.0], [-71.99, 45.01], [-72.0, 45.01], [-72.0, 45.0]]
    ],
}


@pytest.fixture(autouse=True)
def _english_messages():
    """Assert against the English msgids rather than the French default."""
    with agri_i18n.use_locale("en"):
        yield


@pytest.fixture
def processor() -> SomFieldMatchProcessor:
    return SomFieldMatchProcessor({"name": "som-field-match"})


@pytest.fixture
def mock_connect(monkeypatch):
    """Patch psycopg.connect in the SOM fields backend; yields the cursor mock."""
    monkeypatch.setenv("POSTGRES_PASS", "test")
    cursor = MagicMock()
    with patch("processes.spatial_backend.som_fields.psycopg.connect") as connect:
        conn = connect.return_value.__enter__.return_value
        conn.cursor.return_value.__enter__.return_value = cursor
        yield cursor


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@pytest.mark.mocked
def test_matches_keep_query_order_and_round_distance(mock_connect):
    mock_connect.fetchall.return_value = [(12, True, 8.04), (7, False, 0.0)]

    assert match(_SQUARE, 20) == [
        {"gid": 12, "has_gee_data": True, "dist_m": 8.0},
        {"gid": 7, "has_gee_data": False, "dist_m": 0.0},
    ]


@pytest.mark.mocked
def test_no_field_nearby_is_empty(mock_connect):
    mock_connect.fetchall.return_value = []

    assert match(_SQUARE, 20) == []


@pytest.mark.mocked
def test_query_orders_gee_first_and_binds_tolerance(mock_connect):
    mock_connect.fetchall.return_value = []

    match(_SQUARE, 100)

    sql, params = mock_connect.execute.call_args.args
    assert "FROM public.som_field_boundaries" in sql
    assert "ORDER BY has_gee_data DESC, dist ASC" in sql
    assert "%(tolerance_m)s" in sql
    assert params["tolerance_m"] == 100


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_metadata_id_and_languages():
    assert PROCESS_METADATA["id"] == "som-field-match"
    assert set(PROCESS_METADATA["title"]) == {"en", "fr"}
    assert set(PROCESS_METADATA["description"]) == {"en", "fr"}


@pytest.mark.mocked
def test_execute_returns_matches(processor, mock_connect):
    mock_connect.fetchall.return_value = [(12, True, 8.0), (7, False, 0.0)]

    mime, output = processor.execute({"location_type": "polygon", "polygon": _SQUARE})

    assert mime == "application/json"
    assert output == {
        "id": "result",
        "value": {
            "matches": [
                {"gid": 12, "has_gee_data": True, "dist_m": 8.0},
                {"gid": 7, "has_gee_data": False, "dist_m": 0.0},
            ]
        },
    }


@pytest.mark.mocked
def test_execute_point_input_uses_point_geometry(processor, mock_connect):
    mock_connect.fetchall.return_value = [(7, True, 0.0)]

    _mime, output = processor.execute(
        {"location_type": "point", "point": [-72.0, 45.0]}
    )

    _sql, params = mock_connect.execute.call_args.args
    assert params["geom"] == '{"type": "Point", "coordinates": [-72.0, 45.0]}'
    assert params["tolerance_m"] == 20
    assert output["value"]["matches"] == [
        {"gid": 7, "has_gee_data": True, "dist_m": 0.0}
    ]


@pytest.mark.mocked
def test_execute_custom_tolerance(processor, mock_connect):
    mock_connect.fetchall.return_value = [(3, True, 60.0)]

    processor.execute(
        {"location_type": "point", "point": [-72.0, 45.0], "tolerance_m": 100}
    )

    _sql, params = mock_connect.execute.call_args.args
    assert params["tolerance_m"] == 100


@pytest.mark.unit
@pytest.mark.parametrize("tolerance_m", [-1, 1000])
def test_execute_tolerance_out_of_range(processor, tolerance_m):
    with pytest.raises(ProcessorExecuteError, match="tolerance_m"):
        processor.execute(
            {
                "location_type": "point",
                "point": [-72.0, 45.0],
                "tolerance_m": tolerance_m,
            }
        )


@pytest.mark.unit
def test_execute_bbox_rejected(processor):
    with pytest.raises(ProcessorExecuteError, match="Invalid inputs: location_type"):
        processor.execute({"location_type": "bbox", "bbox": [-72, 45, -71, 46]})


@pytest.mark.unit
def test_execute_validation_error_is_french_by_default(processor):
    with agri_i18n.use_locale("fr"):
        with pytest.raises(ProcessorExecuteError) as excinfo:
            processor.execute({"location_type": "polygon"})

    assert "Invalid inputs" not in str(excinfo.value)


@pytest.mark.mocked
def test_execute_database_error_is_generic(processor, mock_connect):
    mock_connect.execute.side_effect = psycopg.OperationalError(
        "password authentication failed"
    )

    with pytest.raises(ProcessorExecuteError) as excinfo:
        processor.execute({"location_type": "polygon", "polygon": _SQUARE})

    assert str(excinfo.value) == (
        "An unexpected error occurred while running this process."
    )
