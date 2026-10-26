"""
Tests for the water-distance process and its PostGIS backend.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (psycopg DB)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest
from processes.spatial_backend.tables import checked_table_name
from processes.spatial_backend.water import nearest_water_distance
from processes.water_distance import WaterDistanceProcessor
from processes.water_distance_metadata import PROCESS_METADATA
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
def processor() -> WaterDistanceProcessor:
    return WaterDistanceProcessor({"name": "water-distance"})


@pytest.fixture
def mock_connect(monkeypatch):
    """Patch psycopg.connect in the water backend; yields the cursor mock."""
    monkeypatch.setenv("POSTGRES_PASS", "test")
    monkeypatch.setenv("WATER_TABLE_NAME", "public.grhq_water_union")
    cursor = MagicMock()
    with patch("processes.spatial_backend.water.psycopg.connect") as connect:
        conn = connect.return_value.__enter__.return_value
        conn.cursor.return_value.__enter__.return_value = cursor
        yield cursor


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@pytest.mark.mocked
def test_distance_returned_as_float(mock_connect):
    mock_connect.fetchone.return_value = (350.25,)

    assert nearest_water_distance(_SQUARE, 100_000) == 350.25


@pytest.mark.mocked
def test_distance_beyond_cutoff_is_none(mock_connect):
    mock_connect.fetchone.return_value = (140_000.0,)

    assert nearest_water_distance(_SQUARE, 100_000) is None


@pytest.mark.mocked
def test_no_feature_is_none(mock_connect):
    mock_connect.fetchone.return_value = (None,)

    assert nearest_water_distance(_SQUARE, 100_000) is None


@pytest.mark.mocked
def test_query_measures_from_interior_point_with_knn(mock_connect):
    mock_connect.fetchone.return_value = (10.0,)

    nearest_water_distance(_SQUARE, 100_000)

    sql, params = mock_connect.execute.call_args.args
    assert "ST_Centroid" not in sql
    assert sql.count("ST_PointOnSurface") == 2
    assert "<->" in sql
    assert "FROM public.grhq_water_union" in sql
    assert params == {
        "geom": '{"type": "Polygon", "coordinates": [[[-72.0, 45.0], '
        "[-71.99, 45.0], [-71.99, 45.01], [-72.0, 45.01], [-72.0, 45.0]]]}"
    }


@pytest.mark.unit
def test_unsafe_table_name_refused():
    with pytest.raises(ValueError, match="disallowed characters"):
        checked_table_name("public.grhq; DROP TABLE x")


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_metadata_id_and_languages():
    assert PROCESS_METADATA["id"] == "water-distance"
    assert set(PROCESS_METADATA["title"]) == {"en", "fr"}
    assert set(PROCESS_METADATA["description"]) == {"en", "fr"}


@pytest.mark.mocked
def test_execute_returns_distance(processor, mock_connect):
    mock_connect.fetchone.return_value = (350.0,)

    mime, output = processor.execute({"location_type": "polygon", "polygon": _SQUARE})

    assert mime == "application/json"
    assert output == {"id": "result", "value": {"distance_m": 350.0}}


@pytest.mark.mocked
def test_execute_custom_cutoff(processor, mock_connect):
    mock_connect.fetchone.return_value = (3_000.0,)

    _mime, output = processor.execute(
        {"location_type": "point", "point": [-72.0, 45.0], "max_distance_m": 2_000}
    )

    assert output["value"] == {"distance_m": None}


@pytest.mark.unit
def test_execute_bbox_rejected(processor):
    with pytest.raises(ProcessorExecuteError, match="Invalid inputs: location_type"):
        processor.execute({"location_type": "bbox", "bbox": [-72, 45, -71, 46]})


@pytest.mark.unit
def test_execute_cutoff_out_of_range(processor):
    with pytest.raises(ProcessorExecuteError, match="max_distance_m"):
        processor.execute(
            {"location_type": "point", "point": [-72.0, 45.0], "max_distance_m": 0}
        )


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
