"""
Pydantic models for climate-timeseries and climate-indicators process
input validation and GeoJSON output.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from agri_i18n import _
from pydantic import BaseModel, Field, field_validator, model_validator

from ..backend_utils import LocationType, LocationValidatorMixin

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

VALID_VARIABLES = frozenset({"tasmin", "tasmax", "pr"})
VALID_SCENARIOS = frozenset({"ssp245", "ssp370", "ssp585"})
VALID_AGGREGATIONS = frozenset({"daily", "monthly"})


class Dataset(str, Enum):
    """Supported climate/weather datasets."""

    ERA5_LAND = "era5_land"
    RDRS_V2_1 = "rdrs_v2_1"
    CMIP6_ESPO_G6_R2 = "cmip6_espo_g6_r2"


class CMIPModel(str, Enum):
    """Supported CMIP6 models in ESPO-G6-R2 v1.0.0."""

    TAIESM1 = "TaiESM1"
    BCC_CSM2_MR = "BCC-CSM2-MR"
    FGOALS_G3 = "FGOALS-g3"
    CANESM5 = "CanESM5"
    CMCC_ESM2 = "CMCC-ESM2"
    CNRM_CM6_1 = "CNRM-CM6-1"
    CNRM_ESM2_1 = "CNRM-ESM2-1"
    ACCESS_CM2 = "ACCESS-CM2"
    ACCESS_ESM1_5 = "ACCESS-ESM1-5"
    EC_EARTH3_CC = "EC-Earth3-CC"
    EC_EARTH3_VEG = "EC-Earth3-Veg"
    EC_EARTH3 = "EC-Earth3"
    INM_CM4_8 = "INM-CM4-8"
    INM_CM5_0 = "INM-CM5-0"
    IPSL_CM6A_LR = "IPSL-CM6A-LR"
    MIROC_ES2L = "MIROC-ES2L"
    MIROC6 = "MIROC6"
    UKESM1_0_LL = "UKESM1-0-LL"
    MPI_ESM1_2_HR = "MPI-ESM1-2-HR"
    MPI_ESM1_2_LR = "MPI-ESM1-2-LR"
    MRI_ESM2_0 = "MRI-ESM2-0"
    NORESM2_LM = "NorESM2-LM"
    NORESM2_MM = "NorESM2-MM"
    KACE_1_0_G = "KACE-1-0-G"
    GFDL_ESM4 = "GFDL-ESM4"
    NESM3 = "NESM3"


class Indicator(str, Enum):
    """Supported agronomic climate indicators."""

    GDD = "gdd"
    FROST_DAYS = "frost_days"
    HEAT_STRESS_DAYS = "heat_stress_days"
    PR_TOTAL = "pr_total"
    PR_DAYS = "pr_days"


# ---------------------------------------------------------------------------
# climate-timeseries input model
# ---------------------------------------------------------------------------


class ClimateTimeseriesInput(LocationValidatorMixin):
    """Validated input for the climate-timeseries process (CMIP6 projections)."""

    location_type: LocationType = Field(...)
    farm_id: Optional[str] = Field(default=None)
    point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)
    bbox: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    polygon: Optional[Dict[str, Any]] = Field(default=None)
    variables: List[Literal["tasmin", "tasmax", "pr"]] = Field(min_length=1)
    start_date: str = Field(...)
    end_date: str = Field(...)
    aggregation: Literal["daily", "monthly"] = Field(default="daily")
    dataset: Dataset = Field(default=Dataset.CMIP6_ESPO_G6_R2)
    scenario: Literal["ssp245", "ssp370", "ssp585"] = Field(...)
    model: CMIPModel = Field(...)

    @field_validator("variables")
    @classmethod
    def deduplicate_variables(cls, v: List[str]) -> List[str]:
        """Remove duplicate variables while preserving order."""
        return list(dict.fromkeys(v))

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Ensure dates are valid ISO 8601 (YYYY-MM-DD) strings."""
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                _("Invalid date format (expected YYYY-MM-DD): {value!r}").format(
                    value=v
                )
            ) from exc
        return v

    @model_validator(mode="after")
    def check_date_order(self) -> "ClimateTimeseriesInput":
        """Ensure start_date <= end_date."""
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if start > end:
            raise ValueError(
                _(
                    "'start_date' ({start}) must be <= 'end_date' ({end})"
                ).format(start=self.start_date, end=self.end_date)
            )
        return self


