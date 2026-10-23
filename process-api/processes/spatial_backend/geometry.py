"""Turn a validated location into the GeoJSON geometry sent to PostGIS."""

from __future__ import annotations

from typing import Any

from pygeoapi.process.base import ProcessorExecuteError
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from agri_i18n import _

from ..backend_utils import LocationType
from ..location_utils import get_geometry_from_db
from .models import SpatialLocationInput


def prepare_geometry(location: SpatialLocationInput) -> dict[str, Any]:
    """Return the location as a valid GeoJSON geometry.

    Points are returned as is. Farm and polygon geometries are repaired when
    invalid rather than rejected, keeping only their polygonal parts.

    Raises:
        ProcessorExecuteError: On an unparsable or empty geometry, or a failed
            farm lookup.
    """
    if location.location_type == LocationType.POINT:
        lon, lat = location.point  # type: ignore[misc]
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}

    if location.location_type == LocationType.FARM_ID:
        geojson = get_geometry_from_db(location.farm_id)  # type: ignore[arg-type]
    else:
        geojson = location.polygon  # type: ignore[assignment]

    return mapping(_repaired(geojson))


def _repaired(geojson: dict[str, Any]) -> BaseGeometry:
    """Parse a GeoJSON geometry and repair it if it is an invalid polygon."""
    try:
        geom = shape(geojson)
    except Exception as exc:
        raise ProcessorExecuteError(
            _("Invalid GeoJSON geometry: {error}").format(error=exc)
        ) from exc
    if isinstance(geom, (Polygon, MultiPolygon)) and not geom.is_valid:
        geom = _polygonal_parts(make_valid(geom))
    if geom.is_empty:
        raise ProcessorExecuteError(_("GeoJSON geometry is invalid or empty"))
    return geom


def _polygonal_parts(geom: BaseGeometry) -> BaseGeometry:
    """Drop the lines and points make_valid can return for collapsed edges."""
    parts = geom.geoms if isinstance(geom, GeometryCollection) else [geom]
    polygons = [g for g in parts if isinstance(g, (Polygon, MultiPolygon))]
    return unary_union(polygons) if polygons else GeometryCollection()
