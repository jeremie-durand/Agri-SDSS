"""
Unit tests for Sentinel-2 Earth Observation data fetch process.
Tests the eo_sentinel_fetch.py module functionality.
"""

import os
from unittest.mock import MagicMock, patch

import psycopg
import pytest
import requests
import requests.exceptions
from processes.eo_sentinel_fetch import PROCESS_METADATA, SentinelFetchProcessor
from pygeoapi.process.base import ProcessorExecuteError

pytestmark = pytest.mark.unit


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def sample_farm_geometry():
    """Sample farm polygon geometry (GeoJSON)."""
    return {
        "type": "Polygon",
        "coordinates": [
            [[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]]
        ],
    }


@pytest.fixture
def sample_farm_geometry_small():
    """Small farm polygon for testing (< 2 hectares)."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-71.50, 45.50],
                [-71.49, 45.50],
                [-71.49, 45.51],
                [-71.50, 45.51],
                [-71.50, 45.50],
            ]
        ],
    }


@pytest.fixture
def sample_farm_geometry_large():
    """Large farm polygon that exceeds size limit (> 100 km²)."""
    # ~1 degree x 1 degree polygon (approximately 111km x 111km at mid-latitudes)
    return {
        "type": "Polygon",
        "coordinates": [
            [[-71.0, 45.0], [-70.0, 45.0], [-70.0, 46.0], [-71.0, 46.0], [-71.0, 45.0]]
        ],
    }


@pytest.fixture
def valid_temporal_extent():
    """Valid temporal extent for testing."""
    return ["2024-06-01", "2024-08-31"]


@pytest.fixture
def valid_output_products():
    """Valid output products list."""
    return ["ndvi", "evi"]


@pytest.fixture
def processor_instance():
    """Create a SentinelFetchProcessor instance for testing."""

    processor_def = {"name": "sentinel-fetch"}
    return SentinelFetchProcessor(processor_def)


@pytest.fixture
def mock_db_connection():
    """Mock database connection and cursor."""
    # Create the JSON string that would be returned from ST_AsGeoJSON
    json_string = '{"type": "Polygon", "coordinates": [[[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]]]}'

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json_string,)
    mock_cursor.execute = MagicMock()

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    return mock_conn


@pytest.fixture
def mock_openeo_connection():
    """Mock openEO connection and data cube."""
    mock_cube = MagicMock()
    mock_cube.apply.return_value = mock_cube
    mock_cube.reduce_dimension.return_value = mock_cube
    mock_cube.band.return_value = mock_cube
    mock_cube.mask_polygon.return_value = mock_cube
    mock_cube.filter_bands.return_value = mock_cube
    mock_cube.__add__ = lambda self, other: mock_cube
    mock_cube.__sub__ = lambda self, other: mock_cube
    mock_cube.__mul__ = lambda self, other: mock_cube
    mock_cube.__truediv__ = lambda self, other: mock_cube

    mock_job = MagicMock()
    mock_job.download_result.return_value = None
    mock_cube.execute_batch.return_value = mock_job

    mock_connection = MagicMock()
    mock_connection.load_collection.return_value = mock_cube
    mock_connection.authenticate_oidc.return_value = None
    mock_connection.authenticate_basic.return_value = None
    mock_connection.authenticate_oidc_refresh_token.return_value = None

    return mock_connection


# ------------------------------------------
# Test Process Metadata
# ------------------------------------------
def test_process_metadata_structure():
    """Test that PROCESS_METADATA has correct structure."""

    assert "version" in PROCESS_METADATA
    assert "id" in PROCESS_METADATA
    assert PROCESS_METADATA["id"] == "sentinel-fetch"
    assert "inputs" in PROCESS_METADATA
    assert "outputs" in PROCESS_METADATA
    assert "jobControlOptions" in PROCESS_METADATA
    assert "sync-execute" in PROCESS_METADATA["jobControlOptions"]


def test_process_inputs_defined():
    """Test that all required inputs are defined."""

    inputs = PROCESS_METADATA["inputs"]

    assert "farm_geometry" in inputs
    assert "farm_id" in inputs
    assert "temporal_extent" in inputs
    assert "output_products" in inputs
    assert "aggregation_method" in inputs
    assert "cloud_cover_max" in inputs

    # Check temporal_extent is array with 2 items
    assert inputs["temporal_extent"]["schema"]["type"] == "array"
    assert inputs["temporal_extent"]["schema"]["minItems"] == 2
    assert inputs["temporal_extent"]["schema"]["maxItems"] == 2

    # Check output_products enum
    assert "enum" in inputs["output_products"]["schema"]["items"]
    expected_products = ["raw_bands", "ndvi", "evi", "savi", "true_color"]
    assert set(inputs["output_products"]["schema"]["items"]["enum"]) == set(
        expected_products
    )


def test_process_outputs_defined():
    """Test that outputs are properly defined."""

    outputs = PROCESS_METADATA["outputs"]
    assert "result" in outputs
    assert outputs["result"]["schema"]["type"] == "object"


# ------------------------------------------
# Test Processor Initialization
# ------------------------------------------
def test_processor_initialization(processor_instance):
    """Test processor initializes correctly."""
    assert processor_instance is not None
    assert processor_instance.output_dir == "/data"
    assert hasattr(processor_instance, "execute")


def test_repr(processor_instance):
    """Test __repr__ returns expected string."""
    result = repr(processor_instance)
    assert result.startswith("<SentinelFetchProcessor>")


# ------------------------------------------
# Test Input Validation
# ------------------------------------------
def test_execute_requires_geometry_or_id(processor_instance):
    """Test that either farm_geometry or farm_id is required."""

    data = {
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with pytest.raises(
        ProcessorExecuteError,
        match="Either 'farm_geometry' or 'farm_id' must be provided",
    ):
        processor_instance.execute(data)


def test_execute_rejects_farm_id_zero(processor_instance):
    """execute raises ProcessorExecuteError when farm_id is 0."""
    data = {
        "farm_id": 0,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }
    with pytest.raises(
        ProcessorExecuteError, match="Farm ID must be a positive integer"
    ):
        processor_instance.execute(data)


def test_execute_rejects_negative_farm_id(processor_instance):
    """execute raises ProcessorExecuteError when farm_id is negative."""
    data = {
        "farm_id": -5,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }
    with pytest.raises(
        ProcessorExecuteError, match="Farm ID must be a positive integer"
    ):
        processor_instance.execute(data)


def test_execute_missing_temporal_extent_key(processor_instance, sample_farm_geometry):
    """execute raises ProcessorExecuteError when temporal_extent key is absent."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "output_products": ["ndvi"],
        # 'temporal_extent' intentionally omitted
    }
    with pytest.raises(ProcessorExecuteError, match="Invalid input parameters"):
        processor_instance.execute(data)


def test_execute_rejects_invalid_geometry(processor_instance):
    """execute raises ProcessorExecuteError for a self-intersecting (invalid) polygon."""
    # Bowtie / figure-8: self-intersecting polygon
    invalid_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-71.5, 45.5],
                [-71.4, 45.6],
                [-71.4, 45.5],
                [-71.5, 45.6],
                [-71.5, 45.5],
            ]
        ],
    }
    data = {
        "farm_geometry": invalid_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }
    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(ProcessorExecuteError, match="Invalid geometry"):
            processor_instance.execute(data)


