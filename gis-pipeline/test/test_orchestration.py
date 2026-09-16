"""End-to-end orchestration tests: vector → raster → STAC in one run.

These tests verify that process_vector_pipeline and process_raster_pipeline
share report_data correctly and that a failure in one stage does not abort the other.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from gis_pipeline.main import process_raster_pipeline, process_vector_pipeline
from gis_pipeline.modules.io_tools.input_data import discover_geodata
from gis_pipeline.modules.processing.geoprocessing import (
    geoprocessing_raster_data as _real_geoprocessing_raster_data,
)
from gis_pipeline.modules.processing.processing_stac import StacApiResponse
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from shapely.geometry import Point


def _make_report():
    return {
        "vector_data": {
            "processed": 0,
            "errors": 0,
            "skipped": 0,
            "non_spatial_csv": 0,
        },
        "raster_data": {"processed": 0, "errors": 0, "skipped": 0},
    }


@pytest.fixture
def input_dir(tmp_path):
    """Temporary input directory with one GeoJSON and one GeoTIFF."""
    data_dir = tmp_path / "input"
    data_dir.mkdir()

    gdf = gpd.GeoDataFrame(
        {"gid": [1], "name": ["site_a"]},
        geometry=[Point(0.0, 0.0)],
        crs="EPSG:4326",
    )
    gdf.to_file(data_dir / "test_vector.geojson", driver="GeoJSON")

    transform = from_bounds(-1.0, -1.0, 1.0, 1.0, 10, 10)
    with rasterio.open(
        data_dir / "test_raster.tif",
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=np.uint8,
        crs=CRS.from_epsg(4326),
        transform=transform,
    ) as dst:
        dst.write(np.full((1, 10, 10), 128, dtype=np.uint8))

    return data_dir


@pytest.fixture
def pipeline_args():
    return SimpleNamespace(crs=4326, collection="test_collection")


@pytest.fixture
def mock_pg():
    """PostGISManager mock acting as a context manager."""
    mg = MagicMock()
    mg.__enter__ = MagicMock(return_value=mg)
    mg.__exit__ = MagicMock(return_value=False)
    return mg


@pytest.fixture
def mock_stac_client():
    success = StacApiResponse(success=True, status_code=201, message="created", data={})
    client = MagicMock()
    client.post_collection.return_value = success
    client.upsert_items.return_value = success
    return client


def _fake_gdalwarp(cmd, *args, **kwargs):
    """Simulate gdalwarp: copy source raster to the output path."""
    src, dst = Path(cmd[-2]), Path(cmd[-1])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    return result


@pytest.mark.mocked
def test_vector_then_raster_populates_report_data(
    input_dir, pipeline_args, tmp_path, mock_pg, mock_stac_client
):
    """Full run: vector processing then raster+STAC share the same report_data dict."""
    cog_dir = tmp_path / "cogs"
    cog_dir.mkdir()
    report_data = _make_report()

    geodata = discover_geodata(input_dir)

    def _raster_with_cog_dir(**kwargs):
        return _real_geoprocessing_raster_data(output_dir=str(cog_dir), **kwargs)

    with (
        patch(
            "gis_pipeline.modules.processing.geoprocessing.PostGISManager",
            return_value=mock_pg,
        ),
        patch("gis_pipeline.modules.processing.geoprocessing.DuckDBManager"),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.subprocess.run",
            side_effect=_fake_gdalwarp,
        ),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.StacApiClient",
            return_value=mock_stac_client,
        ),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.geoprocessing_raster_data",
            new=_raster_with_cog_dir,
        ),
    ):
        process_vector_pipeline(
            vector_files=geodata["vectors"],
            args=pipeline_args,
            report_data=report_data,
        )

        process_raster_pipeline(
            raster_files=geodata["rasters"],
            args=pipeline_args,
            report_data=report_data,
        )

    assert report_data["vector_data"]["processed"] == 1
    assert report_data["vector_data"]["errors"] == 0
    assert report_data["raster_data"]["processed"] == 1
    assert report_data["raster_data"]["errors"] == 0

    mock_pg.insert_table_data.assert_called_once()
    mock_pg.insert_cog_metadata.assert_called_once()
    mock_stac_client.post_collection.assert_called_once()
    mock_stac_client.upsert_items.assert_called_once()


@pytest.mark.mocked
def test_vector_error_does_not_abort_raster_pipeline(
    input_dir, pipeline_args, tmp_path, mock_pg, mock_stac_client
):
    """A VectorProcessingError must not prevent raster processing and STAC publish."""
    cog_dir = tmp_path / "cogs"
    cog_dir.mkdir()
    report_data = _make_report()

    geodata = discover_geodata(input_dir)

    def _raster_with_cog_dir(**kwargs):
        return _real_geoprocessing_raster_data(output_dir=str(cog_dir), **kwargs)

    with (
        patch(
            "gis_pipeline.modules.processing.geoprocessing.PostGISManager",
            return_value=mock_pg,
        ),
        patch("gis_pipeline.modules.processing.geoprocessing.DuckDBManager"),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.subprocess.run",
            side_effect=_fake_gdalwarp,
        ),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.StacApiClient",
            return_value=mock_stac_client,
        ),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.geoprocessing_raster_data",
            new=_raster_with_cog_dir,
        ),
        patch(
            "fiona.listlayers",
            side_effect=Exception("simulated vector failure"),
        ),
    ):
        process_vector_pipeline(
            vector_files=geodata["vectors"],
            args=pipeline_args,
            report_data=report_data,
        )

        process_raster_pipeline(
            raster_files=geodata["rasters"],
            args=pipeline_args,
            report_data=report_data,
        )

    assert report_data["vector_data"]["errors"] == 1
    assert report_data["vector_data"]["processed"] == 0
    assert report_data["raster_data"]["processed"] == 1
    assert report_data["raster_data"]["errors"] == 0
    mock_stac_client.post_collection.assert_called_once()
    mock_stac_client.upsert_items.assert_called_once()
