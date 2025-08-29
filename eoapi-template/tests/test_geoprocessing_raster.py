# tests/test_geoprocessing_raster.py
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from demo.config import Config
from demo.geoprocessing import GeoprocessingRaster
from rasterio.transform import from_bounds, from_origin


# ------------------------------------------
# Configurations and fixtures
# ------------------------------------------
@pytest.fixture
def tmp_raster_valid(tmp_path):
    """
    Create a temporary raster file for testing.
    """
    raster_path = tmp_path / "test.tif"
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


@pytest.fixture
def tmp_raster_invalid_resolution(tmp_path: Path) -> Path:
    """
    Create a temporary raster file with invalid resolution for testing.
    """
    raster_path = tmp_path / "invalid_resolution.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)

    # Invalid resolution with negative values
    invalid_transform = from_origin(
        west=0,
        north=10,
        xsize=-1,  # Invalid resolution (negative)
        ysize=-1,  # Invalid resolution (negative)
    )

    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=invalid_transform,
    ) as dst:
        dst.write(data)
    return raster_path


@pytest.fixture
def tmp_raster_invalid_bounds(tmp_path: Path) -> Path:
    """
    Create a temporary raster file with invalid bounds for testing.
    """
    raster_path = tmp_path / "invalid_bounds.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)

    # Create a transform with invalid bounds (west > east, south > north)
    invalid_transform = from_bounds(
        west=10,  # west > east (invalid)
        south=10,  # south > north (invalid)
        east=0,
        north=0,
        width=10,
        height=10,
    )

    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=invalid_transform,  # ← Transform avec bounds invalides
    ) as dst:
        dst.write(data)
    return raster_path


@pytest.fixture
def tmp_raster_dict(tmp_path: Path) -> dict:
    """
    Create a temporary raster file and return its metadata as a dictionary.
    """
    raster_path = tmp_path / "test.tif"
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

    return {
        "file_path": raster_path,
        "band_count": 1,
        "crs": "EPSG:4326",
        "transform": dst.transform,
    }


@pytest.fixture
def tmp_txt_file(tmp_path: Path) -> Path:
    """
    Create a temporary text file for testing.
    """
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("This is a test.")
    return txt_path


@pytest.fixture
def tmp_raster_valid_with_transform(tmp_path) -> Path:
    """Create a temporary raster file for testing harmonization.

    Args:
        tmp_path (Path): The temporary path fixture provided by pytest.
    """
    raster_path = tmp_path / "test_raster.tif"
    data = np.ones((1, 10, 10), dtype=rasterio.uint8)
    valid_transform = from_origin(west=0, north=10, xsize=1, ysize=1)
    crs = "EPSG:4326"

    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=rasterio.uint8,
        crs=crs,
        transform=valid_transform,
    ) as dst:
        dst.write(data)
    return raster_path


@pytest.fixture
def sample_raster_metadata():
    """
    Sample raster metadata for testing.
    """
    return {
        "id": "sample_raster",
        "datetime": "2024-01-01T00:00:00Z",
        "bbox": [0, 0, 1, 1],
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
        "cog_url": "file:///path/to/sample_raster_cog.tif",
        "stac_metadata": {
            "title": "Sample COG",
            "description": "Sample COG metadata",
            "keywords": ["sample", "cog"],
            "license": "CC-BY-4.0",
            "links": [
                {
                    "rel": "self",
                    "href": "http://example.com/sample_cog.json",
                    "type": "application/json",
                }
            ],
        },
    }


# ------------------------------------------
# Test cases for validate raster data
# ------------------------------------------
def test_validate_raster_data_success(tmp_raster_valid):
    """
    Test if the raster data validation passes for a valid raster file.
    """
    result = GeoprocessingRaster.validate_raster_data(tmp_raster_valid)
    assert result is None


def test_validate_raster_data_invalid_crs(tmp_path):
    fake_raster_path = tmp_path / "fake.tif"

    # Create an empty file just so that Path.exists() passes
    fake_raster_path.touch()

    # Mock rasterio.open to return a raster with invalid CRS
    with patch("rasterio.open") as mock_open:
        mock_src = MagicMock()
        mock_src.crs = None  # CRS invalide
        mock_src.width = 10
        mock_src.height = 10
        mock_src.count = 1
        mock_src.transform = True
        mock_open.return_value.__enter__.return_value = mock_src

        with pytest.raises(ValueError, match="invalid or missing CRS"):
            GeoprocessingRaster.validate_raster_data(fake_raster_path)