# ---------------------------------------------------------------------------
# climate-timeseries GeoJSON output models
# ---------------------------------------------------------------------------


class GeoJSONGeometry(BaseModel):
    """Minimal GeoJSON geometry."""

    type: str
    coordinates: Any


class ClimateTimeseriesProperties(BaseModel):
    """Properties block of the climate timeseries GeoJSON Feature."""

    provider: str
    dataset: str
    scenario: str
    model: str
    variables: List[str]
    aggregation: str
    temporal_extent: List[str] = Field(min_length=2, max_length=2)
    data: Dict[str, List[Any]]
    units: Dict[str, str]


class ClimateTimeseriesFeature(BaseModel):
    """Valid GeoJSON Feature containing CMIP6 climate timeseries data."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: ClimateTimeseriesProperties

    def to_geojson(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# climate-indicators input model
# ---------------------------------------------------------------------------


class ClimateIndicatorsInput(LocationValidatorMixin):
    """Validated input for the climate-indicators process."""

    location_type: LocationType = Field(...)
    farm_id: Optional[str] = Field(default=None)
    point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)
    bbox: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    polygon: Optional[Dict[str, Any]] = Field(default=None)
    indicator: Indicator = Field(...)
    start_date: str = Field(...)
    end_date: str = Field(...)
    dataset: Dataset = Field(
        default=Dataset.ERA5_LAND,
        description="Defaults to era5_land; set to cmip6_espo_g6_r2 with scenario + model for CMIP6 projections.",
    )
    scenario: Optional[Literal["ssp245", "ssp370", "ssp585"]] = Field(default=None)
    model: Optional[CMIPModel] = Field(default=None)
    base_temp: float = Field(
        default=5.0,
        ge=0.0,
        le=15.0,
        description="Common agronomic bases: 0 °C (cool-season crops), 5 °C (most cereals), 10 °C (corn).",
    )
    threshold: float = Field(
        default=30.0,
        ge=0.0,
        le=50.0,
        description="Used by heat_stress_days (°C, default 30) and pr_days (mm/day, default 1).",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Ensure dates are valid ISO 8601 (YYYY-MM-DD) strings."""
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                _("Invalid date format (expected YYYY-MM-DD): {value!r}").format(
                    value=v
                )
            ) from exc
        return v

    @model_validator(mode="after")
    def check_date_order(self) -> "ClimateIndicatorsInput":
        """Ensure start_date <= end_date."""
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if start > end:
            raise ValueError(
                _(
                    "'start_date' ({start}) must be <= 'end_date' ({end})"
                ).format(start=self.start_date, end=self.end_date)
            )
        return self

    @model_validator(mode="after")
    def check_cmip6_fields(self) -> "ClimateIndicatorsInput":
        """Require scenario + model when dataset is a CMIP6 dataset."""
        if self.dataset == Dataset.CMIP6_ESPO_G6_R2:
            if self.scenario is None:
                raise ValueError(
                    _("'scenario' is required when using a CMIP6 dataset")
                )
            if self.model is None:
                raise ValueError(
                    _("'model' is required when using a CMIP6 dataset")
                )
        return self


# ---------------------------------------------------------------------------
# climate-indicators GeoJSON output models
# ---------------------------------------------------------------------------


class ClimateIndicatorsProperties(BaseModel):
    """Properties block of the climate indicators GeoJSON Feature."""

    provider: str
    dataset: str
    indicator: Indicator
    base_temp: Optional[float] = None
    threshold: Optional[float] = None
    temporal_extent: List[str] = Field(min_length=2, max_length=2)
    result: Dict[str, Any]
    units: Dict[str, str]


class ClimateIndicatorsFeature(BaseModel):
    """Valid GeoJSON Feature containing climate indicator results."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: ClimateIndicatorsProperties

    def to_geojson(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return self.model_dump()
