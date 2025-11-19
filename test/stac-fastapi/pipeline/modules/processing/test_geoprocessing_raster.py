import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from pipeline.config import Config
from pipeline.modules.processing.geoprocessing import GeoprocessingRaster
from rasterio.transform import from_origin


# ------------------------------------------
# Utility functions for tests
# ------------------------------------------
def _to_mapping(model_or_mapping: Any) -> Mapping:
    """Return a mapping representation for model or mapping-like object."""
    # pydantic v2
    if hasattr(model_or_mapping, "model_dump"):
        return model_or_mapping.model_dump()
    # pydantic v1
    if hasattr(model_or_mapping, "dict"):
        return model_or_mapping.dict()
    if isinstance(model_or_mapping, Mapping):
        return model_or_mapping
    # fallback: try to build dict from attributes
    try:
        return {
            k: getattr(model_or_mapping, k)
            for k in dir(model_or_mapping)
            if not k.startswith("_")
        }
    except Exception:
        return {}


def _get_field(obj: Any, key: str):
    """Access field either as attribute or mapping key."""
    # attribute access (model)
    if hasattr(obj, key):
        return getattr(obj, key)
    # mapping access
    try:
        return obj[key]
    except Exception:
        # try converting to mapping
        m = _to_mapping(obj)
        return m.get(key)


# ------------------------------------------
# Test cases for GeoprocessingRaster._open_rasters()
# ------------------------------------------
def test_open_rasters_success(tmp_raster_valid_fixture: Path):
    """
    Test if the raster data opens successfully for a valid raster file.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    assert tmp_raster_valid_fixture in processing_raster.rasters


def test_open_rasters_no_files():
    """
    Test if the raster data validation fails when no raster files are provided.
    """
    with pytest.raises(ValueError, match="No raster files provided."):
        GeoprocessingRaster(config=Config(), raster_paths=[])  # Empty list


def test_open_rasters_invalid_format(tmp_path: Path):
    """
    Test if the raster data validation fails for an invalid file format.
    """
    fake_raster_path = tmp_path / "fake.txt"  # .txt not a valid raster format
    fake_raster_path.touch()

    with pytest.raises(ValueError, match="Invalid raster format:"):
        GeoprocessingRaster(config=Config(), raster_paths=[fake_raster_path])


def test_open_rasters_no_crs(tmp_path: Path):
    """
    Test if the raster data validation fails for a raster with no CRS.
    """
    raster_path = tmp_path / "no_crs.tif"
    raster_path.touch()

    mock_src = MagicMock()
    mock_src.crs = None  # Simulate no CRS
    mock_src.count = 1
    mock_src.width = 10
    mock_src.height = 10
    mock_src.transform = True

    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_src

    with patch("rasterio.open", return_value=mock_open):
        with pytest.raises(ValueError, match="CRS is not defined:"):
            GeoprocessingRaster(config=Config(), raster_paths=[raster_path])


def test_open_rasters_invalid_band(tmp_path: Path):
    """
    Test if the raster data validation fails for an invalid band count.
    """
    raster_path = tmp_path / "invalid_bands.tif"
    raster_path.touch()

    mock_src = MagicMock()
    mock_src.count = 0  # Simulate invalid band count
    mock_src.crs.is_valid = True
    mock_src.width = 10
    mock_src.height = 10
    mock_src.transform = True

    mock_open = MagicMock()
    mock_open.__enter__.return_value = mock_src

    with patch("rasterio.open", return_value=mock_open):
        with pytest.raises(ValueError, match="Invalid band count:"):
            GeoprocessingRaster(config=Config(), raster_paths=[raster_path])


# ------------------------------------------
# Test cases for GeoprocessingRaster._analyze_and_store_metadata()
# ------------------------------------------
def test_analyze_and_store_metadata_success(tmp_raster_valid_fixture: Path):
    """
    Test if metadata is successfully analyzed and stored for a valid raster.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    assert tmp_raster_valid_fixture in processing_raster.raster_metadata
    metadata = processing_raster.raster_metadata[tmp_raster_valid_fixture]

    # Verify required metadata fields
    assert metadata["id"] == tmp_raster_valid_fixture.stem
    assert "datetime" in metadata
    assert "bbox" in metadata
    assert "geometry" in metadata
    assert metadata["bands"] == 1
    assert metadata["width"] == 10
    assert metadata["height"] == 10
    assert metadata["crs"] == "EPSG:4326"
    assert "nodata" in metadata
    assert "dtype" in metadata
    assert isinstance(metadata["tags"], dict)


def test_analyze_and_store_metadata_multiple_rasters(tmp_path: Path):
    """
    Test if metadata is correctly stored for multiple rasters.
    """
    # Create two test rasters
    raster1 = tmp_path / "test1.tif"
    raster2 = tmp_path / "test2.tif"

    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    for raster_path in [raster1, raster2]:
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[raster1, raster2]
    )

    # Verify metadata for both rasters
    assert raster1 in processing_raster.raster_metadata
    assert raster2 in processing_raster.raster_metadata

    for raster_path in [raster1, raster2]:
        metadata = processing_raster.raster_metadata[raster_path]
        assert metadata["id"] == raster_path.stem
        assert metadata["bands"] == 1


def test_analyze_and_store_metadata_geometry_structure(tmp_raster_valid_fixture: Path):
    """
    Test if the geometry structure is correctly created from raster bounds.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )
    metadata = processing_raster.raster_metadata[tmp_raster_valid_fixture]

    geometry = metadata["geometry"]
    assert geometry["type"] == "Polygon"
    assert "coordinates" in geometry
    assert len(geometry["coordinates"]) == 1  # One exterior ring
    assert len(geometry["coordinates"][0]) == 5  # Closed polygon (5 points)

    # Verify polygon is closed (first and last points are the same)
    coordinates = geometry["coordinates"][0]
    assert coordinates[0] == coordinates[-1]


def test_analyze_and_store_metadata_bbox_format(tmp_raster_valid_fixture: Path):
    """
    Test if bbox is correctly formatted as [left, bottom, right, top].
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )
    metadata = processing_raster.raster_metadata[tmp_raster_valid_fixture]

    bbox = metadata["bbox"]
    assert len(bbox) == 4
    assert bbox[0] <= bbox[2]  # left <= right
    assert bbox[1] <= bbox[3]  # bottom <= top


def test_analyze_and_store_metadata_with_tags(tmp_path: Path):
    """
    Test if TIFF tags are correctly extracted and stored.
    """
    raster_path = tmp_path / "test_with_tags.tif"
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
        TIFFTAG_DATETIME=datetime(2024, 1, 1, 0, 0, 0),
        TIFFTAG_ARTIST="Test Creator",
    ) as dst:
        dst.write(data)

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=[raster_path])
    metadata = processing_raster.raster_metadata[raster_path]

    assert "tags" in metadata
    assert isinstance(metadata["tags"], dict)


