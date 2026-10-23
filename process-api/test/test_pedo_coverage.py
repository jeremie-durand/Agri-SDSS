"""
Tests for the pedo-coverage process and its PostGIS backend.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
  @pytest.mark.mocked  — external I/O mocked (psycopg DB)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from processes.spatial_backend.pedo import pedo_coverage

_SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 45.0], [-71.99, 45.0], [-71.99, 45.01], [-72.0, 45.01], [-72.0, 45.0]]
    ],
}
_POINT = {"type": "Point", "coordinates": [-72.0, 45.0]}


@pytest.fixture
def mock_cursor(monkeypatch):
    """Patch psycopg.connect in the pedo backend; yields the cursor mock.

    Set ``fetchall.side_effect`` to one row list per query: 2026, then 2022.
    """
    monkeypatch.setenv("POSTGRES_PASS", "test")
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
