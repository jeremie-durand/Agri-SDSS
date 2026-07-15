"""
Shared location-resolution utilities for OGC process inputs.

Converts a location specification (farm_id, point, bbox, or polygon) into
a bounding box and optional polygon GeoJSON for spatial queries.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

import psycopg
from pygeoapi.process.base import ProcessorExecuteError
from shapely.geometry import shape

from .backend_utils import LocationType
from .config import DatabaseConfig, FarmConfig

logger = logging.getLogger(__name__)


def resolve_location(
    location_type: LocationType,
    farm_id: Optional[str],
    point: Optional[list],
    bbox: Optional[list],
    polygon: Optional[Dict[str, Any]],
) -> Tuple[Tuple[float, float, float, float], Optional[Dict[str, Any]]]:
    """Resolve a location specification to (bbox, optional_polygon_geojson).

    Args:
        location_type: One of "farm_id", "point", "bbox", "polygon".
        farm_id: Farm identifier string (used when location_type="farm_id").
        point: [lon, lat] (used when location_type="point").
        bbox: [minx, miny, maxx, maxy] (used when location_type="bbox").
        polygon: GeoJSON Polygon dict (used when location_type="polygon").

    Returns:
        Tuple of (bbox, polygon_geojson) where:
        - bbox is (minx, miny, maxx, maxy) in EPSG:4326.
        - polygon_geojson is None for location type for "point" and "bbox".

    Raises:
        ProcessorExecuteError: On invalid location_type, DB lookup failure,
            or invalid geometry.
    """
    if location_type == LocationType.POINT:
        lon, lat = float(point[0]), float(point[1])  # type: ignore[index]
        return (lon, lat, lon, lat), None

    if location_type == LocationType.BBOX:
        minx, miny, maxx, maxy = (float(v) for v in bbox)  # type: ignore[union-attr]
        return (minx, miny, maxx, maxy), None

    if location_type == LocationType.POLYGON:
        return calc_bbox_from_geojson(polygon), polygon  # type: ignore[arg-type]

    if location_type == LocationType.FARM_ID:
        geom = get_geometry_from_db(farm_id)  # type: ignore[arg-type]
        return calc_bbox_from_geojson(geom), geom

    raise ProcessorExecuteError(f"Unhandled location_type: {location_type!r}")


def calc_bbox_from_geojson(
    geojson: Dict[str, Any],
) -> Tuple[float, float, float, float]:
    """Derive a bounding box from a GeoJSON geometry using shapely.

    Args:
        geojson: GeoJSON geometry dict (Polygon, MultiPolygon, etc.).

    Returns:
        (minx, miny, maxx, maxy) bounding box.

    Raises:
        ProcessorExecuteError: If the geometry is invalid or unsupported.
    """
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise ProcessorExecuteError(f"Invalid GeoJSON geometry: {exc}") from exc
    if not geom.is_valid or geom.is_empty:
        raise ProcessorExecuteError("GeoJSON geometry is invalid or empty")
    minx, miny, maxx, maxy = geom.bounds
    return minx, miny, maxx, maxy


def get_geometry_from_db(farm_id: str) -> Dict[str, Any]:
    """Retrieve farm geometry from PostGIS database.

    Uses environment variables for connection parameters and table/column
    names. Table and column names are validated against a safe regex to
    prevent SQL injection.

    Args:
        farm_id: Farm identifier (must parse as a positive integer).

    Returns:
        GeoJSON geometry dict.

    Raises:
        ProcessorExecuteError: On invalid farm_id, missing farm, or DB error.
    """
    try:
        farm_id_int = int(farm_id)
    except (ValueError, TypeError) as exc:
        raise ProcessorExecuteError(
            f"'farm_id' must be a valid integer, got: {farm_id!r}"
        ) from exc
    if farm_id_int <= 0:
        raise ProcessorExecuteError(
            f"'farm_id' must be a positive integer, got: {farm_id_int}"
        )

    farm = FarmConfig()
    table_name: str = farm.FARM_TABLE_NAME
    geom_column: str = farm.FARM_GEOMETRY_COLUMN
    id_column: str = farm.FARM_ID_COLUMN

    if not re.match(r"^[a-zA-Z0-9_.]+$", table_name):
        raise ProcessorExecuteError("FARM_TABLE_NAME contains disallowed characters")
    if not re.match(r"^[a-zA-Z0-9_]+$", geom_column):
        raise ProcessorExecuteError(
            "FARM_GEOMETRY_COLUMN contains disallowed characters"
        )
    if not re.match(r"^[a-zA-Z0-9_]+$", id_column):
        raise ProcessorExecuteError("FARM_ID_COLUMN contains disallowed characters")

    conn_params = DatabaseConfig().to_conn_params()

    try:
        with psycopg.connect(**conn_params) as conn:  # type: ignore[call-overload]
            with conn.cursor() as cur:
                query = (
                    f"SELECT ST_AsGeoJSON({geom_column}) AS geom "
                    f"FROM {table_name} "
                    f"WHERE {id_column} = %s"
                )
                cur.execute(query, (farm_id_int,))
                row = cur.fetchone()
                if row is None:
                    raise ProcessorExecuteError(
                        f"Farm ID {farm_id_int} not found in database"
                    )
                return json.loads(row[0])
    except ProcessorExecuteError:
        raise
    except psycopg.Error as exc:
        raise ProcessorExecuteError(
            f"Database error retrieving farm geometry: {exc}"
        ) from exc
