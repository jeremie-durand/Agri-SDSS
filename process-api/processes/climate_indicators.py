"""
Climate Indicators OGC API – Processes implementation.

Computes agronomic climate indicators (Growing Degree Days, etc.) from
gridded temperature data sourced from PAVICS THREDDS via OPeNDAP.
Supports historical reanalysis (ERA5-Land, RDRS) and CMIP6 projections.
Returns a valid GeoJSON Feature.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from pydantic import ValidationError
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from .climate_backend import (
    ClimateIndicatorsFeature,
    ClimateIndicatorsInput,
    ClimateTimeseriesFeature,
    CMIPBackend,
    Dataset,
    Indicator,
    calc_growing_degree_days,
)
from .climate_backend.indicators import (
    calc_frost_days,
    calc_heat_stress_days,
    calc_precipitation_days,
    calc_precipitation_total,
)
from .climate_backend.models import ClimateIndicatorsProperties, GeoJSONGeometry
from .climate_indicators_metadata import PROCESS_METADATA
from .location_utils import resolve_location
from .weather_backend import PAVICSBackend, WeatherTimeseriesFeature

logger = logging.getLogger(__name__)


class ClimateIndicatorsProcessor(BaseProcessor):
    """OGC API Process: compute agronomic climate indicators from PAVICS data."""

    _weather_backend: Optional[PAVICSBackend] = None
    _climate_backend: Optional[CMIPBackend] = None

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        if ClimateIndicatorsProcessor._weather_backend is None:
            ClimateIndicatorsProcessor._weather_backend = PAVICSBackend()
        if ClimateIndicatorsProcessor._climate_backend is None:
            ClimateIndicatorsProcessor._climate_backend = CMIPBackend()

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute the climate indicators process.

        Args:
            data: OGC process input dict.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/geo+json", {"id": "result", "value": <GeoJSON>}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            validated = self._validate_inputs(data)
            bbox, polygon_geojson = resolve_location(
                location_type=validated.location_type,
                farm_id=validated.farm_id,
                point=validated.point,
                bbox=validated.bbox,
                polygon=validated.polygon,
            )
            feature = self._compute_indicator(validated, bbox, polygon_geojson)
            return "application/geo+json", {
                "id": "result",
                "value": feature.to_geojson(),
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in ClimateIndicatorsProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"Unexpected error: {exc}") from exc

    def __repr__(self) -> str:
        return f"<ClimateIndicatorsProcessor> {self.name}"

    @staticmethod
    def _validate_inputs(data: Dict[str, Any]) -> ClimateIndicatorsInput:
        """Parse and validate all process inputs with pydantic."""
        try:
            return ClimateIndicatorsInput(**data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ProcessorExecuteError(f"Invalid inputs: {errors}") from exc

    # Map each indicator to the variables it requires from the backend.
    _INDICATOR_VARIABLES: Dict[Indicator, List[str]] = {
        Indicator.GDD: ["tasmin", "tasmax"],
        Indicator.FROST_DAYS: ["tasmin"],
        Indicator.HEAT_STRESS_DAYS: ["tasmax"],
        Indicator.PR_TOTAL: ["pr"],
        Indicator.PR_DAYS: ["pr"],
    }

    def _fetch_raw(
        self,
        validated: ClimateIndicatorsInput,
        variables: List[str],
        bbox: Tuple[float, float, float, float],
        polygon_geojson: Optional[Dict[str, Any]],
    ) -> Union[WeatherTimeseriesFeature, ClimateTimeseriesFeature]:
        """Dispatch fetch to PAVICSBackend or CMIPBackend based on dataset."""
        if validated.dataset == Dataset.CMIP6_ESPO_G6_R2:
            return self._climate_backend.fetch(  # type: ignore[union-attr]
                bbox=bbox,
                variables=variables,
                start_date=validated.start_date,
                end_date=validated.end_date,
                aggregation="daily",
                dataset=validated.dataset,
                scenario=validated.scenario,  # type: ignore[arg-type]
                model=validated.model,  # type: ignore[arg-type]
                polygon_geojson=polygon_geojson,
            )
        return self._weather_backend.fetch(  # type: ignore[union-attr]
            bbox=bbox,
            variables=variables,
            start_date=validated.start_date,
            end_date=validated.end_date,
            aggregation="daily",
            dataset=validated.dataset,
            polygon_geojson=polygon_geojson,
        )

    def _compute_indicator(
        self,
        validated: ClimateIndicatorsInput,
        bbox: Tuple[float, float, float, float],
        polygon_geojson: Optional[Dict[str, Any]],
    ) -> ClimateIndicatorsFeature:
        """Fetch required variables and compute the requested indicator."""
        required_vars = self._INDICATOR_VARIABLES.get(validated.indicator)
        if required_vars is None:
            raise ProcessorExecuteError(
                f"Unsupported indicator: {validated.indicator!r}"
            )

        raw = self._fetch_raw(validated, required_vars, bbox, polygon_geojson)
        provider = raw.properties.provider
        data_props = raw.properties.data
        geometry = GeoJSONGeometry(**raw.geometry.model_dump())
        time_values: List[str] = data_props["time"]

        def _arr(key: str) -> np.ndarray:
            return np.array(
                [v if v is not None else np.nan for v in data_props[key]],
                dtype=np.float64,
            )

        result: Dict[str, Any]
        indicator_units: Dict[str, str]
        threshold_out: Optional[float] = None

        if validated.indicator == Indicator.GDD:
            daily_gdd = calc_growing_degree_days(
                _arr("tasmax"), _arr("tasmin"), validated.base_temp
            )
            result = {
                "total_gdd": round(float(np.nansum(daily_gdd)), 4),
                "daily_gdd": [
                    None if np.isnan(v) else round(float(v), 4)
                    for v in daily_gdd.tolist()
                ],
                "time": time_values,
            }
            indicator_units = {"gdd": "degC·day", "base_temp": "degC"}

        elif validated.indicator == Indicator.FROST_DAYS:
            result = {
                "frost_days": calc_frost_days(_arr("tasmin")),
                "time": time_values,
            }
            indicator_units = {"tasmin": "degC"}

        elif validated.indicator == Indicator.HEAT_STRESS_DAYS:
            threshold_out = validated.threshold
            result = {
                "heat_stress_days": calc_heat_stress_days(
                    _arr("tasmax"), validated.threshold
                ),
                "threshold": validated.threshold,
                "time": time_values,
            }
            indicator_units = {"tasmax": "degC", "threshold": "degC"}

        elif validated.indicator == Indicator.PR_TOTAL:
            result = {
                "pr_total": round(calc_precipitation_total(_arr("pr")), 4),
                "time": time_values,
            }
            indicator_units = {"pr": "mm"}

        elif validated.indicator == Indicator.PR_DAYS:
            threshold_out = validated.threshold
            result = {
                "pr_days": calc_precipitation_days(_arr("pr"), validated.threshold),
                "threshold": validated.threshold,
                "time": time_values,
            }
            indicator_units = {"pr": "mm/day", "threshold": "mm/day"}

        else:
            raise ProcessorExecuteError(
                f"Unsupported indicator: {validated.indicator!r}"
            )

        properties = ClimateIndicatorsProperties(
            provider=provider,
            dataset=validated.dataset,
            indicator=validated.indicator,
            base_temp=(
                validated.base_temp if validated.indicator == Indicator.GDD else None
            ),
            threshold=threshold_out,
            temporal_extent=[validated.start_date, validated.end_date],
            result=result,
            units=indicator_units,
        )
        return ClimateIndicatorsFeature(geometry=geometry, properties=properties)