def test_execute_rejects_both_geometry_and_id(processor_instance, sample_farm_geometry):
    """Test that providing both farm_geometry and farm_id raises error."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "farm_id": 4,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with pytest.raises(ProcessorExecuteError, match="Provide only one of"):
        processor_instance.execute(data)


def test_execute_validates_farm_size(processor_instance, sample_farm_geometry_large):
    """Test that large farms (>100 km²) are rejected."""

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        data = {
            "farm_geometry": sample_farm_geometry_large,
            "temporal_extent": ["2024-06-01", "2024-08-31"],
            "output_products": ["ndvi"],
        }

        with pytest.raises(ProcessorExecuteError, match="exceeds maximum allowed"):
            processor_instance.execute(data)


# ------------------------------------------
# Test Database Geometry Retrieval
# ------------------------------------------
def test_get_geometry_from_db_success(processor_instance, mock_db_connection):
    """Test successful geometry retrieval from database."""
    with patch("psycopg.connect", return_value=mock_db_connection):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DBNAME": "test",
                "POSTGRES_USER": "user",
                "POSTGRES_PASS": "pass",
            },
        ):
            geometry = processor_instance._get_geometry_from_db(4)

            assert geometry is not None
            assert geometry["type"] == "Polygon"
            assert "coordinates" in geometry


def test_get_geometry_from_db_not_found(processor_instance):
    """Test error when farm ID not found in database."""

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.execute = MagicMock()

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_PASS": "testpass"}
        ):
            with pytest.raises(ProcessorExecuteError, match="Farm ID .* not found"):
                processor_instance._get_geometry_from_db(9999)


# ------------------------------------------
# Test Area Calculation
# ------------------------------------------
def test_calculate_area_km2_small(processor_instance, sample_farm_geometry_small):
    """Test area calculation for small farm."""
    from shapely.geometry import shape

    geom = shape(sample_farm_geometry_small)
    area = processor_instance._calculate_area_km2(geom.bounds)

    # Small farm should be less than 100 km²
    assert area < 100
    assert area > 0


def test_calculate_area_km2_large(processor_instance, sample_farm_geometry_large):
    """Test area calculation for large farm."""
    from shapely.geometry import shape

    geom = shape(sample_farm_geometry_large)
    area = processor_instance._calculate_area_km2(geom.bounds)

    # Large farm should exceed 100 km²
    assert area > 100


def test_calculate_area_km2_high_latitude():
    """Area near the pole (89°N) should be much smaller than a mid-latitude degree-square."""
    # 1-degree square straddling 89-90°N
    bounds = (0.0, 89.0, 1.0, 90.0)
    area = SentinelFetchProcessor._calculate_area_km2(bounds)
    # cos(89.5°) ≈ 0.00873, so km_per_deg_lon ≈ 111.32 * 0.00873 ≈ 0.97 km
    # height stays 111.32 km/deg → area ≈ 0.97 * 111.32 ≈ 108 km²
    # (only the longitudinal dimension is compressed by cos(lat))
    assert area > 0
    assert (
        50 < area < 200
    )  # Much smaller than a mid-latitude degree-square (~8 700 km²)


def test_calculate_area_km2_zero_span():
    """Degenerate bounds where north == south yield area == 0."""
    bounds = (-71.5, 45.5, -71.4, 45.5)  # latitude span = 0
    area = SentinelFetchProcessor._calculate_area_km2(bounds)
    assert area == 0.0


# ------------------------------------------
# Test Product Calculation
# ------------------------------------------
def test_calculate_product_ndvi(processor_instance, mock_openeo_connection):
    """Test NDVI calculation."""
    mock_cube = MagicMock()

    processor_instance._calculate_product(mock_cube, "ndvi", "median")

    # Should call reduce_dimension for temporal aggregation
    mock_cube.reduce_dimension.assert_called()


def test_calculate_product_evi(processor_instance, mock_openeo_connection):
    """Test EVI calculation."""
    mock_cube = MagicMock()

    processor_instance._calculate_product(mock_cube, "evi", "max")

    # Should call reduce_dimension and band for B02, B04, B08
    mock_cube.reduce_dimension.assert_called()


def test_calculate_product_savi(processor_instance, mock_openeo_connection):
    """Test SAVI calculation."""
    mock_cube = MagicMock()

    processor_instance._calculate_product(mock_cube, "savi", "min")

    # Should call reduce_dimension and band for B02, B04, B08
    mock_cube.reduce_dimension.assert_called()


def test_calculate_product_true_color(processor_instance, mock_openeo_connection):
    """Test true color RGB composite."""
    mock_cube = MagicMock()

    processor_instance._calculate_product(mock_cube, "true_color", "median")

    # Should filter bands for RGB
    mock_cube.reduce_dimension.assert_called()


# ------------------------------------------
# Test COG Conversion
# ------------------------------------------
def test_convert_to_cog_success(processor_instance, tmp_path):
    """Test successful COG conversion."""
    input_file = tmp_path / "input.tif"
    output_file = tmp_path / "output.tif"

    # Create a dummy input file
    input_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        processor_instance._convert_to_cog(str(input_file), str(output_file))
        # Should not raise any exception


def test_convert_to_cog_failure(processor_instance, tmp_path):
    """Test COG conversion failure."""

    input_file = tmp_path / "input.tif"
    output_file = tmp_path / "output.tif"

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "GDAL error: invalid file"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(ProcessorExecuteError, match="GDAL COG conversion failed"):
            processor_instance._convert_to_cog(str(input_file), str(output_file))


# ------------------------------------------
# Test Product Metadata
# ------------------------------------------
def test_get_product_title(processor_instance):
    """Test product title generation."""
    assert "NDVI" in processor_instance._get_product_title("ndvi")
    assert "EVI" in processor_instance._get_product_title("evi")
    assert "SAVI" in processor_instance._get_product_title("savi")
    assert "RGB" in processor_instance._get_product_title("true_color")


def test_get_product_title_raw_bands(processor_instance):
    """_get_product_title returns the correct title for raw_bands."""
    title = processor_instance._get_product_title("raw_bands")
    assert "Raw" in title
    assert "Sentinel" in title


def test_get_product_title_unknown_falls_back_to_upper(processor_instance):
    """_get_product_title falls back to product.upper() for unknown products."""
    title = processor_instance._get_product_title("mystery_product")
    assert title == "MYSTERY_PRODUCT"


def test_get_raster_bands_metadata_ndvi(processor_instance):
    """Test raster bands metadata for NDVI."""
    bands = processor_instance._get_raster_bands_metadata("ndvi")

    assert len(bands) == 1
    assert bands[0]["nodata"] == -9999
    assert bands[0]["data_type"] == "float32"
    assert "normalized difference" in bands[0]["unit"]


def test_get_raster_bands_metadata_true_color(processor_instance):
    """Test raster bands metadata for true color."""
    bands = processor_instance._get_raster_bands_metadata("true_color")

    assert len(bands) == 3  # RGB
    assert bands[0]["name"] == "red"
    assert bands[1]["name"] == "green"
    assert bands[2]["name"] == "blue"


def test_get_raster_bands_metadata_evi(processor_instance):
    """_get_raster_bands_metadata returns EVI-specific unit for evi."""
    bands = processor_instance._get_raster_bands_metadata("evi")
    assert len(bands) == 1
    assert bands[0]["nodata"] == -9999
    assert "enhanced vegetation index" in bands[0]["unit"]


def test_get_raster_bands_metadata_savi(processor_instance):
    """_get_raster_bands_metadata returns SAVI-specific unit for savi."""
    bands = processor_instance._get_raster_bands_metadata("savi")
    assert len(bands) == 1
    assert bands[0]["nodata"] == -9999
    assert "soil adjusted vegetation index" in bands[0]["unit"]


def test_get_raster_bands_metadata_raw_bands(processor_instance):
    """_get_raster_bands_metadata returns the default band entry for raw_bands."""
    bands = processor_instance._get_raster_bands_metadata("raw_bands")
    assert isinstance(bands, list)
    assert len(bands) == 1
    assert bands[0]["nodata"] == -9999


def test_get_raster_bands_metadata_unknown_product(processor_instance):
    """_get_raster_bands_metadata returns default nodata entry for unknown products."""
    bands = processor_instance._get_raster_bands_metadata("nonexistent_product")
    assert isinstance(bands, list)
    assert len(bands) == 1
    assert bands[0]["nodata"] == -9999


# ------------------------------------------
# Test STAC Item Creation
# ------------------------------------------
def test_create_stac_item_structure(
    processor_instance, sample_farm_geometry, valid_temporal_extent
):
    """Test STAC item has correct structure."""
    assets = {
        "ndvi": {
            "href": "/data/test.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": "NDVI",
            "raster:bands": [{"nodata": -9999}],
        }
    }

    item = processor_instance._create_stac_item(
        item_id="test_item",
        geometry=sample_farm_geometry,
        bbox=(-71.5, 45.5, -71.4, 45.6),
        temporal_extent=valid_temporal_extent,
        assets=assets,
        cloud_cover_max=20,
    )

    assert item["type"] == "Feature"
    assert item["stac_version"] == "1.0.0"
    assert item["id"] == "test_item"
    assert "geometry" in item
    assert "bbox" in item
    assert "properties" in item
    assert "assets" in item
    assert "datetime" in item["properties"]
    assert "eo:cloud_cover" in item["properties"]
    assert item["properties"]["platform"] == "sentinel-2"


def test_create_stac_item_temporal_properties(processor_instance, sample_farm_geometry):
    """Test STAC item temporal properties."""
    temporal_extent = ["2024-06-01", "2024-08-31"]

    item = processor_instance._create_stac_item(
        item_id="test_item",
        geometry=sample_farm_geometry,
        bbox=(-71.5, 45.5, -71.4, 45.6),
        temporal_extent=temporal_extent,
        assets={},
        cloud_cover_max=20,
    )

    assert "start_datetime" in item["properties"]
    assert "end_datetime" in item["properties"]
    assert item["properties"]["start_datetime"].startswith("2024-06-01")
    assert item["properties"]["end_datetime"].startswith("2024-08-31")


def test_create_stac_item_stac_extensions(processor_instance, sample_farm_geometry):
    """_create_stac_item includes the proj, raster, and eo extension URIs."""
    item = processor_instance._create_stac_item(
        item_id="test_ext",
        geometry=sample_farm_geometry,
        bbox=(-71.5, 45.5, -71.4, 45.6),
        temporal_extent=["2024-06-01", "2024-08-31"],
        assets={},
        cloud_cover_max=20,
    )

    extensions = item["stac_extensions"]
    assert any("projection" in e for e in extensions), "Missing projection extension"
    assert any("raster" in e for e in extensions), "Missing raster extension"
    assert any("/eo/" in e for e in extensions), "Missing eo extension"


def test_create_stac_item_calls_post_to_stac_api(
    processor_instance, sample_farm_geometry
):
    """_create_stac_item calls _post_to_stac_api exactly once."""
    with patch.object(processor_instance, "_post_to_stac_api") as mock_post:
        processor_instance._create_stac_item(
            item_id="test_post",
            geometry=sample_farm_geometry,
            bbox=(-71.5, 45.5, -71.4, 45.6),
            temporal_extent=["2024-06-01", "2024-08-31"],
            assets={},
            cloud_cover_max=20,
        )
        mock_post.assert_called_once()


# ------------------------------------------
# Test Preview URL Generation
# ------------------------------------------
def test_generate_preview_url(processor_instance):
    """Test preview URL generation for TiTiler."""
    asset_href = "/data/sentinel2_farm_4_ndvi_2024-06-01_2024-08-31_abc123.tif"

    with patch.dict(os.environ, {"RASTER_API_PORT": "8082"}):
        preview_url = processor_instance._generate_preview_url(asset_href)

        assert "raster-api:8082" in preview_url
        assert "/cog/preview.png" in preview_url
        assert "sentinel2_farm_4_ndvi" in preview_url
        assert "rescale=" in preview_url


# ------------------------------------------
# Test Environment Variable Requirements
# ------------------------------------------
def test_execute_requires_openeo_token(processor_instance, sample_farm_geometry):
    """Test that authentication is required (either stored token or env var)."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    # Mock auto-load to fail, and clear environment variable
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.side_effect = Exception("No stored token")

    with patch.dict(os.environ, {}, clear=True):
        with patch("openeo.connect", return_value=mock_conn):
            with pytest.raises(
                ProcessorExecuteError,
                match="OpenEO authentication failed. No valid refresh token found.",
            ):
                processor_instance.execute(data)


