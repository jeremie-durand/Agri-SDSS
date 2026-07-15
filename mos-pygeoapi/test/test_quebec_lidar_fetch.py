"""
Unit and mocked tests for the Quebec LiDAR fetch process.
Tests quebec_lidar_fetch.py and lidar_backend/quebec_lidar_tile_index.py.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from processes.lidar_backend.quebec_lidar_tile_index import LidarTileIndex
from processes.quebec_lidar_fetch import LidarFetchProcessor
from processes.quebec_lidar_fetch_metadata import PROCESS_METADATA
from pygeoapi.process.base import ProcessorExecuteError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_farm_geometry():
    """Small farm polygon entirely inside Quebec LiDAR coverage."""
    return {
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


@pytest.fixture
def sample_farm_geometry_large():
    """Polygon exceeding the 200 km² area limit (~1° × 1° ≈ 7 700 km²)."""
    return {
        "type": "Polygon",
        "coordinates": [
            [[-71.0, 45.0], [-70.0, 45.0], [-70.0, 46.0], [-71.0, 46.0], [-71.0, 45.0]]
        ],
    }


@pytest.fixture
def processor_instance():
    """LidarFetchProcessor instance."""
    LidarFetchProcessor._collection_checked = False
    return LidarFetchProcessor({"name": "lidar-fetch"})


@pytest.fixture
def mock_tile_index_geojson():
    """Minimal GeoJSON tile index with two features covering the sample bbox."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-71.6, 45.4],
                            [-71.3, 45.4],
                            [-71.3, 45.7],
                            [-71.6, 45.7],
                            [-71.6, 45.4],
                        ]
                    ],
                },
                "properties": {
                    "NUM": 1,
                    "Feuillet20K": "31H05NE",
                    "MNT": "https://example.com/MNT_31H05NE.tif",
                    "MHC": "https://example.com/MHC_31H05NE.tif",
                    "MNT_Ombre": "https://example.com/MNT_Ombre_31H05NE.tif",
                    "Pentes": "https://example.com/Pentes_31H05NE.tif",
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-72.0, 46.0],
                            [-71.0, 46.0],
                            [-71.0, 47.0],
                            [-72.0, 47.0],
                            [-72.0, 46.0],
                        ]
                    ],
                },
                "properties": {
                    "NUM": 2,
                    "Feuillet20K": "31H06NO",
                    "MNT": "https://example.com/MNT_31H06NO.tif",
                    "MHC": "https://example.com/MHC_31H06NO.tif",
                    "MNT_Ombre": "https://example.com/MNT_Ombre_31H06NO.tif",
                    "Pentes": "https://example.com/Pentes_31H06NO.tif",
                },
            },
        ],
    }


@pytest.fixture
def mock_db_connection():
    """Mock psycopg connection returning a valid geometry JSON string."""
    json_string = json.dumps(
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
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json_string,)
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


# ---------------------------------------------------------------------------
# Process metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_process_metadata_structure():
    """PROCESS_METADATA must have the required OGC Process fields."""
    assert PROCESS_METADATA["id"] == "lidar-fetch"
    assert "version" in PROCESS_METADATA
    assert "inputs" in PROCESS_METADATA
    assert "outputs" in PROCESS_METADATA
    assert "sync-execute" in PROCESS_METADATA["jobControlOptions"]


@pytest.mark.unit
def test_process_inputs_defined():
    """All expected inputs are present with correct schema."""
    inputs = PROCESS_METADATA["inputs"]
    assert "farm_geometry" in inputs
    assert "farm_id" in inputs
    assert "products" in inputs

    product_enum = inputs["products"]["schema"]["items"]["enum"]
    assert set(product_enum) == {"dtm", "chm", "hillshade", "slope"}


@pytest.mark.unit
def test_process_outputs_defined():
    """Result output schema is present."""
    assert "result" in PROCESS_METADATA["outputs"]
    assert PROCESS_METADATA["outputs"]["result"]["schema"]["type"] == "object"


# ---------------------------------------------------------------------------
# LidarTileIndex unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tile_index_returns_matching_urls(mock_tile_index_geojson):
    """get_tile_urls returns URLs for tiles that intersect the bbox."""
    index = LidarTileIndex()
    index._features = mock_tile_index_geojson["features"]

    # bbox overlaps only the first feature
    bbox = (-71.55, 45.45, -71.35, 45.65)
    result = index.get_tile_urls(bbox, ["dtm", "slope"])

    assert "dtm" in result
    assert "slope" in result
    assert result["dtm"] == ["https://example.com/MNT_31H05NE.tif"]
    assert result["slope"] == ["https://example.com/Pentes_31H05NE.tif"]


@pytest.mark.unit
def test_tile_index_no_match_returns_empty(mock_tile_index_geojson):
    """get_tile_urls returns an empty dict when no tile intersects the bbox."""
    index = LidarTileIndex()
    index._features = mock_tile_index_geojson["features"]

    # bbox far outside both features
    bbox = (-60.0, 50.0, -59.0, 51.0)
    result = index.get_tile_urls(bbox, ["dtm"])

    assert result == {}


