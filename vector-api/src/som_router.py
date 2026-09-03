"""SOM field-match endpoint for Vector API.

Returns all records from the SOM field boundaries table (configured via
SOM_TABLE_NAME) that spatially intersect a given GeoJSON geometry,
ordered by distance (GEE-positive fields first).
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

_SOM_TABLE = os.environ.get("SOM_TABLE_NAME", "public.som_field_boundaries")


@router.post("/som-field-match")
async def som_field_match(body: Dict[str, Any]) -> JSONResponse:
    """Return all som_field_boundaries records intersecting the given geometry.

    Uses ST_Intersects on the GiST index to find all candidates, then orders by
    has_gee_data DESC and ST_Area(ST_Intersection(...)) DESC so GEE-positive
    fields with the greatest overlap come first.

    Request body: ``{"geometry": <GeoJSON geometry object>}``

    Response: ``{"matches": [{"gid": <int>, "has_gee_data": <bool>}, ...]}``
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

    # _TOLERANCE_M: max distance (metres) between polygon edges to still consider
    # a match. Handles slightly offset boundaries from different data sources.
    # Intersecting polygons have distance 0 so they always rank first.
    sql = f"""
        SELECT gid, has_gee_data,
            ST_Distance(
                geometry::geography,
                ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography
            ) AS dist
        FROM {_SOM_TABLE}
        WHERE ST_DWithin(
            geometry::geography,
            ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography,
            20
        )
        ORDER BY
            has_gee_data DESC,
            dist ASC
    """

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, geom_json)

        matches = [
            {
                "gid": int(r["gid"]),
                "has_gee_data": bool(r["has_gee_data"]),
                "dist_m": round(r["dist"], 1),
            }
            for r in rows
        ]
        return JSONResponse({"matches": matches})

    except asyncpg.PostgresError as exc:
        logger.error("PostGIS query error in som_field_match: %s", exc)
        raise HTTPException(
            status_code=500, detail=_("Internal database error")
        ) from exc
