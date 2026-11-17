"""Mocked tests for the pygeoapi job manager (no database)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from process_api.test.job_processors import (
    ASYNC_PROCESS,
    FAILING_PROCESS,
    SYNC_PROCESS,
    processes_config,
)
from processes.jobs.manager import AgriJobManager
from processes.jobs.store import NewJob
from pygeoapi.plugin import load_plugin
from pygeoapi.process.base import JobNotFoundError, JobResultNotFoundError
from pygeoapi.process.manager.dummy import DummyManager
from pygeoapi.util import JobStatus, RequestedProcessExecutionMode

from agri_i18n import use_locale

pytestmark = pytest.mark.mocked

RESPOND_ASYNC = RequestedProcessExecutionMode.respond_async
WAIT = RequestedProcessExecutionMode.wait


class FakeStore:
    """In-memory stand-in recording what the manager writes."""

    def __init__(self) -> None:
        self.accepted: list[NewJob] = []
        self.jobs: dict[str, dict[str, Any]] = {}
        self.page_status: str | None = None

    def insert_accepted(self, job: NewJob) -> None:
        self.accepted.append(job)

    def page(
        self, limit: int | None, offset: int | None, status: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        self.page_status = status
        return list(self.jobs.values())[offset or 0 :][:limit], len(self.jobs)

    def get(self, identifier: str) -> dict[str, Any] | None:
        return self.jobs.get(identifier)

    def delete(self, identifier: str) -> bool:
        return self.jobs.pop(identifier, None) is not None


def _manager_def(**processors: str) -> dict[str, Any]:
    return {
        "name": "processes.jobs.manager.AgriJobManager",
        "connection": None,
        "output_dir": None,
        "processes": processes_config(**processors),
    }


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def manager(store: FakeStore) -> AgriJobManager:
    return AgriJobManager(
        _manager_def(
            **{
                "async-echo": ASYNC_PROCESS,
                "sync-echo": SYNC_PROCESS,
                "failing": FAILING_PROCESS,
            }
        ),
        store=store,
    )


def _dummy(**processors: str) -> DummyManager:
    return DummyManager(_manager_def(**processors) | {"name": "Dummy"})


def test_loads_as_pygeoapi_process_manager():
    manager = load_plugin("process_manager", _manager_def())

    assert isinstance(manager, AgriJobManager)
    assert manager.is_async


@pytest.mark.parametrize("response", ["raw", "document"])
def test_sync_success_matches_dummy(manager, store, response):
    _, mimetype, outputs, status, headers = manager.execute_process(
        "async-echo", {"x": 1}, requested_response=response
    )
    expected = _dummy(**{"async-echo": ASYNC_PROCESS}).execute_process(
        "async-echo", {"x": 1}, requested_response=response
    )

    assert (mimetype, outputs, status, headers) == expected[1:]
    assert status == JobStatus.successful
    assert store.accepted == []


def test_sync_failure_matches_dummy(manager, store):
    with use_locale("fr"):
        result = manager.execute_process("failing", {})
        expected = _dummy(failing=FAILING_PROCESS).execute_process("failing", {})

    assert result[1:] == expected[1:]
    assert result[3] == JobStatus.failed
    assert result[2]["description"] == (
        "Error executing process: Paramètres d'entrée invalides : farm_id"
    )
    assert store.accepted == []


def test_async_request_on_async_process_is_queued(manager, store):
    with use_locale("en"):
        job_id, mimetype, outputs, status, headers = manager.execute_process(
            "async-echo",
            {"x": 1},
            execution_mode=RESPOND_ASYNC,
            requested_outputs={"result": {}},
            requested_response="document",
        )

    assert status == JobStatus.accepted
    assert outputs is None
    assert headers == {"Preference-Applied": "respond-async"}
    assert store.accepted == [
        NewJob(
            identifier=job_id,
            process_id="async-echo",
            locale="en",
            inputs={"x": 1},
            requested_outputs={"result": {}},
            requested_response="document",
        )
    ]


def test_async_request_on_sync_only_process_runs_sync(manager, store):
    _, _, outputs, status, headers = manager.execute_process(
        "sync-echo", {"x": 1}, execution_mode=RESPOND_ASYNC
    )

    assert status == JobStatus.successful
    assert outputs == {"id": "result", "value": {"x": 1}}
    assert headers == {"Preference-Applied": "wait"}
    assert store.accepted == []


def test_explicit_wait_runs_sync(manager, store):
    *_, status, headers = manager.execute_process("async-echo", {}, execution_mode=WAIT)

    assert status == JobStatus.successful
    assert headers == {"Preference-Applied": "wait"}


def test_job_results(manager, store):
    store.jobs = {
        "done": {"status": "successful", "result": {"v": 1}, "mimetype": "a/b"},
        "running": {"status": "running", "result": None, "mimetype": None},
        "lost": {"status": "successful", "result": None, "mimetype": None},
    }

    assert manager.get_job_result("done") == ("a/b", {"v": 1})
    assert manager.get_job_result("running") == (None,)
    with pytest.raises(JobResultNotFoundError):
        manager.get_job_result("lost")
    with pytest.raises(JobNotFoundError):
        manager.get_job_result("missing")


def test_get_jobs_and_delete(manager, store):
    store.jobs = {"a": {"identifier": "a"}, "b": {"identifier": "b"}}

    assert manager.get_jobs(limit=1, offset=1) == {
        "jobs": [{"identifier": "b"}],
        "numberMatched": 2,
    }
    manager.get_jobs(status=JobStatus.accepted)
    assert store.page_status == "accepted"
    assert manager.delete_job("a")
    with pytest.raises(JobNotFoundError):
        manager.delete_job("a")
    with pytest.raises(JobNotFoundError):
        manager.get_job("a")


ASYNC_METADATA_MODULES: tuple[str, ...] = (
    "eo_sentinel_fetch_metadata",
    "quebec_lidar_fetch_metadata",
    "som_predict_soil_metadata",
)
SYNC_METADATA_MODULES: tuple[str, ...] = (
    "climate_indicators_metadata",
    "climate_timeseries_metadata",
    "msc_observations_metadata",
    "pedo_coverage_metadata",
    "som_field_match_metadata",
    "water_distance_metadata",
    "weather_timeseries_metadata",
)


@pytest.mark.unit
@pytest.mark.parametrize("module", ASYNC_METADATA_MODULES)
def test_long_processes_declare_async(module):
    metadata = importlib.import_module(f"processes.{module}").PROCESS_METADATA

    assert metadata["jobControlOptions"] == ["sync-execute", "async-execute"]


@pytest.mark.unit
@pytest.mark.parametrize("module", SYNC_METADATA_MODULES)
def test_short_processes_stay_sync_only(module):
    metadata = importlib.import_module(f"processes.{module}").PROCESS_METADATA

    assert metadata.get("jobControlOptions", ["sync-execute"]) == ["sync-execute"]
