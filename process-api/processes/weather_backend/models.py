"""
Pydantic models for weather-timeseries process input validation and GeoJSON output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..backend_utils import LocationType, LocationValidatorMixin

# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

VALID_VARIABLES = frozenset({"tasmin", "tasmax", "tas", "pr"})
VALID_LOCATION_TYPES = frozenset({"farm_id", "point", "bbox", "polygon"})
VALID_AGGREGATIONS = frozenset({"daily", "monthly"})
DEFAULT_DATASET = "era5_land"


class WeatherTimeseriesInput(LocationValidatorMixin):
    """Validated input for the weather-timeseries process."""

    location_type: LocationType
    farm_id: Optional[str] = None
    point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)
    bbox: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    polygon: Optional[Dict[str, Any]] = None
    variables: List[Literal["tasmin", "tasmax", "tas", "pr"]] = Field(min_length=1)
    start_date: str
    end_date: str
    aggregation: Literal["daily", "monthly"] = "daily"
    dataset: str = DEFAULT_DATASET

    @field_validator("variables")
    @classmethod
    def deduplicate_variables(cls, v: List[str]) -> List[str]:
        """Remove duplicate variables while preserving order."""
        return list(dict.fromkeys(v))

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Ensure dates are valid ISO 8601 (YYYY-MM-DD) strings."""
        from datetime import date

        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date format (expected YYYY-MM-DD): {v!r}"
            ) from exc
        return v

    @field_validator("dataset")
    @classmethod
    def validate_dataset_not_empty(cls, v: str) -> str:
        """Ensure dataset identifier is a non-empty string."""
        if not v or not v.strip():
            raise ValueError("'dataset' must be a non-empty string")
        return v

    @model_validator(mode="after")
    def check_date_order(self) -> "WeatherTimeseriesInput":
        """Ensure start_date <= end_date."""
        from datetime import date

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if start > end:
            raise ValueError(
                f"'start_date' ({self.start_date}) must be <= 'end_date' ({self.end_date})"
            )
        return self


# ---------------------------------------------------------------------------
# GeoJSON output models
# ---------------------------------------------------------------------------


class GeoJSONGeometry(BaseModel):
    """Minimal GeoJSON geometry."""

    type: str
    coordinates: Any


class WeatherTimeseriesProperties(BaseModel):
    """Properties block of the weather timeseries GeoJSON Feature."""

    provider: str
    dataset: str
    variables: List[str]
    aggregation: str
    temporal_extent: List[str] = Field(min_length=2, max_length=2)
    data: Dict[str, List[Any]]
    units: Dict[str, str]


class WeatherTimeseriesFeature(BaseModel):
    """Valid GeoJSON Feature containing weather timeseries data."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: WeatherTimeseriesProperties

    def to_geojson(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return self.model_dump()
