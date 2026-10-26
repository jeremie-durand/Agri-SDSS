"""Pydantic input models for the spatial utility processes."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import Field, ValidationError, field_validator
from pygeoapi.process.base import ProcessorExecuteError

from agri_i18n import _

from ..backend_utils import LocationType, LocationValidatorMixin

DEFAULT_MAX_DISTANCE_M: float = 100_000.0
DEFAULT_MIN_DESCRIBED_PCT: float = 50.0
DEFAULT_TOLERANCE_M: float = 20.0

InputModel = TypeVar("InputModel", bound="SpatialLocationInput")


class SpatialLocationInput(LocationValidatorMixin):
    """Location of a parcel: a stored farm, a point or a polygon."""

    location_type: LocationType
    farm_id: str | None = None
    point: list[float] | None = Field(default=None, min_length=2, max_length=2)
    polygon: dict[str, Any] | None = None

    @field_validator("location_type")
    @classmethod
    def reject_bbox(cls, v: LocationType) -> LocationType:
        """Reject bbox: a distance or an area share from a bbox means nothing."""
        if v == LocationType.BBOX:
            raise ValueError(_("location_type 'bbox' is not supported by this process"))
        return v


class WaterDistanceInput(SpatialLocationInput):
    """Validated input for the water-distance process."""

    max_distance_m: float = Field(default=DEFAULT_MAX_DISTANCE_M, gt=0, le=100_000)


class PedoCoverageInput(SpatialLocationInput):
    """Validated input for the pedo-coverage process."""

    min_described_pct: float = Field(default=DEFAULT_MIN_DESCRIBED_PCT, ge=0, le=100)


class SomFieldMatchInput(SpatialLocationInput):
    """Validated input for the som-field-match process."""

    tolerance_m: float = Field(default=DEFAULT_TOLERANCE_M, ge=0, le=500)


def parse_inputs(model: type[InputModel], data: dict[str, Any]) -> InputModel:
    """Validate raw process inputs, turning pydantic errors into a process error.

    Raises:
        ProcessorExecuteError: Listing every invalid field.
    """
    try:
        return model(**data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        raise ProcessorExecuteError(
            _("Invalid inputs: {errors}").format(errors=errors)
        ) from exc