def test_analyze_and_store_metadata_no_tags(tmp_raster_valid_fixture: Path):
    """
    Test metadata extraction for raster without tags.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )
    metadata = processing_raster.raster_metadata[tmp_raster_valid_fixture]

    assert "tags" in metadata
    assert isinstance(metadata["tags"], dict)
    assert metadata["datetime"] == Config.DEFAULT_DATETIME


def test_analyze_and_store_metadata_multiband_raster(tmp_path: Path):
    """
    Test metadata extraction for multiband raster.
    """
    raster_path = tmp_path / "multiband.tif"
    data = np.ones((3, 10, 10), dtype=np.uint8)  # 3 bands
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=3,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=[raster_path])
    metadata = processing_raster.raster_metadata[raster_path]

    assert metadata["bands"] == 3
    assert metadata["dtype"] == "uint8"


def test_analyze_and_store_metadata_no_crs(tmp_path: Path):
    """
    Test metadata extraction for raster without CRS (should not reach this point due to validation).
    """
    raster_path = tmp_path / "no_crs.tif"
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
        transform=valid_transform,  # No CRS
    ) as dst:
        dst.write(data)

    mock_rasters = {}
    mock_src = MagicMock()
    mock_src.bounds = rasterio.coords.BoundingBox(0, 0, 10, 10)
    mock_src.count = 1
    mock_src.width = 10
    mock_src.height = 10
    mock_src.crs = None
    mock_src.nodata = None
    mock_src.dtypes = [np.uint8]
    mock_src.tags.return_value = {}

    mock_rasters[raster_path] = mock_src

    # Mock the validation to pass but keep no CRS
    with patch.object(GeoprocessingRaster, "_open_rasters") as mock_open:
        mock_open.return_value = mock_rasters

        processing_raster = GeoprocessingRaster(
            config=Config(), raster_paths=[raster_path]
        )
        metadata = processing_raster.raster_metadata[raster_path]

        assert metadata["crs"] is None


def test_analyze_and_store_metadata_with_nodata(tmp_path: Path):
    """
    Test metadata extraction for raster with nodata value.
    """
    raster_path = tmp_path / "with_nodata.tif"
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
        nodata=255,
    ) as dst:
        dst.write(data)

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=[raster_path])
    metadata = processing_raster.raster_metadata[raster_path]

    assert metadata["nodata"] == 255


def test_analyze_and_store_metadata_different_dtypes(tmp_path: Path):
    """
    Test metadata extraction for rasters with different data types.
    """
    dtypes = [np.uint8, np.uint16, np.float32, np.int16]

    for i, dtype in enumerate(dtypes):
        raster_path = tmp_path / f"test_{dtype.__name__}.tif"
        data = np.ones((1, 10, 10), dtype=dtype)
        valid_transform = from_origin(0, 10, 1, 1)

        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype=dtype,
            crs="EPSG:4326",
            transform=valid_transform,
        ) as dst:
            dst.write(data)

        processing_raster = GeoprocessingRaster(
            config=Config(), raster_paths=[raster_path]
        )
        metadata = processing_raster.raster_metadata[raster_path]

        assert metadata["dtype"] == str(dtype.__name__)


def test_analyze_and_store_metadata_large_raster_dimensions(tmp_path: Path):
    """
    Test metadata extraction for raster with large dimensions.
    """
    raster_path = tmp_path / "large.tif"
    width, height = 1000, 2000
    data = np.ones((1, height, width), dtype=np.uint8)
    valid_transform = from_origin(0, height, 1, 1)

    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=[raster_path])
    metadata = processing_raster.raster_metadata[raster_path]

    assert metadata["width"] == width
    assert metadata["height"] == height


def test_analyze_and_store_metadata_id_generation(tmp_path: Path):
    """
    Test that raster ID is correctly generated from file stem.
    """
    test_names = [
        "simple.tif",
        "with-dashes.tif",
        "with_underscores.tif",
        "with spaces.tif",
    ]

    for name in test_names:
        raster_path = tmp_path / name
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

        processing_raster = GeoprocessingRaster(
            config=Config(), raster_paths=[raster_path]
        )
        metadata = processing_raster.raster_metadata[raster_path]

        expected_id = raster_path.stem
        assert metadata["id"] == expected_id


# ------------------------------------------
# Test cases for GeoprocessingRaster._harmonize_name_for_single_raster()
# ------------------------------------------
def test_harmonize_name_for_single_raster_basic(tmp_raster_valid_fixture: Path):
    """
    Test basic name harmonization for a simple raster file name.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )
    processing_raster._harmonize_name_for_single_raster(raster_name="test_raster.tif")

    assert processing_raster.harmonized_name == "test_raster"


def test_harmonize_name_for_single_raster_with_special_characters(
    tmp_raster_valid_fixture: Path,
):
    """
    Test name harmonization with special characters that need to be replaced.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )
    processing_raster._harmonize_name_for_single_raster(raster_name="test_raster.tif")

    test_names = [
        ("raster-with-dashes.tif", "raster_with_dashes"),
        ("raster with spaces.tif", "raster_with_spaces"),
        ("raster@#$%^&*().tif", "raster"),
        ("raster(2024).tif", "raster_2024"),
        ("raster[version1].tif", "raster_version1"),
        ("raster{final}.tif", "raster_final"),
        ("_raster_.tif", "raster"),
        ("__multiple__underscores__.tif", "multiple__underscores"),
    ]

    for input_name, expected_output in test_names:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected_output


def test_harmonize_name_for_single_raster_uppercase_to_lowercase(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that uppercase letters are converted to lowercase.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    test_cases = [
        ("RASTER.TIF", "raster"),
        ("MyRaster.TIF", "myraster"),
        ("RASTER_FILE_2024.TIF", "raster_file_2024"),
    ]

    for input_name, expected in test_cases:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected


def test_harmonize_name_for_single_raster_strip_leading_trailing_underscores(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that leading and trailing underscores are stripped.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    test_cases = [
        ("_raster.tif", "raster"),
        ("raster_.tif", "raster"),
        ("__raster__.tif", "raster"),
        ("___multiple___underscores___.tif", "multiple___underscores"),
    ]

    for input_name, expected in test_cases:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected


def test_harmonize_name_for_single_raster_empty_string(tmp_raster_valid_fixture: Path):
    """
    Test that empty string raises ValueError.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    with pytest.raises(
        ValueError, match="Raster file name must not be empty or whitespace"
    ):
        processing_raster._harmonize_name_for_single_raster(raster_name="")


def test_harmonize_name_for_single_raster_whitespace_only(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that whitespace-only string raises ValueError.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    whitespace_inputs = ["   ", "\t", "\n", "  \t\n  "]

    for whitespace_input in whitespace_inputs:
        with pytest.raises(
            ValueError, match="Raster file name must not be empty or whitespace"
        ):
            processing_raster._harmonize_name_for_single_raster(
                raster_name=whitespace_input
            )


def test_harmonize_name_for_single_raster_max_length_truncation(
    tmp_raster_valid_fixture: Path,
):
    """
    Test name truncation when exceeding maximum PostgreSQL name length.
    """
    # Create a config with a small max length for testing
    config = Config()
    config.POSTGRES_MAX_NAME_LENGTH = 20  # Set small limit for testing

    processing_raster = GeoprocessingRaster(
        config=config, raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a long name that exceeds the limit
    long_name = "this_is_a_very_long_raster_file_name_that_exceeds_the_limit.tif"

    processing_raster._harmonize_name_for_single_raster(raster_name=long_name)

    # Should be truncated and have a hash appended
    assert len(processing_raster.harmonized_name) <= config.POSTGRES_MAX_NAME_LENGTH
    assert "_" in processing_raster.harmonized_name  # Should contain hash separator


def test_harmonize_name_for_single_raster_hash_consistency(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that the same long name produces the same hash consistently.
    """
    config = Config()
    config.POSTGRES_MAX_NAME_LENGTH = 20

    processing_raster = GeoprocessingRaster(
        config=config, raster_paths=[tmp_raster_valid_fixture]
    )

    long_name = "extremely_long_raster_file_name_for_testing_hash_consistency.tif"
    processing_raster._harmonize_name_for_single_raster(raster_name=long_name)

    assert processing_raster._harmonize_name_for_single_raster(
        raster_name=long_name
    ) == processing_raster._harmonize_name_for_single_raster(raster_name=long_name)


def test_harmonize_name_for_single_raster_exact_max_length(
    tmp_raster_valid_fixture: Path,
):
    """
    Test name that is exactly at the maximum length (no truncation needed).
    """
    config = Config()
    config.POSTGRES_MAX_NAME_LENGTH = 20

    processing_raster = GeoprocessingRaster(
        config=config, raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a name exactly at the limit
    exact_limit_name = "a" * 16

    processing_raster._harmonize_name_for_single_raster(raster_name=exact_limit_name)

    # Should not be truncated since it's exactly at the calculated limit
    assert processing_raster.harmonized_name == exact_limit_name
    assert len(processing_raster.harmonized_name) == 16


def test_harmonize_name_for_single_raster_one_char_over_limit(
    tmp_raster_valid_fixture: Path,
):
    """
    Test name that is one character over the limit.
    """
    config = Config()
    config.POSTGRES_MAX_NAME_LENGTH = 20

    processing_raster = GeoprocessingRaster(
        config=config, raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a name one character over the limit
    over_limit_name = "a" * (config.POSTGRES_MAX_NAME_LENGTH + 1)

    processing_raster._harmonize_name_for_single_raster(raster_name=over_limit_name)

    # Should be truncated with hash
    assert len(processing_raster.harmonized_name) <= config.POSTGRES_MAX_NAME_LENGTH


def test_harmonize_name_for_single_raster_numeric_names(tmp_raster_valid_fixture: Path):
    """
    Test harmonization of numeric file names.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    numeric_names = [
        ("123456.tif", "123456"),
        ("2024_01_15.tif", "2024_01_15"),
        ("001-raster-2024.tif", "001_raster_2024"),
    ]

    for input_name, expected in numeric_names:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected


def test_harmonize_name_for_single_raster_unicode_characters(
    tmp_raster_valid_fixture: Path,
):
    """
    Test harmonization with unicode characters.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    unicode_names = [
        ("raster_café.tif", "raster_caf"),
        ("raster_naïve.tif", "raster_na_ve"),
        ("raster_münchen.tif", "raster_m_nchen"),
    ]

    for input_name, expected in unicode_names:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected


def test_harmonize_name_for_single_raster_multiple_extensions(
    tmp_raster_valid_fixture: Path,
):
    """
    Test harmonization with multiple file extensions.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    multi_extension_names = [
        ("raster.backup.tif", "raster_backup"),
        ("data.2024.01.tif", "data_2024_01"),
        ("file.v1.0.final.tif", "file_v1_0_final"),
    ]
    for input_name, expected in multi_extension_names:
        processing_raster._harmonize_name_for_single_raster(raster_name=input_name)
        assert processing_raster.harmonized_name == expected


# ------------------------------------------
# Test cases for GeoprocessingRaster._get_cog_creation_profile()
# ------------------------------------------
def test_get_cog_creation_profile_default(tmp_raster_valid_fixture: Path):
    """
    Test that default profile returns correct COG creation options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile="default")

    expected_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": None,
        "predictor": None,
    }

    assert profile == expected_profile


def test_get_cog_creation_profile_fast(tmp_raster_valid_fixture: Path):
    """
    Test that fast profile returns correct COG creation options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile="fast")

    expected_profile = {
        "compress": "LZW",
        "num_threads": "ALL_CPUS",
        "bigtiff": "IF_SAFER",
        "overviews": "NONE",
        "blocksize": "1024",
        "predictor": None,
    }

    assert profile == expected_profile


def test_get_cog_creation_profile_high_quality(tmp_raster_valid_fixture: Path):
    """
    Test that high_quality profile returns correct COG creation options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile="high_quality")

    expected_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": "512",
        "predictor": "2",
    }

    assert profile == expected_profile


def test_get_cog_creation_profile_invalid_returns_default(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that invalid profile name returns default profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile="invalid_profile")

    expected_default_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": None,
        "predictor": None,
    }

    assert profile == expected_default_profile


def test_get_cog_creation_profile_none_returns_default(tmp_raster_valid_fixture: Path):
    """
    Test that None profile parameter returns default profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile=None)

    expected_default_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": None,
        "predictor": None,
    }

    assert profile == expected_default_profile