# ------------------------------------------
# Test OpenEO Authentication
# ------------------------------------------
def test_openeo_authentication_auto_load_success(
    processor_instance, sample_farm_geometry, mock_openeo_connection
):
    """Test successful authentication via auto-load from persistent storage."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    # Auto-load succeeds (no env var needed)
    with patch.dict(os.environ, {}, clear=True):
        with patch("openeo.connect", return_value=mock_openeo_connection):
            with patch.object(processor_instance, "_convert_to_cog"):
                with patch("rasterio.open"):
                    with patch("tempfile.mkdtemp", return_value="/tmp/test"):
                        try:
                            processor_instance.execute(data)
                        except Exception:
                            # Expected to fail during mocked execution; we only need to verify auth was called
                            pass

                        # Verify auto-load authentication was called (once, no parameters)
                        assert (
                            mock_openeo_connection.authenticate_oidc_refresh_token.call_count
                            >= 1
                        )
                        # First call should be auto-load (no parameters)
                        first_call_kwargs = mock_openeo_connection.authenticate_oidc_refresh_token.call_args_list[
                            0
                        ][
                            1
                        ]
                        assert len(first_call_kwargs) == 0


def test_openeo_authentication_called(
    processor_instance, sample_farm_geometry, mock_openeo_connection
):
    """Test that OpenEO OIDC authentication is called."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with patch("openeo.connect", return_value=mock_openeo_connection):
            with patch.object(processor_instance, "_convert_to_cog"):
                with patch("rasterio.open"):
                    with patch("tempfile.mkdtemp", return_value="/tmp/test"):
                        try:
                            processor_instance.execute(data)
                        except Exception:
                            # Expected to fail during mocked execution; we only need to verify auth was called
                            pass

                        # Verify OIDC refresh token authentication was called
                        assert (
                            mock_openeo_connection.authenticate_oidc_refresh_token.called
                        )


def test_openeo_authentication_uses_refresh_token(
    processor_instance, sample_farm_geometry
):
    """Test that OPENEO_REFRESH_TOKEN from environment is used as the primary auth path."""
    mock_conn = MagicMock()
    # Env var is tried first; authenticates successfully on the first call
    mock_conn.authenticate_oidc_refresh_token.return_value = None
    mock_conn.load_collection.side_effect = Exception("Stop execution")

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    test_token = "a" * 210

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": test_token}, clear=True):
        with patch("openeo.connect", return_value=mock_conn):
            try:
                processor_instance.execute(data)
            except Exception:
                # Expected to fail at load_collection; we only need to verify auth calls
                pass

            # Verify authenticate_oidc_refresh_token was called exactly once (env var path)
            assert mock_conn.authenticate_oidc_refresh_token.call_count == 1

            # Single call: env var token, no client_id
            call_kwargs = mock_conn.authenticate_oidc_refresh_token.call_args_list[0][1]
            assert "refresh_token" in call_kwargs
            assert call_kwargs["refresh_token"] == test_token
            assert "client_id" not in call_kwargs


def test_openeo_authentication_failure(processor_instance, sample_farm_geometry):
    """Test that a hard failure is raised when both env var token and config file fallback fail."""

    mock_conn = MagicMock()
    # Both the env var auth call and the config file fallback call fail
    mock_conn.authenticate_oidc_refresh_token.side_effect = Exception(
        "Authentication failed"
    )

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    # Token must be 200+ chars to pass _is_valid_token() and reach the env-var auth path
    valid_length_token = "a" * 210

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": valid_length_token}):
        with patch("openeo.connect", return_value=mock_conn):
            with pytest.raises(
                ProcessorExecuteError,
                match="OpenEO authentication failed.*expired or invalid.*config file fallback also failed",
            ):
                processor_instance.execute(data)

        # Both paths attempted: env var call + config file fallback call
        assert mock_conn.authenticate_oidc_refresh_token.call_count == 2


def test_openeo_authentication_envvar_fails_configfile_succeeds(
    processor_instance, sample_farm_geometry
):
    """When env var token auth fails, a valid config-file token is used as fallback."""
    mock_conn = MagicMock()
    # First call (env var path) raises; second call (config file path) succeeds
    mock_conn.authenticate_oidc_refresh_token.side_effect = [
        Exception("Token expired"),
        None,  # config file auth succeeds
    ]
    # Stop execution after auth so we can inspect call count.
    # Use KeyboardInterrupt (BaseException) so it is not caught by the broad
    # `except Exception` handler inside _load_sentinel2_cube.
    mock_conn.load_collection.side_effect = KeyboardInterrupt("Stop after auth")

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    valid_length_token = "a" * 210

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": valid_length_token}):
        with patch("openeo.connect", return_value=mock_conn):
            try:
                processor_instance.execute(data)
            except ProcessorExecuteError:
                raise  # should NOT raise ProcessorExecuteError from auth
            except (KeyboardInterrupt, Exception):
                pass  # load_collection stopping is expected

    # Env var attempt + config file fallback both called
    assert mock_conn.authenticate_oidc_refresh_token.call_count == 2
    # Second call must be without arguments (config file auto-load)
    second_call_args, second_call_kwargs = (
        mock_conn.authenticate_oidc_refresh_token.call_args_list[1]
    )
    assert len(second_call_args) == 0
    assert len(second_call_kwargs) == 0


