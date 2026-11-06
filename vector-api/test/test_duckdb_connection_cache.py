"""Unit tests for the bounded cache of materialized DuckDB connections (#288)."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import duckdb
import geopandas as gpd
import pytest
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager, MaterializedEntry
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit

COLLECTIONS: list[str] = ["alpha", "bravo", "charlie"]


def _is_closed(conn: duckdb.DuckDBPyConnection) -> bool:
    try:
        conn.execute("SELECT 1").fetchone()
    except duckdb.ConnectionException:
        return True
    return False


def _feature_ids(manager: DuckDBManager, collection_id: str) -> list[int]:
    return [f["id"] for f in manager.query_items(collection_id, limit=10)["features"]]


def _invalidate_after_lookup(
    manager: DuckDBManager, monkeypatch: pytest.MonkeyPatch, times: int
) -> list[str]:
    """Make the next `times` lookups close their connection right after.

    Reproduces a request that looked up a connection just before an eviction
    or `/invalidate` closed it. Returns the list of raced collection ids.
    """
    lookup = manager._get_materialized_connection
    raced: list[str] = []

    def lookup_then_invalidate(collection_id: str) -> MaterializedEntry | None:
        entry = lookup(collection_id)
        if len(raced) < times:
            raced.append(collection_id)
            manager.invalidate_materialized(collection_id)
        return entry

    monkeypatch.setattr(
        manager, "_get_materialized_connection", lookup_then_invalidate
    )
    return raced


@pytest.fixture
def materialized_dir(tmp_path: Path) -> Path:
    for index, collection_id in enumerate(COLLECTIONS):
        gdf = gpd.GeoDataFrame(
            {
                "gid": [index * 10 + 1, index * 10 + 2],
                "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6)],
            },
            crs="EPSG:4326",
        )
        parquet_path = tmp_path / f"{collection_id}.parquet"
        gdf.to_parquet(parquet_path)
        materialize_collection(parquet_path, tmp_path / f"{collection_id}.duckdb")
    return tmp_path


@pytest.fixture
def manager(materialized_dir: Path) -> Iterator[DuckDBManager]:
    manager = DuckDBManager(data_dir=str(materialized_dir), max_open=2)
    yield manager
    manager.close()


def test_least_recently_used_connection_is_closed(manager: DuckDBManager) -> None:
    manager.query_items("alpha")
    manager.query_items("bravo")
    bravo_conn, _ = manager._materialized_conns["bravo"]
    manager.query_items("alpha")

    manager.query_items("charlie")

    assert set(manager._materialized_conns) == {"alpha", "charlie"}
    assert _is_closed(bravo_conn)


def test_evicted_collection_is_served_again(manager: DuckDBManager) -> None:
    before = _feature_ids(manager, "alpha")
    manager.query_items("bravo")
    manager.query_items("charlie")
    assert "alpha" not in manager._materialized_conns

    assert _feature_ids(manager, "alpha") == before == [1, 2]


def test_running_query_finishes_before_its_connection_is_closed(
    manager: DuckDBManager,
) -> None:
    manager.query_items("alpha")
    manager.query_items("bravo")
    alpha_conn, alpha_lock = manager._materialized_conns["alpha"]

    with alpha_lock:
        evicting = threading.Thread(target=manager.query_items, args=("charlie",))
        evicting.start()
        evicting.join(timeout=0.5)
        assert evicting.is_alive(), "eviction must wait for the running query"
        assert not _is_closed(alpha_conn)

    evicting.join(timeout=5)
    assert not evicting.is_alive()
    assert _is_closed(alpha_conn)
    assert set(manager._materialized_conns) == {"bravo", "charlie"}


def test_connection_closed_between_lookup_and_query_is_reopened(
    manager: DuckDBManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _feature_ids(manager, "alpha")
    raced = _invalidate_after_lookup(manager, monkeypatch, times=1)

    assert _feature_ids(manager, "alpha") == expected
    assert raced == ["alpha"]
    reopened_conn, _ = manager._materialized_conns["alpha"]
    assert not _is_closed(reopened_conn)


def test_get_item_by_id_survives_a_closed_connection(
    manager: DuckDBManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    raced = _invalidate_after_lookup(manager, monkeypatch, times=1)

    feature = manager.get_item_by_id("alpha", 2)

    assert feature is not None and feature["id"] == 2
    assert raced == ["alpha"]


def test_connection_closed_twice_falls_back_to_parquet(
    manager: DuckDBManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    expected = _feature_ids(manager, "alpha")
    raced = _invalidate_after_lookup(manager, monkeypatch, times=4)

    with caplog.at_level("WARNING", logger="vector_api.duckdb_manager"):
        assert _feature_ids(manager, "alpha") == expected
        feature = manager.get_item_by_id("bravo", 11)

    assert feature is not None and feature["id"] == 11
    assert raced == ["alpha", "alpha", "bravo", "bravo"]
    assert caplog.text.count("closed twice") == 2


FetchAll = Callable[..., tuple[list[tuple], list[str]]]


class _OverlapRecorder:
    """Wraps _fetchall_unlocked to record the peak number of concurrent calls.

    Each call waits on a barrier sized to the number of threads: when the
    slots allow it, all threads meet inside the call at the same time; when
    they don't, the barrier times out and the call proceeds alone.
    """

    def __init__(self, threads: int, timeout: float) -> None:
        self.barrier = threading.Barrier(threads, timeout=timeout)
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0

    def wrap(self, fetchall: FetchAll) -> FetchAll:
        def recording(
            conn: duckdb.DuckDBPyConnection, query: str, params: list | None = None
        ) -> tuple[list[tuple], list[str]]:
            with self.lock:
                self.running += 1
                self.peak = max(self.peak, self.running)
            try:
                try:
                    self.barrier.wait()
                except threading.BrokenBarrierError:
                    pass
                return fetchall(conn, query, params)
            finally:
                with self.lock:
                    self.running -= 1

        return recording


@pytest.mark.parametrize(
    ("max_queries", "barrier_timeout"),
    [(1, 0.5), (2, 5.0)],
    ids=["one-slot", "two-slots"],
)
def test_materialized_queries_never_exceed_the_query_slots(
    materialized_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_queries: int,
    barrier_timeout: float,
) -> None:
    """With one slot the barrier always times out, so it is kept short."""
    manager = DuckDBManager(
        data_dir=str(materialized_dir), max_open=2, max_queries=max_queries
    )
    try:
        manager.query_items("alpha")
        manager.query_items("bravo")
        recorder = _OverlapRecorder(threads=2, timeout=barrier_timeout)
        monkeypatch.setattr(
            manager,
            "_fetchall_unlocked",
            recorder.wrap(DuckDBManager._fetchall_unlocked),
        )
        errors: list[Exception] = []

        def query(collection_id: str) -> None:
            try:
                manager.get_item_by_id(collection_id, 1)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=query, args=(c,)) for c in ("alpha", "bravo")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
        assert recorder.peak == max_queries
    finally:
        manager.close()
