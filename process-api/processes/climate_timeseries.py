"""
Climate Timeseries OGC API – Processes implementation.

Retrieves CMIP6 climate projection timeseries from the Ouranos PAVICS
THREDDS server (OPeNDAP) for a given spatial area and time range.
Returns a valid GeoJSON Feature.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from .climate_backend import (
    ClimateTimeseriesFeature,
    ClimateTimeseriesInput,
    CMIPBackend,
)
from .climate_timeseries_metadata import PROCESS_METADATA
from .location_utils import resolve_location

logger = logging.getLogger(__name__)


class ClimateTimeseriesProcessor(BaseProcessor):
    """OGC API Process: retrieve CMIP6 climate projection timeseries from PAVICS."""

    # Shared backend instance — safe to reuse across requests.
    _backend: Optional[CMIPBackend] = None

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        if ClimateTimeseriesProcessor._backend is None:
            ClimateTimeseriesProcessor._backend = CMIPBackend()

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute the climate timeseries process.

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
            feature: ClimateTimeseriesFeature = self._backend.fetch(  # type: ignore[union-attr]
                bbox=bbox,
                variables=validated.variables,
                start_date=validated.start_date,
                end_date=validated.end_date,
                aggregation=validated.aggregation,
                dataset=validated.dataset,
                scenario=validated.scenario,
                model=validated.model,
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
                "Unexpected error in ClimateTimeseriesProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"Unexpected error: {exc}") from exc

    def __repr__(self) -> str:
        return f"<ClimateTimeseriesProcessor> {self.name}"

    @staticmethod
    def _validate_inputs(data: Dict[str, Any]) -> ClimateTimeseriesInput:
        """Parse and validate all process inputs with pydantic.

        Args:
            data: Raw OGC process input dict.

        Returns:
            Validated ClimateTimeseriesInput instance.

        Raises:
            ProcessorExecuteError: On any validation failure.
        """
        try:
            return ClimateTimeseriesInput(**data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ProcessorExecuteError(f"Invalid inputs: {errors}") from exc
