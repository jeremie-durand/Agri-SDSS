"""Pedological classes covering a parcel, from the IRDA 2026 or 2022 soil map."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from ..config import DatabaseConfig, SpatialTablesConfig
from .tables import checked_table_name

POINT_BUFFER_M: float = 5.0

_PARCEL = "ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)"
_BUFFERED_POINT = f"ST_Buffer({_PARCEL}::geography, %(buffer_m)s)::geometry"

_SQL = """
    SELECT {symbol} AS symbole, {description} AS description,
        SUM(
            ST_Area(ST_Intersection(t.geometry, parcel.g)::geography) / parcel.area
        ) * 100 AS share_pct
    FROM {table} t
    CROSS JOIN (
        SELECT g, ST_Area(g::geography) AS area FROM (SELECT {parcel} AS g) p
    ) parcel
    WHERE ST_Intersects(t.geometry, parcel.g)
    GROUP BY 1, 2
    ORDER BY share_pct DESC, symbole
"""


@dataclass(frozen=True)
class _Release:
    """Where one IRDA release keeps its classes."""

    source: str
    table: str
    symbol_column: str
    description_column: str | None


def pedo_coverage(geometry: dict[str, Any], min_described_pct: float) -> dict[str, Any]:
    """Describe the parcel from the 2026 map, or from 2022 if 2026 covers too little.

    A point is buffered by POINT_BUFFER_M metres so area shares are defined.
    2022 is used only when the 2026 classes describe less than
    *min_described_pct* of the parcel and 2022 has any class there; the two
    releases are never mixed.

    Returns:
        ``{"source", "symbole", "description", "count", "described_pct",
        "classes": [{"symbole", "description", "share_pct"}]}``, with
        ``source`` ``"irda_2026"``, ``"irda_2022"`` or None when neither
        release covers the parcel.
    """
    tables = SpatialTablesConfig()
    release_2026 = _Release(
        "irda_2026", checked_table_name(tables.PEDO_TABLE_NAME), "symbole", None
    )
    release_2022 = _Release(
        "irda_2022",
        checked_table_name(tables.PEDO_2022_TABLE_NAME),
        "symbol",
        "description",
    )
    params = {"geom": json.dumps(geometry), "buffer_m": POINT_BUFFER_M}
    is_point = geometry["type"] == "Point"

    with psycopg.connect(**DatabaseConfig().to_conn_params()) as conn:
        source = release_2026.source
        classes = _classes(conn, release_2026, params, is_point)
        if _described_pct(classes) < min_described_pct:
            fallback = _classes(conn, release_2022, params, is_point)
            if fallback:
                source, classes = release_2022.source, fallback

    return _result(source if classes else None, classes)


def _classes(
    conn: psycopg.Connection,
    release: _Release,
    params: dict[str, Any],
    is_point: bool,
) -> list[dict[str, Any]]:
    """Return the release's classes over the parcel, largest share first."""
    sql = _SQL.format(
        symbol=f"t.{release.symbol_column}",
        description=(
            f"t.{release.description_column}"
            if release.description_column
            else "NULL::text"
        ),
        table=release.table,
        parcel=_BUFFERED_POINT if is_point else _PARCEL,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {"symbole": symbole, "description": description, "share_pct": float(share)}
        for symbole, description, share in rows
    ]


def _described_pct(classes: list[dict[str, Any]]) -> float:
    return sum(c["share_pct"] for c in classes)


def _result(source: str | None, classes: list[dict[str, Any]]) -> dict[str, Any]:
    dominant = classes[0] if classes else {"symbole": None, "description": None}
    return {
        "source": source,
        "symbole": dominant["symbole"],
        "description": dominant["description"],
        "count": len(classes),
        "described_pct": round(_described_pct(classes), 1),
        "classes": [{**c, "share_pct": round(c["share_pct"], 1)} for c in classes],
    }
