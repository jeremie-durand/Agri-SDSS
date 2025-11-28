from datetime import datetime as dt
from datetime import timezone
from os import getenv

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pipeline.config import Config
from rasterio.transform import from_origin
from shapely.geometry import Point


# ------------------------------------------
# Environment variable checks
# ------------------------------------------
def check_required_env_variables():
    required_vars = [
        "STAC_API_URL",
        "PYGEOAPI_API_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "DUCKDB_DATA_DIR",
        "DUCKDB_DATABASE",
    ]
    for var in required_vars:
        value = getenv(var)
        error_msg = f"Required env variable {var} is not set"
        if value is None:
            raise AssertionError(error_msg)

        stripped_value = value.strip()
        if stripped_value == "" or stripped_value.lower() == "none":
            raise AssertionError(error_msg)


# ------------------------------------------
# Pytest configuration for environment markers
# ------------------------------------------
# for mocked testing
@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "mocked: mark test to run only on mocked environment"
    )


# ------------------------------------------
# Global fixtures for API URLs
# ------------------------------------------
# API URLs based on config ports
STAC_API_URL = f"http://localhost:{Config.STAC_API_PORT}"
RASTER_API_URL = f"http://localhost:{Config.RASTER_API_PORT}"
VECTOR_API_URL = f"http://localhost:{Config.VECTOR_API_PORT}"
STACBROWSER_API_URL = f"http://localhost:{Config.FRONTEND_PORT}"
PYGEOAPI_API_URL = f"http://localhost:{Config.PYGEOAPI_API_PORT}"


@pytest.fixture(scope="session")
def stac_api_url_fixture():
    return STAC_API_URL


@pytest.fixture(scope="session")
def raster_api_url_fixture():
    return RASTER_API_URL


@pytest.fixture(scope="session")
def vector_api_url_fixture():
    return VECTOR_API_URL


@pytest.fixture(scope="session")
def stacbrowser_api_url_fixture():
    return STACBROWSER_API_URL


@pytest.fixture(scope="session")
def pygeoapi_api_url_fixture():
    return PYGEOAPI_API_URL


# ------------------------------------------
# Temporary raster file fixtures
# ------------------------------------------
@pytest.fixture(scope="session")
def tmp_raster_valid_fixture(tmp_path_factory):
    """
    Create a temporary raster file for testing.
    """
    raster_path = tmp_path_factory.mktemp("raster") / "test.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)
    return raster_path


# ------------------------------------------
# Sample vector data fixtures
# ------------------------------------------
@pytest.fixture(scope="session")
def single_feature_polygon_fixture():
    """Sample single feature response."""
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


@pytest.fixture(scope="session")
def gdf_points_fixture():
    """Complex GeoDataFrame with points."""
    gdf = gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "name": ["Feature1", "Feature2"],
            "datetime": [
                dt(2024, 6, 1, tzinfo=timezone.utc),
                dt(2024, 6, 2, tzinfo=timezone.utc),
            ],
            "bbox": [[-10, -10, 10, 10], [-20, -20, 20, 20]],
            "file_url": ["file1.tif", "file2.tif"],
            "metadata": [{"bands": 3}, {"bands": 4}],
            "geometry": [Point(0, 0), Point(1, 1)],
        },
        crs="EPSG:4326",
    )
    return gdf


@pytest.fixture(scope="session")
def gdf_points_fixture_id():
    """Complex GeoDataFrame with points."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "name": ["Feature1", "Feature2"],
            "geometry": gpd.points_from_xy([0, 0], [0, 1]),
        },
        crs="EPSG:4326",
    )
    return gdf


@pytest.fixture(scope="session")
def gdf_points_with_null_like_values_fixture():
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2, 3],
            "status": ["active", "N/A", "NULL"],  # Values that should be normalized
            "geometry": gpd.points_from_xy([0, 1, 2], [0, 1, 2]),
        },
        crs="EPSG:4326",
    )
    return gdf


@pytest.fixture(scope="session")
def gdf_polygon_fixture():
    """
    Sample GeoDataFrame for testing.
    """
    data = {
        "geometry": [Point(0, 0), Point(1, 1)],
        "other": [1, 2],
    }
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.crs = "EPSG:4326"
    return gdf
