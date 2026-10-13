"""Pedological properties endpoint for Vector API.

Joins the IRDA pedological coverage for a parcel: the 2026 polygons in PostGIS
give each overlapped ``code_polygone`` and its share of the parcel, then the
GeoParquet attribute tables give each polygon's soil components, their NRCS
hydrologic group (BDHP) and their bulk density by horizon.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from agri_i18n import _

from .db_pool import get_pool
from .duckdb_manager import DuckDBSpatialExtensionError, get_shared_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Spatial Utilities"])

_POLYGON_TABLE = os.environ.get(
    "PEDO_POLYGON_TABLE_NAME",
    "public.couverture_pedologique_2026_01_couverture_p_cbc3c8",
)
_COMPONENTS = os.environ.get(
    "PEDO_COMPONENTS_COLLECTION", "couverture_pedologique_2026_01_couverture_pps"
)
_HYDRO = os.environ.get(
    "PEDO_HYDRO_COLLECTION", "couverture_pedologique_2026_01_bdhp_2026"
)
_BULK_DENSITY = os.environ.get(
    "PEDO_BULK_DENSITY_COLLECTION", "couverture_pedologique_2026_01_ppc_eessaq"
)
_BULK_DENSITY_1990 = os.environ.get(
    "PEDO_BULK_DENSITY_1990_COLLECTION",
    "couverture_pedologique_2026_01_ppc_inventaire_1990",
)

_VALID_HYDRO_GROUPS = {"A", "B", "C", "D", "A/D", "B/D", "C/D"}

_OVERLAP_SQL = f"""
    WITH parcel AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326) AS g)
    SELECT p.code_polygone,
           ST_Area(ST_Intersection(p.geometry, parcel.g)::geography)
             / NULLIF(ST_Area(parcel.g::geography), 0) AS fraction
    FROM {_POLYGON_TABLE} p, parcel
    WHERE ST_Intersects(p.geometry, parcel.g)
"""


@router.post("/pedo-properties")
async def pedo_properties(body: Dict[str, Any]) -> JSONResponse:
    """Return the soil components, hydrologic group and bulk density of a parcel.

    Request body: ``{"geometry": <GeoJSON geometry object>}``

    Response::

        {
          "components": [
            {"composante": str, "code_sol": str | null, "share_pct": float,
             "hydrologic_group": str | null,
             "bulk_density": {"source": "eessaq" | "inventaire_1990" | null,
                              "horizons": [{"horizon", "depth_top_cm",
                                            "depth_bottom_cm", "g_cm3"}]}}
          ],
          "dominant_hydrologic_group": str | null,
          "described_pct": float
        }

    ``share_pct`` is the percentage of the parcel attributed to a component;
    ``described_pct`` is their sum, so the rest of the parcel has no data.
    Bulk density is in g/cm³; depths are in cm and null when unknown.
    """
    geom_json = _geometry_json(body)
    fractions = await _polygon_fractions(geom_json)
    manager = _manager()
    try:
        components = _load_components(manager, list(fractions))
        code_sols = sorted({c["code_sol"] for c in components if c["code_sol"]})
        densities = _load_bulk_densities(manager, code_sols)
    except FileNotFoundError as exc:
        logger.error("Pedological Parquet table missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=_("Pedological property tables are unavailable."),
        ) from exc
    return JSONResponse(_aggregate(fractions, components, densities))


def _geometry_json(body: Dict[str, Any]) -> str:
    """Validate the request body and return its geometry as a JSON string."""
    geometry = body.get("geometry")
    if not geometry:
        raise HTTPException(status_code=422, detail=_("'geometry' field is required"))
    try:
        return json.dumps(geometry)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Invalid geometry: {error}").format(error=exc),
        ) from exc


async def _polygon_fractions(geom_json: str) -> Dict[str, float]:
    """Return {code_polygone: fraction of the parcel area it covers}."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_OVERLAP_SQL, geom_json)
    except asyncpg.PostgresError as exc:
        logger.error("PostGIS query error in pedo_properties: %s", exc)
        raise HTTPException(
            status_code=500, detail=_("Internal database error")
        ) from exc
    return {r["code_polygone"]: float(r["fraction"] or 0.0) for r in rows}


