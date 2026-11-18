"""Pydantic input model for the lidar-flowpath process."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from shapely.geometry import MultiPolygon, Polygon, shape

from agri_i18n import _

from ..backend_utils import LocationType, LocationValidatorMixin

DEFAULT_UPSTREAM_MARGIN_M: int = 300
MAX_UPSTREAM_MARGIN_M: int = 1000
MAX_ZONES: int = 50


class FlowpathInputs(LocationValidatorMixin):
    """Validated inputs: one field, its upstream margin and optional zones."""

    location_type: LocationType
    farm_id: str | None = None
    point: list[float] | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    polygon: dict[str, Any] | None = None
    upstream_margin_m: int = Field(
        default=DEFAULT_UPSTREAM_MARGIN_M, ge=0, le=MAX_UPSTREAM_MARGIN_M
    )
    zones: dict[str, Any] | None = None

    @field_validator("location_type")
    @classmethod
    def reject_point(cls, v: LocationType) -> LocationType:
        """Reject point: runoff layers need an area."""
        if v == LocationType.POINT:
            raise ValueError(
                _("location_type 'point' is not supported by this process")
            )
        return v

    @field_validator("zones")
    @classmethod
    def validate_zones(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Require a FeatureCollection of 1 to MAX_ZONES polygonal features."""
        if v is None:
            return v
        features = v.get("features")
        if v.get("type") != "FeatureCollection" or not isinstance(features, list):
            raise ValueError(_("'zones' must be a GeoJSON FeatureCollection"))
        if not 1 <= len(features) <= MAX_ZONES:
            raise ValueError(
                _("'zones' must hold between 1 and {maximum} features").format(
                    maximum=MAX_ZONES
                )
            )
        for position, feature in enumerate(features, start=1):
            if not _is_polygonal(feature):
                raise ValueError(
                    _("Zone {zone} must be a Polygon or MultiPolygon").format(
                        zone=zone_label(feature, position)
                    )
                )
            properties = feature.get("properties")
            if properties is not None and not isinstance(properties, dict):
                raise ValueError(
                    _("Zone {zone} properties must be an object or null").format(
                        zone=position
                    )
                )
        return v


def zone_label(feature: Any, position: int) -> Any:
    """Return a zone's ``id`` property, or its 1-based position when absent.

    The id is any JSON value the caller sent, returned unchanged.
    """
    properties = feature.get("properties") if isinstance(feature, dict) else None
    zone_id = properties.get("id") if isinstance(properties, dict) else None
    return position if zone_id is None else zone_id


def _is_polygonal(feature: Any) -> bool:
    if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
        return False
    try:
        geometry = shape(feature["geometry"])
    except Exception:
        return False
    return isinstance(geometry, (Polygon, MultiPolygon)) and not geometry.is_empty
