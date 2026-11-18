"""A large geometry collection served without its .duckdb is logged once (#282)."""

import logging
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pytest
from vector_api.duckdb_manager import DuckDBManager
from vector_api.materialize import materialize_collection

pytestmark = pytest.mark.unit

WARNING_TEXT: str = "from raw Parquet"
ONE_MB: int = 1024 * 1024


@pytest.fixture
def add_collection(
    tmp_path: Path, large_sources: dict[str, Path]
) -> Callable[[str, str], Path]:
    def add(collection_id: str, source: str) -> Path:
        path = tmp_path / f"{collection_id}.parquet"
        shutil.copy(large_sources[source], path)
        return path

    return add


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[DuckDBManager]:
    manager = DuckDBManager(data_dir=str(tmp_path), raw_parquet_warn_mb=1)
    yield manager
    manager.close()


def _raw_parquet_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and WARNING_TEXT in record.getMessage()
    ]


def test_large_collection_without_index_warns_once(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    size_mb = add_collection("big", "geo").stat().st_size / ONE_MB
    caplog.set_level(logging.WARNING)

    manager.query_items("big", limit=1)
    manager.query_items("big", limit=1, offset=5)
    manager.get_item_by_id("big", 1)

    warnings = _raw_parquet_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0] == (
        f"Serving big from raw Parquet ({size_mb:.1f} MB, no .duckdb)"
    )


def test_first_query_by_id_also_warns(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big", "geo")
    caplog.set_level(logging.WARNING)

    manager.get_item_by_id("big", 1)

    assert len(_raw_parquet_warnings(caplog)) == 1


def test_each_large_collection_warns_once(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big_a", "geo")
    add_collection("big_b", "geo")
    caplog.set_level(logging.WARNING)

    for collection_id in ("big_a", "big_b", "big_a", "big_b"):
        manager.query_items(collection_id, limit=1)

    warnings = _raw_parquet_warnings(caplog)
    assert len(warnings) == 2
    assert any("big_a" in w for w in warnings)
    assert any("big_b" in w for w in warnings)


def test_small_collection_without_index_is_silent(
    tmp_path: Path,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big", "geo")
    manager = DuckDBManager(data_dir=str(tmp_path), raw_parquet_warn_mb=10)
    caplog.set_level(logging.WARNING)
    try:
        manager.query_items("big", limit=1)
    finally:
        manager.close()

    assert _raw_parquet_warnings(caplog) == []


def test_large_collection_without_geometry_is_silent(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big_table", "plain")
    caplog.set_level(logging.WARNING)

    manager.query_items("big_table", limit=1)

    assert _raw_parquet_warnings(caplog) == []


def test_large_collection_with_index_is_silent(
    tmp_path: Path,
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    parquet_path = add_collection("big", "geo")
    materialize_collection(parquet_path, tmp_path / "big.duckdb")
    caplog.set_level(logging.WARNING)

    manager.query_items("big", limit=1)

    assert _raw_parquet_warnings(caplog) == []


def test_unopenable_index_is_not_reported_as_missing(
    tmp_path: Path,
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big", "geo")
    (tmp_path / "big.duckdb").write_text("not a real duckdb file")
    caplog.set_level(logging.WARNING)

    manager.query_items("big", limit=1)
    manager.get_item_by_id("big", 1)

    assert _raw_parquet_warnings(caplog) == []
    assert any("Failed to open materialized" in r.getMessage() for r in caplog.records)


def test_warns_when_the_bbox_scan_keeps_failing(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A schema whose bbox scan raised is not cached; the warning must not wait."""
    add_collection("big", "geo")
    original_fetchone = manager._fetchone

    def failing_bbox(query: str, params: list[Any] | None = None) -> tuple | None:
        if "ST_XMin" in query:
            raise duckdb.OutOfMemoryException("bbox scan out of memory")
        return original_fetchone(query, params)

    caplog.set_level(logging.WARNING)
    with patch.object(manager, "_fetchone", side_effect=failing_bbox):
        manager.query_items("big", limit=1)

    assert "big" not in manager._schema_cache
    assert len(_raw_parquet_warnings(caplog)) == 1


def test_invalidate_rearms_the_warning(
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big", "geo")
    caplog.set_level(logging.WARNING)

    manager.query_items("big", limit=1)
    manager.invalidate_materialized("big")
    manager.query_items("big", limit=1)

    assert len(_raw_parquet_warnings(caplog)) == 2


def test_warning_leaves_the_result_unchanged(
    tmp_path: Path,
    manager: DuckDBManager,
    add_collection: Callable[[str, str], Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_collection("big", "geo")
    silent = DuckDBManager(data_dir=str(tmp_path), raw_parquet_warn_mb=10_000)
    caplog.set_level(logging.WARNING)
    try:
        expected = silent.query_items("big", limit=5, offset=10)
    finally:
        silent.close()
    assert _raw_parquet_warnings(caplog) == []

    assert manager.query_items("big", limit=5, offset=10) == expected
    assert len(_raw_parquet_warnings(caplog)) == 1
