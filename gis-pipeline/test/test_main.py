"""Unit tests for gis_pipeline/main.py — CLI parsing and pipeline orchestration."""

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ------------------------------------------
# parse_args
# ------------------------------------------


@pytest.mark.unit
def test_parse_args_return_parser_true_gives_argumentparser():
    """parse_args(return_parser=True) must return an ArgumentParser, not a Namespace."""
    from gis_pipeline.main import parse_args

    result = parse_args(return_parser=True)
    assert isinstance(result, argparse.ArgumentParser)


@pytest.mark.unit
def test_parse_args_defaults_match_config():
    """Default argument values must match Config class constants."""
    from gis_pipeline.core.config import Config
    from gis_pipeline.main import parse_args

    parser = parse_args(return_parser=True)
    args = parser.parse_args([])

    assert args.crs == Config.GLOBAL_CRS
    assert args.collection == Config.STAC_COLLECTION_ID
    assert args.input == Path(Config.INPUT_DATA_PATH)


@pytest.mark.unit
def test_parse_args_custom_crs():
    """--crs flag must override the default CRS value."""
    from gis_pipeline.main import parse_args

    parser = parse_args(return_parser=True)
    args = parser.parse_args(["--crs", "32198"])

    assert args.crs == 32198


@pytest.mark.unit
def test_parse_args_custom_collection():
    """--collection flag must set the collection ID."""
    from gis_pipeline.main import parse_args

    parser = parse_args(return_parser=True)
    args = parser.parse_args(["--collection", "my-dataset-2024"])

    assert args.collection == "my-dataset-2024"


# ------------------------------------------
# process_vector_pipeline
# ------------------------------------------


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


def _make_args(crs=4326, collection="test-collection"):
    return SimpleNamespace(crs=crs, collection=collection)


@pytest.mark.unit
def test_process_vector_pipeline_empty_list_increments_skipped():
    """An empty vector file list must increment the skipped counter and return early."""
    from gis_pipeline.main import process_vector_pipeline

    report_data = _make_report()
    process_vector_pipeline([], _make_args(), report_data)

    assert report_data["vector_data"]["skipped"] == 1
    assert report_data["vector_data"]["processed"] == 0


@pytest.mark.unit
def test_process_vector_pipeline_empty_list_does_not_call_geoprocessing():
    """An empty vector file list must not invoke geoprocessing functions."""
    from gis_pipeline.main import process_vector_pipeline

    report_data = _make_report()
    with patch(
        "gis_pipeline.modules.processing.geoprocessing.geoprocessing_vector_data"
    ) as mock_geo:
        process_vector_pipeline([], _make_args(), report_data)
        mock_geo.assert_not_called()


@pytest.mark.unit
def test_process_vector_pipeline_calls_geoprocessing_vector_data():
    """With spatial vector files, geoprocessing_vector_data must be called."""
    import geopandas as gpd
    from gis_pipeline.main import process_vector_pipeline
    from shapely.geometry import Point

    report_data = _make_report()
    fake_files = [Path("/data/input/parcels.geojson")]
    minimal_gdf = gpd.GeoDataFrame(
        {"gid": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326"
    )

    mock_src = MagicMock()
    mock_src.__len__ = MagicMock(return_value=1)
    mock_fiona_open = MagicMock()
    mock_fiona_open.return_value.__enter__ = MagicMock(return_value=mock_src)
    mock_fiona_open.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "gis_pipeline.modules.io_tools.input_data.detect_non_spatial_csv",
            return_value=[],
        ),
        patch("fiona.listlayers", return_value=["layer1"]),
        patch("fiona.open", mock_fiona_open),
        patch("geopandas.read_file", return_value=minimal_gdf),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.geoprocessing_vector_data"
        ) as mock_geo,
    ):
        process_vector_pipeline(fake_files, _make_args(), report_data)
        mock_geo.assert_called_once()

    assert report_data["vector_data"]["processed"] == 1


@pytest.mark.unit
def test_process_vector_pipeline_gis_error_increments_errors():
    """An error during vector layer reading must increment errors, not raise."""
    from gis_pipeline.main import process_vector_pipeline

    report_data = _make_report()
    fake_files = [Path("/data/input/bad.geojson")]

    with (
        patch(
            "gis_pipeline.modules.io_tools.input_data.detect_non_spatial_csv",
            return_value=[],
        ),
        patch("fiona.listlayers", side_effect=Exception("vector error")),
    ):
        process_vector_pipeline(fake_files, _make_args(), report_data)

    assert report_data["vector_data"]["errors"] == 1
    assert report_data["vector_data"]["processed"] == 0


# ------------------------------------------
# process_raster_pipeline
# ------------------------------------------


@pytest.mark.unit
def test_process_vector_pipeline_non_spatial_csv_increments_counter():
    """When detect_non_spatial_csv returns files, non_spatial_csv counter increments."""
    import pandas as pd
    from gis_pipeline.main import process_vector_pipeline

    report_data = _make_report()
    fake_csv = [Path("/data/input/nonspatial.csv")]

    with (
        patch(
            "gis_pipeline.modules.io_tools.input_data.detect_non_spatial_csv",
            return_value=fake_csv,
        ),
        patch(
            "gis_pipeline.modules.io_tools.input_data.read_csv_file",
            return_value=pd.DataFrame({"a": [1]}),
        ),
        patch("gis_pipeline.modules.db.duckdb_utils.DuckDBManager"),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.GeoprocessingVector"
            ".convert_vector_files_to_gdf",
            return_value=[],
        ),
        patch(
            "gis_pipeline.modules.processing.geoprocessing.geoprocessing_vector_data"
        ),
    ):
        process_vector_pipeline(fake_csv, _make_args(), report_data)

    assert report_data["vector_data"]["non_spatial_csv"] == 1


# ------------------------------------------
# process_raster_pipeline
# ------------------------------------------


@pytest.mark.unit
def test_process_raster_pipeline_empty_list_increments_skipped():
    """An empty raster file list must increment the skipped counter."""
    from gis_pipeline.main import process_raster_pipeline

    report_data = _make_report()
    process_raster_pipeline([], _make_args(), report_data)

    assert report_data["raster_data"]["skipped"] == 1
    assert report_data["raster_data"]["processed"] == 0


@pytest.mark.unit
def test_process_raster_pipeline_calls_geoprocessing_raster_data():
    """With raster files, geoprocessing_raster_data must be called."""
    from gis_pipeline.main import process_raster_pipeline

    report_data = _make_report()
    fake_files = [Path("/data/input/dem.tif"), Path("/data/input/ndvi.tif")]

    with patch(
        "gis_pipeline.modules.processing.geoprocessing.geoprocessing_raster_data"
    ) as mock_geo:
        process_raster_pipeline(fake_files, _make_args(), report_data)
        mock_geo.assert_called_once()

    assert report_data["raster_data"]["processed"] == 2


@pytest.mark.unit
def test_process_raster_pipeline_gis_error_increments_errors():
    """RasterProcessingError during raster processing must increment errors, not raise."""
    from gis_pipeline.core.exceptions import RasterProcessingError
    from gis_pipeline.main import process_raster_pipeline

    report_data = _make_report()
    fake_files = [Path("/data/input/bad.tif")]

    with patch(
        "gis_pipeline.modules.processing.geoprocessing.geoprocessing_raster_data",
        side_effect=RasterProcessingError("raster error"),
    ):
        process_raster_pipeline(fake_files, _make_args(), report_data)

    assert report_data["raster_data"]["errors"] == 1
    assert report_data["raster_data"]["processed"] == 0
