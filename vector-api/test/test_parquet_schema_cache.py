"""Schema cache rules: a schema whose bbox scan failed is retried, not kept."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vector_api.duckdb_manager import DuckDBManager
from vector_api.parquet_router import router as parquet_router

pytestmark = pytest.mark.integration

COLLECTION_ID = "test_collection"
EXPECTED_BBOX = [-73.7, 45.5, -73.5, 45.7]


@pytest.fixture
def manager(temp_parquet_dir: Path) -> Iterator[DuckDBManager]:
    manager = DuckDBManager(data_dir=str(temp_parquet_dir))
    yield manager
    manager.close()


def _fail_bbox_once(manager: DuckDBManager) -> list[str]:
    """Make the first bbox query raise; return the log of bbox queries run."""
    original_fetchone = manager._fetchone
    bbox_queries: list[str] = []

    def fetchone(query: str, *args: Any, **kwargs: Any) -> Any:
        if "ST_XMin" in query:
            bbox_queries.append(query)
            if len(bbox_queries) == 1:
                raise duckdb.OutOfMemoryException("simulated bbox OOM")
        return original_fetchone(query, *args, **kwargs)

    manager._fetchone = fetchone
    return bbox_queries


def test_failed_bbox_scan_is_retried_on_next_call(
    manager: DuckDBManager, sample_geoparquet: Path
) -> None:
    bbox_queries = _fail_bbox_once(manager)

    first = manager.get_parquet_schema(COLLECTION_ID)
    second = manager.get_parquet_schema(COLLECTION_ID)

    assert first["bbox"] is None
    assert second["bbox"] == pytest.approx(EXPECTED_BBOX)
    assert len(bbox_queries) == 2


def test_successful_schema_is_computed_once(
    manager: DuckDBManager, sample_geoparquet: Path
) -> None:
    with patch.object(manager, "_fetchall", wraps=manager._fetchall) as fetchall:
        manager.get_parquet_schema(COLLECTION_ID)
        manager.get_parquet_schema(COLLECTION_ID)

    assert fetchall.call_count == 1


def test_schema_without_geometry_is_cached(
    manager: DuckDBManager, temp_parquet_dir: Path
) -> None:
    pd.DataFrame({"gid": [1, 2], "name": ["a", "b"]}).to_parquet(
        temp_parquet_dir / "attributes_only.parquet"
    )

    with patch.object(manager, "_fetchall", wraps=manager._fetchall) as fetchall:
        first = manager.get_parquet_schema("attributes_only")
        manager.get_parquet_schema("attributes_only")

    assert first["has_geometry"] is False
    assert first["bbox"] is None
    assert fetchall.call_count == 1


def test_collection_listing_recovers_extent_after_failed_bbox_scan(
    manager: DuckDBManager, sample_geoparquet: Path
) -> None:
    _fail_bbox_once(manager)
    app = FastAPI()
    app.include_router(parquet_router)

    with patch("vector_api.parquet_router.get_shared_manager", return_value=manager):
        with TestClient(app) as client:
            first = client.get("/parquet/collections").json()["collections"][0]
            second = client.get("/parquet/collections").json()["collections"][0]

    assert first["extent"] is None
    assert second["extent"]["spatial"]["bbox"][0] == pytest.approx(EXPECTED_BBOX)