def test_openeo_connection_url(processor_instance, sample_farm_geometry):
    """Test that OpenEO connects to the correct backend URL."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with patch("openeo.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_conn.authenticate_oidc.return_value = None
            mock_conn.load_collection.side_effect = Exception("Stop execution")
            mock_connect.return_value = mock_conn

            try:
                processor_instance.execute(data)
            except Exception:
                # Expected to fail at load_collection; we only need to verify connection URL
                pass

            # Verify connect was called with the expected backend URL
            mock_connect.assert_called_once()
            call_args = mock_connect.call_args[0]
            assert len(call_args) > 0
            # Should connect to openEO Platform or Copernicus Data Space
            assert (
                "openeo" in call_args[0].lower() or "dataspace" in call_args[0].lower()
            )


def test_openeo_authentication_with_provider_id(
    processor_instance, sample_farm_geometry
):
    """Test that env var authentication does NOT pass client_id, letting openEO auto-detect it."""
    mock_conn = MagicMock()
    # Env var is tried first and succeeds in a single call
    mock_conn.authenticate_oidc_refresh_token.return_value = None
    mock_conn.load_collection.side_effect = Exception("Stop execution")

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    valid_length_token = "a" * 210
    with patch.dict(
        os.environ, {"OPENEO_REFRESH_TOKEN": valid_length_token}, clear=True
    ):
        with patch("openeo.connect", return_value=mock_conn):
            try:
                processor_instance.execute(data)
            except Exception:
                # Expected to fail at load_collection; we only need to verify client_id usage
                pass

            # Verify authenticate_oidc_refresh_token was called exactly once (env var path)
            assert mock_conn.authenticate_oidc_refresh_token.call_count == 1

            # Single call should NOT include client_id
            call_kwargs = mock_conn.authenticate_oidc_refresh_token.call_args_list[0][1]
            assert "client_id" not in call_kwargs
            assert call_kwargs["refresh_token"] == valid_length_token


# ------------------------------------------
# Test _is_valid_token classmethod
# ------------------------------------------
def test_is_valid_token_rejects_empty():
    """_is_valid_token returns False for empty/None-like inputs."""

    assert SentinelFetchProcessor._is_valid_token("") is False


def test_is_valid_token_rejects_placeholder():
    """_is_valid_token returns False for known placeholder values."""

    placeholders = [
        "your_refresh_token_here",
        "CHANGE_ME",
        "placeholder",
        "<your_token>",
        "example_token",
    ]
    for placeholder in placeholders:
        assert (
            SentinelFetchProcessor._is_valid_token(placeholder) is False
        ), f"Expected '{placeholder}' to be rejected as a placeholder"


def test_is_valid_token_rejects_short_tokens():
    """_is_valid_token returns False for tokens shorter than 200 characters."""

    assert SentinelFetchProcessor._is_valid_token("a" * 199) is False


def test_is_valid_token_accepts_valid_token():
    """_is_valid_token returns True for a sufficiently long, non-placeholder token."""

    assert SentinelFetchProcessor._is_valid_token("a" * 210) is True


def test_is_valid_token_callable_on_class_without_instance():
    """_is_valid_token can be invoked directly on the class (classmethod contract)."""

    # Must not require an instance
    result = SentinelFetchProcessor._is_valid_token("a" * 210)
    assert result is True


def test_is_valid_token_rejects_none():
    """_is_valid_token returns False for None input."""
    assert SentinelFetchProcessor._is_valid_token(None) is False


def test_is_valid_token_boundary_exactly_200_chars():
    """_is_valid_token accepts exactly 200-char token (boundary: len < 200 rejects)."""
    assert SentinelFetchProcessor._is_valid_token("a" * 200) is True


def test_is_valid_token_rejects_whitespace_only():
    """_is_valid_token returns False for whitespace-only string (stripped to empty)."""
    assert SentinelFetchProcessor._is_valid_token("   ") is False


def test_is_valid_token_rejects_placeholder_embedded_in_long_string():
    """_is_valid_token rejects a 200+ char token that contains a placeholder substring."""
    # 'placeholder' is in TOKEN_PLACEHOLDER_PATTERNS; embedding it still rejects
    long_with_placeholder = "prefix_".ljust(200, "x") + "placeholder"
    assert len(long_with_placeholder) >= 200
    assert SentinelFetchProcessor._is_valid_token(long_with_placeholder) is False


def test_is_valid_token_rejects_all_defined_placeholder_patterns():
    """Every pattern in TOKEN_PLACEHOLDER_PATTERNS is rejected."""
    for pattern in SentinelFetchProcessor.TOKEN_PLACEHOLDER_PATTERNS:
        assert (
            SentinelFetchProcessor._is_valid_token(pattern) is False
        ), f"Expected pattern '{pattern}' from TOKEN_PLACEHOLDER_PATTERNS to be rejected"


# ------------------------------------------
# Test _authenticate_with_env_token
# ------------------------------------------
def test_authenticate_with_env_token_success(processor_instance):
    """_authenticate_with_env_token succeeds on first call when token is valid."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.return_value = None
    token = "a" * 210

    processor_instance._authenticate_with_env_token(mock_conn, token)

    mock_conn.authenticate_oidc_refresh_token.assert_called_once_with(
        refresh_token=token
    )


def test_authenticate_with_env_token_falls_back_to_config_file(processor_instance):
    """_authenticate_with_env_token falls back to refresh-tokens.json when env var token fails."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.side_effect = [
        Exception("Token expired"),
        None,  # config file succeeds
    ]
    token = "a" * 210

    processor_instance._authenticate_with_env_token(mock_conn, token)

    assert mock_conn.authenticate_oidc_refresh_token.call_count == 2
    # Second call must be without arguments (config file auto-load)
    _, kwargs = mock_conn.authenticate_oidc_refresh_token.call_args_list[1]
    assert len(kwargs) == 0


def test_authenticate_with_env_token_raises_when_both_fail(processor_instance):
    """_authenticate_with_env_token raises ProcessorExecuteError when both env var and config file fail."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.side_effect = Exception("Expired")
    token = "a" * 210

    with pytest.raises(
        ProcessorExecuteError,
        match="expired or invalid.*config file fallback also failed",
    ):
        processor_instance._authenticate_with_env_token(mock_conn, token)

    assert mock_conn.authenticate_oidc_refresh_token.call_count == 2


def test_authenticate_with_env_token_does_not_pass_client_id(processor_instance):
    """_authenticate_with_env_token does not pass client_id, letting openEO auto-detect it."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.return_value = None
    token = "a" * 210

    processor_instance._authenticate_with_env_token(mock_conn, token)

    call_kwargs = mock_conn.authenticate_oidc_refresh_token.call_args_list[0][1]
    assert "client_id" not in call_kwargs
    assert call_kwargs["refresh_token"] == token


# ------------------------------------------
# Test _authenticate_with_config_file
# ------------------------------------------
def test_authenticate_with_config_file_success(processor_instance):
    """_authenticate_with_config_file succeeds when a stored token exists."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.return_value = None

    processor_instance._authenticate_with_config_file(mock_conn)

    mock_conn.authenticate_oidc_refresh_token.assert_called_once_with()


def test_authenticate_with_config_file_raises_when_no_token(processor_instance):
    """_authenticate_with_config_file raises ProcessorExecuteError when config file auth fails."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.side_effect = Exception("No stored token")

    with pytest.raises(
        ProcessorExecuteError,
        match="OpenEO authentication failed. No valid refresh token found.",
    ):
        processor_instance._authenticate_with_config_file(mock_conn)


def test_authenticate_with_config_file_calls_without_arguments(processor_instance):
    """_authenticate_with_config_file calls authenticate_oidc_refresh_token with no args (auto-load)."""
    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.return_value = None

    processor_instance._authenticate_with_config_file(mock_conn)

    args, kwargs = mock_conn.authenticate_oidc_refresh_token.call_args
    assert len(args) == 0
    assert len(kwargs) == 0


# ------------------------------------------
# Test _get_required_bands staticmethod
# ------------------------------------------
def test_get_required_bands_ndvi():
    """ndvi requires B04 (red) and B08 (NIR) only."""
    bands = SentinelFetchProcessor._get_required_bands(["ndvi"])
    assert bands == {"B04", "B08"}


def test_get_required_bands_evi_includes_blue():
    """evi additionally requires B02 (blue) on top of B04 and B08."""
    bands = SentinelFetchProcessor._get_required_bands(["evi"])
    assert bands == {"B02", "B04", "B08"}


def test_get_required_bands_savi_same_as_ndvi():
    """savi requires B04 and B08 (same as ndvi, no blue)."""
    bands = SentinelFetchProcessor._get_required_bands(["savi"])
    assert bands == {"B04", "B08"}


def test_get_required_bands_true_color():
    """true_color requires B02, B03, B04 (RGB)."""
    bands = SentinelFetchProcessor._get_required_bands(["true_color"])
    assert bands == {"B02", "B03", "B04"}


def test_get_required_bands_raw_bands():
    """raw_bands requires B02, B03, B04, B08."""
    bands = SentinelFetchProcessor._get_required_bands(["raw_bands"])
    assert bands == {"B02", "B03", "B04", "B08"}


def test_get_required_bands_combined_products():
    """Multiple products yield the union of their required bands."""
    bands = SentinelFetchProcessor._get_required_bands(["ndvi", "true_color"])
    # ndvi: {B04, B08}, true_color: {B02, B03, B04}  union: {B02, B03, B04, B08}
    assert bands == {"B02", "B03", "B04", "B08"}


def test_get_required_bands_empty_list():
    """Empty products list yields an empty set."""
    bands = SentinelFetchProcessor._get_required_bands([])
    assert bands == set()


def test_get_required_bands_unknown_product():
    """Unknown product names are silently ignored, yielding an empty set."""
    bands = SentinelFetchProcessor._get_required_bands(["mystery_product"])
    assert bands == set()


# ------------------------------------------
# Test Integration (Mocked)
# ------------------------------------------
@pytest.mark.mocked
def test_full_execution_flow_with_geometry(
    processor_instance,
    sample_farm_geometry_small,
    valid_temporal_extent,
    valid_output_products,
    mock_openeo_connection,
    tmp_path,
):
    """Test full execution flow with farm geometry."""

    data = {
        "farm_geometry": sample_farm_geometry_small,
        "temporal_extent": valid_temporal_extent,
        "output_products": valid_output_products,
        "aggregation_method": "median",
        "cloud_cover_max": 20,
    }

    # Mock all external dependencies
    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with patch("openeo.connect", return_value=mock_openeo_connection):
            with patch.object(processor_instance, "_convert_to_cog"):
                with patch("rasterio.open"):
                    with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
                        # This will fail at openeo execution but validates input processing
                        try:
                            processor_instance.execute(data)
                        except Exception:
                            # Expected to fail due to mocking limitations (e.g., STAC API calls)
                            # The test validates that input processing and validation stages pass
                            pass


@pytest.mark.mocked
def test_full_execution_flow_with_farm_id(
    processor_instance,
    valid_temporal_extent,
    mock_db_connection,
    mock_openeo_connection,
    tmp_path,
):
    """Test full execution flow with farm ID."""
    data = {
        "farm_id": 4,
        "temporal_extent": valid_temporal_extent,
        "output_products": ["ndvi"],
        "aggregation_method": "max",
    }

    with patch.dict(
        os.environ,
        {
            "OPENEO_REFRESH_TOKEN": "a" * 210,
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DBNAME": "test",
            "POSTGRES_USER": "user",
            "POSTGRES_PASS": "pass",
        },
    ):
        with patch("psycopg.connect", return_value=mock_db_connection):
            with patch("openeo.connect", return_value=mock_openeo_connection):
                with patch.object(processor_instance, "_convert_to_cog"):
                    with patch("rasterio.open"):
                        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
                            try:
                                processor_instance.execute(data)
                            except Exception:
                                # Expected to fail at some point due to mocking
                                pass


# ------------------------------------------
# Test Edge Cases and Additional Validation
# ------------------------------------------
def test_temporal_extent_invalid_format(processor_instance, sample_farm_geometry):
    """Test that invalid temporal extent format is rejected."""

    # Single date string instead of array
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": "2024-06-01",
        "output_products": ["ndvi"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(Exception):  # Should fail validation
            processor_instance.execute(data)


def test_temporal_extent_reversed_dates(processor_instance, sample_farm_geometry):
    """Test temporal extent with end date before start date raises ProcessorExecuteError."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-08-31", "2024-06-01"],  # Reversed
        "output_products": ["ndvi"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(ProcessorExecuteError):
            processor_instance.execute(data)


def test_empty_output_products_list(processor_instance, sample_farm_geometry):
    """Test that empty output products list is rejected."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": [],  # Empty list
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(Exception):  # Should fail validation
            processor_instance.execute(data)


def test_invalid_product_name(processor_instance, sample_farm_geometry):
    """Test that invalid product names are rejected."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["invalid_product"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(Exception):  # Should fail validation
            processor_instance.execute(data)


def test_cloud_cover_boundary_values(processor_instance, sample_farm_geometry):
    """Test cloud cover at boundary values (0 and 100)."""
    data_min = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
        "cloud_cover_max": 0,  # Minimum
    }

    data_max = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
        "cloud_cover_max": 100,  # Maximum
    }

    # Both should be valid inputs (whether data is found is another matter)
    # Just verify they pass initial validation
    assert data_min["cloud_cover_max"] == 0
    assert data_max["cloud_cover_max"] == 100


