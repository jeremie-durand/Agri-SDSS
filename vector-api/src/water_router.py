"""Water distance endpoint for Vector API.

Computes the minimum distance in metres from a given GeoJSON geometry
to the nearest GRHQ hydrographic feature (lines and polygons only).
"""

import json
import logging
import os
from typing import Any, Dict

import asyncpg
from agri_i18n import _
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .db_pool import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Spatial Utilities"])

_WATER_TABLE = os.environ.get("WATER_TABLE_NAME", "public.grhq_water_union")


@router.post("/water-distance")
async def water_distance(body: Dict[str, Any]) -> JSONResponse:
    """Return the minimum distance in metres from *geometry* to the nearest
    GRHQ water feature (lines and polygons, excluding point tables).

    Uses the centroid of the input geometry so that water features that merely
    touch or cross the farm boundary don't collapse the distance to 0.
    KNN index scan (<->) finds 5 nearest candidates, then computes exact
    geography distance on only those rows.
    Returns null when the nearest feature is beyond 100 km (out of GRHQ coverage).

    Request body: ``{"geometry": <GeoJSON geometry object>}``

    Response: ``{"distance_m": <float | null>}``
    """
    geometry = body.get("geometry")
    if not geometry:
        raise HTTPException(
            status_code=422, detail=_("'geometry' field is required")
        )

    try:
        geom_json = json.dumps(geometry)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Invalid geometry: {error}").format(error=exc),
        ) from exc

    # Inline the centroid expression directly in ORDER BY so the planner can
    # use the GiST KNN index (<->). A CTE on the right-hand side forces a seq scan.
    sql = f"""
        SELECT MIN(ST_Distance(
            geometry::geography,
            ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))::geography
        )) AS distance_m
        FROM (
            SELECT geometry
            FROM {_WATER_TABLE}
            ORDER BY geometry <-> ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))
            LIMIT 5
        ) candidates
    """

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            distance_m = await conn.fetchval(sql, geom_json)

        if distance_m is not None and distance_m > 100_000:
            return JSONResponse({"distance_m": None})

        return JSONResponse(
            {"distance_m": float(distance_m) if distance_m is not None else None}
        )

    except asyncpg.PostgresError as exc:
        logger.error("PostGIS query error in water_distance: %s", exc)
        raise HTTPException(
            status_code=500, detail=_("Internal database error")
        ) from exc
