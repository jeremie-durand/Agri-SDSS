"""
Pedo coverage OGC API – Processes implementation.

Returns the pedological classes covering a parcel, from the IRDA 2026 soil map
or, where it covers too little of the parcel, the IRDA 2022 map.
"""

from __future__ import annotations

import logging
from typing import Any

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from agri_i18n import _

from .pedo_coverage_metadata import PROCESS_METADATA
from .spatial_backend import (
    PedoCoverageInput,
    parse_inputs,
    pedo_coverage,
    prepare_geometry,
)

logger = logging.getLogger(__name__)


class PedoCoverageProcessor(BaseProcessor):
    """OGC API Process: pedological classes covering a parcel."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)

    def execute(
        self, data: dict[str, Any], outputs: Any | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Execute the pedo-coverage process.

        Args:
            data: OGC process input dict.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/json", {"id": "result", "value": {"source",
                "symbole", "description", "count", "described_pct", "classes"}}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            validated = parse_inputs(PedoCoverageInput, data)
            coverage = pedo_coverage(
                prepare_geometry(validated), validated.min_described_pct
            )
            return "application/json", {"id": "result", "value": coverage}

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in PedoCoverageProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(
                _("An unexpected error occurred while running this process.")
            ) from exc

    def __repr__(self) -> str:
        return f"<PedoCoverageProcessor> {self.name}"
