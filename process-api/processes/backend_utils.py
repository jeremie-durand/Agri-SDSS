"""Shared utilities for PAVICS and CMIP backend data processing."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Self, Tuple

import numpy as np
from agri_i18n import _
from pydantic import BaseModel, field_validator, model_validator


class LocationType(str, Enum):
    """Supported spatial location types for OGC process inputs."""

    FARM_ID = "farm_id"
    POINT = "point"
    BBOX = "bbox"
    POLYGON = "polygon"


class LocationValidatorMixin(BaseModel):
    """Mixin that validates `point` and `bbox` fields for location-based input models."""

    @field_validator("point", check_fields=False)
    @classmethod
    def validate_point_coords(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Validate longitude and latitude ranges for point coordinates."""
        if v is None:
            return v
        lon, lat = float(v[0]), float(v[1])
        if not -180 <= lon <= 180:
            raise ValueError(
                _("Longitude {value} out of range [-180, 180]").format(value=lon)
            )
        if not -90 <= lat <= 90:
            raise ValueError(
                _("Latitude {value} out of range [-90, 90]").format(value=lat)
            )
        return v

    @field_validator("bbox", check_fields=False)
    @classmethod
    def validate_bbox_order(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Validate that minx < maxx and miny < maxy."""
        if v is None:
            return v
        minx, miny, maxx, maxy = (float(c) for c in v)
        if minx >= maxx:
            raise ValueError(
                _("bbox minx ({minx}) must be < maxx ({maxx})").format(
                    minx=minx, maxx=maxx
                )
            )
        if miny >= maxy:
            raise ValueError(
                _("bbox miny ({miny}) must be < maxy ({maxy})").format(
                    miny=miny, maxy=maxy
                )
            )
        return v

    @model_validator(mode="after")
    def check_location_field_provided(self) -> Self:
        """Ensure the field matching location_type is present."""
        loc = self.location_type
        missing = _("'{field}' must be provided when location_type is '{field}'")
        if loc == LocationType.FARM_ID and self.farm_id is None:
            raise ValueError(missing.format(field="farm_id"))
        if loc == LocationType.POINT and self.point is None:
            raise ValueError(missing.format(field="point"))
        if loc == LocationType.BBOX and self.bbox is None:
            raise ValueError(missing.format(field="bbox"))
        if loc == LocationType.POLYGON and self.polygon is None:
            raise ValueError(missing.format(field="polygon"))
        return self


def apply_variable_conversions(
    ds: Any,
    canonical_to_netcdf: Dict[str, str],
    var_registry: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Apply scale/offset conversions and extract per-variable data from a dataset.

    Args:
        ds: xarray Dataset (subset, time × space already resolved to a 1-D array).
        canonical_to_netcdf: Mapping from canonical variable name to NetCDF name.
        var_registry: Variable metadata dict from the dataset registry (scale_factor,
            add_offset, output_units, …).

    Returns:
        Tuple of (values, units) where values maps canonical name → converted list
        or scalar, and units maps canonical name → output unit string.
    """
    values: Dict[str, Any] = {}
    units: Dict[str, str] = {}
    for canonical, netcdf_name in canonical_to_netcdf.items():
        var_meta: Dict[str, Any] = var_registry[canonical]
        scale: float = float(var_meta.get("scale_factor", 1.0))
        offset: float = float(var_meta.get("add_offset", 0.0))
        arr = ds[netcdf_name].values
        if isinstance(arr, np.ndarray) and arr.ndim > 0:
            converted: np.ndarray = arr * scale + offset
            values[canonical] = [
                None if np.isnan(v) else round(float(v), 4) for v in converted.tolist()
            ]
        else:
            values[canonical] = round(float(arr) * scale + offset, 4)
        units[canonical] = var_meta.get("output_units", var_meta.get("units", ""))
    return values, units