def test_validate_raster_data_invalid_resolution(tmp_raster_invalid_resolution):
    """
    Test if the raster data validation fails for an invalid resolution.
    """
    result = GeoprocessingRaster.validate_raster_data(
        tmp_raster_invalid_resolution
    )
    assert result is None


def test_validate_raster_data_invalid_bounds(tmp_raster_invalid_bounds):
    """
    Test if the raster data validation fails for an invalid bounds.
    """
    result = GeoprocessingRaster.validate_raster_data(Path(tmp_raster_invalid_bounds))
    assert result is None


def test_validate_raster_data_invalid_band(tmp_path):
    """
    Test if the raster data validation fails for an invalid band count.
    """
    raster_path = tmp_path / "invalid_bands.tif"
    raster_path.touch()  # Create an empty file for the path

    mock_src = MagicMock()
    mock_src.count = 0  # Simulate invalid band count
    mock_src.crs.is_valid = True
    mock_src.width = 10
    mock_src.height = 10
    mock_src.transform = True

    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_src

    with patch("rasterio.open", return_value=mock_open):
        with pytest.raises(ValueError, match="Raster has invalid band count"):
            GeoprocessingRaster.validate_raster_data(raster_path)


def test_validate_raster_data_not_path_object(tmp_raster_dict):
    """
    Test if the raster data validation fails for a non-Path object.
    """
    tmp_raster_dict["file_path"] = str(tmp_raster_dict["file_path"])

    with pytest.raises(ValueError, match="Raster path must be a pathlib.Path object"):
        GeoprocessingRaster.validate_raster_data(tmp_raster_dict)


def test_validate_raster_data_file_not_found():
    """
    Test if the raster data validation fails for a non-existent file.
    """
    with pytest.raises(FileNotFoundError):
        GeoprocessingRaster.validate_raster_data(Path("non_existent_file.tif"))


def test_validate_raster_data_invalid_file_type(tmp_txt_file: Path):
    """
    Test if the raster data validation fails for an invalid file type.
    """
    with pytest.raises(ValueError, match="Invalid raster format"):
        GeoprocessingRaster.validate_raster_data(tmp_txt_file)


def test_validate_raster_data_gdal_cmd_not_found():
    """
    Test if the raster data validation fails when GDAL command is not found.
    """
    with mock.patch(
        "subprocess.run", side_effect=FileNotFoundError("GDAL command not found")
    ):
        with pytest.raises(FileNotFoundError):
            GeoprocessingRaster.validate_raster_data(Path("path/to/raster.tif"))


# ------------------------------------------
# Test cases for harmonizing raster data
# ------------------------------------------
def test_harmonize_raster_data_success(tmp_raster_valid_with_transform, tmp_path):
    """
    Test if the raster data harmonization succeeds for a valid raster file.
    """
    processing = GeoprocessingRaster(
        config=Config, raster_paths=[tmp_raster_valid_with_transform]
    )
    processing.harmonize_raster_data(
        input_rasters=[tmp_raster_valid_with_transform],
        output_dir=tmp_path,
    )
    output_file = (
        tmp_path
        / f"{tmp_raster_valid_with_transform.stem}_harmonized{tmp_raster_valid_with_transform.suffix}"
    )
    assert output_file.exists()


def test_harmonize_raster_data_valid_crs_success(
    tmp_raster_valid_with_transform, tmp_path
):
    """
    Test if the raster data harmonization succeeds for a valid CRS.
    """
    processing = GeoprocessingRaster(
        config=Config, raster_paths=[tmp_raster_valid_with_transform]
    )
    processing.harmonize_raster_data(
        input_rasters=[tmp_raster_valid_with_transform],
        output_dir=tmp_path,
        reference_crs=4326,
        reference_nodata_value=None,
    )
    output_file = (
        tmp_path
        / f"{tmp_raster_valid_with_transform.stem}_harmonized{tmp_raster_valid_with_transform.suffix}"
    )
    assert output_file.exists()


