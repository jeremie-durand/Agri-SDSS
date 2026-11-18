"""
Quebec SDSS (Spatial Decision Support System) Tools

Plain async functions following the upstream FunctionTool pattern.
Called by the /sdss/query agent loop in sdss_api.py.
"""

import asyncio
import logging
import os
import time
from contextvars import ContextVar
from typing import Callable, Set

import httpx

from agri_i18n import get_locale

logger = logging.getLogger(__name__)

PYGEOAPI_URL = os.environ.get("PYGEOAPI_INTERNAL_URL", "http://process-api:5000")
PROCESS_WAIT_SECONDS: float = float(
    os.environ.get("CHATBOT_PROCESS_WAIT_SECONDS", "480")
)
PROCESS_POLL_SECONDS: float = 3.0
STILL_RUNNING_MESSAGE: str = (
    "The job is still running on the server and will finish on its own. "
    "Tell the user it was started and give them the job_url, where they can "
    "follow it and read its results. Do not run the process again."
)

_wait_deadline: ContextVar[float | None] = ContextVar(
    "process_wait_deadline", default=None
)


class ProcessJobFailed(RuntimeError):
    """An async process job ended ``failed``; the message is the job's."""


def start_process_wait_budget() -> None:
    """Share one ``PROCESS_WAIT_SECONDS`` budget among every process tool call
    of the current request, so their waits together stay below its timeout."""
    _wait_deadline.set(time.monotonic() + PROCESS_WAIT_SECONDS)


def _locale_headers() -> dict:
    """Forward the request's language to process-api.

    These are server-side calls, so no browser header reaches them. Without
    this the process catalog and error messages fed to the LLM would always
    be the platform default, whatever language the user is chatting in.
    """
    return {"Accept-Language": get_locale()}


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
    async with httpx.AsyncClient(timeout=10, headers=_locale_headers()) as client:
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
    async with httpx.AsyncClient(timeout=10, headers=_locale_headers()) as client:
        resp = await client.get(f"{PYGEOAPI_URL}/processes/{process_id}?f=json")
        resp.raise_for_status()
        return resp.json()


async def execute_pygeoapi_process(process_id: str, inputs: dict) -> dict:
    """
    Execute an OGC API process on the Process API server.
    Use list_pygeoapi_processes to discover available processes and
    get_process_schema to know what inputs each one requires.
    Returns the process outputs as a dict. Long processes (Sentinel, LiDAR,
    SOM prediction) run as server jobs and may take several minutes; if one
    is still running when the wait ends, the result is
    {"job_id", "job_url", "status", "message"} instead of the outputs.
    """
    async with httpx.AsyncClient(timeout=30, headers=_locale_headers()) as client:
        resp = await client.post(
            f"{PYGEOAPI_URL}/processes/{process_id}/execution",
            json={"inputs": inputs},
            headers={"Prefer": "respond-async"},
        )
        resp.raise_for_status()
        if resp.status_code != 201:
            return resp.json()
        return await _wait_for_job(client, resp.headers["Location"])


async def _wait_for_job(client: httpx.AsyncClient, location: str) -> dict:
    """Poll a job on the internal URL until it finishes or the wait ends."""
    job_id = location.rstrip("/").rsplit("/", 1)[-1]
    job_url = f"{PYGEOAPI_URL}/jobs/{job_id}"
    deadline = _wait_deadline.get()
    if deadline is None:
        deadline = time.monotonic() + PROCESS_WAIT_SECONDS
    while True:
        await asyncio.sleep(PROCESS_POLL_SECONDS)
        resp = await client.get(f"{job_url}?f=json")
        resp.raise_for_status()
        job = resp.json()
        status = job.get("status")
        if status == "successful":
            results = await client.get(f"{job_url}/results?f=json")
            results.raise_for_status()
            return results.json()
        if status == "failed":
            raise ProcessJobFailed(job.get("message") or f"Job {job_id} failed")
        if time.monotonic() + PROCESS_POLL_SECONDS >= deadline:
            logger.info("Stopped waiting for job %s (%s)", job_id, status)
            return {
                "job_id": job_id,
                "job_url": location,
                "status": status,
                "message": STILL_RUNNING_MESSAGE,
            }


def create_sdss_tools() -> Set[Callable]:
    """Return the set of SDSS tool functions for registration with the agent."""
    return {list_pygeoapi_processes, get_process_schema, execute_pygeoapi_process}


SDSS_TOOLS = create_sdss_tools()