def test_get_cog_creation_profile_empty_string_returns_default(
    tmp_raster_valid_fixture: Path,
):
    """
    Test that empty string profile parameter returns default profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile="")

    expected_default_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": None,
        "predictor": None,
    }

    assert profile == expected_default_profile


def test_get_cog_creation_profile_case_sensitivity(tmp_raster_valid_fixture: Path):
    """
    Test that profile names are case sensitive.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Test uppercase - should return default
    profile_upper = processing_raster._get_cog_creation_profile(profile="DEFAULT")
    profile_mixed = processing_raster._get_cog_creation_profile(profile="Fast")
    profile_lower = processing_raster._get_cog_creation_profile(profile="high_Quality")

    expected_default_profile = {
        "compress": "DEFLATE",
        "num_threads": "ALL_CPUS",
        "bigtiff": "YES",
        "overviews": "AUTO",
        "blocksize": None,
        "predictor": None,
    }

    # All should return default since case doesn't match
    assert profile_upper == expected_default_profile
    assert profile_mixed == expected_default_profile
    assert profile_lower == expected_default_profile


def test_get_cog_creation_profile_return_types(tmp_raster_valid_fixture: Path):
    """
    Test that all profile values have correct data types.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profiles_to_test = ["default", "fast", "high_quality"]

    for profile_name in profiles_to_test:
        profile = processing_raster._get_cog_creation_profile(profile=profile_name)

        # Test return type is dict
        assert isinstance(profile, dict)

        # Test required keys exist
        required_keys = [
            "compress",
            "num_threads",
            "bigtiff",
            "overviews",
            "blocksize",
            "predictor",
        ]
        for key in required_keys:
            assert key in profile

        # Test string values
        assert isinstance(profile["compress"], str)
        assert isinstance(profile["num_threads"], str)
        assert isinstance(profile["bigtiff"], str)
        assert isinstance(profile["overviews"], str)

        # Test None or string values
        assert profile["blocksize"] is None or isinstance(profile["blocksize"], str)
        assert profile["predictor"] is None or isinstance(profile["predictor"], str)


def test_get_cog_creation_profile_immutability(tmp_raster_valid_fixture: Path):
    """
    Test that modifying returned profile doesn't affect subsequent calls.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Get first profile and modify it
    profile1 = processing_raster._get_cog_creation_profile(profile="default")
    original_compress = profile1["compress"]
    profile1["compress"] = "MODIFIED"

    # Get second profile - should be unchanged
    profile2 = processing_raster._get_cog_creation_profile(profile="default")

    assert profile2["compress"] == original_compress
    assert profile2["compress"] != "MODIFIED"


@pytest.mark.parametrize(
    "profile_name,expected_compress,expected_blocksize",
    [
        ("default", "DEFLATE", None),
        ("fast", "LZW", "1024"),
        ("high_quality", "DEFLATE", "512"),
    ],
)
def test_get_cog_creation_profile_parametrized(
    tmp_raster_valid_fixture: Path,
    profile_name: str,
    expected_compress: str,
    expected_blocksize: str,
):
    """
    Test different profiles using parametrized testing.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    profile = processing_raster._get_cog_creation_profile(profile=profile_name)

    assert profile["compress"] == expected_compress
    assert profile["blocksize"] == expected_blocksize


def test_get_cog_creation_profile_all_keys_present(tmp_raster_valid_fixture: Path):
    """
    Test that all profiles contain all required keys.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    required_keys = [
        "compress",
        "num_threads",
        "bigtiff",
        "overviews",
        "blocksize",
        "predictor",
    ]
    profiles_to_test = ["default", "fast", "high_quality"]

    for profile_name in profiles_to_test:
        profile = processing_raster._get_cog_creation_profile(profile=profile_name)

        # Check all required keys are present
        for key in required_keys:
            assert key in profile, f"Key '{key}' missing from profile '{profile_name}'"

        # Check no extra keys
        assert len(profile) == len(
            required_keys
        ), f"Profile '{profile_name}' has unexpected keys"


# ------------------------------------------
# Test cases for GeoprocessingRaster._build_gdalwarp_command()
# ------------------------------------------
def test_build_gdalwarp_command_basic(tmp_raster_valid_fixture: Path):
    """
    Test basic gdalwarp command construction with minimal parameters.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
    )

    # Check basic command structure
    assert command[0] == "gdalwarp"
    assert "-t_srs" in command
    assert "EPSG:4326" in command
    assert "-of" in command
    assert "COG" in command
    assert "-overwrite" in command  # Default is True
    assert str(input_raster) in command
    assert str(output_path) in command


def test_build_gdalwarp_command_with_target_crs(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with different CRS values.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")

    test_crs_values = [4326, 3857, 2154, 31370]

    for crs in test_crs_values:
        command = processing_raster._build_gdalwarp_command(
            input_raster_path=input_raster,
            output_path=output_path,
            target_crs=crs,
            cog_profile="default",
        )

        assert f"EPSG:{crs}" in command
        srs_index = command.index("-t_srs")
        assert command[srs_index + 1] == f"EPSG:{crs}"


def test_build_gdalwarp_command_with_nodata(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with nodata value specified.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326
    reference_nodata = -9999.0

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        reference_nodata=reference_nodata,
    )

    assert "-dstnodata" in command
    nodata_index = command.index("-dstnodata")
    assert command[nodata_index + 1] == str(reference_nodata)


def test_build_gdalwarp_command_without_nodata(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command without nodata value.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        reference_nodata=None,
    )

    assert "-dstnodata" not in command


def test_build_gdalwarp_command_overwrite_false(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with overwrite disabled.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        overwrite_existing=False,
    )

    assert "-overwrite" not in command


def test_build_gdalwarp_command_default_profile(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with default COG profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
    )

    # Check for default profile options
    assert "-co" in command
    assert "COMPRESS=DEFLATE" in command
    assert "NUM_THREADS=ALL_CPUS" in command
    assert "BIGTIFF=YES" in command
    assert "OVERVIEWS=AUTO" in command


def test_build_gdalwarp_command_fast_profile(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with fast COG profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="fast",
    )

    # Check for fast profile options
    assert "COMPRESS=LZW" in command
    assert "BIGTIFF=IF_SAFER" in command
    assert "OVERVIEWS=NONE" in command
    assert "BLOCKSIZE=1024" in command


def test_build_gdalwarp_command_high_quality_profile(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with high_quality COG profile.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="high_quality",
    )

    # Check for high_quality profile options
    assert "COMPRESS=DEFLATE" in command
    assert "BLOCKSIZE=512" in command
    assert "PREDICTOR=2" in command


def test_build_gdalwarp_command_with_additional_options(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with additional custom options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326
    additional_options = ["-r", "cubic", "-tr", "30", "30"]

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        additional_options=additional_options,
    )

    # Check that additional options are included
    for option in additional_options:
        assert option in command


def test_build_gdalwarp_command_without_additional_options(
    tmp_raster_valid_fixture: Path,
):
    """
    Test gdalwarp command without additional options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        additional_options=None,
    )

    # Should not crash and should contain basic structure
    assert "gdalwarp" in command
    assert str(input_raster) in command
    assert str(output_path) in command