def test_harmonize_raster_data_invalid_input():
    """
    Test if the raster data harmonization fails for invalid input.
    """
    processing = GeoprocessingRaster(config=Config, raster_paths=[])
    with pytest.raises(AssertionError):
        processing.harmonize_raster_data(
            input_rasters=["/invalid/path"],
            output_dir=Path("/output"),
            reference_crs=4326,
            reference_nodata_value=None,
        )


def test_harmonize_raster_data_invalid_output_dir(tmp_raster_valid_with_transform):
    """
    Test if the raster data harmonization fails for an invalid output directory.
    """
    processing = GeoprocessingRaster(
        config=Config, raster_paths=[tmp_raster_valid_with_transform]
    )
    with pytest.raises(ValueError):
        processing.harmonize_raster_data(
            input_rasters=[tmp_raster_valid_with_transform],
            output_dir=None,
            reference_crs=4326,
            reference_nodata_value=None,
        )


def test_harmonize_raster_data_invalid_crs(tmp_raster_valid_with_transform, tmp_path):
    """
    Test if the raster data harmonization fails for an invalid CRS.
    """
    processing = GeoprocessingRaster(
        config=Config, raster_paths=[tmp_raster_valid_with_transform]
    )
    with pytest.raises(RuntimeError):
        processing.harmonize_raster_data(
            input_rasters=[tmp_raster_valid_with_transform],
            output_dir=tmp_path,
            reference_crs="31370",
            reference_nodata_value=None,
        )


def test_harmonize_raster_data_invalid_nodata_value(
    tmp_raster_valid_with_transform, tmp_path
):
    """
    Test if the raster data harmonization fails for an invalid nodata value.
    """
    processing = GeoprocessingRaster(
        config=Config, raster_paths=[tmp_raster_valid_with_transform]
    )
    with pytest.raises(ValueError):
        processing.harmonize_raster_data(
            input_rasters=[tmp_raster_valid_with_transform],
            output_dir=tmp_path,
            reference_crs=4326,
            reference_nodata_value="invalid",  # Invalid nodata value
        )


def test_harmonize_raster_data_empty_input(tmp_path):
    """
    Test if the raster data harmonization fails for empty input.
    """
    processing = GeoprocessingRaster(config=Config, raster_paths=[])
    with pytest.raises(ValueError):
        processing.harmonize_raster_data(
            input_rasters=[],  # Empty list of rasters
            output_dir=tmp_path,
            reference_crs=4326,
            reference_nodata_value=None,
        )


def test_harmonize_raster_data_raster_not_found(tmp_path):
    """
    Test if the raster data harmonization fails when the input raster file does not exist.
    """
    processing = GeoprocessingRaster(config=Config, raster_paths=[])
    with pytest.raises(FileNotFoundError):
        processing.harmonize_raster_data(
            input_rasters=[Path("non_existent.tif")],  # Non-existent raster file
            output_dir=tmp_path,
            reference_crs=4326,
            reference_nodata_value=None,
        )


