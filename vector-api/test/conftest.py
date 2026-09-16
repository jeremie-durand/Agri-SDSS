import os
from unittest.mock import patch

import geopandas as gpd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point
from vector_api.duckdb_manager import DuckDBManager
from vector_api.parquet_router import router as parquet_router


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
