"""Field geometry on the metric 2 m grid: projection, snapping, masks, statistics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pygeoapi.process.base import ProcessorExecuteError
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from agri_i18n import _

from .models import zone_label

GRID_CRS: str = "EPSG:32198"
GEOGRAPHIC_CRS: str = "EPSG:4326"
SQUARE_METRES_PER_HECTARE: float = 10_000.0

Bounds = tuple[float, float, float, float]


def to_grid_crs(geometry: dict[str, Any]) -> BaseGeometry:
    """Project a GeoJSON geometry from EPSG:4326 to the grid CRS."""
    return shape(transform_geom(GEOGRAPHIC_CRS, GRID_CRS, geometry))


def snap_outwards(bounds: Bounds, cell_size: float) -> Bounds:
    """Expand bounds to the nearest multiples of ``cell_size``."""
    west, south, east, north = bounds
    return (
        math.floor(west / cell_size) * cell_size,
        math.floor(south / cell_size) * cell_size,
        math.ceil(east / cell_size) * cell_size,
        math.ceil(north / cell_size) * cell_size,
    )


def widen(bounds: Bounds, margin: float) -> Bounds:
    """Widen bounds by ``margin`` on every side."""
    west, south, east, north = bounds
    return (west - margin, south - margin, east + margin, north + margin)


def grid_shape(bounds: Bounds, cell_size: float) -> tuple[int, int]:
    """Return (rows, cols) of a grid snapped to ``cell_size``."""
    west, south, east, north = bounds
    return round((north - south) / cell_size), round((east - west) / cell_size)


def grid_transform(bounds: Bounds, cell_size: float) -> Affine:
    """Return the north-up affine transform of a grid with these bounds."""
    west, _south, _east, north = bounds
    return Affine(cell_size, 0.0, west, 0.0, -cell_size, north)


def crop_slices(outer: Bounds, inner: Bounds, cell_size: float) -> tuple[slice, slice]:
    """Return the row and column slices of ``inner`` inside ``outer``.

    Both bounds must be snapped to ``cell_size`` and ``inner`` must lie within
    ``outer``.
    """
    rows, cols = grid_shape(inner, cell_size)
    row_offset = round((outer[3] - inner[3]) / cell_size)
    col_offset = round((inner[0] - outer[0]) / cell_size)
    return (
        slice(row_offset, row_offset + rows),
        slice(col_offset, col_offset + cols),
    )


def inside_mask(
    geometry: BaseGeometry, transform: Affine, out_shape: tuple[int, int]
) -> NDArray[np.bool_]:
    """Return True for pixels whose centre lies inside ``geometry``."""
    if geometry.is_empty:
        return np.zeros(out_shape, dtype=bool)
    return geometry_mask(
        [mapping(geometry)], out_shape=out_shape, transform=transform, invert=True
    )


def layer_statistics(values: NDArray[np.floating]) -> dict[str, float | None]:
    """Return mean, median, 90th percentile and maximum, or nulls when empty."""
    if values.size == 0:
        return {"mean": None, "median": None, "p90": None, "max": None}
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "max": float(np.max(values)),
    }


def field_summary(
    field_pixels: NDArray[np.bool_],
    slope: NDArray[np.floating],
    ls: NDArray[np.floating],
) -> dict[str, Any]:
    """Return the slope mean and LS statistics over the selected pixels."""
    slope_values = slope[field_pixels]
    return {
        "slope": {
            "mean_percent": (
                float(np.mean(slope_values)) if slope_values.size else None
            )
        },
        "ls": layer_statistics(ls[field_pixels]),
    }


def prepare_zones(
    zones: dict[str, Any], field: BaseGeometry
) -> list[tuple[Any, BaseGeometry]]:
    """Return each zone's label and its part inside the field, in the grid CRS.

    Raises:
        ProcessorExecuteError: When a zone does not intersect the field.
    """
    prepared: list[tuple[Any, BaseGeometry]] = []
    for position, feature in enumerate(zones["features"], start=1):
        label = zone_label(feature, position)
        zone = to_grid_crs(feature["geometry"]).buffer(0).intersection(field)
        if zone.is_empty:
            raise ProcessorExecuteError(
                _("Invalid inputs: {errors}").format(
                    errors=_("Zone {zone} does not intersect the field").format(
                        zone=label
                    )
                )
            )
        prepared.append((label, zone))
    return prepared


def zone_summaries(
    zones: list[tuple[Any, BaseGeometry]],
    field_pixels: NDArray[np.bool_],
    transform: Affine,
    slope: NDArray[np.floating],
    ls: NDArray[np.floating],
    cell_size: float,
) -> list[dict[str, Any]]:
    """Return one summary per prepared zone, over its pixels in the field."""
    summaries: list[dict[str, Any]] = []
    for label, zone in zones:
        pixels = inside_mask(zone, transform, field_pixels.shape) & field_pixels
        summaries.append(
            {
                "id": label,
                "area_ha": float(pixels.sum() * cell_size * cell_size)
                / SQUARE_METRES_PER_HECTARE,
                **field_summary(pixels, slope, ls),
            }
        )
    return summaries
