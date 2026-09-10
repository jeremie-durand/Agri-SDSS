from datetime import datetime as dt
from datetime import timezone

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point


@pytest.fixture(scope="session")
def tmp_raster_valid_fixture(tmp_path_factory):
    raster_path = tmp_path_factory.mktemp("raster") / "test.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    transform = from_origin(0, 10, 1, 1)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)
    return raster_path


@pytest.fixture(scope="session")
def gdf_points_fixture():
    return gpd.GeoDataFrame(
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


@pytest.fixture(scope="session")
def gdf_points_fixture_id():
    return gpd.GeoDataFrame(
        {
            "gid": [1, 2],
            "name": ["Feature1", "Feature2"],
            "geometry": gpd.points_from_xy([0, 0], [0, 1]),
        },
        crs="EPSG:4326",
    )


@pytest.fixture(scope="session")
def gdf_points_with_null_like_values_fixture():
    return gpd.GeoDataFrame(
        {
            "gid": [1, 2, 3],
            "status": ["active", "N/A", "NULL"],
            "geometry": gpd.points_from_xy([0, 1, 2], [0, 1, 2]),
        },
        crs="EPSG:4326",
    )


@pytest.fixture(scope="session")
def gdf_polygon_fixture():
    data = {"geometry": [Point(0, 0), Point(1, 1)], "other": [1, 2]}
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.crs = "EPSG:4326"
    return gdf