@pytest.mark.unit
def test_tile_index_unknown_product_raises():
    """get_tile_urls raises ValueError for unknown product names."""
    index = LidarTileIndex()
    index._features = []

    with pytest.raises(ValueError, match="Unknown LiDAR product"):
        index.get_tile_urls((-71.5, 45.5, -71.4, 45.6), ["dsm"])


@pytest.mark.unit
def test_tile_index_multiple_tiles(mock_tile_index_geojson):
    """get_tile_urls collects URLs from multiple intersecting tiles."""
    index = LidarTileIndex()
    index._features = mock_tile_index_geojson["features"]

    # Wide bbox covering both features
    bbox = (-72.1, 45.3, -70.9, 47.1)
    result = index.get_tile_urls(bbox, ["dtm"])

    assert len(result["dtm"]) == 2


# ---------------------------------------------------------------------------
# LidarFetchProcessor input validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_execute_requires_geometry_or_id(processor_instance):
    """Both geometry and farm_id missing raises ProcessorExecuteError."""
    with pytest.raises(ProcessorExecuteError, match="farm_geometry.*farm_id"):
        processor_instance.execute({})


@pytest.mark.unit
def test_execute_rejects_both_geometry_and_id(processor_instance, sample_farm_geometry):
    """Providing both farm_geometry and farm_id raises ProcessorExecuteError."""
    with pytest.raises(ProcessorExecuteError, match="only one"):
        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "farm_id": 1}
        )


@pytest.mark.unit
def test_execute_rejects_non_positive_farm_id(processor_instance):
    """A non-positive farm_id raises ProcessorExecuteError."""
    with pytest.raises(ProcessorExecuteError, match="positive integer"):
        processor_instance.execute({"farm_id": 0})


@pytest.mark.unit
def test_execute_rejects_unknown_products(processor_instance, sample_farm_geometry):
    """Unknown product names raise ProcessorExecuteError."""
    with pytest.raises(ProcessorExecuteError, match="Unknown product"):
        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dsm", "aspect"]}
        )


@pytest.mark.unit
def test_execute_area_limit_exceeded(processor_instance, sample_farm_geometry_large):
    """Farm area exceeding MAX_FARM_AREA_KM2 raises ProcessorExecuteError."""
    with pytest.raises(ProcessorExecuteError, match="exceeds maximum"):
        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry_large, "products": ["dtm"]}
        )


@pytest.mark.unit
def test_execute_no_tiles_found(processor_instance, sample_farm_geometry):
    """Empty tile index result raises ProcessorExecuteError."""
    with patch(
        "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls", return_value={}
    ):
        with pytest.raises(ProcessorExecuteError, match="No LiDAR tiles found"):
            processor_instance.execute(
                {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
            )


# ---------------------------------------------------------------------------
# LidarFetchProcessor mocked end-to-end test
# ---------------------------------------------------------------------------


@pytest.mark.mocked
def test_execute_success_with_geometry(
    processor_instance, sample_farm_geometry, tmp_path
):
    """Full execute() flow with all external calls mocked."""
    processor_instance.output_dir = str(tmp_path)

    fake_cog = tmp_path / "lidar_dtm_geom_abc123.tif"
    fake_cog.write_bytes(b"fake")  # rasterio.open is mocked below

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 1.5

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.bounds = MagicMock(left=-71.5, bottom=45.5, right=-71.4, top=45.6)
    mock_rasterio_ds.dtypes = ("float32",)
    mock_rasterio_ds.read.return_value = mock_band

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ),
        patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run,
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(processor_instance, "_post_to_stac_api", return_value=True),
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        mimetype, result = processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
        )

    assert mimetype == "application/json"
    assert "dtm" in result["products"]
    assert len(result["stac_items"]) == 1
    assert "dtm" in result["assets"]
    assert result["bbox"] == list((-71.5, 45.5, -71.4, 45.6))


@pytest.mark.mocked
def test_execute_success_with_farm_id(processor_instance, mock_db_connection, tmp_path):
    """execute() resolves geometry from PostGIS when farm_id is supplied."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"slope": ["https://example.com/Pentes_31H05NE.tif"]}

    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 1.5

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.bounds = MagicMock(left=-71.5, bottom=45.5, right=-71.4, top=45.6)
    mock_rasterio_ds.dtypes = ("float32",)
    mock_rasterio_ds.read.return_value = mock_band

    with (
        patch(
            "processes.quebec_lidar_fetch.psycopg.connect",
            return_value=mock_db_connection,
        ),
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ),
        patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run,
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(processor_instance, "_post_to_stac_api", return_value=True),
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        mimetype, result = processor_instance.execute(
            {"farm_id": 4, "products": ["slope"]}
        )

    assert mimetype == "application/json"
    assert "slope" in result["products"]
    assert len(result["stac_items"]) == 1


@pytest.mark.mocked
def test_execute_gdal_failure_raises(
    processor_instance, sample_farm_geometry, tmp_path
):
    """ProcessorExecuteError is raised when gdalwarp returns non-zero exit code."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ),
        patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run,
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=1, stderr="gdalwarp: some error")

        with pytest.raises(ProcessorExecuteError, match="gdalwarp"):
            processor_instance.execute(
                {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
            )