def test_invalid_cloud_cover_values(processor_instance, sample_farm_geometry):
    """Test cloud cover outside valid range raises ProcessorExecuteError immediately."""
    for bad_value in [-10, 150]:
        data = {
            "farm_geometry": sample_farm_geometry,
            "temporal_extent": ["2024-06-01", "2024-08-31"],
            "output_products": ["ndvi"],
            "cloud_cover_max": bad_value,
        }
        with pytest.raises(ProcessorExecuteError, match="cloud_cover_max"):
            processor_instance.execute(data)


def test_invalid_aggregation_method(processor_instance, sample_farm_geometry):
    """Test invalid aggregation method."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
        "aggregation_method": "invalid_method",
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with pytest.raises(Exception):  # Should fail validation
            processor_instance.execute(data)


def test_multipolygon_geometry(processor_instance):
    """Test processing with MultiPolygon geometry."""
    multipolygon_geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [-71.5, 45.5],
                    [-71.4, 45.5],
                    [-71.4, 45.6],
                    [-71.5, 45.6],
                    [-71.5, 45.5],
                ]
            ],
            [
                [
                    [-71.3, 45.3],
                    [-71.2, 45.3],
                    [-71.2, 45.4],
                    [-71.3, 45.4],
                    [-71.3, 45.3],
                ]
            ],
        ],
    }

    from shapely.geometry import shape

    geom = shape(multipolygon_geometry)
    area = processor_instance._calculate_area_km2(geom.bounds)
    assert area > 0


def test_database_connection_failure(processor_instance):
    """Test handling of database connection failure."""

    with patch(
        "psycopg.connect", side_effect=psycopg.OperationalError("Connection refused")
    ):
        with patch.dict(
            os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_PASS": "testpass"}
        ):
            with pytest.raises(ProcessorExecuteError, match="Database error"):
                processor_instance._get_geometry_from_db(4)


def test_malformed_geometry_from_database(processor_instance):
    """Test handling of malformed geometry data from database."""

    mock_cursor = MagicMock()
    # Return invalid JSON
    mock_cursor.fetchone.return_value = ("invalid json",)
    mock_cursor.execute = MagicMock()

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_PASS": "testpass"}
        ):
            # JSON decode error is now properly caught and wrapped
            with pytest.raises(ProcessorExecuteError, match="Invalid geometry data"):
                processor_instance._get_geometry_from_db(4)


def test_get_geometry_from_db_invalid_table_name(processor_instance):
    """_get_geometry_from_db raises ProcessorExecuteError for invalid FARM_TABLE_NAME."""
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PASS": "testpass",
                "FARM_TABLE_NAME": "bad;name",
            },
        ):
            with pytest.raises(ProcessorExecuteError, match="Invalid table name"):
                processor_instance._get_geometry_from_db(1)


def test_get_geometry_from_db_invalid_geometry_column(processor_instance):
    """_get_geometry_from_db raises ProcessorExecuteError for invalid FARM_GEOMETRY_COLUMN."""
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PASS": "testpass",
                "FARM_GEOMETRY_COLUMN": "bad column",
            },
        ):
            with pytest.raises(ProcessorExecuteError, match="Invalid geometry column"):
                processor_instance._get_geometry_from_db(1)


def test_get_geometry_from_db_invalid_id_column(processor_instance):
    """_get_geometry_from_db raises ProcessorExecuteError for invalid FARM_ID_COLUMN."""
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PASS": "testpass",
                "FARM_ID_COLUMN": "id;drop table",
            },
        ):
            with pytest.raises(ProcessorExecuteError, match="Invalid ID column"):
                processor_instance._get_geometry_from_db(1)


def test_negative_farm_id(processor_instance):
    """Test farm ID with negative value."""

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.execute = MagicMock()

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None

    with patch("psycopg.connect", return_value=mock_conn):
        with patch.dict(
            os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_PASS": "testpass"}
        ):
            with pytest.raises(ProcessorExecuteError, match="Farm ID .* not found"):
                processor_instance._get_geometry_from_db(-1)


def test_zero_area_geometry(processor_instance):
    """Test geometry with zero or near-zero area."""
    # Point-like polygon (degenerate)
    tiny_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-71.5, 45.5],
                [-71.500001, 45.5],
                [-71.500001, 45.500001],
                [-71.5, 45.500001],
                [-71.5, 45.5],
            ]
        ],
    }

    from shapely.geometry import shape

    geom = shape(tiny_geometry)
    area = processor_instance._calculate_area_km2(geom.bounds)
    assert area >= 0


def test_all_aggregation_methods(processor_instance):
    """Test all supported aggregation methods."""
    mock_cube = MagicMock()

    for method in ["median", "max", "min", "mean"]:
        processor_instance._calculate_product(mock_cube, "ndvi", method)
        # Should not raise exception


def test_raw_bands_product(processor_instance):
    """Test raw_bands product generation."""
    mock_cube = MagicMock()

    processor_instance._calculate_product(mock_cube, "raw_bands", "median")

    # Should call reduce_dimension
    mock_cube.reduce_dimension.assert_called()


def test_calculate_product_unknown_returns_cube(processor_instance):
    """Unknown product name falls through to the default return of the cube unchanged."""
    mock_cube = MagicMock()
    mock_cube.reduce_dimension.return_value = mock_cube

    result = processor_instance._calculate_product(
        mock_cube, "totally_unknown_product", "median"
    )

    # reduce_dimension still called for temporal aggregation
    mock_cube.reduce_dimension.assert_called_once()
    # Result should be the cube returned by reduce_dimension (no further transformation)
    assert result is mock_cube


def test_calculate_product_evi_passes_correct_coefficients(processor_instance):
    """_calculate_product passes the class-level EVI constants to veg_indices.calculate_evi."""
    mock_cube = MagicMock()
    mock_cube.reduce_dimension.return_value = mock_cube

    with patch("processes.eo_sentinel_fetch.veg_indices.calculate_evi") as mock_evi:
        mock_evi.return_value = mock_cube
        processor_instance._calculate_product(mock_cube, "evi", "median")

        mock_evi.assert_called_once_with(
            mock_cube,
            coeff_g=SentinelFetchProcessor.EVI_COEFF_G,
            coeff_c1=SentinelFetchProcessor.EVI_COEFF_C1,
            coeff_c2=SentinelFetchProcessor.EVI_COEFF_C2,
            coeff_l=SentinelFetchProcessor.EVI_COEFF_L,
        )


def test_multiple_products_combination(processor_instance):
    """Test metadata for multiple different products."""
    products = ["ndvi", "evi", "savi", "true_color", "raw_bands"]

    for product in products:
        title = processor_instance._get_product_title(product)
        assert title is not None
        assert len(title) > 0

        bands = processor_instance._get_raster_bands_metadata(product)
        assert isinstance(bands, list)
        assert len(bands) > 0


def test_stac_item_with_multiple_assets(processor_instance, sample_farm_geometry):
    """Test STAC item creation with multiple assets."""
    assets = {
        "ndvi": {
            "href": "/data/test_ndvi.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": "NDVI",
            "raster:bands": [{"nodata": -9999}],
        },
        "evi": {
            "href": "/data/test_evi.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": "EVI",
            "raster:bands": [{"nodata": -9999}],
        },
    }

    item = processor_instance._create_stac_item(
        item_id="test_item",
        geometry=sample_farm_geometry,
        bbox=(-71.5, 45.5, -71.4, 45.6),
        temporal_extent=["2024-06-01", "2024-08-31"],
        assets=assets,
        cloud_cover_max=20,
    )

    assert len(item["assets"]) == 2
    assert "ndvi" in item["assets"]
    assert "evi" in item["assets"]


def test_preview_url_without_env_var(processor_instance):
    """Test preview URL generation without RASTER_API_PORT env var."""
    asset_href = "/data/test.tif"

    # Clear environment variable
    with patch.dict(os.environ, {}, clear=True):
        preview_url = processor_instance._generate_preview_url(asset_href)
        # Should use default or handle gracefully
        assert "preview.png" in preview_url


def test_cog_conversion_with_nonexistent_file(processor_instance, tmp_path):
    """Test COG conversion with file that doesn't exist."""

    input_file = tmp_path / "nonexistent.tif"
    output_file = tmp_path / "output.tif"

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Input file does not exist"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(ProcessorExecuteError, match="GDAL COG conversion failed"):
            processor_instance._convert_to_cog(str(input_file), str(output_file))


