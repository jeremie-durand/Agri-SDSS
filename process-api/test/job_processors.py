"""Trivial processors for the job manager and worker tests.

They live in an importable module so pygeoapi's ``load_plugin`` and ``spawn``
children can resolve them by dotted path.
"""

from __future__ import annotations

import os
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from agri_i18n import _

ASYNC_PROCESS: str = "process_api.test.job_processors.AsyncEchoProcessor"
SYNC_PROCESS: str = "process_api.test.job_processors.SyncEchoProcessor"
FAILING_PROCESS: str = "process_api.test.job_processors.FailingProcessor"
CRASHING_PROCESS: str = "process_api.test.job_processors.CrashingProcessor"
SLEEPING_PROCESS: str = "process_api.test.job_processors.SleepingProcessor"
BYTES_PROCESS: str = "process_api.test.job_processors.BytesProcessor"
NAN_PROCESS: str = "process_api.test.job_processors.NanProcessor"
TYPED_PROCESS: str = "process_api.test.job_processors.TypedProcessor"


def _metadata(process_id: str, job_control: list[str]) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "id": process_id,
        "title": {"en": process_id, "fr": process_id},
        "description": {"en": process_id, "fr": process_id},
        "keywords": [],
        "jobControlOptions": job_control,
        "inputs": {},
        "outputs": {"result": {"schema": {"type": "object"}}},
        "example": {},
    }


ASYNC_CAPABLE: list[str] = ["sync-execute", "async-execute"]


class AsyncEchoProcessor(BaseProcessor):
    """Returns its inputs; declares async support."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("async-echo", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        return "application/json", {"id": "result", "value": data}


class SyncEchoProcessor(BaseProcessor):
    """Returns its inputs; sync-only."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("sync-echo", ["sync-execute"]))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        return "application/json", {"id": "result", "value": data}


class FailingProcessor(BaseProcessor):
    """Raises the translated validation error."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("failing", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        raise ProcessorExecuteError(
            _("Invalid inputs: {errors}").format(errors="farm_id")
        )


class CrashingProcessor(BaseProcessor):
    """Kills its own process, as the kernel's OOM killer would."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("crashing", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        os._exit(1)


class SleepingProcessor(BaseProcessor):
    """Sleeps ``data["seconds"]`` then returns them."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("sleeping", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        time.sleep(float(data["seconds"]))
        return "application/json", {"id": "result", "value": data["seconds"]}


class BytesProcessor(BaseProcessor):
    """Returns a non-JSON payload."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("bytes", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        return "image/png", b"\x89PNG"


class NanProcessor(BaseProcessor):
    """Returns a NaN, which JSON and jsonb reject."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("nan", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        return "application/json", {"id": "result", "value": float("nan")}


class TypedProcessor(BaseProcessor):
    """Returns values only pygeoapi's JSON serialiser accepts."""

    def __init__(self, processor_def: dict[str, Any]) -> None:
        super().__init__(processor_def, _metadata("typed", ASYNC_CAPABLE))

    def execute(self, data: dict[str, Any], outputs: Any = None) -> tuple[str, Any]:
        value = {
            "ratio": Decimal("0.25"),
            "date": date(2026, 11, 18),
            "path": Path("/data/x.tif"),
        }
        return "application/json", {"id": "result", "value": value}


def processes_config(**processors: str) -> dict[str, dict[str, Any]]:
    """pygeoapi ``resources`` entries mapping process ids to dotted classes."""
    return {
        process_id: {"type": "process", "processor": {"name": dotted}}
        for process_id, dotted in processors.items()
    }
