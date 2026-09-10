"""Pedo-coverage endpoint for Vector API.

Returns the dominant pedological class (symbole) from the pedological coverage
table (configured via PEDO_TABLE_NAME) that overlaps most with a given GeoJSON geometry.
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

_PEDO_TABLE = os.environ.get("PEDO_TABLE_NAME", "public.pedo_coverage")


@router.post("/pedo-coverage")
async def pedo_coverage(body: Dict[str, Any]) -> JSONResponse:
    """Return the dominant pedo class overlapping the given geometry.

    Uses ST_Intersects on the GiST index to find candidates, then ranks by
    ST_Area(ST_Intersection(...)) to return the class with the largest overlap.

    Request body: ``{"geometry": <GeoJSON geometry object>}``

    Response: ``{"description": <str | null>, "count": <int>}``
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

    sql = f"""
        SELECT symbole, COUNT(*) OVER () AS total
        FROM {_PEDO_TABLE}
        WHERE ST_Intersects(geometry, ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))
        ORDER BY ST_Area(
            ST_Intersection(geometry, ST_SetSRID(ST_GeomFromGeoJSON($1), 4326))::geography
        ) DESC
        LIMIT 1
    """

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, geom_json)

        if row is None:
            return JSONResponse({"description": None, "count": 0})

        return JSONResponse({"description": row["symbole"], "count": int(row["total"])})

    except asyncpg.PostgresError as exc:
        logger.error("PostGIS query error in pedo_coverage: %s", exc)
        raise HTTPException(
            status_code=500, detail=_("Internal database error")
        ) from exc