def _manager():
    """Return the shared DuckDB manager, or raise 503 if it cannot load."""
    try:
        return get_shared_manager()
    except DuckDBSpatialExtensionError as exc:
        logger.error("DuckDB unavailable in pedo_properties: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=_("Pedological property tables are unavailable."),
        ) from exc


def _load_components(manager, codes: List[str]) -> List[Dict[str, Any]]:
    """Return the components of the given polygons, with their BDHP attributes."""
    if not codes:
        return []
    query = f"""
        SELECT p.code_polygone, p.composante, p.pourcentage,
               b.code_sol, b.groupe_hydrologique
        FROM {manager.parquet_source(_COMPONENTS)} p
        LEFT JOIN {manager.parquet_source(_HYDRO)} b ON b.composante = p.composante
        WHERE list_contains($1, p.code_polygone)
    """
    return manager.query_rows(query, [codes])


def _load_bulk_densities(manager, code_sols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Return {code_sol: bulk density entry}, preferring the eessaq horizons."""
    if not code_sols:
        return {}
    eessaq = manager.query_rows(
        f"""
        SELECT codesiscan AS code_sol, hzn AS horizon,
               profondeurlimiteinf AS depth_bottom_cm, mva3 AS g_cm3
        FROM {manager.parquet_source(_BULK_DENSITY)}
        WHERE list_contains($1, codesiscan) AND mva3 IS NOT NULL
        ORDER BY codesiscan, profondeurlimiteinf NULLS LAST, hzn
        """,
        [code_sols],
    )
    inventory = manager.query_rows(
        f"""
        SELECT code_sol, horizon, NULL AS depth_bottom_cm, densite AS g_cm3
        FROM {manager.parquet_source(_BULK_DENSITY_1990)}
        WHERE list_contains($1, code_sol) AND densite IS NOT NULL
        ORDER BY code_sol, horizon
        """,
        [code_sols],
    )
    densities = _group_horizons(inventory, "inventaire_1990")
    densities.update(_group_horizons(eessaq, "eessaq"))
    return densities


def _group_horizons(
    rows: List[Dict[str, Any]], source: str
) -> Dict[str, Dict[str, Any]]:
    """Group ordered horizon rows by soil, deriving each horizon's top depth."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        entry = grouped.setdefault(row["code_sol"], {"source": source, "horizons": []})
        horizons = entry["horizons"]
        previous_bottom = horizons[-1]["depth_bottom_cm"] if horizons else 0.0
        horizons.append(
            {
                "horizon": row["horizon"],
                "depth_top_cm": previous_bottom if source == "eessaq" else None,
                "depth_bottom_cm": _round(row["depth_bottom_cm"]),
                "g_cm3": _round(row["g_cm3"], 3),
            }
        )
    return grouped


def _aggregate(
    fractions: Dict[str, float],
    components: List[Dict[str, Any]],
    densities: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Weight each component by the parcel area it covers and summarise."""
    by_component: Dict[str, Dict[str, Any]] = {}
    for row in components:
        share = fractions.get(row["code_polygone"], 0.0) * row["pourcentage"]
        entry = by_component.setdefault(
            row["composante"],
            {
                "composante": row["composante"],
                "code_sol": row["code_sol"],
                "share_pct": 0.0,
                "hydrologic_group": _hydro_group(row["groupe_hydrologique"]),
                "bulk_density": densities.get(
                    row["code_sol"], {"source": None, "horizons": []}
                ),
            },
        )
        entry["share_pct"] += share
    ranked = sorted(by_component.values(), key=lambda c: c["share_pct"], reverse=True)
    for entry in ranked:
        entry["share_pct"] = _round(entry["share_pct"])
    return {
        "components": ranked,
        "dominant_hydrologic_group": _dominant_group(ranked),
        "described_pct": _round(sum(c["share_pct"] for c in ranked)),
    }


def _hydro_group(value: Optional[str]) -> Optional[str]:
    """Return the NRCS group, or None for empty and 'NA' values."""
    return value if value in _VALID_HYDRO_GROUPS else None


def _dominant_group(components: List[Dict[str, Any]]) -> Optional[str]:
    """Return the hydrologic group covering the largest share of the parcel."""
    totals: Dict[str, float] = {}
    for component in components:
        group = component["hydrologic_group"]
        if group:
            totals[group] = totals.get(group, 0.0) + component["share_pct"]
    return max(totals, key=totals.get) if totals else None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    """Round a float, passing None through."""
    return None if value is None else round(float(value), digits)
