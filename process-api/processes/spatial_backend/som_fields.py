"""SOM field boundaries within a tolerance of a location."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from ..config import DatabaseConfig, SpatialTablesConfig
from .tables import checked_column_name, checked_table_name

_SQL = """
    SELECT {id_column}, has_gee_data,
        ST_Distance(
            geometry::geography,
            ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)::geography
        ) AS dist
    FROM {table}
    WHERE ST_DWithin(
        geometry::geography,
        ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)::geography,
        %(tolerance_m)s
    )
    ORDER BY has_gee_data DESC, dist ASC
"""


def som_table_and_id_column() -> tuple[str, str]:
    """Return the SOM field table and the column holding the field ids callers use.

    Callers send and receive this column's values as ``gid``, whatever the
    column is named; it must be an integer unique per field.
    """
    tables = SpatialTablesConfig()
    return (
        checked_table_name(tables.SOM_TABLE_NAME),
        checked_column_name(tables.SOM_ID_COLUMN),
    )


def match(geometry: dict[str, Any], tolerance_m: float) -> list[dict[str, Any]]:
    """Return the SOM fields within *tolerance_m* metres of *geometry*.

    Fields with GEE data come first, then by increasing geodesic distance; an
    intersecting field has a distance of 0.

    Returns:
        ``[{"gid": int, "has_gee_data": bool, "dist_m": float}, ...]``
    """
    table, id_column = som_table_and_id_column()
    with psycopg.connect(**DatabaseConfig().to_conn_params()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _SQL.format(table=table, id_column=id_column),
                {"geom": json.dumps(geometry), "tolerance_m": tolerance_m},
            )
            rows = cur.fetchall()

    return [
        {
            "gid": int(gid),
            "has_gee_data": bool(has_gee_data),
            "dist_m": round(float(dist), 1),
        }
        for gid, has_gee_data, dist in rows
    ]
