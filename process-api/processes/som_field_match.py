"""
SOM field match OGC API – Processes implementation.

Returns the SOM field boundaries near a parcel, GEE-positive fields first.
"""

from __future__ import annotations

import logging
from typing import Any

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from agri_i18n import _

from .som_field_match_metadata import PROCESS_METADATA
from .spatial_backend import (
    SomFieldMatchInput,
    match_som_fields,
    parse_inputs,
    prepare_geometry,
)

logger = logging.getLogger(__name__)


class SomFieldMatchProcessor(BaseProcessor):
    """OGC API Process: SOM fields within a tolerance of a parcel."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)

    def execute(
        self, data: dict[str, Any], outputs: Any | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Execute the som-field-match process.

        Args:
            data: OGC process input dict.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/json",
                {"id": "result", "value": {"matches": [...]}}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            validated = parse_inputs(SomFieldMatchInput, data)
            matches = match_som_fields(
                prepare_geometry(validated), validated.tolerance_m
            )
            return "application/json", {
                "id": "result",
                "value": {"matches": matches},
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in SomFieldMatchProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(
                _("An unexpected error occurred while running this process.")
            ) from exc

    def __repr__(self) -> str:
        return f"<SomFieldMatchProcessor> {self.name}"
