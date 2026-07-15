"""
MSC GeoMet Observations OGC API – Processes implementation.

Retrieves surface weather station observations from the Meteorological Service
of Canada (MSC) GeoMet OGC API for a given spatial area and time range.
Returns a GeoJSON FeatureCollection with one Feature per station.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from .location_utils import resolve_location
from .msc_observations_metadata import PROCESS_METADATA
from .weather_backend import MSCBackend, MSCObservationsInput

logger = logging.getLogger(__name__)


class MSCObservationsProcessor(BaseProcessor):
    """OGC API Process: retrieve weather station observations from MSC GeoMet."""

    _backend: Optional[MSCBackend] = None

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        if MSCObservationsProcessor._backend is None:
            MSCObservationsProcessor._backend = MSCBackend()

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute the msc-observations process.

        Args:
            data: OGC process input dict.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/geo+json",
                {"id": "result", "value": <FeatureCollection>}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            validated = self._validate_inputs(data)
            bbox, _ = resolve_location(
                location_type=validated.location_type,
                farm_id=validated.farm_id,
                point=validated.point,
                bbox=validated.bbox,
                polygon=validated.polygon,
            )
            feature_collection = self._backend.fetch(  # type: ignore[union-attr]
                bbox=bbox,
                collection=validated.collection,
                variables=validated.variables,
                start_date=validated.start_date,
                end_date=validated.end_date,
                limit=validated.limit,
            )
            return "application/geo+json", {
                "id": "result",
                "value": feature_collection.to_geojson(),
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in MSCObservationsProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"Unexpected error: {exc}") from exc

    def __repr__(self) -> str:
        return f"<MSCObservationsProcessor> {self.name}"

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(data: Dict[str, Any]) -> MSCObservationsInput:
        """Parse and validate all process inputs with pydantic.

        Args:
            data: Raw OGC process input dict.

        Returns:
            Validated MSCObservationsInput instance.

        Raises:
            ProcessorExecuteError: On any validation failure.
        """
        try:
            return MSCObservationsInput(**data)
        except ValidationError as exc:
            errors = "; ".join(
                f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ProcessorExecuteError(f"Invalid inputs: {errors}") from exc
