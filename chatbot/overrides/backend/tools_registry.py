"""
Quebec SDSS (Spatial Decision Support System) Tools

Plain async functions following the upstream FunctionTool pattern.
Add to the kernel via: kernel.add_plugin(create_sdss_plugin(), "sdss")
"""

import logging
import os
from typing import Callable, Set

import httpx

logger = logging.getLogger(__name__)

PYGEOAPI_URL = os.environ.get("PYGEOAPI_INTERNAL_URL", "http://process-api:5000")


async def predict_soil_organic_matter(lat: float, lon: float, land_use: str) -> dict:
    """Predicts soil organic matter potential for a Quebec agricultural location."""
    raise NotImplementedError


async def query_agricultural_parcels(region: str) -> dict:
    """Returns agricultural parcel boundaries and attributes for a Quebec region."""
    raise NotImplementedError


async def search_soil_datasets(keywords: str) -> dict:
    """Searches available STAC datasets related to soil organic matter in Quebec."""
    raise NotImplementedError


async def run_som_process(parcel_id: str, year: int) -> dict:
    """Runs an OGC process to compute soil organic matter potential for a parcel."""
    raise NotImplementedError


async def list_pygeoapi_processes() -> list:
    """
    List all OGC processes available on the Process API server.
    Call this first to discover what spatial analyses are possible.
    Returns a list of objects with id, title, and description.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{PYGEOAPI_URL}/processes?f=json")
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "id": p["id"],
                "title": p.get("title", ""),
                "description": p.get("description", ""),
            }
            for p in data.get("processes", [])
        ]


async def get_process_schema(process_id: str) -> dict:
    """
    Get the full input/output schema for a specific OGC process.
    Call this before executing a process to understand required inputs.
    Returns the process metadata including inputs and outputs schemas.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{PYGEOAPI_URL}/processes/{process_id}?f=json")
        resp.raise_for_status()
        return resp.json()


async def execute_pygeoapi_process(process_id: str, inputs: dict) -> dict:
    """
    Execute an OGC API process on the Process API server.
    Use list_pygeoapi_processes to discover available processes and
    get_process_schema to know what inputs each one requires.
    Returns the process outputs as a dict.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PYGEOAPI_URL}/processes/{process_id}/execution",
            json={"inputs": inputs},
        )
        resp.raise_for_status()
        return resp.json()


def create_sdss_tools() -> Set[Callable]:
    """Return the set of SDSS tool functions for registration with the agent."""
    return {list_pygeoapi_processes, get_process_schema, execute_pygeoapi_process}


SDSS_TOOLS = create_sdss_tools()