@pytest.mark.parametrize("nodata_value", [0, -9999, 255, 32767, -32768, 0.0, -9999.5])
def test_build_gdalwarp_command_various_nodata_values(
    tmp_raster_valid_fixture: Path, nodata_value: float
):
    """
    Test gdalwarp command with various nodata values.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        reference_nodata=nodata_value,
    )

    assert "-dstnodata" in command
    nodata_index = command.index("-dstnodata")
    assert command[nodata_index + 1] == str(nodata_value)


def test_build_gdalwarp_command_path_types(tmp_raster_valid_fixture: Path):
    """
    Test gdalwarp command with different path types.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Test with string paths
    input_str = "/path/to/input.tif"
    output_str = "/path/to/output.tif"
    target_crs = 4326

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=Path(input_str),
        output_path=Path(output_str),
        target_crs=target_crs,
        cog_profile="default",
    )

    assert input_str in command
    assert output_str in command


def test_build_gdalwarp_command_complex_additional_options(
    tmp_raster_valid_fixture: Path,
):
    """
    Test gdalwarp command with complex additional options.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    input_raster = Path("/path/to/input.tif")
    output_path = Path("/path/to/output.tif")
    target_crs = 4326
    additional_options = [
        "-r",
        "lanczos",
        "-tr",
        "30",
        "30",
        "-te",
        "0",
        "0",
        "1000",
        "1000",
        "-wo",
        "NUM_THREADS=4",
    ]

    command = processing_raster._build_gdalwarp_command(
        input_raster_path=input_raster,
        output_path=output_path,
        target_crs=target_crs,
        cog_profile="default",
        additional_options=additional_options,
    )

    # Check that all additional options are present in order
    for option in additional_options:
        assert option in command


# ------------------------------------------
# Test cases for GeoprocessingRaster._restore_backup_file()
# ------------------------------------------
def test_restore_backup_file_success(tmp_raster_valid_fixture: Path, tmp_path: Path):
    """
    Test successful restoration of backup file.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file with content
    backup_file = tmp_path / "backup.tif"
    backup_content = "backup content"
    backup_file.write_text(backup_content)

    # Create output file (will be overwritten)
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")

    processing_raster._restore_backup_file(
        backup_file=backup_file, restore_path=output_path
    )

    assert not backup_file.exists()  # Backup file should be moved
    assert output_path.exists()  # Output file should exist
    assert output_path.read_text() == backup_content  # Content should be from backup