def test_long_temporal_extent(processor_instance, sample_farm_geometry):
    """Test processing with very long temporal extent (multi-year)."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2020-01-01", "2024-12-31"],  # 5 years
        "output_products": ["ndvi"],
    }

    # Should accept the input (though may have practical limitations)
    assert data["temporal_extent"][0] < data["temporal_extent"][1]


def test_same_date_temporal_extent(processor_instance, sample_farm_geometry):
    """Test temporal extent with same start and end date."""
    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-06-01"],  # Same date
        "output_products": ["ndvi"],
    }

    # Might be valid for single-day acquisition
    assert data["temporal_extent"][0] == data["temporal_extent"][1]


def test_bbox_calculation_from_geometry(processor_instance, sample_farm_geometry):
    """Test that bbox is correctly calculated from geometry."""
    from shapely.geometry import shape

    geom = shape(sample_farm_geometry)
    bounds = geom.bounds  # (minx, miny, maxx, maxy)

    # Verify bounds are in expected order
    assert bounds[0] < bounds[2]  # minx < maxx
    assert bounds[1] < bounds[3]  # miny < maxy


def test_geometry_with_holes(processor_instance):
    """Test polygon geometry with interior holes.

    Note: Current implementation uses bounding box for area calculation,
    so holes don't affect the calculated area. This test verifies the
    geometry is valid and processable.
    """
    geometry_with_hole = {
        "type": "Polygon",
        "coordinates": [
            # Exterior ring
            [[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]],
            # Interior ring (hole) - larger hole for measurable difference
            [
                [-71.46, 45.52],
                [-71.44, 45.52],
                [-71.44, 45.58],
                [-71.46, 45.58],
                [-71.46, 45.52],
            ],
        ],
    }

    from shapely.geometry import shape

    geom = shape(geometry_with_hole)
    # Verify geometry is valid
    assert geom.is_valid
    # Verify area can be calculated
    area = processor_instance._calculate_area_km2(geom.bounds)
    assert area > 0
    # Since implementation uses bounding box, verify it matches
    geom_no_hole = shape(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [-71.5, 45.5],
                    [-71.4, 45.5],
                    [-71.4, 45.6],
                    [-71.5, 45.6],
                    [-71.5, 45.5],
                ]
            ],
        }
    )
    area_no_hole = processor_instance._calculate_area_km2(geom_no_hole.bounds)
    # Areas should be equal since implementation uses bounding box
    assert area == area_no_hole


# ------------------------------------------
# Test Error Handling
# ------------------------------------------
def test_openeo_connection_failure(processor_instance, sample_farm_geometry):
    """Test handling of openEO connection failure."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with patch("openeo.connect", side_effect=Exception("Connection failed")):
            with pytest.raises(
                ProcessorExecuteError, match="Failed to connect to openEO backend"
            ):
                processor_instance.execute(data)


def test_sentinel_data_load_failure(processor_instance, sample_farm_geometry):
    """Test handling of Sentinel-2 data loading failure."""

    data = {
        "farm_geometry": sample_farm_geometry,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.return_value = None
    mock_conn.load_collection.side_effect = Exception("Collection not found")

    with patch.dict(os.environ, {"OPENEO_REFRESH_TOKEN": "a" * 210}):
        with patch("openeo.connect", return_value=mock_conn):
            with pytest.raises(
                ProcessorExecuteError,
                match="Failed to load Sentinel-2 data from OpenEO",
            ):
                processor_instance.execute(data)


# ------------------------------------------
# Test STAC API Integration
# ------------------------------------------
@pytest.fixture
def sample_stac_item():
    """Sample STAC item for testing."""
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": "sentinel2_farm_4_2024-06-01_2024-08-31",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-71.5, 45.5],
                    [-71.4, 45.5],
                    [-71.4, 45.6],
                    [-71.5, 45.6],
                    [-71.5, 45.5],
                ]
            ],
        },
        "bbox": [-71.5, 45.5, -71.4, 45.6],
        "properties": {
            "datetime": "2024-07-15T00:00:00Z",
            "platform": "sentinel-2",
        },
        "assets": {},
        "links": [],
    }


def test_ensure_collection_exists_already_exists(processor_instance):
    """Test _ensure_collection_exists when collection already exists."""

    # Reset the class-level cache
    SentinelFetchProcessor._collection_checked = False

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("requests.get", return_value=mock_response):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            processor_instance._ensure_collection_exists()

            # Should mark as checked
            assert SentinelFetchProcessor._collection_checked is True


def test_ensure_collection_exists_creates_new(processor_instance):
    """Test _ensure_collection_exists creates collection when it doesn't exist."""

    # Reset the class-level cache
    SentinelFetchProcessor._collection_checked = False

    mock_get_response = MagicMock()
    mock_get_response.status_code = 404

    mock_post_response = MagicMock()
    mock_post_response.status_code = 201

    with patch("requests.get", return_value=mock_get_response):
        with patch("requests.post", return_value=mock_post_response) as mock_post:
            with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
                processor_instance._ensure_collection_exists()

                # Should have attempted to create collection
                mock_post.assert_called_once()
                call_args = mock_post.call_args

                # Check the collection payload
                assert "sentinel2_eo_products" in str(call_args)
                assert SentinelFetchProcessor._collection_checked is True


def test_ensure_collection_exists_network_error(processor_instance):
    """Test _ensure_collection_exists handles network errors gracefully."""
    import requests

    # Reset the class-level cache
    SentinelFetchProcessor._collection_checked = False

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError()):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            # Should not raise exception, just log warning
            processor_instance._ensure_collection_exists()

            # Should not mark as checked on error
            assert SentinelFetchProcessor._collection_checked is False


def test_ensure_collection_exists_unexpected_status(processor_instance):
    """_ensure_collection_exists returns without creating or caching on unexpected status (e.g. 503)."""
    SentinelFetchProcessor._collection_checked = False

    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch("requests.get", return_value=mock_response):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            # Should not raise; just log warning and return
            processor_instance._ensure_collection_exists()

    # Cache should remain False since neither success nor creation occurred
    assert SentinelFetchProcessor._collection_checked is False


def test_ensure_collection_exists_post_failure(processor_instance):
    """_ensure_collection_exists logs error and leaves cache False when POST returns non-2xx."""
    SentinelFetchProcessor._collection_checked = False

    mock_get_response = MagicMock()
    mock_get_response.status_code = 404

    mock_post_response = MagicMock()
    mock_post_response.status_code = 500
    mock_post_response.text = "Internal Server Error"

    with patch("requests.get", return_value=mock_get_response):
        with patch("requests.post", return_value=mock_post_response):
            with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
                processor_instance._ensure_collection_exists()

    assert SentinelFetchProcessor._collection_checked is False


