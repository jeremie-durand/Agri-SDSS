import os
import random
import string
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import geopandas as gpd
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
from vector_api.parquet_router import router as parquet_router

_SESSION_START: float = time.time()


@pytest.fixture
def session_start_time() -> float:
    """Wall-clock time at which this conftest was imported, before any test ran."""
    return _SESSION_START


@pytest.fixture(scope="session", autouse=True)
def _no_schema_warmup() -> Iterator[None]:
    """Keep the app lifespan from warming the real singleton.

    The test container bind-mounts the real data at DUCKDB_DATA_DIR, so a real
    warm-up would scan every production collection while holding the request
    gate. Session scope: a session-scoped TestClient (as in
    test_postgis_integration.py) enters the lifespan before any function-scoped
    patch exists, and its warm-up then stalls every later gated test.
    """
    with patch("vector_api.app.warm_schema_cache", new=AsyncMock()):
        yield


@pytest.fixture
def temp_parquet_dir(tmp_path):
    """Temporary directory for Parquet test files."""
    return tmp_path


@pytest.fixture
def sample_geoparquet(temp_parquet_dir):
    """GeoParquet file with 3 Point features near Montreal."""
    data = {
        "gid": [1, 2, 3],
        "name": ["Feature A", "Feature B", "Feature C"],
        "value": [100.5, 200.0, 300.75],
        "category": ["cat1", "cat2", "cat1"],
        "geometry": [Point(-73.5, 45.5), Point(-73.6, 45.6), Point(-73.7, 45.7)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    output_path = temp_parquet_dir / "test_collection.parquet"
    gdf.to_parquet(output_path)
    return output_path


@pytest.fixture(scope="session")
def large_sources(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """GeoParquet ("geo") and plain Parquet ("plain") files just over 1 MiB.

    Random 64-character strings keep compression from shrinking them below
    the 1 MB threshold set by the tests that use them.
    """
    base = tmp_path_factory.mktemp("large_sources")
    rows = 30_000
    rng = random.Random(282)
    alphabet = string.ascii_letters + string.digits
    text = ["".join(rng.choices(alphabet, k=64)) for _ in range(rows)]
    gids = list(range(1, rows + 1))

    geo_path = base / "geo.parquet"
    gpd.GeoDataFrame(
        {
            "gid": gids,
            "text": text,
            "geometry": [Point(-73.5 + i * 1e-6, 45.5) for i in gids],
        },
        crs="EPSG:4326",
    ).to_parquet(geo_path)

    plain_path = base / "plain.parquet"
    pd.DataFrame({"gid": gids, "text": text}).to_parquet(plain_path)

    for path in (geo_path, plain_path):
        assert path.stat().st_size > 1024 * 1024
    return {"geo": geo_path, "plain": plain_path}


@pytest.fixture(scope="session")
def vector_api_url_fixture():
    return os.getenv("VECTOR_API_URL", "http://localhost:8083")


@pytest.fixture(scope="session")
def single_feature_polygon_fixture():
    return {
        "type": "Feature",
        "id": "region-1",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-73.123, 45.456],
                    [-73.124, 45.457],
                    [-73.125, 45.456],
                    [-73.123, 45.456],
                ]
            ],
        },
        "properties": {
            "name": "Montérégie",
            "region_code": "16",
            "area_km2": 11111.5,
            "population": 1534000,
        },
    }


@pytest.fixture
def parquet_app_client(temp_parquet_dir, sample_geoparquet):
    """FastAPI TestClient with the parquet router and a real DuckDB manager.

    Shared between test_parquet_endpoints and test_parquet_ogc_compliance.
    """
    real_manager = DuckDBManager(data_dir=str(temp_parquet_dir))
    app = FastAPI()
    app.include_router(parquet_router)
    with patch(
        "vector_api.parquet_router.get_shared_manager", return_value=real_manager
    ):
        with TestClient(app) as client:
            yield client
    real_manager.close()
