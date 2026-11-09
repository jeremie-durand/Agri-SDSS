"""DuckDB work never blocks the event loop, and runs one request at a time (#280).

Each test drives the real ASGI app concurrently. A patched manager call blocks
on a ``threading.Event`` that the test sets only after a non-DuckDB request has
returned. While DuckDB work runs on the event loop, that request cannot be
served, so the wait times out and the test fails without hanging.
"""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx
import pytest
from vector_api import parquet_router
from vector_api.app import app
from vector_api.duckdb_manager import DuckDBManager, run_duckdb_request

RELEASE_TIMEOUT_S: float = 5.0
COLLECTION: str = "test_collection"
PARCEL: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [
        [[-72.35, 45.79], [-72.34, 45.79], [-72.34, 45.8], [-72.35, 45.79]]
    ],
}

READ_ROUTES: list[tuple[str, str]] = [
    ("/parquet/collections", "list_parquet_files"),
    (f"/parquet/collections/{COLLECTION}", "get_parquet_schema"),
    (f"/parquet/collections/{COLLECTION}/items", "query_items"),
    (f"/parquet/collections/{COLLECTION}/items/1", "get_item_by_id"),
    (f"/parquet/collections/{COLLECTION}/queryables", "get_parquet_schema"),
]


class Blocker:
    """Wraps manager calls so the first one blocks until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.timed_out: list[bool] = []
        self._calls = 0
        self._lock = threading.Lock()

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self._calls += 1
                first = self._calls == 1
            if first:
                self.entered.set()
                self.timed_out.append(not self.release.wait(RELEASE_TIMEOUT_S))
            return func(*args, **kwargs)

        return blocked

    async def wait_entered(self) -> None:
        assert await anyio.to_thread.run_sync(self.entered.wait, RELEASE_TIMEOUT_S)


class PeakCounter:
    """Wraps calls to record how many run at the same moment."""

    def __init__(self) -> None:
        self.peak = 0
        self._running = 0
        self._lock = threading.Lock()

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        def counted(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                self._running += 1
                self.peak = max(self.peak, self._running)
            try:
                time.sleep(0.2)
                return func(*args, **kwargs)
            finally:
                with self._lock:
                    self._running -= 1

        return counted


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def manager(temp_parquet_dir: Path, sample_geoparquet: Path) -> Iterator[DuckDBManager]:
    """Real manager over the sample collection, shared by the Parquet routes."""
    real = DuckDBManager(data_dir=str(temp_parquet_dir))
    with patch("vector_api.parquet_router.get_shared_manager", return_value=real):
        yield real
    real.close()


@pytest.fixture
def pedo_manager() -> Iterator[MagicMock]:
    """Pedo-properties dependencies: one overlapped polygon, no soil rows."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"code_polygone": "P1", "fraction": 1.0}])
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    fake = MagicMock()
    fake.parquet_source = MagicMock(return_value="pedo_table")
    fake.query_rows = MagicMock(return_value=[])
    with (
        patch(
            "vector_api.pedo_properties_router.get_pool",
            new=AsyncMock(return_value=pool),
        ),
        patch(
            "vector_api.pedo_properties_router.get_shared_manager",
            return_value=fake,
        ),
    ):
        yield fake


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def _landing_answers_while_blocked(
    blocker: Blocker, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    """Start the slow request, fetch GET / while it is blocked, then release it."""
    slow: dict[str, httpx.Response] = {}
    async with _client() as client:

        async def run_slow() -> None:
            slow["response"] = await client.request(method, path, **kwargs)

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_slow)
            await blocker.wait_entered()
            landing = await client.get("/")
            blocker.release.set()

    assert landing.status_code == 200
    assert blocker.timed_out == [False], "GET / waited for the DuckDB call"
    return slow["response"]


@pytest.mark.anyio
@pytest.mark.unit
async def test_gate_runs_one_request_at_a_time() -> None:
    """Concurrent run_duckdb_request calls never overlap, and all complete."""
    counter = PeakCounter()
    results: list[int] = []

    async def run(value: int) -> None:
        results.append(await run_duckdb_request(counter.wrap(lambda: value)))

    async with anyio.create_task_group() as tg:
        for value in range(3):
            tg.start_soon(run, value)

    assert sorted(results) == [0, 1, 2]
    assert counter.peak == 1


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("path,method_name", READ_ROUTES)
async def test_read_route_leaves_event_loop_free(
    manager: DuckDBManager, path: str, method_name: str
) -> None:
    """GET / answers while any Parquet read route waits on DuckDB."""
    blocker = Blocker()
    with patch.object(
        manager, method_name, blocker.wrap(getattr(manager, method_name))
    ):
        response = await _landing_answers_while_blocked(blocker, "GET", path)

    assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.integration
async def test_response_rendering_leaves_event_loop_free(
    manager: DuckDBManager,
) -> None:
    """GET / answers while a Parquet response body is being rendered."""
    blocker = Blocker()
    with patch.object(
        parquet_router,
        "_json_response",
        blocker.wrap(parquet_router._json_response),
    ):
        response = await _landing_answers_while_blocked(
            blocker, "GET", f"/parquet/collections/{COLLECTION}/items"
        )

    assert response.status_code == 200
    assert response.json()["numberReturned"] == 3