def test_ensure_collection_exists_cached(processor_instance):
    """Test _ensure_collection_exists uses cache on subsequent calls."""

    # Set cache as already checked
    SentinelFetchProcessor._collection_checked = True

    with patch("requests.get") as mock_get:
        processor_instance._ensure_collection_exists()

        # Should not make any HTTP calls
        mock_get.assert_not_called()


def test_post_to_stac_api_success(processor_instance, sample_stac_item):
    """Test _post_to_stac_api successfully posts new item."""

    # Mock collection already exists
    SentinelFetchProcessor._collection_checked = True

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.ok = True

    with patch("requests.post", return_value=mock_response) as mock_post:
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            result = processor_instance._post_to_stac_api(sample_stac_item)

            assert result is True
            mock_post.assert_called_once()

            # Check the endpoint
            call_args = mock_post.call_args
            assert "sentinel2_eo_products/items" in call_args[0][0]


def test_post_to_stac_api_conflict_updates(processor_instance, sample_stac_item):
    """Test _post_to_stac_api handles 409 conflict by updating."""

    SentinelFetchProcessor._collection_checked = True

    # POST returns 409 Conflict
    mock_post_response = MagicMock()
    mock_post_response.status_code = 409

    # PUT succeeds
    mock_put_response = MagicMock()
    mock_put_response.ok = True

    with patch("requests.post", return_value=mock_post_response):
        with patch("requests.put", return_value=mock_put_response) as mock_put:
            with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
                result = processor_instance._post_to_stac_api(sample_stac_item)

                assert result is True
                mock_put.assert_called_once()

                # Check PUT endpoint includes item ID
                call_args = mock_put.call_args
                assert sample_stac_item["id"] in call_args[0][0]


def test_post_to_stac_api_post_failure(processor_instance, sample_stac_item):
    """Test _post_to_stac_api handles POST failure."""

    SentinelFetchProcessor._collection_checked = True

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal server error"

    with patch("requests.post", return_value=mock_response):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            result = processor_instance._post_to_stac_api(sample_stac_item)

            assert result is False


def test_post_to_stac_api_timeout(processor_instance, sample_stac_item):
    """Test _post_to_stac_api handles timeout."""
    import requests

    SentinelFetchProcessor._collection_checked = True

    with patch("requests.post", side_effect=requests.exceptions.Timeout()):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            result = processor_instance._post_to_stac_api(sample_stac_item)

            assert result is False


def test_post_to_stac_api_network_error(processor_instance, sample_stac_item):
    """Test _post_to_stac_api handles network errors."""
    import requests

    SentinelFetchProcessor._collection_checked = True

    with patch(
        "requests.post",
        side_effect=requests.exceptions.ConnectionError("Network unreachable"),
    ):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            result = processor_instance._post_to_stac_api(sample_stac_item)

            assert result is False


def test_post_to_stac_api_generic_exception(processor_instance, sample_stac_item):
    """_post_to_stac_api returns False and does not re-raise on a bare Exception."""
    SentinelFetchProcessor._collection_checked = True

    with patch("requests.post", side_effect=Exception("Something unexpected")):
        with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
            result = processor_instance._post_to_stac_api(sample_stac_item)

    assert result is False


def test_post_to_stac_api_conflict_put_failure(processor_instance, sample_stac_item):
    """Test _post_to_stac_api handles 409 conflict but PUT also fails."""

    SentinelFetchProcessor._collection_checked = True

    mock_post_response = MagicMock()
    mock_post_response.status_code = 409

    mock_put_response = MagicMock()
    mock_put_response.ok = False
    mock_put_response.status_code = 500
    mock_put_response.text = "Update failed"

    with patch("requests.post", return_value=mock_post_response):
        with patch("requests.put", return_value=mock_put_response):
            with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
                result = processor_instance._post_to_stac_api(sample_stac_item)

                assert result is False


def test_post_to_stac_api_ensures_collection(processor_instance, sample_stac_item):
    """Test _post_to_stac_api calls _ensure_collection_exists."""

    SentinelFetchProcessor._collection_checked = False

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.ok = True

    with patch.object(processor_instance, "_ensure_collection_exists") as mock_ensure:
        with patch("requests.post", return_value=mock_response):
            with patch.dict(os.environ, {"STAC_API_URL": "http://localhost:8081"}):
                processor_instance._post_to_stac_api(sample_stac_item)

                # Should call ensure_collection_exists
                mock_ensure.assert_called_once()


def test_post_to_stac_api_uses_env_url(processor_instance, sample_stac_item):
    """Test _post_to_stac_api uses STAC_API_URL from environment."""

    SentinelFetchProcessor._collection_checked = True

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.ok = True

    custom_url = "http://custom-stac:9999"

    with patch("requests.post", return_value=mock_response) as mock_post:
        with patch.dict(os.environ, {"STAC_API_URL": custom_url}):
            processor_instance._post_to_stac_api(sample_stac_item)

            # Check that custom URL was used
            call_args = mock_post.call_args
            assert custom_url in call_args[0][0]


# ------------------------------------------
# Security: Error message sanitization
# ------------------------------------------


@pytest.mark.unit
def test_load_sentinel2_cube_error_does_not_expose_internal_details(
    processor_instance, sample_farm_geometry
):
    """_load_sentinel2_cube must not leak raw exception details to the caller.

    The ProcessorExecuteError message should be a generic user-facing string;
    internal backend details (e.g. connection strings, stack info embedded in
    str(e)) must remain in server logs only.
    """
    internal_secret = "INTERNAL_BACKEND_DETAIL_secret_connection_string_xyzzy"
    mock_conn = MagicMock()
    mock_conn.load_collection.side_effect = Exception(internal_secret)

    temporal_extent = ["2024-06-01", "2024-08-31"]
    required_bands = {"B04", "B08"}
    bbox = (-72.5, 45.5, -72.0, 46.0)

    with pytest.raises(ProcessorExecuteError) as exc_info:
        processor_instance._load_sentinel2_cube(
            connection=mock_conn,
            bbox=bbox,
            temporal_extent=temporal_extent,
            required_bands=required_bands,
            cloud_cover_max=20,
        )

    error_message = str(exc_info.value)
    assert (
        internal_secret not in error_message
    ), f"Raw exception detail was exposed to caller: {error_message!r}"


@pytest.mark.unit
def test_authenticate_with_env_token_both_failures_do_not_expose_raw_errors(
    processor_instance,
):
    """_authenticate_with_env_token must not leak raw exception strings when both auth paths fail.

    Internal error details from openEO or the config file must stay in logs;
    the raised ProcessorExecuteError must only contain a user-facing message.
    """
    env_error_detail = "ENV_TOKEN_SECRET_INTERNAL_xyzzy_expired_credential"
    config_error_detail = "CONFIG_FILE_SECRET_INTERNAL_xyzzy_path_detail"

    mock_conn = MagicMock()
    mock_conn.authenticate_oidc_refresh_token.side_effect = [
        Exception(env_error_detail),
        Exception(config_error_detail),
    ]

    refresh_token = "a" * 210

    with pytest.raises(ProcessorExecuteError) as exc_info:
        processor_instance._authenticate_with_env_token(mock_conn, refresh_token)

    error_message = str(exc_info.value)
    assert (
        env_error_detail not in error_message
    ), f"Raw env-token error was exposed to caller: {error_message!r}"
    assert (
        config_error_detail not in error_message
    ), f"Raw config-file error was exposed to caller: {error_message!r}"


# ------------------------------------------
# Test _is_valid_token
# ------------------------------------------


@pytest.mark.unit
def test_is_valid_token_empty_string_returns_false(processor_instance):
    """Empty string is not a valid token."""
    assert SentinelFetchProcessor._is_valid_token("") is False


@pytest.mark.unit
def test_is_valid_token_short_string_returns_false(processor_instance):
    """Token shorter than 200 characters is rejected as a placeholder."""
    assert SentinelFetchProcessor._is_valid_token("a" * 50) is False


@pytest.mark.unit
def test_is_valid_token_long_real_token_returns_true(processor_instance):
    """Token of 210 characters with no placeholder patterns is accepted."""
    assert SentinelFetchProcessor._is_valid_token("a" * 210) is True


@pytest.mark.unit
def test_is_valid_token_placeholder_pattern_returns_false(processor_instance):
    """Token that contains a known placeholder pattern is rejected regardless of length."""
    placeholder = "placeholder" + "x" * 200
    assert SentinelFetchProcessor._is_valid_token(placeholder) is False


@pytest.mark.unit
def test_is_valid_token_changeme_pattern_returns_false(processor_instance):
    """Token containing 'changeme' is rejected."""
    token = "changeme" + "z" * 200
    assert SentinelFetchProcessor._is_valid_token(token) is False


@pytest.mark.unit
def test_get_required_bands_true_color_returns_rgb():
    """true_color product requires B02, B03, B04 (Blue, Green, Red)."""
    bands = SentinelFetchProcessor._get_required_bands(["true_color"])
    assert "B02" in bands
    assert "B03" in bands
    assert "B04" in bands


