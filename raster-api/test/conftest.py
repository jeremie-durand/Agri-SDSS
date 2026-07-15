import os

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


@pytest.fixture(scope="session")
def raster_api_url_fixture():
    return os.getenv("RASTER_API_URL", "http://localhost:8082")


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