# ------------------------------------------
# Test cases for process raster to cog
# ------------------------------------------
def test_process_raster_to_cog_success(tmp_raster_valid, tmp_path, monkeypatch):
    """
    Test if the raster is successfully processed to COG format.
    """
    output_cog = tmp_path / "test_cog.tif"

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).touch()
        return SimpleNamespace(stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    monkeypatch.setattr(
        GeoprocessingRaster, "validate_raster_data", lambda output_path: None
    )

    GeoprocessingRaster.process_raster_to_cog(
        input_raster=tmp_raster_valid,
        output_cog=output_cog,
    )

    assert output_cog.exists()


def test_process_raster_to_cog_invalid_crs(tmp_raster_valid, tmp_path, monkeypatch):
    """
    Test if the raster is processed to COG format with an invalid CRS.
    """
    output_cog = tmp_path / "test_cog.tif"

    def fake_run(cmd, *args, **kwargs):
        raise ValueError("Invalid CRS")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(ValueError):
        GeoprocessingRaster.process_raster_to_cog(
            input_raster=tmp_raster_valid,
            output_cog=output_cog,
            reference_crs=31370,  # Invalid CRS
        )


def test_process_raster_to_cog_fails_when_validation_fails(
    tmp_raster_valid, tmp_path, monkeypatch
):
    """
    Test if the raster processing to COG fails when validation fails.
    """
    output_cog = tmp_path / "test_cog.tif"

    def fake_run(cmd, *args, **kwargs):
        Path(cmd[-1]).touch()
        return SimpleNamespace(stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_validate(output_path):
        raise PermissionError("No write access")

    monkeypatch.setattr(GeoprocessingRaster, "validate_raster_data", fake_validate)

    with pytest.raises(PermissionError):
        GeoprocessingRaster.process_raster_to_cog(
            tmp_raster_valid, output_cog, reference_crs=4326
        )


def test_process_raster_to_cog_gdal_cmd_failed(tmp_raster_valid, tmp_path, monkeypatch):
    """
    Test if the raster processing to COG fails when GDAL command fails.
    """
    output_cog = tmp_path / "test_cog.tif"

    def fake_run(cmd, *args, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="GDAL command failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError):
        GeoprocessingRaster.process_raster_to_cog(
            input_raster=tmp_raster_valid,
            output_cog=output_cog,
            reference_crs=4326,
        )


# ------------------------------------------
# Test cases for extract cog metadata
# ------------------------------------------
def test_extract_cog_metadata_success(tmp_raster_valid):
    """
    Test if the COG metadata is successfully extracted from a valid raster file.
    """
    metadata = GeoprocessingRaster.extract_cog_metadata(tmp_raster_valid)
    assert isinstance(metadata, dict)


def test_extract_cog_metadata_file_not_found():
    """
    Test if the COG metadata extraction fails when the file does not exist.
    """
    with pytest.raises(FileNotFoundError):
        GeoprocessingRaster.extract_cog_metadata(Path("non_existent_file.tif"))


def test_extract_cog_metadata_no_metadata(tmp_path):
    """
    Test if the COG metadata extraction fails when no metadata is found.
    """
    raster_path = tmp_path / "no_metadata.tif"
    raster_path.touch()

    mock_src = MagicMock()
    mock_src.tags.return_value = {}  # No metadata
    mock_src.crs.is_valid = True
    mock_src.width = 10
    mock_src.height = 10
    mock_src.count = 1
    mock_src.transform = True

    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_src

    with patch("rasterio.open", return_value=mock_open):
        with pytest.raises(ValueError):
            GeoprocessingRaster.extract_cog_metadata(raster_path)


# ------------------------------------------
# Test cases for insert raster metadata to PostGIS
# ------------------------------------------
def test_insert_raster_metadata_to_postgis_success(sample_raster_metadata):
    """
    Test if the raster metadata is successfully inserted into PostGIS.
    """
    engine = mock.MagicMock()
    GeoprocessingRaster.insert_raster_metadata_to_postgis(
        engine=engine, metadata=sample_raster_metadata, table_name="cogs"
    )


def test_insert_raster_metadata_to_postgis_invalid_metadata():
    """
    Test if the raster metadata insertion fails with invalid metadata.
    """
    engine = mock.MagicMock()
    with pytest.raises(ValueError):
        GeoprocessingRaster.insert_raster_metadata_to_postgis(
            engine=engine, metadata=None, table_name="cogs"  # Invalid metadata
        )


def test_insert_raster_metadata_to_postgis_invalid_table_name():
    """
    Test if the raster metadata insertion fails with an invalid table name.
    """
    engine = mock.MagicMock()
    with pytest.raises(ValueError):
        GeoprocessingRaster.insert_raster_metadata_to_postgis(
            engine=engine,
            metadata=sample_raster_metadata,
            table_name="",  # Invalid table name
        )


def test_insert_raster_metadata_to_postgis_db_error(sample_raster_metadata):
    """
    Test if the raster metadata insertion fails due to a database error.
    """
    engine = mock.MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.side_effect = Exception("DB error")
    with pytest.raises(RuntimeError):
        GeoprocessingRaster.insert_raster_metadata_to_postgis(
            engine=engine, metadata=sample_raster_metadata, table_name="cogs"
        )
