"""SOM field boundaries within a tolerance of a location."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from ..config import DatabaseConfig, SpatialTablesConfig
from .tables import checked_table_name

_SQL = """
    SELECT gid, has_gee_data,
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


def match(geometry: dict[str, Any], tolerance_m: float) -> list[dict[str, Any]]:
    """Return the SOM fields within *tolerance_m* metres of *geometry*.

    Fields with GEE data come first, then by increasing geodesic distance; an
    intersecting field has a distance of 0.

    Returns:
        ``[{"gid": int, "has_gee_data": bool, "dist_m": float}, ...]``
    """
    table = checked_table_name(SpatialTablesConfig().SOM_TABLE_NAME)
    with psycopg.connect(**DatabaseConfig().to_conn_params()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _SQL.format(table=table),
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
