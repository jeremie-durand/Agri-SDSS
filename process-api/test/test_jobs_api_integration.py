"""Integration tests for async execution through pygeoapi's Processes API.

pygeoapi's real request handlers run against the job manager and a throwaway
``zz_it_jobs_*`` table on the live database. They skip when PostgreSQL is
unreachable.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import yaml
from flask.testing import FlaskClient
from process_api.test.job_api import PUBLIC_URL, api_config, build_app
from process_api.test.job_processors import (
    ASYNC_PROCESS,
    SLEEPING_PROCESS,
    SYNC_PROCESS,
    processes_config,
)
from processes.config import DatabaseConfig, JobQueueConfig
from processes.jobs.schema import ensure_schema
from processes.jobs.store import JobStore
from processes.worker import Worker, stopped_message
from psycopg import sql

pytestmark = pytest.mark.integration

ASYNC: dict[str, str] = {"Prefer": "respond-async"}
BODY: dict[str, Any] = {"inputs": {"farm_id": 7}}
PROCESSES: dict[str, dict[str, Any]] = processes_config(
    **{
        "async-echo": ASYNC_PROCESS,
        "sync-echo": SYNC_PROCESS,
        "sleeping": SLEEPING_PROCESS,
    }
)


@pytest.fixture(scope="module")
def conn_params() -> dict[str, Any]:
    params = DatabaseConfig().to_conn_params()
    try:
        psycopg.connect(**params, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable, skipping job API integration: {exc}")
    return params


@pytest.fixture
def table(conn_params: dict[str, Any]) -> Iterator[str]:
    name = f"public.zz_it_jobs_{uuid4().hex[:8]}"
    ensure_schema(name, conn_params)
    yield name
    with psycopg.connect(**conn_params) as conn:
        conn.execute(
            sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(*name.split(".")))
        )


@pytest.fixture
def store(table: str, conn_params: dict[str, Any]) -> JobStore:
    return JobStore(table, conn_params)


@pytest.fixture
def client(table: str) -> FlaskClient:
    return build_app(api_config(table, PROCESSES)).test_client()


def _submit(
    client: FlaskClient, process_id: str = "async-echo", body: dict | None = None
) -> str:
    response = client.post(
        f"/processes/{process_id}/execution?f=json", json=body or BODY, headers=ASYNC
    )
    assert response.status_code == 201
    return response.headers["Location"].rsplit("/", 1)[-1]


def _worker(store: JobStore, tmp_path: Path, name: str = "worker-it") -> Worker:
    return Worker(
        store,
        PROCESSES,
        JobQueueConfig(),
        name,
        heartbeat=tmp_path / f"{name}.heartbeat",
        join_slice=0.2,
    )


def _wait_for_status(store: JobStore, job_id: str, status: str) -> None:
    deadline = time.monotonic() + 60
    while store.get(job_id)["status"] != status:
        assert time.monotonic() < deadline, f"job never reached {status}"
        time.sleep(0.1)


@pytest.fixture
def worker_process(
    table: str, tmp_path: Path
) -> Iterator[Callable[[], subprocess.Popen]]:
    """Start ``python -m processes.worker`` on the throwaway table."""
    config_path = tmp_path / "pygeoapi-config.yaml"
    config_path.write_text(yaml.safe_dump(api_config(table, PROCESSES)))
    env = {
        **os.environ,
        "PYGEOAPI_CONFIG": str(config_path),
        "PROCESS_WORKER_POLL_SECONDS": "0.2",
    }
    started: list[subprocess.Popen] = []

    def start() -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, "-m", "processes.worker"],
            cwd="/app",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        started.append(process)
        return process

    yield start
    for process in started:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_async_request_is_accepted_with_location(client: FlaskClient):
    response = client.post(
        "/processes/async-echo/execution?f=json", json=BODY, headers=ASYNC
    )

    assert response.status_code == 201
    assert response.headers["Preference-Applied"] == "respond-async"
    job_id = response.headers["Location"].rsplit("/", 1)[-1]
    assert response.headers["Location"] == f"{PUBLIC_URL}/jobs/{job_id}"


def test_accepted_job_status_and_results_not_ready(
    client: FlaskClient, store: JobStore
):
    job_id = _submit(client)

    status = client.get(f"/jobs/{job_id}?f=json")
    results = client.get(f"/jobs/{job_id}/results?f=json")

    assert status.status_code == 200
    assert status.get_json()["status"] == "accepted"
    assert results.status_code == 404
    assert results.get_json()["code"] == "ResultNotReady"
    assert store.get(job_id)["inputs"] == BODY["inputs"]


def test_unknown_job_is_not_found(client: FlaskClient):
    assert client.get("/jobs/does-not-exist?f=json").status_code == 404


def test_sync_request_is_unchanged_and_unrecorded(client: FlaskClient, store: JobStore):
    response = client.post("/processes/async-echo/execution?f=json", json=BODY)

    assert response.status_code == 200
    assert response.get_json() == {"id": "result", "value": BODY["inputs"]}
    assert "Location" not in response.headers
    assert store.page(None, None) == ([], 0)


def test_async_request_on_sync_only_process_runs_sync(client: FlaskClient):
    response = client.post(
        "/processes/sync-echo/execution?f=json", json=BODY, headers=ASYNC
    )

    assert response.status_code == 200
    assert response.headers["Preference-Applied"] == "wait"
    assert "Location" not in response.headers
    assert response.get_json() == {"id": "result", "value": BODY["inputs"]}


def test_job_list_is_paged_newest_first(client: FlaskClient):
    submitted = [_submit(client) for _ in range(3)]

    listed = client.get("/jobs?f=json&limit=2").get_json()["jobs"]

    assert [job["jobID"] for job in listed] == submitted[::-1][:2]


@pytest.mark.parametrize(
    ("process_id", "options"),
    [
        ("sync-echo", ["sync-execute"]),
        ("async-echo", ["sync-execute", "async-execute"]),
    ],
)
def test_process_description_serves_declared_job_control(
    client: FlaskClient, process_id: str, options: list[str]
):
    one = client.get(f"/processes/{process_id}?f=json").get_json()
    listed = {
        process["id"]: process["jobControlOptions"]
        for process in client.get("/processes?f=json").get_json()["processes"]
    }

    assert one["jobControlOptions"] == options
    assert listed[process_id] == options
    assert "job-list" not in str(one["links"])


def test_worker_runs_the_job_to_the_sync_result(
    client: FlaskClient, store: JobStore, tmp_path: Path
):
    job_id = _submit(client)

    with store.connect(autocommit=True) as conn:
        assert _worker(store, tmp_path).run_once(conn)

    status = client.get(f"/jobs/{job_id}?f=json").get_json()
    results = client.get(f"/jobs/{job_id}/results?f=json")
    sync = client.post("/processes/async-echo/execution?f=json", json=BODY)
    assert status["status"] == "successful"
    assert results.status_code == 200
    assert results.get_json() == sync.get_json()


def test_two_workers_drain_two_jobs_once_each(
    client: FlaskClient, store: JobStore, tmp_path: Path
):
    jobs = [_submit(client, "sleeping", {"inputs": {"seconds": 1}}) for _ in range(2)]
    ran: dict[str, list[bool]] = {}

    def drain(name: str) -> None:
        worker = _worker(store, tmp_path, name)
        with store.connect(autocommit=True) as conn:
            ran[name] = [worker.run_once(conn), worker.run_once(conn)]

    threads = [threading.Thread(target=drain, args=(n,)) for n in ("w1", "w2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    finished = [store.get(job_id) for job_id in jobs]
    assert [job["status"] for job in finished] == ["successful", "successful"]
    assert {job["worker"] for job in finished} == {"w1", "w2"}
    assert ran == {"w1": [True, False], "w2": [True, False]}


def test_processes_answer_while_a_job_runs(
    client: FlaskClient, store: JobStore, tmp_path: Path
):
    job_id = _submit(client, "sleeping", {"inputs": {"seconds": 5}})
    worker = _worker(store, tmp_path)

    def run() -> None:
        with store.connect(autocommit=True) as conn:
            worker.run_once(conn)

    thread = threading.Thread(target=run)
    thread.start()
    _wait_for_status(store, job_id, "running")
    started = time.monotonic()
    response = client.get("/processes?f=json")
    elapsed = time.monotonic() - started
    still_running = store.get(job_id)["status"] == "running"
    thread.join(timeout=60)

    assert response.status_code == 200
    assert elapsed < 1
    assert still_running
    assert store.get(job_id)["status"] == "successful"


def test_killed_worker_job_is_failed_by_the_sweep(
    client: FlaskClient,
    store: JobStore,
    worker_process: Callable[[], subprocess.Popen],
):
    job_id = _submit(client, "sleeping", {"inputs": {"seconds": 3}})
    process = worker_process()
    _wait_for_status(store, job_id, "running")

    process.kill()
    process.wait(timeout=10)

    deadline = time.monotonic() + 10
    while store.sweep(stopped_message) != [job_id]:
        assert time.monotonic() < deadline, "the sweep never failed the job"
        time.sleep(0.1)
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["message"] == stopped_message("fr")


def test_worker_logs_ready_and_exits_zero_on_sigterm(
    client: FlaskClient,
    store: JobStore,
    worker_process: Callable[[], subprocess.Popen],
):
    job_id = _submit(client, "sleeping", {"inputs": {"seconds": 60}})
    process = worker_process()
    _wait_for_status(store, job_id, "running")

    process.send_signal(signal.SIGTERM)
    output, _ = process.communicate(timeout=30)

    assert process.returncode == 0
    assert "ready" in output
    assert store.get(job_id)["status"] == "failed"
    assert store.get(job_id)["message"] == stopped_message("fr")
