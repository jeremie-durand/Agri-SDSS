"""Integration tests for async execution through pygeoapi's Processes API.

pygeoapi's real request handlers run against the job manager and a throwaway
``zz_it_jobs_*`` table on the live database. They skip when PostgreSQL is
unreachable.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from flask.testing import FlaskClient
from process_api.test.job_api import PUBLIC_URL, api_config, build_app
from process_api.test.job_processors import (
    ASYNC_PROCESS,
    SYNC_PROCESS,
    processes_config,
)
from processes.config import DatabaseConfig
from processes.jobs.schema import ensure_schema
from processes.jobs.store import JobStore
from psycopg import sql

pytestmark = pytest.mark.integration

ASYNC: dict[str, str] = {"Prefer": "respond-async"}
BODY: dict[str, Any] = {"inputs": {"farm_id": 7}}


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
    config = api_config(
        table,
        processes_config(**{"async-echo": ASYNC_PROCESS, "sync-echo": SYNC_PROCESS}),
    )
    return build_app(config).test_client()


def _submit(client: FlaskClient) -> str:
    response = client.post(
        "/processes/async-echo/execution?f=json", json=BODY, headers=ASYNC
    )
    assert response.status_code == 201
    return response.headers["Location"].rsplit("/", 1)[-1]


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