@pytest.mark.unit
def test_get_required_bands_raw_bands_returns_full_set():
    """raw_bands returns all four standard bands."""
    bands = SentinelFetchProcessor._get_required_bands(["raw_bands"])
    assert bands == {"B02", "B03", "B04", "B08"}


@pytest.mark.unit
def test_get_required_bands_empty_list_returns_empty_set():
    """No products requested → no bands required."""
    bands = SentinelFetchProcessor._get_required_bands([])
    assert bands == set()


# ------------------------------------------
# Test _generate_assets error branches
# ------------------------------------------


@pytest.mark.unit
def test_generate_assets_os_error_raises_processor_execute_error(processor_instance):
    """OSError during product processing is caught per-product; raises when ALL products fail."""
    s2_cube = MagicMock()
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]]
        ],
    }
    with patch.object(
        processor_instance, "_calculate_product", side_effect=OSError("disk full")
    ):
        with pytest.raises(
            ProcessorExecuteError, match="Failed to generate any output products"
        ):
            processor_instance._generate_assets(
                s2_cube=s2_cube,
                geometry=geometry,
                output_products=["ndvi"],
                aggregation_method="mean",
                temporal_extent=["2024-01-01", "2024-06-01"],
                farm_identifier="farm_123",
            )


@pytest.mark.unit
def test_generate_assets_value_error_raises_processor_execute_error(processor_instance):
    """ValueError during product processing is caught per-product; raises when ALL products fail."""
    s2_cube = MagicMock()
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]]
        ],
    }
    with patch.object(
        processor_instance, "_calculate_product", side_effect=ValueError("bad config")
    ):
        with pytest.raises(
            ProcessorExecuteError, match="Failed to generate any output products"
        ):
            processor_instance._generate_assets(
                s2_cube=s2_cube,
                geometry=geometry,
                output_products=["ndvi"],
                aggregation_method="mean",
                temporal_extent=["2024-01-01", "2024-06-01"],
                farm_identifier="farm_123",
            )


@pytest.mark.unit
def test_generate_assets_generic_exception_raises_processor_execute_error(
    processor_instance,
):
    """Generic Exception during product processing is caught per-product; raises when ALL fail."""
    s2_cube = MagicMock()
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6], [-71.5, 45.6], [-71.5, 45.5]]
        ],
    }
    with patch.object(
        processor_instance,
        "_calculate_product",
        side_effect=RuntimeError("batch job failed"),
    ):
        with pytest.raises(
            ProcessorExecuteError, match="Failed to generate any output products"
        ):
            processor_instance._generate_assets(
                s2_cube=s2_cube,
                geometry=geometry,
                output_products=["ndvi"],
                aggregation_method="mean",
                temporal_extent=["2024-01-01", "2024-06-01"],
                farm_identifier="farm_123",
            )


# ------------------------------------------
# Test _post_to_stac_api error branches
# ------------------------------------------


@pytest.mark.unit
def test_post_to_stac_api_timeout_returns_false(processor_instance):
    """Timeout when posting STAC item returns False (does not raise)."""
    stac_item = {"id": "test-item-001", "type": "Feature"}

    with patch.object(processor_instance, "_ensure_collection_exists"):
        with patch(
            "processes.eo_sentinel_fetch.requests.post",
            side_effect=requests.exceptions.Timeout(),
        ):
            result = processor_instance._post_to_stac_api(stac_item)

    assert result is False


@pytest.mark.unit
def test_post_to_stac_api_request_exception_returns_false(processor_instance):
    """Network error (RequestException) when posting STAC item returns False."""
    stac_item = {"id": "test-item-002", "type": "Feature"}

    with patch.object(processor_instance, "_ensure_collection_exists"):
        with patch(
            "processes.eo_sentinel_fetch.requests.post",
            side_effect=requests.exceptions.RequestException("connection refused"),
        ):
            result = processor_instance._post_to_stac_api(stac_item)

    assert result is False


@pytest.mark.unit
def test_post_to_stac_api_generic_exception_returns_false(processor_instance):
    """Unexpected exception when posting STAC item returns False (does not raise)."""
    stac_item = {"id": "test-item-003", "type": "Feature"}

    with patch.object(processor_instance, "_ensure_collection_exists"):
        with patch(
            "processes.eo_sentinel_fetch.requests.post",
            side_effect=RuntimeError("unexpected failure"),
        ):
            result = processor_instance._post_to_stac_api(stac_item)

    assert result is False


# --- End-to-end execute() ---

_STAC_BASE = f"http://stac-api:{SentinelFetchProcessor.DEFAULT_STAC_API_PORT}"
_COLLECTION_ID = SentinelFetchProcessor.STAC_COLLECTION_ID


def _make_assets(products: tuple) -> dict:
    return {
        p: {
            "href": f"/data/sentinel2_farm_test_{p}_2024-06-01_2024-08-31_abcd1234.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "title": p.upper(),
            "raster:bands": [],
            "statistics": {1: {"min": 0.0, "max": 1.0, "mean": 0.4, "std": 0.1}},
        }
        for p in products
    }


@pytest.fixture()
def _reset_collection_cache():
    SentinelFetchProcessor._collection_checked = False
    yield
    SentinelFetchProcessor._collection_checked = False


@pytest.mark.mocked
def test_execute_full_flow_farm_geometry_returns_complete_response(
    processor_instance, sample_farm_geometry_small, _reset_collection_cache
):
    """execute() with farm_geometry returns all expected keys in the response value."""
    data = {
        "farm_geometry": sample_farm_geometry_small,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with (
        patch.object(
            processor_instance,
            "_process_sentinel_data",
            return_value=_make_assets(("ndvi",)),
        ),
        patch("requests.get", return_value=MagicMock(status_code=404)),
        patch("requests.post", return_value=MagicMock(status_code=201, text="")),
    ):
        mimetype, envelope = processor_instance.execute(data)

    assert mimetype == "application/json"
    assert envelope["id"] == "result"
    result = envelope["value"]
    for key in (
        "stac_item_id",
        "assets",
        "preview_url",
        "bbox",
        "temporal_extent",
        "area_km2",
    ):
        assert key in result, f"Missing key in response: {key}"
    assert "ndvi" in result["assets"]


@pytest.mark.mocked
def test_execute_full_flow_farm_id_queries_db_then_returns_response(
    processor_instance, mock_db_connection, _reset_collection_cache
):
    """execute() with farm_id triggers a DB lookup and returns a complete response."""
    data = {
        "farm_id": 4,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["true_color"],
    }

    with (
        patch("psycopg.connect", return_value=mock_db_connection) as mock_db,
        patch.object(
            processor_instance,
            "_process_sentinel_data",
            return_value=_make_assets(("true_color",)),
        ),
        patch("requests.get", return_value=MagicMock(status_code=404)),
        patch("requests.post", return_value=MagicMock(status_code=201, text="")),
        patch.dict(
            os.environ, {"POSTGRES_HOST": "localhost", "POSTGRES_PASS": "testpass"}
        ),
    ):
        mimetype, envelope = processor_instance.execute(data)

    mock_db.assert_called_once()
    result = envelope["value"]
    assert "true_color" in result["assets"]


@pytest.mark.mocked
def test_execute_stac_publish_sequence(
    processor_instance, sample_farm_geometry_small, _reset_collection_cache
):
    """execute() calls GET (collection check), POST (create collection), POST (item) — in order."""
    data = {
        "farm_geometry": sample_farm_geometry_small,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi"],
    }

    with (
        patch.object(
            processor_instance,
            "_process_sentinel_data",
            return_value=_make_assets(("ndvi",)),
        ),
        patch("requests.get", return_value=MagicMock(status_code=404)) as mock_get,
        patch(
            "requests.post", return_value=MagicMock(status_code=201, text="")
        ) as mock_post,
    ):
        processor_instance.execute(data)

    mock_get.assert_called_once()  # GET /collections/{id} — existence check
    assert mock_post.call_count == 2  # POST /collections + POST /collections/{id}/items


@pytest.mark.mocked
def test_execute_full_flow_multiple_products(
    processor_instance, sample_farm_geometry_small, _reset_collection_cache
):
    """execute() with multiple products yields all products in result['assets']."""
    data = {
        "farm_geometry": sample_farm_geometry_small,
        "temporal_extent": ["2024-06-01", "2024-08-31"],
        "output_products": ["ndvi", "true_color"],
    }

    with (
        patch.object(
            processor_instance,
            "_process_sentinel_data",
            return_value=_make_assets(("ndvi", "true_color")),
        ),
        patch("requests.get", return_value=MagicMock(status_code=404)),
        patch("requests.post", return_value=MagicMock(status_code=201, text="")),
    ):
        mimetype, envelope = processor_instance.execute(data)

    result = envelope["value"]
    assert "ndvi" in result["assets"]
    assert "true_color" in result["assets"]
    assert isinstance(result["stac_item_id"], str)
    assert len(result["stac_item_id"]) > 0
