"""Integration tests for the process jobs store against live PostgreSQL.

The queue, crash detection and retention rely on PostgreSQL semantics
(``SKIP LOCKED``, session advisory locks released with the connection) that a
mock cannot reproduce. Each test runs on a throwaway ``zz_it_jobs_*`` table.
They skip when PostgreSQL is unreachable; ``make test-process-api`` starts the
database service first.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from processes.config import DatabaseConfig
from processes.jobs.schema import ensure_schema
from processes.jobs.store import JobStore, NewJob
from psycopg import sql

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn_params() -> dict[str, Any]:
    params = DatabaseConfig().to_conn_params()
    try:
        psycopg.connect(**params, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable, skipping job store integration: {exc}")
    return params


@pytest.fixture
def table(conn_params: dict[str, Any]) -> Iterator[str]:
    name = f"public.zz_it_jobs_{uuid4().hex[:8]}"
    yield name
    with psycopg.connect(**conn_params) as conn:
        conn.execute(
            sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(*name.split(".")))
        )


@pytest.fixture
def store(table: str, conn_params: dict[str, Any]) -> JobStore:
    ensure_schema(table, conn_params)
    return JobStore(table, conn_params)


def _accepted(store: JobStore, locale: str = "fr") -> str:
    identifier = uuid4().hex
    store.insert_accepted(
        NewJob(
            identifier=identifier,
            process_id="lidar-fetch",
            locale=locale,
            inputs={"products": ["dtm"]},
        )
    )
    return identifier


def _execute(store: JobStore, query: str, *params: object) -> None:
    with store.connect() as conn:
        conn.execute(
            sql.SQL(query).format(table=sql.Identifier(*store.table.split("."))),
            params,
        )


def _sweep_until(store: JobStore, expected: list[str]) -> list[str]:
    """Sweep until ``expected`` is reported: a closed session's advisory locks
    are released only once its backend has exited."""
    deadline = time.monotonic() + 5
    while True:
        failed = store.sweep(lambda locale: f"stopped ({locale})")
        if failed == expected or time.monotonic() > deadline:
            return failed
        time.sleep(0.1)


def test_ensure_schema_is_concurrent_then_idempotent(
    table: str, conn_params: dict[str, Any]
):
    start_together = threading.Barrier(4)

    def create() -> None:
        start_together.wait(timeout=10)
        ensure_schema(table, conn_params)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(create) for _ in range(4)]:
            future.result()
    ensure_schema(table, conn_params)

    assert JobStore(table, conn_params).page(None, None) == ([], 0)


def test_two_claimers_get_distinct_jobs_in_creation_order(store: JobStore):
    first, second = _accepted(store), _accepted(store)

    with store.connect() as one, store.connect() as two, store.connect() as three:
        claimed_one = store.claim(one, "worker-1")
        claimed_two = store.claim(two, "worker-2")
        claimed_three = store.claim(three, "worker-3")

    assert claimed_one["identifier"] == first
    assert claimed_two["identifier"] == second
    assert claimed_three is None
    assert claimed_one["status"] == "running"
    assert claimed_one["inputs"] == {"products": ["dtm"]}


def test_accepted_sync_jobs_are_never_claimed(store: JobStore):
    identifier = _accepted(store)
    _execute(
        store,
        "UPDATE {table} SET execution_mode = 'sync' WHERE identifier = %s",
        identifier,
    )

    with store.connect() as worker:
        assert store.claim(worker, "worker-1") is None


def test_insert_accepted_notifies_listeners(store: JobStore):
    with store.connect(autocommit=True) as listener:
        store.listen(listener)
        identifier = _accepted(store)

        notification = next(listener.notifies(timeout=5, stop_after=1))

    assert notification.channel == store.channel
    assert notification.payload == identifier


def test_release_frees_the_job_for_the_sweeper(store: JobStore):
    identifier = _accepted(store)

    with store.connect() as owner:
        store.claim(owner, "worker-1")
        assert store.sweep(lambda locale: "stopped") == []

        store.release(owner, identifier)

        assert store.sweep(lambda locale: "stopped") == [identifier]


def test_sweep_fails_only_jobs_whose_owner_is_gone(store: JobStore):
    dead, alive = _accepted(store, "en"), _accepted(store)
    dead_owner = store.connect()
    store.claim(dead_owner, "worker-1")
    dead_owner.close()

    with store.connect() as live_owner:
        store.claim(live_owner, "worker-2")
        failed = _sweep_until(store, [dead])

        assert failed == [dead]
        assert store.get(dead)["status"] == "failed"
        assert store.get(dead)["message"] == "stopped (en)"
        assert store.get(alive)["status"] == "running"


def test_sweep_fails_sync_job_whose_request_died(store: JobStore):
    owner = store.connect()
    store.insert_running(
        owner, NewJob(identifier="sync-1", process_id="water-distance", locale="fr")
    )

    assert store.sweep(lambda locale: "stopped") == []

    owner.close()

    assert _sweep_until(store, ["sync-1"]) == ["sync-1"]


def test_finish_only_updates_a_running_job(store: JobStore):
    identifier = _accepted(store)

    assert not store.finish(identifier, "successful", "done")

    with store.connect() as owner:
        store.claim(owner, "worker-1")
        assert store.finish(
            identifier, "successful", "done", {"value": 1}, "application/json"
        )
        assert not store.finish(identifier, "failed", "late", conn=owner)

    job = store.get(identifier)
    assert job["status"] == "successful"
    assert job["result"] == {"value": 1}
    assert job["finished"].endswith("Z")


def test_purge_removes_only_old_finished_jobs(store: JobStore):
    old_done, recent_done, old_accepted = (
        _accepted(store),
        _accepted(store),
        _accepted(store),
    )
    _execute(
        store,
        "UPDATE {table} SET status = 'successful', finished = now() "
        "WHERE identifier = ANY(%s)",
        [old_done, recent_done],
    )
    _execute(
        store,
        "UPDATE {table} SET finished = now() - interval '8 days' "
        "WHERE identifier = %s",
        old_done,
    )
    _execute(
        store,
        "UPDATE {table} SET created = now() - interval '30 days' "
        "WHERE identifier = %s",
        old_accepted,
    )

    assert store.purge(7) == 1
    assert store.get(old_done) is None
    assert store.get(recent_done) is not None
    assert store.get(old_accepted) is not None


def test_page_is_newest_first_with_limit_and_offset(store: JobStore):
    identifiers = [_accepted(store) for _ in range(5)]
    for age, identifier in enumerate(reversed(identifiers)):
        _execute(
            store,
            "UPDATE {table} SET created = now() - make_interval(mins => %s) "
            "WHERE identifier = %s",
            age,
            identifier,
        )

    jobs, total = store.page(2, 1)

    assert total == 5
    assert [job["identifier"] for job in jobs] == [identifiers[3], identifiers[2]]


def test_delete_reports_whether_the_job_existed(store: JobStore):
    identifier = _accepted(store)

    assert store.delete(identifier)
    assert not store.delete(identifier)
    assert store.get(identifier) is None


def test_finish_on_the_owner_connection_commits(store: JobStore):
    with store.connect() as owner:
        store.insert_running(
            owner, NewJob(identifier="sync-1", process_id="water-distance", locale="fr")
        )

        assert store.finish("sync-1", "successful", "done", conn=owner)
        assert store.get("sync-1")["status"] == "successful"
