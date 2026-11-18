"""
Water distance OGC API – Processes implementation.

Returns the distance from a parcel to the nearest GRHQ hydrographic feature.
"""

from __future__ import annotations

import logging
from typing import Any

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from agri_i18n import _

from .spatial_backend import (
    WaterDistanceInput,
    nearest_water_distance,
    parse_inputs,
    prepare_geometry,
)
from .water_distance_metadata import PROCESS_METADATA

logger = logging.getLogger(__name__)


class WaterDistanceProcessor(BaseProcessor):
    """OGC API Process: distance from a parcel to the nearest water feature."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)

    def execute(
        self, data: dict[str, Any], outputs: Any | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Execute the water-distance process.

        Args:
            data: OGC process input dict.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/json",
                {"id": "result", "value": {"distance_m": <float | None>}}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            validated = parse_inputs(WaterDistanceInput, data)
            distance_m = nearest_water_distance(
                prepare_geometry(validated), validated.max_distance_m
            )
            return "application/json", {
                "id": "result",
                "value": {"distance_m": distance_m},
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in WaterDistanceProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(
                _("An unexpected error occurred while running this process.")
            ) from exc

    def __repr__(self) -> str:
        return f"<WaterDistanceProcessor> {self.name}"