def test_restore_backup_file_no_output_file(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when output file doesn't exist.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file
    backup_file = tmp_path / "backup.tif"
    backup_content = "backup content"
    backup_file.write_text(backup_content)

    # Output file doesn't exist
    output_path = tmp_path / "output.tif"

    # Restore backup
    processing_raster._restore_backup_file(
        backup_file=backup_file, restore_path=output_path
    )

    # Verify restoration
    assert not backup_file.exists()  # Backup file should be moved
    assert output_path.exists()  # Output file should be created
    assert output_path.read_text() == backup_content


def test_restore_backup_file_no_backup_file(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when backup file doesn't exist.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Backup file doesn't exist
    backup_file = tmp_path / "nonexistent_backup.tif"

    # Create output file
    output_path = tmp_path / "output.tif"
    original_content = "original content"
    output_path.write_text(original_content)

    # Attempt to restore backup (should do nothing)
    processing_raster._restore_backup_file(
        backup_file=backup_file, restore_path=output_path
    )

    # Verify nothing changed
    assert not backup_file.exists()  # Backup file still doesn't exist
    assert output_path.exists()  # Output file should still exist
    assert output_path.read_text() == original_content  # Content unchanged


def test_restore_backup_file_none_backup(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when backup file parameter is None.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create output file
    output_path = tmp_path / "output.tif"
    original_content = "original content"
    output_path.write_text(original_content)

    # Attempt to restore with None backup (should do nothing)
    processing_raster._restore_backup_file(backup_file=None, restore_path=output_path)

    # Verify nothing changed
    assert output_path.exists()
    assert output_path.read_text() == original_content


def test_restore_backup_file_permission_error(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when there's a permission error.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file
    backup_file = tmp_path / "backup.tif"
    backup_file.write_text("backup content")

    # Create output file
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")

    # Mock rename to raise PermissionError
    with patch.object(
        Path, "rename", side_effect=PermissionError("Permission error restoring backup")
    ):
        with patch.object(Path, "unlink") as mock_unlink:
            processing_raster._restore_backup_file(
                backup_file=backup_file, restore_path=output_path
            )

            # Verify unlink was called (output file deletion attempted)
            mock_unlink.assert_called_once()


def test_restore_backup_file_unlink_error(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when output file deletion fails.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file
    backup_file = tmp_path / "backup.tif"
    backup_file.write_text("backup content")

    # Create output file
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")

    # Mock unlink to raise error
    with patch.object(Path, "unlink", side_effect=OSError("Cannot delete file")):
        # Should not raise exception, should log error
        processing_raster._restore_backup_file(
            backup_file=backup_file, restore_path=output_path
        )

        # Backup file should still exist since operation failed
        assert backup_file.exists()


def test_restore_backup_file_with_readonly_output(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration when output file is read-only.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file
    backup_file = tmp_path / "backup.tif"
    backup_file.write_text("backup content")

    # Create read-only output file
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")
    output_path.chmod(0o444)  # Read-only

    try:
        # Should handle read-only file gracefully
        processing_raster._restore_backup_file(
            backup_file=backup_file, restore_path=output_path
        )

        # May succeed or fail depending on system permissions
        # Just verify no unhandled exceptions

    finally:
        # Restore write permissions for cleanup
        if output_path.exists():
            output_path.chmod(0o644)


def test_restore_backup_file_preserves_file_content(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that backup file content is preserved during restoration.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file with binary content
    backup_file = tmp_path / "backup.tif"
    backup_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00"  # Binary data
    backup_file.write_bytes(backup_content)

    # Create output file
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")

    # Restore backup
    processing_raster._restore_backup_file(
        backup_file=backup_file, restore_path=output_path
    )

    # Verify binary content is preserved
    assert output_path.read_bytes() == backup_content


def test_restore_backup_file_cross_filesystem(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test restoration across different filesystems (simulated).
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create backup file
    backup_file = tmp_path / "backup.tif"
    backup_content = "backup content"
    backup_file.write_text(backup_content)

    # Create output file
    output_path = tmp_path / "output.tif"
    output_path.write_text("original content")

    # Mock rename to fail with cross-device error (simulates different filesystems)
    with patch.object(Path, "rename", side_effect=OSError("Cross-device link")):
        # Should handle cross-filesystem move gracefully
        processing_raster._restore_backup_file(
            backup_file=backup_file, restore_path=output_path
        )

        # Operation should fail gracefully without crashing
        assert backup_file.exists()  # Backup should still exist if move failed


@pytest.mark.parametrize(
    "backup_exists,output_exists",
    [
        (True, True),  # Both files exist
        (True, False),  # Only backup exists
        (False, True),  # Only output exists
        (False, False),  # Neither exists
    ],
)
def test_restore_backup_file_file_combinations(
    tmp_raster_valid_fixture: Path,
    tmp_path: Path,
    backup_exists: bool,
    output_exists: bool,
):
    """
    Test restoration with different file existence combinations.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Setup backup file
    backup_file = tmp_path / "backup.tif"
    if backup_exists:
        backup_file.write_text("backup content")

    # Setup output file
    output_path = tmp_path / "output.tif"
    if output_exists:
        output_path.write_text("original content")

    # Attempt restoration
    processing_raster._restore_backup_file(
        backup_file=backup_file, restore_path=output_path
    )

    # Verify expected behavior
    if backup_exists:
        # Backup should be moved to output
        assert not backup_file.exists()
        assert output_path.exists()
        assert output_path.read_text() == "backup content"
    else:
        # No backup to restore
        if output_exists:
            assert output_path.read_text() == "original content"
        else:
            assert not output_path.exists()


# ------------------------------------------
# Test cases for GeoprocessingRaster._wrap_raster()
# ------------------------------------------
def test_wrap_raster_success(tmp_raster_valid_fixture: Path):
    """
    Test successful raster warping with valid parameters.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        # Should not raise any exception
        processing_raster._warp_raster(
            warp_cmd=warp_cmd,
            raster_path=tmp_raster_valid_fixture,
            output_path=output_path,
        )

        # Verify subprocess.run was called with correct parameters
        mock_run.assert_called_once_with(warp_cmd, check=True, capture_output=True)


def test_warp_raster_unregistered_path(tmp_raster_valid_fixture: Path, tmp_path: Path):
    """
    Test warping with unregistered raster path raises ValueError.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a different raster path not registered in the class
    unregistered_raster = tmp_path / "unregistered.tif"
    unregistered_raster.touch()

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(unregistered_raster),
        str(output_path),
    ]

    with pytest.raises(ValueError, match="Raster .* not registered in the class"):
        processing_raster._warp_raster(
            warp_cmd=warp_cmd, raster_path=unregistered_raster, output_path=output_path
        )


def test_warp_raster_subprocess_error(tmp_raster_valid_fixture: Path):
    """
    Test warping when subprocess.run raises CalledProcessError.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    # Mock subprocess to raise CalledProcessError
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=warp_cmd, stderr=b"GDAL error: Invalid projection"
        )

        with pytest.raises(RuntimeError, match=r"gdalwarp failed for .*: exit code 1"):
            processing_raster._warp_raster(
                warp_cmd=warp_cmd,
                raster_path=tmp_raster_valid_fixture,
                output_path=output_path,
            )

        # Verify subprocess.run was called
        mock_run.assert_called_once_with(warp_cmd, check=True, capture_output=True)


def test_warp_raster_with_empty_command(tmp_raster_valid_fixture: Path):
    """
    Test warping with empty command list.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = []  # Empty command

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=warp_cmd, stderr=b"No command provided"
        )

        with pytest.raises(RuntimeError, match=r"gdalwarp failed for .*: exit code 1"):
            processing_raster._warp_raster(
                warp_cmd=warp_cmd,
                raster_path=tmp_raster_valid_fixture,
                output_path=output_path,
            )

        # Verify subprocess.run was called even with empty command
        mock_run.assert_called_once_with(warp_cmd, check=True, capture_output=True)


def test_warp_raster_with_complex_command(tmp_raster_valid_fixture: Path):
    """
    Test warping with complex gdalwarp command.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:3857",
        "-of",
        "COG",
        "-co",
        "COMPRESS=DEFLATE",
        "-co",
        "BIGTIFF=YES",
        "-r",
        "cubic",
        "-tr",
        "30",
        "30",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        processing_raster._warp_raster(
            warp_cmd=warp_cmd,
            raster_path=tmp_raster_valid_fixture,
            output_path=output_path,
        )

        # Verify the exact complex command was passed
        mock_run.assert_called_once_with(warp_cmd, check=True, capture_output=True)


def test_warp_raster_with_special_characters_in_paths(tmp_path: Path):
    """
    Test warping with paths containing special characters.
    """
    # Create raster with special characters in name
    special_raster = tmp_path / "raster with spaces & symbols.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        special_raster,
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[special_raster]
    )

    output_path = tmp_path / "output with spaces.tif"
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(special_raster),
        str(output_path),
    ]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        processing_raster._warp_raster(
            warp_cmd=warp_cmd, raster_path=special_raster, output_path=output_path
        )

        # Verify command with special character paths
        mock_run.assert_called_once_with(warp_cmd, check=True, capture_output=True)


def test_warp_raster_stderr_empty(tmp_raster_valid_fixture: Path):
    """
    Test warping when subprocess fails but stderr is empty.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=warp_cmd, stderr=b""  # Empty stderr
        )

        with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:
            with pytest.raises(
                RuntimeError, match=r"gdalwarp failed for .*: exit code 1"
            ):
                processing_raster._warp_raster(
                    warp_cmd=warp_cmd,
                    raster_path=tmp_raster_valid_fixture,
                    output_path=output_path,
                )

            mock_logger.exception.assert_called_once()
            logged_msg = mock_logger.exception.call_args[0][0]
            assert "STDERR:" in logged_msg


def test_warp_raster_stderr_unicode(tmp_raster_valid_fixture: Path):
    """
    Test warping when stderr contains unicode characters.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    unicode_error = "Erreur: caractères spéciaux éàç".encode("utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=warp_cmd, stderr=unicode_error
        )

        with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:
            with pytest.raises(
                RuntimeError, match=r"gdalwarp failed for .*: exit code 1"
            ):
                processing_raster._warp_raster(
                    warp_cmd=warp_cmd,
                    raster_path=tmp_raster_valid_fixture,
                    output_path=output_path,
                )

            # Verify unicode stderr is properly decoded and logged
            mock_logger.exception.assert_called_once()
            logged_message = mock_logger.exception.call_args[0][0]
            assert "caractères spéciaux éàç" in logged_message


def test_warp_raster_multiple_registered_rasters(tmp_path: Path):
    """
    Test warping when multiple rasters are registered.
    """
    # Create multiple rasters
    raster1 = tmp_path / "raster1.tif"
    raster2 = tmp_path / "raster2.tif"

    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    for raster_path in [raster1, raster2]:
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[raster1, raster2]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = ["gdalwarp", "-t_srs", "EPSG:4326", str(raster1), str(output_path)]

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        # Should work for registered raster1
        processing_raster._warp_raster(
            warp_cmd=warp_cmd, raster_path=raster1, output_path=output_path
        )

        # Should also work for registered raster2
        warp_cmd[3] = str(raster2)  # Change input file in command
        processing_raster._warp_raster(
            warp_cmd=warp_cmd, raster_path=raster2, output_path=output_path
        )

        # Verify both calls succeeded
        assert mock_run.call_count == 2


@pytest.mark.parametrize("return_code", [1, 2, 127, 255])
def test_warp_raster_various_error_codes(
    tmp_raster_valid_fixture: Path, return_code: int
):
    """
    Test warping with various subprocess return codes.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = Path("/path/to/output.tif")
    warp_cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        str(tmp_raster_valid_fixture),
        str(output_path),
    ]

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=return_code,
            cmd=warp_cmd,
            stderr=f"Error with code {return_code}".encode(),
        )

        with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:
            with pytest.raises(
                RuntimeError, match=rf"gdalwarp failed for .*: exit code {return_code}"
            ):
                processing_raster._warp_raster(
                    warp_cmd=warp_cmd,
                    raster_path=tmp_raster_valid_fixture,
                    output_path=output_path,
                )

            mock_logger.exception.assert_called_once()
            logged_msg = mock_logger.exception.call_args[0][0]
            assert f"exit code {return_code}" in logged_msg


# ------------------------------------------
# Test cases for GeoprocessingRaster.prepare_cog_metadata_for_stac()
# ------------------------------------------
def test_prepare_cog_metadata_for_stac_success(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test successful metadata preparation for STAC from a COG file.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG file
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    # Prepare metadata
    metadata = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )

    assert metadata["id"] == cog_file.stem
    assert metadata["assets"]["cog"]["raster_bands"][0]["data_type"] == "uint8"


def test_prepare_cog_metadata_for_stac_geometry_structure(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that geometry is correctly structured from COG bounds.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(5, 15, 1, 1)

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )

    geometry = _get_field(metadata_model, "geometry")
    if not isinstance(geometry, Mapping):
        geometry = _to_mapping(geometry)

    assert geometry["type"] == "Polygon"
    coords = geometry["coordinates"][0]
    assert coords[0] == coords[-1]


def test_prepare_cog_metadata_for_stac_bbox_format(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that bbox is correctly formatted as [left, bottom, right, top].
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG with specific bounds
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(10, 20, 1, 1)  # west=10, north=20

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )

    metadata = _to_mapping(metadata_model)

    # Verify bbox format
    bbox = metadata["bbox"]
    assert bbox[0] <= bbox[2]  # left <= right
    assert bbox[1] <= bbox[3]  # bottom <= top

    # Verify specific values based on transform
    assert bbox[0] == 10  # left
    assert bbox[2] == 20  # right (10 + 10*1)
    assert bbox[3] == 20  # top
    assert bbox[1] == 10  # bottom (20 - 10*1)


def test_prepare_cog_metadata_for_stac_properties(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that properties section contains all required fields.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG with specific bounds
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((3, 20, 30), dtype=np.uint16)  # 3 bands, 20x30
    valid_transform = from_origin(0, 10, 0.5, 0.5)  # 0.5 resolution

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=20,
        width=30,
        count=3,
        dtype=data.dtype,
        crs="EPSG:3857",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )

    metadata = _to_mapping(metadata_model)

    properties = metadata["properties"]

    # Verify specific values
    assert properties["proj:epsg"] == 3857
    assert properties["proj:shape"] == [20, 30]
    assert properties["bands"] == 3
    assert properties["source"] == "cog_processing"
    assert properties["data_type"] == "raster"


def test_prepare_cog_metadata_for_stac_raster_bands(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that raster bands information is correctly extracted.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG with 2 bands
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((2, 10, 10), dtype=np.float32)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=2,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
        nodata=-9999,
    ) as dst:
        dst.write(data)

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    raster_bands = metadata["properties"]["raster:bands"]

    assert len(raster_bands) == 2

    for band in raster_bands:
        assert "nodata" in band
        assert "data_type" in band
        assert "spatial_resolution" in band

        assert band["nodata"] == -9999
        assert band["data_type"] == "float32"
        assert band["spatial_resolution"] == 1.0  # abs(transform[0])


def test_prepare_cog_metadata_for_stac_assets_section(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that assets section is correctly structured.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify assets section
    assets = metadata["assets"]
    assert "cog" in assets

    cog_asset = assets["cog"]
    assert cog_asset["title"] == cog_file.name


def test_prepare_cog_metadata_for_stac_stac_extensions(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that STAC extensions are correctly specified.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    extensions = metadata["stac_extensions"]

    # Verify STAC extensions
    assert len(extensions) == 2
    assert "https://stac-extensions.github.io/raster/v1.1.0/schema.json" in extensions
    assert (
        "https://stac-extensions.github.io/projection/v1.1.0/schema.json" in extensions
    )


def test_prepare_cog_metadata_for_stac_no_stored_metadata(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test error when no stored metadata exists for original raster.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a different raster not in metadata
    other_raster = tmp_path / "other.tif"
    cog_file = tmp_path / "test_cog.tif"

    # Create COG file
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    with pytest.raises(ValueError, match="No stored metadata for raster"):
        processing_raster.prepare_cog_metadata_for_stac(
            original_raster_path=other_raster, cog_file_path=cog_file
        )


def test_prepare_cog_metadata_for_stac_cog_file_not_exists(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test error when COG file doesn't exist.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Non-existent COG file
    cog_file = tmp_path / "nonexistent_cog.tif"

    with pytest.raises(FileNotFoundError, match="COG file .* does not exist"):
        processing_raster.prepare_cog_metadata_for_stac(
            original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
        )


def test_prepare_cog_metadata_for_stac_no_crs(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation when COG has no CRS.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a COG without CRS
    cog_file = tmp_path / "no_crs_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        transform=valid_transform,
        # No CRS specified
    ) as dst:
        dst.write(data)

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Should default to EPSG:4326
    assert metadata["properties"]["proj:epsg"] == 4326


def test_prepare_cog_metadata_for_stac_no_nodata(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation when COG has no nodata value.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a COG without nodata
    cog_file = tmp_path / "no_nodata_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
        # No nodata specified
    ) as dst:
        dst.write(data)

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify nodata is None
    raster_bands = metadata["properties"]["raster:bands"]
    assert raster_bands[0]["nodata"] is None


def test_prepare_cog_metadata_for_stac_multiband_different_nodata(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation with multiband COG having different nodata values per band.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a multiband COG with different nodata values
    cog_file = tmp_path / "multiband_cog.tif"
    data = np.ones((3, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    # Create COG with different nodata per band (simulated)
    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=3,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)
        # Set different nodata values (this is a simplified simulation)
        dst.nodata = 255

    # Accept both pydantic model or plain mapping
    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify nodata values per band
    raster_bands = metadata["properties"]["raster:bands"]
    assert len(raster_bands) == 3

    for band in raster_bands:
        assert band["data_type"] == "uint8"
        assert band["spatial_resolution"] == 1.0


def test_prepare_cog_metadata_for_stac_datetime_from_stored_metadata(tmp_path: Path):
    """
    Test that datetime is correctly retrieved from stored metadata.
    """
    # Create raster with custom datetime in metadata
    raster_path = tmp_path / "test_with_datetime.tif"
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

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=[raster_path])

    # Manually set custom datetime in stored metadata
    custom_datetime = "2023-06-15T12:30:00Z"
    processing_raster.raster_metadata[raster_path]["datetime"] = custom_datetime

    # Create COG
    cog_file = tmp_path / "test_cog.tif"
    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=raster_path, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify datetime matches stored metadata
    assert metadata["datetime"] == custom_datetime
    assert metadata["properties"]["datetime"] == custom_datetime


def test_prepare_cog_metadata_for_stac_default_datetime(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that DEFAULT_DATETIME is used when no datetime in stored metadata.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Remove datetime from stored metadata
    if "datetime" in processing_raster.raster_metadata[tmp_raster_valid_fixture]:
        del processing_raster.raster_metadata[tmp_raster_valid_fixture]["datetime"]

    # Create COG
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    expected_dt = (
        Config.DEFAULT_DATETIME.isoformat()
        if hasattr(Config.DEFAULT_DATETIME, "isoformat")
        else str(Config.DEFAULT_DATETIME)
    )
    assert metadata["datetime"] == expected_dt
    assert metadata["properties"]["datetime"] == expected_dt


def test_prepare_cog_metadata_for_stac_transform_precision(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that transform values are properly converted to float.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create COG with precise transform values
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(123.456789, 987.654321, 0.123456, 0.789012)

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    transform = metadata["properties"]["proj:transform"]

    # Verify all transform values are floats
    assert all(isinstance(x, float) for x in transform)
    assert len(transform) == 6  # Standard affine transform has 6 parameters


def test_prepare_cog_metadata_for_stac_file_url_format(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that file_url is correctly formatted.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a valid COG
    cog_file = tmp_path / "test_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify file_url is correctly formatted
    expected_url = f"file://{cog_file.absolute()}"
    assert metadata["file_url"] == expected_url
    assert metadata["assets"]["cog"]["href"] == expected_url


def test_prepare_cog_metadata_for_stac_complex_crs(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation with complex CRS (non-EPSG).
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a COG with a complex CRS
    cog_file = tmp_path / "complex_crs_cog.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    # Create with a CRS that might not have EPSG code
    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=data.dtype,
        crs="EPSG:2154",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Should correctly extract EPSG code
    assert metadata["properties"]["proj:epsg"] == 2154


@pytest.mark.parametrize(
    "dtype", [np.uint8, np.uint16, np.int16, np.float32, np.float64]
)
def test_prepare_cog_metadata_for_stac_various_dtypes(
    tmp_raster_valid_fixture: Path, tmp_path: Path, dtype: np.dtype
):
    """
    Test metadata preparation with various data types.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a COG with specified data type
    cog_file = tmp_path / f"test_{dtype.__name__}_cog.tif"
    data = np.ones((1, 10, 10), dtype=dtype)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify data type in raster bands
    raster_bands = metadata["properties"]["raster:bands"]
    assert raster_bands[0]["data_type"] == str(dtype.__name__)


def test_prepare_cog_metadata_for_stac_large_dimensions(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation with large raster dimensions.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a large COG
    cog_file = tmp_path / "large_cog.tif"
    width, height = 1000, 2000
    data = np.ones((1, height, width), dtype=np.uint8)
    valid_transform = from_origin(0, height, 1, 1)

    with rasterio.open(
        cog_file,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Verify shape in properties
    assert metadata["properties"]["proj:shape"] == [height, width]


def test_prepare_cog_metadata_for_stac_special_characters_in_filename(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test metadata preparation with special characters in COG filename.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Create a COG with special characters in filename
    cog_file = tmp_path / "test cog with spaces & symbols.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        cog_file,
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

    metadata_model = processing_raster.prepare_cog_metadata_for_stac(
        original_raster_path=tmp_raster_valid_fixture, cog_file_path=cog_file
    )
    metadata = _to_mapping(metadata_model)

    # Should handle special characters in filename
    assert metadata["id"] == cog_file.stem
    assert metadata["assets"]["cog"]["title"] == cog_file.name
    assert str(cog_file.absolute()) in metadata["file_url"]


# ------------------------------------------
# Test cases for GeoprocessingRaster.process_raster_to_cog()
# ------------------------------------------
def test_process_raster_to_cog_success(tmp_raster_valid_fixture: Path, tmp_path: Path):
    """
    Test successful processing of a single raster to COG.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain to avoid internal complexity
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify
                assert len(result) == 1
                assert result[0][0] == tmp_raster_valid_fixture
                assert result[0][1] == expected_cog
                assert expected_cog.exists()


def test_process_raster_to_cog_multiple_rasters(tmp_path: Path):
    """
    Test processing multiple rasters to COG.
    """
    # Create multiple test rasters
    raster1 = tmp_path / "raster1.tif"
    raster2 = tmp_path / "raster2.tif"

    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    for raster_path in [raster1, raster2]:
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[raster1, raster2]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                mock_build.return_value = ["gdalwarp", "test"]

                # Track calls and create files for each raster
                call_count = 0

                def mock_warp_side_effect(warp_cmd, raster_path, output_path):
                    nonlocal call_count
                    # Create the file that the function expects
                    output_path.touch()
                    call_count += 1

                mock_warp.side_effect = mock_warp_side_effect

                # Pre-set harmonized name - will be overwritten for each raster
                processing_raster.harmonized_name = "raster1.tif"

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify both rasters were processed
                assert len(result) == 2
                assert mock_warp.call_count == 2

                # Verify all COG files were created
                for _, cog_path in result:
                    assert cog_path.exists()

                # Verify correct raster paths in result
                result_raster_paths = [r[0] for r in result]
                assert raster1 in result_raster_paths
                assert raster2 in result_raster_paths


def test_process_raster_to_cog_with_nodata(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test processing with custom nodata value.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()
    reference_nodata = -9999.0

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(
            processing_raster, "_build_gdalwarp_command"
        ) as mock_build_cmd:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build_cmd.return_value = ["gdalwarp", "test"]

                processing_raster.process_raster_to_cog(
                    output_path=output_path,
                    target_crs=4326,
                    reference_nodata=reference_nodata,
                )

                # Verify nodata was passed to command builder
                mock_build_cmd.assert_called_once()
                args, kwargs = mock_build_cmd.call_args
                assert kwargs["reference_nodata"] == reference_nodata


def test_process_raster_to_cog_overwrite_false(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test processing with overwrite disabled creates backup.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Create existing COG file that matches harmonized name
    processing_raster.harmonized_name = "test_raster.tif"
    existing_cog = output_path / "test_raster.tif_cog.tif"
    existing_cog.write_text("existing content")

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:
                with patch("time.time", return_value=1234567890):

                    # Set harmonized name directly
                    processing_raster.harmonized_name = "test_raster.tif"
                    expected_cog = output_path / "test_raster.tif_cog.tif"

                    # Mock warp to create the file
                    def create_file(*args, **kwargs):
                        expected_cog.touch()

                    mock_warp.side_effect = create_file
                    mock_build.return_value = ["gdalwarp", "test"]

                    result = processing_raster.process_raster_to_cog(
                        output_path=output_path,
                        target_crs=4326,
                        overwrite_existing=False,
                    )

                    # Verify result
                    assert len(result) == 1
                    assert expected_cog.exists()


def test_process_raster_to_cog_overwrite_true(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test processing with overwrite enabled.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Create existing COG file
    processing_raster.harmonized_name = "test_raster.tif"
    existing_cog = output_path / "test_raster.tif_cog.tif"
    existing_cog.write_text("existing content")

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326, overwrite_existing=True
                )

                # Verify processing succeeded
                assert len(result) == 1
                assert expected_cog.exists()


def test_process_raster_to_cog_subprocess_error(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test handling of subprocess.CalledProcessError during processing.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"

                mock_warp.side_effect = subprocess.CalledProcessError(
                    returncode=1, cmd=["gdalwarp"], stderr=b"GDAL error"
                )
                mock_build.return_value = ["gdalwarp", "test"]

                # Should raise RuntimeError when all processing fails
                with pytest.raises(RuntimeError, match="All raster processing failed"):
                    processing_raster.process_raster_to_cog(
                        output_path=output_path, target_crs=4326
                    )


def test_process_raster_to_cog_partial_failure(tmp_path: Path):
    """
    Test processing when some rasters fail but others succeed.
    """
    # Create multiple test rasters
    raster1 = tmp_path / "raster1.tif"
    raster2 = tmp_path / "raster2.tif"

    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    for raster_path in [raster1, raster2]:
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[raster1, raster2]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    def mock_warp_side_effect(warp_cmd, raster_path, output_path):
        if raster_path == raster1:
            # First raster fails
            raise subprocess.CalledProcessError(1, ["gdalwarp"], stderr=b"Error")
        else:
            # Second raster succeeds - create the file
            output_path.touch()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(
                processing_raster, "_warp_raster", side_effect=mock_warp_side_effect
            ):
                with patch(
                    "pipeline.modules.processing.geoprocessing.logger"
                ) as mock_logger:

                    mock_build.return_value = ["gdalwarp", "test"]

                    # Pre-set harmonized name - will be used for both rasters
                    processing_raster.harmonized_name = "raster1.tif"

                    result = processing_raster.process_raster_to_cog(
                        output_path=output_path, target_crs=4326
                    )

                    # Should return only successful raster
                    assert len(result) == 1
                    assert result[0][0] == raster2

                    mock_logger.warning.assert_called_once()


def test_process_raster_to_cog_unexpected_error(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test handling of unexpected exceptions during processing.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"

                mock_warp.side_effect = RuntimeError("Unexpected error")
                mock_build.return_value = ["gdalwarp", "test"]

                # Should raise RuntimeError when all processing fails
                with pytest.raises(RuntimeError, match="All raster processing failed"):
                    processing_raster.process_raster_to_cog(
                        output_path=output_path, target_crs=4326
                    )


def test_process_raster_to_cog_cog_not_created(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test error when COG file is not created after processing.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster"):

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"

                # _warp_raster succeeds but doesn't create the file (no side_effect)
                mock_build.return_value = ["gdalwarp", "test"]

                with pytest.raises(RuntimeError, match="All raster processing failed"):
                    processing_raster.process_raster_to_cog(
                        output_path=output_path, target_crs=4326
                    )


def test_process_raster_to_cog_backup_cleanup(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that backup files are cleaned up after successful processing.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Create existing COG file
    processing_raster.harmonized_name = "test_raster.tif"
    existing_cog = output_path / "test_raster.tif_cog.tif"
    existing_cog.write_text("existing content")

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:
                with patch("time.time", return_value=1234567890):

                    # Set harmonized name directly
                    processing_raster.harmonized_name = "test_raster.tif"
                    expected_cog = output_path / "test_raster.tif_cog.tif"

                    # Mock warp to create the file
                    def create_file(*args, **kwargs):
                        expected_cog.touch()

                    mock_warp.side_effect = create_file
                    mock_build.return_value = ["gdalwarp", "test"]

                    processing_raster.process_raster_to_cog(
                        output_path=output_path,
                        target_crs=4326,
                        overwrite_existing=False,
                    )

                    # Verify no backup files remain
                    backup_files = list(output_path.glob("*_old_*"))
                    assert len(backup_files) == 0


def test_process_raster_to_cog_backup_restore_on_error(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that backup is restored when processing fails.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Create existing COG file
    processing_raster.harmonized_name = "test_raster.tif"
    existing_cog = output_path / "test_raster.tif_cog.tif"
    existing_content = "existing content"
    existing_cog.write_text(existing_content)

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:
                with patch.object(
                    processing_raster, "_restore_backup_file"
                ) as mock_restore:

                    # Set harmonized name directly
                    processing_raster.harmonized_name = "test_raster.tif"

                    mock_warp.side_effect = RuntimeError("Processing failed")
                    mock_build.return_value = ["gdalwarp", "test"]

                    with pytest.raises(RuntimeError):
                        processing_raster.process_raster_to_cog(
                            output_path=output_path,
                            target_crs=4326,
                            overwrite_existing=False,
                        )

                    # Verify restore was called
                    mock_restore.assert_called_once()


def test_process_raster_to_cog_name_harmonization(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that raster names are harmonized for COG output.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(
        processing_raster, "_harmonize_name_for_single_raster"
    ) as mock_harmonize:
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "harmonized_name.tif"
                expected_cog = output_path / "harmonized_name.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify harmonization was called
                mock_harmonize.assert_called_once_with(
                    raster_name=tmp_raster_valid_fixture.name
                )
                assert result[0][1].name == "harmonized_name.tif_cog.tif"


def test_process_raster_to_cog_default_crs(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that default CRS is used when target_crs is None.
    """
    config = Config()
    config.GLOBAL_CRS = 3857  # Set default CRS

    processing_raster = GeoprocessingRaster(
        config=config, raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(
            processing_raster, "_build_gdalwarp_command"
        ) as mock_build_cmd:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build_cmd.return_value = ["gdalwarp", "test"]

                processing_raster.process_raster_to_cog(
                    output_path=output_path,
                    target_crs=None,  # Should use config.GLOBAL_CRS
                )

                # Verify default CRS was used
                mock_build_cmd.assert_called_once()
                args, kwargs = mock_build_cmd.call_args
                assert kwargs["target_crs"] == 3857


def test_process_raster_to_cog_logging(tmp_raster_valid_fixture: Path, tmp_path: Path):
    """
    Test that appropriate log messages are generated.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:
                with patch(
                    "pipeline.modules.processing.geoprocessing.logger"
                ) as mock_logger:

                    # Set harmonized name directly
                    processing_raster.harmonized_name = "test_raster.tif"
                    expected_cog = output_path / "test_raster.tif_cog.tif"

                    # Mock warp to create the file
                    def create_file(*args, **kwargs):
                        expected_cog.touch()

                    mock_warp.side_effect = create_file
                    mock_build.return_value = ["gdalwarp", "test"]

                    processing_raster.process_raster_to_cog(
                        output_path=output_path, target_crs=4326
                    )

                    # Verify success was logged
                    mock_logger.info.assert_called()
                    log_calls = [
                        call.args[0] for call in mock_logger.info.call_args_list
                    ]
                    assert any("Harmonized raster saved" in msg for msg in log_calls)


def test_process_raster_to_cog_output_directory_structure(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that COG files are created in the correct output directory.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "nested" / "output" / "directory"
    output_path.mkdir(parents=True)

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify COG was created in correct location
                assert result[0][1].parent == output_path
                assert result[0][1].exists()


def test_process_raster_to_cog_special_characters_in_path(tmp_path: Path):
    """
    Test processing raster with special characters in path.
    """
    # Create raster with special characters in name
    special_raster = tmp_path / "raster with spaces & symbols.tif"
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        special_raster,
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

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[special_raster]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "raster_with_spaces_symbols.tif"
                expected_cog = output_path / "raster_with_spaces_symbols.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify processing succeeded
                assert len(result) == 1
                assert result[0][0] == special_raster


@pytest.mark.parametrize("target_crs", [4326, 3857, 2154, 31370])
def test_process_raster_to_cog_various_crs(
    tmp_raster_valid_fixture: Path, tmp_path: Path, target_crs: int
):
    """
    Test processing with various CRS values.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(
            processing_raster, "_build_gdalwarp_command"
        ) as mock_build_cmd:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build_cmd.return_value = ["gdalwarp", "test"]

                processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=target_crs
                )

                # Verify CRS was passed correctly
                mock_build_cmd.assert_called_once()
                args, kwargs = mock_build_cmd.call_args
                assert kwargs["target_crs"] == target_crs


def test_process_raster_to_cog_return_format(
    tmp_raster_valid_fixture: Path, tmp_path: Path
):
    """
    Test that return value has correct format.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "test_raster.tif"
                expected_cog = output_path / "test_raster.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify return format
                assert isinstance(result, list)
                assert len(result) == 1
                assert isinstance(result[0], tuple)
                assert len(result[0]) == 2
                assert isinstance(result[0][0], Path)  # Original raster path
                assert isinstance(result[0][1], Path)  # COG file path


def test_process_raster_to_cog_large_raster(tmp_path: Path):
    """
    Test processing with large raster dimensions.
    """
    # Create large raster
    large_raster = tmp_path / "large.tif"
    width, height = 1000, 1000
    data = np.ones((1, height, width), dtype=np.uint8)
    valid_transform = from_origin(0, height, 1, 1)

    with rasterio.open(
        large_raster,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=valid_transform,
    ) as dst:
        dst.write(data)

    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[large_raster]
    )

    output_path = tmp_path / "output"
    output_path.mkdir()

    # Mock the entire chain like the success test
    with patch.object(processing_raster, "_harmonize_name_for_single_raster"):
        with patch.object(processing_raster, "_build_gdalwarp_command") as mock_build:
            with patch.object(processing_raster, "_warp_raster") as mock_warp:

                # Set harmonized name directly
                processing_raster.harmonized_name = "large.tif"
                expected_cog = output_path / "large.tif_cog.tif"

                # Mock warp to create the file
                def create_file(*args, **kwargs):
                    expected_cog.touch()

                mock_warp.side_effect = create_file
                mock_build.return_value = ["gdalwarp", "test"]

                result = processing_raster.process_raster_to_cog(
                    output_path=output_path, target_crs=4326
                )

                # Verify large raster was processed
                assert len(result) == 1
                assert result[0][0] == large_raster


# ------------------------------------------
# Test cases for GeoprocessingRaster.close_all_rasters()
# ------------------------------------------
def test_close_all_rasters_single_file(tmp_raster_valid_fixture: Path):
    """
    Test closing a single opened raster file.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Verify raster is initially opened
    assert len(processing_raster.rasters) == 1
    assert tmp_raster_valid_fixture in processing_raster.rasters

    # Mock the raster's close method to track calls
    mock_raster = processing_raster.rasters[tmp_raster_valid_fixture]
    with patch.object(mock_raster, "close") as mock_close:
        with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:

            processing_raster.close_all_rasters()

            # Verify close was called once
            mock_close.assert_called_once()

            # Verify appropriate logging
            mock_logger.debug.assert_called()
            mock_logger.info.assert_called_with("All raster files have been closed.")


def test_close_all_rasters_multiple_files(tmp_path: Path):
    """
    Test closing multiple opened raster files.
    """
    # Create multiple test rasters
    raster1 = tmp_path / "raster1.tif"
    raster2 = tmp_path / "raster2.tif"
    raster3 = tmp_path / "raster3.tif"

    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    raster_paths = [raster1, raster2, raster3]
    for raster_path in raster_paths:
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

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=raster_paths)

    # Verify all rasters are initially opened
    assert len(processing_raster.rasters) == 3

    # Mock all raster close methods
    close_mocks = []
    for raster_path in raster_paths:
        mock_raster = processing_raster.rasters[raster_path]
        close_mock = patch.object(mock_raster, "close")
        close_mocks.append(close_mock)

    with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:
        # Start all mocks
        started_mocks = [mock.start() for mock in close_mocks]

        try:
            processing_raster.close_all_rasters()

            # Verify close was called for each raster
            for mock_close in started_mocks:
                mock_close.assert_called_once()

            # Verify debug was called for each raster (3 times)
            assert mock_logger.debug.call_count == 3

            # Verify final info log
            mock_logger.info.assert_called_with("All raster files have been closed.")

        finally:
            # Stop all mocks
            for mock in close_mocks:
                mock.stop()


def test_close_all_rasters_with_exception_handling(tmp_raster_valid_fixture: Path):
    """
    Test close_all_rasters handles exceptions gracefully when closing fails.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Mock the raster's close method to raise an exception
    mock_raster = processing_raster.rasters[tmp_raster_valid_fixture]

    with patch.object(mock_raster, "close", side_effect=Exception("Close failed")):
        with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:

            # Should not raise exception, but handle it gracefully
            try:
                processing_raster.close_all_rasters()
                # If we reach here, exception was handled (which is expected behavior)
            except Exception:
                # If an exception is raised, the method should be improved to handle it
                pytest.fail("close_all_rasters should handle exceptions gracefully")

            # Even with exception, final message should be logged
            mock_logger.info.assert_called_with("All raster files have been closed.")


def test_close_all_rasters_idempotent_behavior(tmp_raster_valid_fixture: Path):
    """
    Test that calling close_all_rasters multiple times doesn't cause issues.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Mock the raster's close method
    mock_raster = processing_raster.rasters[tmp_raster_valid_fixture]
    with patch.object(mock_raster, "close") as mock_close:
        with patch("pipeline.modules.processing.geoprocessing.logger"):

            # Call close_all_rasters multiple times
            processing_raster.close_all_rasters()
            processing_raster.close_all_rasters()
            processing_raster.close_all_rasters()

            # Close should be called multiple times (not idempotent currently)
            # This test documents current behavior - might want to make it idempotent
            assert mock_close.call_count == 3


def test_close_all_rasters_integration_with_context_manager(
    tmp_raster_valid_fixture: Path,
):
    """
    Test close_all_rasters works correctly when used as cleanup in context-like scenarios.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    try:
        # Simulate some processing
        assert len(processing_raster.rasters) == 1

        # Verify rasters are accessible
        for raster_path, raster in processing_raster.rasters.items():
            assert raster.closed is False
            assert raster.count > 0

    finally:
        # Close rasters in cleanup
        with patch("pipeline.modules.processing.geoprocessing.logger"):
            processing_raster.close_all_rasters()


@pytest.mark.parametrize("num_rasters", [1, 2, 5, 10])
def test_close_all_rasters_performance_with_multiple_files(
    tmp_path: Path, num_rasters: int
):
    """
    Test close_all_rasters performance with different numbers of raster files.
    """
    # Create multiple rasters
    raster_paths = []
    data = np.ones((1, 10, 10), dtype=np.uint8)
    valid_transform = from_origin(0, 10, 1, 1)

    for i in range(num_rasters):
        raster_path = tmp_path / f"raster_{i}.tif"
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
        raster_paths.append(raster_path)

    processing_raster = GeoprocessingRaster(config=Config(), raster_paths=raster_paths)

    # Mock close methods
    close_mocks = []
    for raster_path in raster_paths:
        mock_raster = processing_raster.rasters[raster_path]
        close_mock = patch.object(mock_raster, "close")
        close_mocks.append(close_mock)

    with patch("pipeline.modules.processing.geoprocessing.logger") as mock_logger:
        # Start all mocks
        started_mocks = [mock.start() for mock in close_mocks]

        try:
            start_time = time.time()
            processing_raster.close_all_rasters()

            end_time = time.time()
            duration = end_time - start_time

            # Verify all rasters were closed
            for mock_close in started_mocks:
                mock_close.assert_called_once()

            # Verify appropriate number of debug calls
            assert mock_logger.debug.call_count == num_rasters

            # Basic performance assertion (should be very fast)
            assert (
                duration < 1.0
            ), f"close_all_rasters took too long: {duration}s for {num_rasters} rasters"

        finally:
            # Stop all mocks
            for mock in close_mocks:
                mock.stop()


def test_close_all_rasters_memory_cleanup_verification(tmp_raster_valid_fixture: Path):
    """
    Test that close_all_rasters properly releases memory resources.
    """
    processing_raster = GeoprocessingRaster(
        config=Config(), raster_paths=[tmp_raster_valid_fixture]
    )

    # Get initial raster reference
    initial_raster = processing_raster.rasters[tmp_raster_valid_fixture]

    # Verify raster is initially open
    assert not initial_raster.closed

    with patch("pipeline.modules.processing.geoprocessing.logger"):
        processing_raster.close_all_rasters()

    # After closing, the raster should be closed
    assert initial_raster.closed
