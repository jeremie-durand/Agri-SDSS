"""Distance from a parcel to the nearest GRHQ hydrographic feature."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from ..config import DatabaseConfig, SpatialTablesConfig
from .tables import checked_table_name

# The interior point is inlined in ORDER BY rather than taken from a CTE so the
# planner keeps the GiST KNN index scan (<->); a CTE forces a sequential scan.
_SQL = """
    SELECT MIN(ST_Distance(
        geometry::geography,
        ST_PointOnSurface(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))::geography
    ))
    FROM (
        SELECT geometry
        FROM {table}
        ORDER BY geometry
            <-> ST_PointOnSurface(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))
        LIMIT 5
    ) candidates
"""


def nearest_water_distance(
    geometry: dict[str, Any], max_distance_m: float
) -> float | None:
    """Return the geodesic distance in metres from the parcel's interior point.

    The KNN scan picks 5 candidates by planar distance, then the exact
    geography distance is computed on those rows only.

    Returns:
        The distance, or None when there is no feature within *max_distance_m*.
    """
    table = checked_table_name(SpatialTablesConfig().WATER_TABLE_NAME)
    with psycopg.connect(**DatabaseConfig().to_conn_params()) as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL.format(table=table), {"geom": json.dumps(geometry)})
            row = cur.fetchone()

    distance_m = row[0] if row else None
    if distance_m is None or distance_m > max_distance_m:
        return None
    return float(distance_m)
