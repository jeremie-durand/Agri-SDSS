"""
Weather Timeseries OGC API – Processes implementation.

Retrieves gridded climate and reanalysis timeseries from the Ouranos PAVICS
THREDDS server (OPeNDAP) for a given spatial area and time range.
Returns a valid GeoJSON Feature.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from .location_utils import resolve_location
from .weather_backend import (
    PAVICSBackend,
    WeatherTimeseriesFeature,
    WeatherTimeseriesInput,
)
from .weather_timeseries_metadata import PROCESS_METADATA

logger = logging.getLogger(__name__)


class WeatherTimeseriesProcessor(BaseProcessor):
    """OGC API Process: retrieve weather timeseries from PAVICS THREDDS."""

    # Shared backend instance — stateless after __init__, safe to reuse.
    _backend: Optional[PAVICSBackend] = None

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        if WeatherTimeseriesProcessor._backend is None:
            WeatherTimeseriesProcessor._backend = PAVICSBackend()

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute the weather timeseries process.

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
            feature: WeatherTimeseriesFeature = self._backend.fetch(  # type: ignore[union-attr]
                bbox=bbox,
                variables=validated.variables,
                start_date=validated.start_date,
                end_date=validated.end_date,
                aggregation=validated.aggregation,
                dataset=validated.dataset,
                polygon_geojson=polygon_geojson,
            )
            return "application/geo+json", {
                "id": "result",
                "value": feature.to_geojson(),
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in WeatherTimeseriesProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"Unexpected error: {exc}") from exc

    def __repr__(self) -> str:
        return f"<WeatherTimeseriesProcessor> {self.name}"

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(data: Dict[str, Any]) -> WeatherTimeseriesInput:
        """Parse and validate all process inputs with pydantic.

        Args:
            data: Raw OGC process input dict.

        Returns:
            Validated WeatherTimeseriesInput instance.

        Raises:
            ProcessorExecuteError: On any validation failure.
        """
        try:
            return WeatherTimeseriesInput(**data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ProcessorExecuteError(f"Invalid inputs: {errors}") from exc