@pytest.mark.anyio
@pytest.mark.mocked
async def test_pedo_properties_join_leaves_event_loop_free(
    pedo_manager: MagicMock,
) -> None:
    """GET / answers while /pedo-properties runs its DuckDB joins."""
    blocker = Blocker()
    pedo_manager.query_rows = MagicMock(side_effect=blocker.wrap(lambda *_: []))

    response = await _landing_answers_while_blocked(
        blocker, "POST", "/pedo-properties", json={"geometry": PARCEL}
    )

    assert response.status_code == 200
    assert response.json()["components"] == []


@pytest.mark.anyio
@pytest.mark.integration
async def test_invalidate_leaves_event_loop_free(manager: DuckDBManager) -> None:
    """Invalidate waiting on a connection lock does not block GET /."""
    blocker = Blocker()
    with patch.object(
        manager,
        "invalidate_materialized",
        blocker.wrap(manager.invalidate_materialized),
    ):
        response = await _landing_answers_while_blocked(
            blocker, "POST", f"/parquet/collections/{COLLECTION}/invalidate"
        )

    assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.integration
async def test_invalidate_does_not_queue_behind_other_collection(
    manager: DuckDBManager,
) -> None:
    """Invalidating B answers while a query on A is still running."""
    blocker = Blocker()
    slow: dict[str, httpx.Response] = {}
    with patch.object(manager, "query_items", blocker.wrap(manager.query_items)):
        async with _client() as client:

            async def run_slow() -> None:
                slow["response"] = await client.get(
                    f"/parquet/collections/{COLLECTION}/items"
                )

            async with anyio.create_task_group() as tg:
                tg.start_soon(run_slow)
                await blocker.wait_entered()
                invalidate = await client.post(
                    "/parquet/collections/other_collection/invalidate"
                )
                blocker.release.set()

    assert invalidate.status_code == 200
    assert invalidate.json() == {
        "collection_id": "other_collection",
        "invalidated": False,
    }
    assert blocker.timed_out == [False], "invalidate waited for the query on A"
    assert slow["response"].status_code == 200


@pytest.mark.anyio
@pytest.mark.integration
async def test_two_parquet_requests_never_overlap(
    manager: DuckDBManager, temp_parquet_dir: Path, sample_geoparquet: Path
) -> None:
    """Two items requests never overlap in DuckDB work or response rendering."""
    (temp_parquet_dir / "second_collection.parquet").write_bytes(
        sample_geoparquet.read_bytes()
    )
    counter = PeakCounter()
    responses: list[httpx.Response] = []
    with (
        patch.object(manager, "query_items", counter.wrap(manager.query_items)),
        patch.object(
            parquet_router,
            "_json_response",
            counter.wrap(parquet_router._json_response),
        ),
    ):
        async with _client() as client:

            async def fetch(collection_id: str) -> None:
                responses.append(
                    await client.get(f"/parquet/collections/{collection_id}/items")
                )

            async with anyio.create_task_group() as tg:
                tg.start_soon(fetch, COLLECTION)
                tg.start_soon(fetch, "second_collection")

    assert [r.status_code for r in responses] == [200, 200]
    assert counter.peak == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_parquet_and_pedo_properties_never_overlap(
    manager: DuckDBManager, pedo_manager: MagicMock
) -> None:
    """A Parquet query and a pedo-properties join run their DuckDB work in turn."""
    counter = PeakCounter()
    pedo_manager.query_rows = MagicMock(side_effect=counter.wrap(lambda *_: []))
    responses: dict[str, httpx.Response] = {}
    with patch.object(manager, "query_items", counter.wrap(manager.query_items)):
        async with _client() as client:

            async def items() -> None:
                responses["items"] = await client.get(
                    f"/parquet/collections/{COLLECTION}/items"
                )

            async def pedo() -> None:
                responses["pedo"] = await client.post(
                    "/pedo-properties", json={"geometry": PARCEL}
                )

            async with anyio.create_task_group() as tg:
                tg.start_soon(items)
                tg.start_soon(pedo)

    assert responses["items"].status_code == 200
    assert responses["pedo"].status_code == 200
    assert counter.peak == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_landing_answers_with_many_queued_parquet_requests(
    manager: DuckDBManager,
) -> None:
    """GET / and the default thread pool stay free while 50 requests queue."""
    blocker = Blocker()
    responses: list[httpx.Response] = []
    with patch.object(manager, "query_items", blocker.wrap(manager.query_items)):
        async with _client() as client:

            async def fetch() -> None:
                responses.append(
                    await client.get(f"/parquet/collections/{COLLECTION}/items")
                )

            async with anyio.create_task_group() as tg:
                for _ in range(50):
                    tg.start_soon(fetch)
                await blocker.wait_entered()
                landing = await client.get("/")
                with anyio.fail_after(RELEASE_TIMEOUT_S):
                    await anyio.to_thread.run_sync(lambda: None)
                blocker.release.set()

    assert landing.status_code == 200
    assert blocker.timed_out == [False], "GET / waited for the queued requests"
    assert [r.status_code for r in responses] == [200] * 50
