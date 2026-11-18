"""Mocked tests for the async job worker (file-backed fake store, no database).

Each job runs in a real ``spawn`` child, as in production.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from process_api.test.job_processors import (
    ASYNC_PROCESS,
    BYTES_PROCESS,
    CRASHING_PROCESS,
    FAILING_PROCESS,
    NAN_PROCESS,
    SLEEPING_PROCESS,
    TYPED_PROCESS,
    processes_config,
)
from process_api.test.job_store_fake import FakeConnection, FileJobStore
from processes import worker as worker_module
from processes.config import JobQueueConfig
from processes.worker import (
    Worker,
    jobs_table,
    load_processes,
    stopped_message,
    timeout_message,
)

from agri_i18n import _, use_locale

pytestmark = pytest.mark.mocked

PROCESSES: dict[str, dict[str, Any]] = processes_config(
    echo=ASYNC_PROCESS,
    failing=FAILING_PROCESS,
    crashing=CRASHING_PROCESS,
    sleeping=SLEEPING_PROCESS,
    bytes=BYTES_PROCESS,
    nan=NAN_PROCESS,
    typed=TYPED_PROCESS,
)


@pytest.fixture
def store(tmp_path: Path) -> FileJobStore:
    return FileJobStore(tmp_path / "jobs.json")


def _worker(store: FileJobStore, tmp_path: Path, timeout_seconds: int = 60) -> Worker:
    return Worker(
        store,
        PROCESSES,
        JobQueueConfig(PROCESS_JOB_TIMEOUT_SECONDS=timeout_seconds),
        "worker-test",
        heartbeat=tmp_path / "heartbeat",
        join_slice=0.1,
        kill_grace=1,
    )


def _wait_for_status(store: FileJobStore, identifier: str, status: str) -> None:
    deadline = time.monotonic() + 30
    while store.get(identifier)["status"] != status:
        assert time.monotonic() < deadline, f"job never reached {status}"
        time.sleep(0.05)


def test_success_writes_the_document_wrapped_result(
    store: FileJobStore, tmp_path: Path
):
    store.add("job-1", "echo", inputs={"farm_id": 7}, requested_response="document")
    worker = _worker(store, tmp_path)

    assert worker.run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "successful"
    assert job["result"] == {"outputs": [{"id": "result", "value": {"farm_id": 7}}]}
    assert job["mimetype"] == "application/json"
    assert store.released() == ["job-1"]
    assert (tmp_path / "heartbeat").exists()


def test_processor_error_writes_the_sync_description(
    store: FileJobStore, tmp_path: Path
):
    store.add("job-1", "failing", locale="en")

    _worker(store, tmp_path).run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "failed"
    assert job["message"] == "Error executing process: Invalid inputs: farm_id"
    assert job["result"] is None


def test_processor_error_is_translated_in_the_job_locale(
    store: FileJobStore, tmp_path: Path
):
    store.add("job-1", "failing", locale="fr")

    _worker(store, tmp_path).run_once(FakeConnection())

    with use_locale("fr"):
        expected = _("Invalid inputs: {errors}").format(errors="farm_id")
    assert store.get("job-1")["message"] == f"Error executing process: {expected}"


def test_child_crash_fails_the_job_and_the_loop_continues(
    store: FileJobStore, tmp_path: Path
):
    store.add("job-1", "crashing")
    store.add("job-2", "echo")
    worker = _worker(store, tmp_path)

    assert worker.run_once(FakeConnection())
    assert worker.run_once(FakeConnection())
    assert not worker.run_once(FakeConnection())

    assert store.get("job-1")["status"] == "failed"
    assert store.get("job-1")["message"] == stopped_message("fr")
    assert store.get("job-2")["status"] == "successful"
    assert store.released() == ["job-1", "job-2"]


def test_job_past_the_time_budget_is_killed_and_failed(
    store: FileJobStore, tmp_path: Path
):
    store.add("job-1", "sleeping", inputs={"seconds": 60}, locale="en")
    started = time.monotonic()

    _worker(store, tmp_path, timeout_seconds=1).run_once(FakeConnection())

    assert time.monotonic() - started < 20
    job = store.get("job-1")
    assert job["status"] == "failed"
    assert job["message"] == timeout_message("en", 1)
    assert job["message"] == "The job exceeded its time budget of 1 seconds."
    assert store.released() == ["job-1"]


def test_non_json_result_fails_the_job(store: FileJobStore, tmp_path: Path):
    store.add("job-1", "bytes", locale="en")

    _worker(store, tmp_path).run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "failed"
    assert job["message"] == (
        "The process returned a result that cannot be stored as JSON."
    )


def test_nan_result_fails_the_job(store: FileJobStore, tmp_path: Path):
    store.add("job-1", "nan", locale="en")

    _worker(store, tmp_path).run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "failed"
    assert job["message"] == (
        "The process returned a result that cannot be stored as JSON."
    )


def test_result_is_serialised_like_the_sync_answer(store: FileJobStore, tmp_path: Path):
    store.add("job-1", "typed")

    _worker(store, tmp_path).run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "successful"
    assert job["result"] == {
        "id": "result",
        "value": {"ratio": 0.25, "date": "2026-11-18", "path": "/data/x.tif"},
    }


def test_unknown_process_fails_the_job(store: FileJobStore, tmp_path: Path):
    store.add("job-1", "removed-process")

    _worker(store, tmp_path).run_once(FakeConnection())

    job = store.get("job-1")
    assert job["status"] == "failed"
    assert job["message"].startswith("Error executing process:")


@pytest.fixture
def sigterm_handler() -> Iterator[None]:
    previous = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, previous)


def test_sigterm_fails_the_running_job_and_stops_serving(
    store: FileJobStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sigterm_handler: None,
):
    monkeypatch.setattr(worker_module, "ensure_schema", lambda *args: None)
    store.add("job-1", "sleeping", inputs={"seconds": 60})
    store.add("job-2", "echo")
    worker = _worker(store, tmp_path)
    signal.signal(signal.SIGTERM, worker.stop)

    def terminate_once_running() -> None:
        try:
            _wait_for_status(store, "job-1", "running")
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    killer = threading.Thread(target=terminate_once_running)
    killer.start()
    worker.serve()
    killer.join()

    assert store.get("job-1")["status"] == "failed"
    assert store.get("job-1")["message"] == stopped_message("fr")
    assert store.get("job-2")["status"] == "accepted"
    assert store.released() == ["job-1"]


def test_maintain_sweeps_and_purges_with_the_retention():
    store = MagicMock()
    store.sweep.return_value = []
    store.purge.return_value = 0
    worker = Worker(
        store, {}, JobQueueConfig(PROCESS_JOB_RETENTION_DAYS=3), "worker-test"
    )

    worker.maintain()

    store.sweep.assert_called_once_with(stopped_message)
    store.purge.assert_called_once_with(3)


def test_load_processes_keeps_process_resources_only():
    config = {
        "resources": {
            "lidar-fetch": {"type": "process", "processor": {"name": "a.B"}},
            "obs": {"type": "collection"},
        }
    }

    assert load_processes(config) == {
        "lidar-fetch": {"type": "process", "processor": {"name": "a.B"}}
    }


def test_jobs_table_follows_the_manager_connection():
    assert jobs_table({"server": {}}) == "public.process_jobs"
    assert (
        jobs_table({"server": {"manager": {"connection": {"table": "public.zz"}}}})
        == "public.zz"
    )
