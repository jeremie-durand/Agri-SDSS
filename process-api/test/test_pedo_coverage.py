"""
Tests for the pedo-coverage process and its PostGIS backend.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (psycopg DB)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import psycopg
import pytest
from processes.pedo_coverage import PedoCoverageProcessor
from processes.pedo_coverage_metadata import PROCESS_METADATA
from processes.spatial_backend.pedo import pedo_coverage
from pygeoapi.process.base import ProcessorExecuteError

import agri_i18n

_SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 45.0], [-71.99, 45.0], [-71.99, 45.01], [-72.0, 45.01], [-72.0, 45.0]]
    ],
}
_POINT = {"type": "Point", "coordinates": [-72.0, 45.0]}


@pytest.fixture(autouse=True)
def _english_messages():
    """Assert against the English msgids rather than the French default."""
    with agri_i18n.use_locale("en"):
        yield


@pytest.fixture
def processor() -> PedoCoverageProcessor:
    return PedoCoverageProcessor({"name": "pedo-coverage"})


@pytest.fixture
def mock_cursor(monkeypatch):
    """Patch psycopg.connect in the pedo backend; yields the cursor mock.

    Set ``fetchall.side_effect`` to one row list per query: 2026, then 2022.
    """
    monkeypatch.setenv("POSTGRES_PASS", "test")
    monkeypatch.setenv(
        "PEDO_TABLE_NAME", "public.couverture_pedologique_2026_01_couverture_p_cbc3c8"
    )
    monkeypatch.setenv("PEDO_2022_TABLE_NAME", "public.couverture_pedo_2022")
    cursor = MagicMock()
    with patch("processes.spatial_backend.pedo.psycopg.connect") as connect:
        conn = connect.return_value.__enter__.return_value
        conn.cursor.return_value.__enter__.return_value = cursor
        yield cursor


def _queries(cursor: MagicMock) -> list[str]:
    return [c.args[0] for c in cursor.execute.call_args_list]


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@pytest.mark.mocked
def test_2026_accepted_when_described_enough(mock_cursor):
    mock_cursor.fetchall.side_effect = [
        [("ARGILE Bon", None, 62.04), ("TILL Bon", None, 37.96)]
    ]

    result = pedo_coverage(_SQUARE, 50)

    assert result == {
        "source": "irda_2026",
        "symbole": "ARGILE Bon",
        "description": None,
        "count": 2,
        "described_pct": 100.0,
        "classes": [
            {"symbole": "ARGILE Bon", "description": None, "share_pct": 62.0},
            {"symbole": "TILL Bon", "description": None, "share_pct": 38.0},
        ],
    }
    assert mock_cursor.execute.call_count == 1


@pytest.mark.mocked
def test_2026_below_threshold_falls_back_to_2022(mock_cursor):
    mock_cursor.fetchall.side_effect = [
        [("ARGILE Bon", None, 20.0)],
        [("TILL Imparfait", "Loam till, imperfectly drained", 95.0)],
    ]

    result = pedo_coverage(_SQUARE, 50)

    assert result["source"] == "irda_2022"
    assert result["symbole"] == "TILL Imparfait"
    assert result["description"] == "Loam till, imperfectly drained"
    assert result["classes"] == [
        {
            "symbole": "TILL Imparfait",
            "description": "Loam till, imperfectly drained",
            "share_pct": 95.0,
        }
    ]
    sql_2026, sql_2022 = _queries(mock_cursor)
    assert "FROM public.couverture_pedologique_2026_01_couverture_p_cbc3c8" in sql_2026
    assert "t.symbole AS symbole, NULL::text AS description" in sql_2026
    assert "FROM public.couverture_pedo_2022" in sql_2022
    assert "t.symbol AS symbole, t.description AS description" in sql_2022


@pytest.mark.mocked
def test_2022_empty_keeps_partial_2026(mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 20.0)], []]

    result = pedo_coverage(_SQUARE, 50)

    assert result["source"] == "irda_2026"
    assert result["described_pct"] == 20.0
    assert result["count"] == 1


@pytest.mark.mocked
def test_nothing_in_either_release_is_empty(mock_cursor):
    mock_cursor.fetchall.side_effect = [[], []]

    assert pedo_coverage(_SQUARE, 50) == {
        "source": None,
        "symbole": None,
        "description": None,
        "count": 0,
        "described_pct": 0,
        "classes": [],
    }


@pytest.mark.mocked
def test_lower_threshold_keeps_2026(mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 30.0)]]

    result = pedo_coverage(_SQUARE, 25)

    assert result["source"] == "irda_2026"
    assert mock_cursor.execute.call_count == 1


@pytest.mark.mocked
def test_count_is_distinct_classes_grouped_in_sql(mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 100.0)]]

    result = pedo_coverage(_SQUARE, 50)

    assert result["count"] == 1
    assert "GROUP BY 1, 2" in _queries(mock_cursor)[0]
    assert "COUNT(" not in _queries(mock_cursor)[0]


@pytest.mark.mocked
def test_water_class_is_kept(mock_cursor):
    mock_cursor.fetchall.side_effect = [
        [("ARGILE Bon", None, 90.0), ("Étendue d'eau", None, 10.0)]
    ]

    result = pedo_coverage(_SQUARE, 50)

    assert {"symbole": "Étendue d'eau", "description": None, "share_pct": 10.0} in (
        result["classes"]
    )


@pytest.mark.mocked
def test_point_is_buffered_polygon_is_not(mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 100.0)]]
    pedo_coverage(_POINT, 50)
    point_sql = _queries(mock_cursor)[0]
    params = mock_cursor.execute.call_args.args[1]

    mock_cursor.reset_mock()
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 100.0)]]
    pedo_coverage(_SQUARE, 50)
    polygon_sql = _queries(mock_cursor)[0]

    assert "ST_Buffer(" in point_sql
    assert params["buffer_m"] == 5.0
    assert "ST_Buffer(" not in polygon_sql
    assert "WHERE ST_Intersects(t.geometry, parcel.g)" in polygon_sql


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_metadata_id_and_languages():
    assert PROCESS_METADATA["id"] == "pedo-coverage"
    assert set(PROCESS_METADATA["title"]) == {"en", "fr"}
    assert set(PROCESS_METADATA["description"]) == {"en", "fr"}


@pytest.mark.mocked
def test_execute_returns_coverage(processor, mock_cursor):
    mock_cursor.fetchall.side_effect = [
        [("ARGILE Bon", None, 62.0), ("TILL Bon", None, 38.0)]
    ]

    mime, output = processor.execute({"location_type": "polygon", "polygon": _SQUARE})

    assert mime == "application/json"
    assert output["id"] == "result"
    assert set(output["value"]) == {
        "source",
        "symbole",
        "description",
        "count",
        "described_pct",
        "classes",
    }
    assert output["value"]["source"] == "irda_2026"
    assert [c["symbole"] for c in output["value"]["classes"]] == [
        "ARGILE Bon",
        "TILL Bon",
    ]


@pytest.mark.mocked
def test_execute_point_input_is_buffered(processor, mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 100.0)]]

    _mime, output = processor.execute(
        {"location_type": "point", "point": [-72.0, 45.0]}
    )

    sql, params = mock_cursor.execute.call_args.args
    assert "ST_Buffer(" in sql
    assert params["geom"] == '{"type": "Point", "coordinates": [-72.0, 45.0]}'
    assert output["value"]["classes"][0]["share_pct"] == 100.0


@pytest.mark.mocked
def test_execute_custom_threshold(processor, mock_cursor):
    mock_cursor.fetchall.side_effect = [[("ARGILE Bon", None, 30.0)]]

    _mime, output = processor.execute(
        {"location_type": "polygon", "polygon": _SQUARE, "min_described_pct": 25}
    )

    assert output["value"]["source"] == "irda_2026"
    assert mock_cursor.execute.call_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("min_described_pct", [-1, 120])
def test_execute_threshold_out_of_range(processor, min_described_pct):
    with pytest.raises(ProcessorExecuteError, match="min_described_pct"):
        processor.execute(
            {
                "location_type": "polygon",
                "polygon": _SQUARE,
                "min_described_pct": min_described_pct,
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
def test_execute_database_error_is_generic(processor, mock_cursor):
    mock_cursor.execute.side_effect = psycopg.OperationalError(
        "password authentication failed"
    )

    with pytest.raises(ProcessorExecuteError) as excinfo:
        processor.execute({"location_type": "polygon", "polygon": _SQUARE})

    assert str(excinfo.value) == (
        "An unexpected error occurred while running this process."
    )
