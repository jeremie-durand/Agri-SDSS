"""Start-up schema warm-up: fills the cache through the request gate (#281)."""

import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import anyio
import geopandas as gpd
import pytest
from shapely.geometry import Point
from vector_api import duckdb_manager
from vector_api.duckdb_manager import (
    DuckDBManager,
    DuckDBSpatialExtensionError,
    run_duckdb_request,
    warm_schema_cache,
)

pytestmark = pytest.mark.integration

RELEASE_TIMEOUT_S: float = 5.0
FIRST_COLLECTION: str = "test_collection"
SECOND_COLLECTION: str = "zz_collection"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def second_geoparquet(temp_parquet_dir: Path) -> Path:
    path = temp_parquet_dir / f"{SECOND_COLLECTION}.parquet"
    gpd.GeoDataFrame(
        {"gid": [1], "geometry": [Point(-71.2, 46.8)]}, crs="EPSG:4326"
    ).to_parquet(path)
    return path


@pytest.fixture
def manager(temp_parquet_dir: Path) -> Iterator[DuckDBManager]:
    real = DuckDBManager(data_dir=str(temp_parquet_dir))
    with patch("vector_api.duckdb_manager.get_shared_manager", return_value=real):
        yield real
    real.close()


@pytest.mark.anyio
async def test_warmup_caches_every_collection(
    manager: DuckDBManager, sample_geoparquet: Path, second_geoparquet: Path
) -> None:
    await warm_schema_cache()

    assert set(manager._schema_cache) == {FIRST_COLLECTION, SECOND_COLLECTION}


@pytest.mark.anyio
async def test_broken_file_is_logged_and_skipped(
    manager: DuckDBManager,
    temp_parquet_dir: Path,
    sample_geoparquet: Path,
    second_geoparquet: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (temp_parquet_dir / "broken.parquet").write_bytes(b"not a parquet file")

    with caplog.at_level(logging.WARNING, logger="vector_api.duckdb_manager"):
        await warm_schema_cache()

    assert set(manager._schema_cache) == {FIRST_COLLECTION, SECOND_COLLECTION}
    assert any(
        record.levelno == logging.WARNING and "broken" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_manager_failure_is_logged_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "vector_api.duckdb_manager.get_shared_manager",
            side_effect=DuckDBSpatialExtensionError("spatial missing"),
        ),
        caplog.at_level(logging.WARNING, logger="vector_api.duckdb_manager"),
    ):
        await warm_schema_cache()

    assert any(
        record.levelno == logging.WARNING and "spatial missing" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_request_runs_between_warmup_scans(
    manager: DuckDBManager,
    sample_geoparquet: Path,
    second_geoparquet: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    running = 0
    peak = 0
    counter_lock = threading.Lock()
    first_scan_entered = threading.Event()
    release_first_scan = threading.Event()
    original_get_schema = manager.get_parquet_schema

    def track(label: str) -> None:
        nonlocal running, peak
        with counter_lock:
            order.append(label)
            running += 1
            peak = max(peak, running)

    def untrack() -> None:
        nonlocal running
        with counter_lock:
            running -= 1

    def scan(collection_id: str) -> object:
        track(f"scan:{collection_id}")
        try:
            if collection_id == FIRST_COLLECTION:
                first_scan_entered.set()
                assert release_first_scan.wait(RELEASE_TIMEOUT_S)
            return original_get_schema(collection_id)
        finally:
            untrack()

    def request_work() -> None:
        track("request")
        untrack()

    monkeypatch.setattr(manager, "get_parquet_schema", scan)

    async with anyio.create_task_group() as tg:
        tg.start_soon(warm_schema_cache)
        assert await anyio.to_thread.run_sync(
            first_scan_entered.wait, RELEASE_TIMEOUT_S
        )
        tg.start_soon(run_duckdb_request, request_work)
        with anyio.fail_after(RELEASE_TIMEOUT_S):
            while duckdb_manager._REQUEST_GATE.statistics().tasks_waiting < 1:
                await anyio.sleep(0.01)
        release_first_scan.set()

    assert order == [
        f"scan:{FIRST_COLLECTION}",
        "request",
        f"scan:{SECOND_COLLECTION}",
    ]
    assert peak == 1
