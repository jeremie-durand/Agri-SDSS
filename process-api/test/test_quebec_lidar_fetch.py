"""
Unit and mocked tests for the Quebec LiDAR fetch process.
Tests quebec_lidar_fetch.py and lidar_backend/quebec_lidar_tile_index.py.
"""

import json
import math
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from processes.lidar_backend.quebec_lidar_config import PRODUCT_COLUMN, VALID_PRODUCTS
from processes.lidar_backend.quebec_lidar_tile_index import LidarTileIndex
from processes.quebec_lidar_fetch import LidarFetchProcessor
from processes.quebec_lidar_fetch_metadata import PROCESS_METADATA
from pygeoapi.process.base import ProcessorExecuteError


def _write_test_raster(path, values, nodata=None):
    """Write a small single-band GeoTIFF for zonal-statistics tests.

    The raster origin is fixed at (-72.0, 46.0) with 0.01-degree pixels, so
    tests can build simple, hand-computable polygons in EPSG:4326.
    """
    array = np.asarray(values, dtype="float32")
    transform = from_origin(-72.0, 46.0, 0.01, 0.01)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


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
def test_aspect_is_valid_but_not_an_mrnf_column():
    """'aspect' is a valid product but has no MRNF tile column — it must
    never be sent to LidarTileIndex.get_tile_urls, which would KeyError."""
    assert "aspect" in VALID_PRODUCTS
    assert "aspect" not in PRODUCT_COLUMN


@pytest.mark.unit
def test_process_inputs_defined():
    """All expected inputs are present with correct schema."""
    inputs = PROCESS_METADATA["inputs"]
    assert "farm_geometry" in inputs
    assert "farm_id" in inputs
    assert "products" in inputs

    product_enum = inputs["products"]["schema"]["items"]["enum"]
    assert set(product_enum) == {"dtm", "chm", "hillshade", "slope", "aspect"}


@pytest.mark.unit
def test_process_outputs_document_statistics_and_summary():
    """Outputs schema documents per-asset statistics and the slope/aspect
    top-level summary fields, so external callers don't have to read the
    processor source to know they exist."""
    properties = PROCESS_METADATA["outputs"]["result"]["schema"]["properties"]
    assert "slope" in properties
    assert "aspect" in properties
    assert "statistics" in PROCESS_METADATA["outputs"]["result"]["description"]


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
# Zonal statistics tests (exact-polygon masking, slope, aspect)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_masked_zonal_values_excludes_pixels_outside_polygon(
    processor_instance, tmp_path
):
    """Only pixels whose center falls inside the polygon are returned, even
    though the raster covers a larger rectangular extent."""
    raster_path = tmp_path / "values.tif"
    _write_test_raster(
        raster_path,
        [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]],
    )
    # Left half only (cols 0-1) of the 4x4 raster, which spans
    # x=[-72.00,-71.96], y=[45.96,46.00].
    left_half = {
        "type": "Polygon",
        "coordinates": [
            [
                [-72.00, 45.96],
                [-71.98, 45.96],
                [-71.98, 46.00],
                [-72.00, 46.00],
                [-72.00, 45.96],
            ]
        ],
    }

    values = processor_instance._masked_zonal_values(str(raster_path), left_half)

    assert sorted(values.tolist()) == [1.0, 2.0, 5.0, 6.0, 9.0, 10.0, 13.0, 14.0]


@pytest.mark.unit
def test_slope_statistics_uses_per_pixel_percent_conversion(
    processor_instance, tmp_path
):
    """mean_percent must be the average of per-pixel tan(radians(deg))*100,
    not tan(radians(mean_degrees))*100 — the two differ for non-uniform
    input, and only the per-pixel version is numerically correct."""
    raster_path = tmp_path / "slope.tif"
    degrees = [[10.0, 20.0], [30.0, 40.0]]
    _write_test_raster(raster_path, degrees)
    full_coverage = {
        "type": "Polygon",
        "coordinates": [
            [
                [-72.00, 45.98],
                [-71.98, 45.98],
                [-71.98, 46.00],
                [-72.00, 46.00],
                [-72.00, 45.98],
            ]
        ],
    }

    stats = processor_instance._slope_statistics(str(raster_path), full_coverage)

    flat_degrees = np.array([10.0, 20.0, 30.0, 40.0])
    expected_mean_degrees = float(flat_degrees.mean())
    expected_mean_percent = float(
        (np.tan(np.radians(flat_degrees)) * 100.0).mean()
    )
    wrong_way_percent = math.tan(math.radians(expected_mean_degrees)) * 100.0

    assert stats["mean_degrees"] == pytest.approx(expected_mean_degrees)
    assert stats["mean_percent"] == pytest.approx(expected_mean_percent, abs=1e-3)
    assert stats["mean_percent"] != pytest.approx(wrong_way_percent, abs=0.5)


@pytest.mark.unit
def test_slope_statistics_empty_polygon_returns_none(processor_instance, tmp_path):
    """A polygon that covers no pixels returns None rather than NaN/crashing."""
    raster_path = tmp_path / "slope_empty.tif"
    _write_test_raster(raster_path, [[10.0, 20.0], [30.0, 40.0]])
    outside_polygon = {
        "type": "Polygon",
        "coordinates": [
            [[-60.0, 50.0], [-59.99, 50.0], [-59.99, 50.01], [-60.0, 50.01], [-60.0, 50.0]]
        ],
    }

    stats = processor_instance._slope_statistics(str(raster_path), outside_polygon)

    assert stats == {"mean_degrees": None, "mean_percent": None}


@pytest.mark.unit
def test_masked_zonal_values_excludes_nodata_pixels_inside_polygon(
    processor_instance, tmp_path
):
    """Pixels that are inside the polygon but flagged as nodata must be
    excluded from the result — polygon coverage alone isn't sufficient."""
    raster_path = tmp_path / "values_with_nodata.tif"
    _write_test_raster(
        raster_path,
        [[1, 2], [-9999, 4]],
        nodata=-9999,
    )
    full_coverage = {
        "type": "Polygon",
        "coordinates": [
            [
                [-72.00, 45.98],
                [-71.98, 45.98],
                [-71.98, 46.00],
                [-72.00, 46.00],
                [-72.00, 45.98],
            ]
        ],
    }

    values = processor_instance._masked_zonal_values(str(raster_path), full_coverage)

    assert sorted(values.tolist()) == [1.0, 2.0, 4.0]


@pytest.mark.unit
def test_aspect_statistics_circular_mean_handles_wraparound(
    processor_instance, tmp_path
):
    """350 deg and 10 deg must average to ~0 deg (near-north), not ~180 deg
    — a naive arithmetic mean gets this exactly backwards."""
    raster_path = tmp_path / "aspect_wrap.tif"
    _write_test_raster(raster_path, [[350.0, 10.0]])
    full_coverage = {
        "type": "Polygon",
        "coordinates": [
            [
                [-72.00, 45.99],
                [-71.98, 45.99],
                [-71.98, 46.00],
                [-72.00, 46.00],
                [-72.00, 45.99],
            ]
        ],
    }

    stats = processor_instance._aspect_statistics(str(raster_path), full_coverage)

    assert stats["mean_degrees"] == pytest.approx(0.0, abs=1e-4) or stats[
        "mean_degrees"
    ] == pytest.approx(360.0, abs=1e-4)


@pytest.mark.unit
def test_aspect_statistics_excludes_nodata_flat_cells(processor_instance, tmp_path):
    """gdaldem aspect marks flat/edge cells as nodata (-9999) — those must
    not pollute the circular mean."""
    raster_path = tmp_path / "aspect_nodata.tif"
    _write_test_raster(
        raster_path, [[45.0, -9999.0], [90.0, -9999.0]], nodata=-9999.0
    )
    full_coverage = {
        "type": "Polygon",
        "coordinates": [
            [
                [-72.00, 45.98],
                [-71.98, 45.98],
                [-71.98, 46.00],
                [-72.00, 46.00],
                [-72.00, 45.98],
            ]
        ],
    }

    stats = processor_instance._aspect_statistics(str(raster_path), full_coverage)

    assert stats["mean_degrees"] == pytest.approx(67.5, abs=0.01)


@pytest.mark.unit
def test_aspect_statistics_empty_polygon_returns_none(processor_instance, tmp_path):
    """A polygon that covers no pixels returns None rather than crashing."""
    raster_path = tmp_path / "aspect_empty.tif"
    _write_test_raster(raster_path, [[45.0, 90.0]])
    outside_polygon = {
        "type": "Polygon",
        "coordinates": [
            [[-60.0, 50.0], [-59.99, 50.0], [-59.99, 50.01], [-60.0, 50.01], [-60.0, 50.0]]
        ],
    }

    stats = processor_instance._aspect_statistics(str(raster_path), outside_polygon)

    assert stats == {"mean_degrees": None}


@pytest.mark.unit
def test_compute_aspect_cog_invokes_gdaldem(processor_instance, tmp_path):
    """_compute_aspect_cog shells out to gdaldem aspect with the DTM COG
    as input, mirroring how _clip_and_convert_to_cog shells out to
    gdalwarp."""
    dtm_path = str(tmp_path / "dtm.tif")
    aspect_path = str(tmp_path / "aspect.tif")

    with patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        processor_instance._compute_aspect_cog(dtm_path, aspect_path)

    args = mock_run.call_args.args[0]
    assert args[0] == "gdaldem"
    assert args[1] == "aspect"
    assert dtm_path in args
    assert aspect_path in args


@pytest.mark.unit
def test_compute_aspect_cog_raises_on_gdal_failure(processor_instance, tmp_path):
    """A non-zero gdaldem exit code raises ProcessorExecuteError with the
    stderr output, matching the gdalwarp failure pattern."""
    with patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stderr="gdaldem: some error"
        )
        with pytest.raises(ProcessorExecuteError, match="gdaldem aspect"):
            processor_instance._compute_aspect_cog(
                str(tmp_path / "dtm.tif"), str(tmp_path / "aspect.tif")
            )


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
            {"farm_geometry": sample_farm_geometry, "products": ["dsm"]}
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


@pytest.mark.unit
def test_execute_no_dtm_tiles_for_aspect_raises(
    processor_instance, sample_farm_geometry
):
    """Aspect is requested but no DTM tiles are found (even though other
    requested products do have tiles) — raises a clear, specific error."""
    tile_urls = {"slope": ["https://example.com/Pentes_31H05NE.tif"]}
    with patch(
        "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
        return_value=tile_urls,
    ):
        with pytest.raises(ProcessorExecuteError, match="DTM"):
            processor_instance.execute(
                {
                    "farm_geometry": sample_farm_geometry,
                    "products": ["slope", "aspect"],
                }
            )


@pytest.mark.mocked
def test_execute_default_products_excludes_aspect(
    processor_instance, sample_farm_geometry, tmp_path
):
    """Omitting 'products' must not silently include aspect — it's
    opt-in only, matching the documented schema default. Verified by
    running execute() to completion (not just checking fetch_products),
    since aspect's absence from fetch_products doesn't by itself prove
    it wasn't computed via some other path."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {
        "dtm": ["https://example.com/MNT_31H05NE.tif"],
        "chm": ["https://example.com/MHC_31H05NE.tif"],
        "hillshade": ["https://example.com/MNT_Ombre_31H05NE.tif"],
        "slope": ["https://example.com/Pentes_31H05NE.tif"],
    }

    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 1.5

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
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
        patch.object(
            processor_instance, "_compute_aspect_cog"
        ) as mock_compute_aspect,
        patch.object(
            processor_instance,
            "_slope_statistics",
            return_value={"mean_degrees": 1.5, "mean_percent": 2.6},
        ),
        patch.object(processor_instance, "_post_to_stac_api", return_value=True),
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        mimetype, result = processor_instance.execute(
            {"farm_geometry": sample_farm_geometry}
        )

    mock_compute_aspect.assert_not_called()
    assert "aspect" not in result["assets"]
    assert "aspect" not in result["products"]
    assert set(result["products"]) == {"dtm", "chm", "hillshade", "slope"}


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

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.bounds = MagicMock(left=-71.5, bottom=45.5, right=-71.4, top=45.6)
    mock_rasterio_ds.dtypes = ("float32",)

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
        patch.object(
            processor_instance,
            "_slope_statistics",
            return_value={"mean_degrees": 1.5, "mean_percent": 2.6},
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
    assert result["slope"] == {"mean_degrees": 1.5, "mean_percent": 2.6}


@pytest.mark.mocked
def test_execute_aspect_only_fetches_dtm_as_dependency(
    processor_instance, sample_farm_geometry, tmp_path
):
    """Requesting only 'aspect' fetches DTM internally (aspect is derived
    from it) but DTM is excluded from the output since the caller didn't
    ask for it."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.dtypes = ("float32",)

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ) as mock_get_tile_urls,
        patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run,
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(processor_instance, "_compute_aspect_cog"),
        patch.object(
            processor_instance,
            "_aspect_statistics",
            return_value={"mean_degrees": 187.5},
        ),
        patch.object(processor_instance, "_post_to_stac_api", return_value=True),
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        mimetype, result = processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["aspect"]}
        )

    # DTM was fetched as a dependency for aspect derivation...
    assert mock_get_tile_urls.call_args.args[1] == ["dtm"]
    # ...but excluded from the output, since the caller didn't request it.
    assert "dtm" not in result["assets"]
    assert result["products"] == ["aspect"]
    assert "aspect" in result["assets"]
    assert result["aspect"] == {"mean_degrees": 187.5}
    assert len(result["stac_items"]) == 1


@pytest.mark.mocked
def test_execute_dtm_and_aspect_both_explicitly_requested(
    processor_instance, sample_farm_geometry, tmp_path
):
    """When dtm is explicitly requested alongside aspect (not just fetched
    as aspect's dependency), it must still appear in the output — the
    'dependency-only, skip the asset' logic must not swallow an explicit
    request just because dtm also happens to be aspect's source product."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.dtypes = ("float32",)
    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 312.4
    mock_rasterio_ds.read.return_value = mock_band

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ) as mock_get_tile_urls,
        patch("processes.quebec_lidar_fetch.subprocess.run") as mock_run,
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(processor_instance, "_compute_aspect_cog"),
        patch.object(
            processor_instance,
            "_aspect_statistics",
            return_value={"mean_degrees": 187.5},
        ),
        patch.object(processor_instance, "_post_to_stac_api", return_value=True),
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        mimetype, result = processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm", "aspect"]}
        )

    # dtm fetched once, no duplication in fetch_products
    assert mock_get_tile_urls.call_args.args[1] == ["dtm"]
    # both explicitly-requested products appear in the output
    assert "dtm" in result["assets"]
    assert "aspect" in result["assets"]
    assert set(result["products"]) == {"dtm", "aspect"}
    assert len(result["stac_items"]) == 2


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


# ---------------------------------------------------------------------------
# STAC publish caching tests (marker written after a successful publish;
# skips republishing on a warm COG cache; retries after a failed publish;
# invalidated when the COG is rebuilt)
# ---------------------------------------------------------------------------


def _fake_gdalwarp(cmd, capture_output, text):
    """subprocess.run stand-in that actually writes the output COG file, so
    the on-disk cache check in _get_or_build_cog behaves realistically
    across repeated execute() calls."""
    output_path = cmd[-1]
    with open(output_path, "wb") as f:
        f.write(b"fake")
    return MagicMock(returncode=0, stderr="")


@pytest.mark.mocked
def test_execute_second_call_skips_stac_publish_on_warm_cache(
    processor_instance, sample_farm_geometry, tmp_path
):
    """A second call against an already-cached COG must not re-publish the
    STAC item — this is the warm-cache latency the hotfix targets."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 1.5

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.dtypes = ("float32",)
    mock_rasterio_ds.read.return_value = mock_band

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ),
        patch(
            "processes.quebec_lidar_fetch.subprocess.run", side_effect=_fake_gdalwarp
        ),
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(
            processor_instance, "_post_to_stac_api", return_value=True
        ) as mock_post,
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
        )
        assert mock_post.call_count == 1

        mimetype, result = processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
        )

    assert mock_post.call_count == 1  # not called again on the warm-cache run
    assert "dtm" in result["assets"]
    assert len(result["stac_items"]) == 1


@pytest.mark.mocked
def test_execute_retries_stac_publish_after_previous_failure(
    processor_instance, sample_farm_geometry, tmp_path
):
    """If _post_to_stac_api fails, no marker is written, so a later call —
    even with a warm COG cache — retries the publish instead of the item
    staying unpublished forever."""
    processor_instance.output_dir = str(tmp_path)

    tile_urls = {"dtm": ["https://example.com/MNT_31H05NE.tif"]}

    mock_band = MagicMock()
    mock_band.count.return_value = 100
    mock_band.mean.return_value = 1.5

    mock_rasterio_ds = MagicMock()
    mock_rasterio_ds.__enter__ = MagicMock(return_value=mock_rasterio_ds)
    mock_rasterio_ds.__exit__ = MagicMock(return_value=False)
    mock_rasterio_ds.dtypes = ("float32",)
    mock_rasterio_ds.read.return_value = mock_band

    with (
        patch(
            "processes.quebec_lidar_fetch.LidarTileIndex.get_tile_urls",
            return_value=tile_urls,
        ),
        patch(
            "processes.quebec_lidar_fetch.subprocess.run", side_effect=_fake_gdalwarp
        ),
        patch(
            "processes.quebec_lidar_fetch.rasterio.open", return_value=mock_rasterio_ds
        ),
        patch.object(
            processor_instance, "_post_to_stac_api", return_value=False
        ) as mock_post,
        patch.object(processor_instance, "_ensure_collection_exists"),
    ):
        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
        )
        assert mock_post.call_count == 1

        processor_instance.execute(
            {"farm_geometry": sample_farm_geometry, "products": ["dtm"]}
        )

    assert mock_post.call_count == 2  # retried since no marker was written


@pytest.mark.unit
def test_get_or_build_cog_invalidates_stale_marker_on_rebuild(
    processor_instance, tmp_path
):
    """Rebuilding a COG (cache miss) must delete any leftover STAC marker
    from a previous version of the raster, so a stale item isn't served."""
    cog_path = str(tmp_path / "lidar_dtm_test.tif")
    marker_path = cog_path + ".stac.json"

    with open(marker_path, "w") as f:
        json.dump({"id": "stale"}, f)

    build_called = []

    def fake_build():
        build_called.append(True)
        with open(cog_path, "wb") as f:
            f.write(b"fake")

    processor_instance._get_or_build_cog(cog_path, "dtm", fake_build)

    assert build_called == [True]
    assert not os.path.exists(marker_path)


@pytest.mark.unit
def test_get_or_build_cog_keeps_marker_on_cache_hit(processor_instance, tmp_path):
    """A COG cache hit (no rebuild) must leave an existing marker intact."""
    cog_path = str(tmp_path / "lidar_dtm_test.tif")
    marker_path = cog_path + ".stac.json"
    with open(cog_path, "wb") as f:
        f.write(b"fake")
    with open(marker_path, "w") as f:
        json.dump({"id": "cached"}, f)

    build_called = []
    processor_instance._get_or_build_cog(
        cog_path, "dtm", lambda: build_called.append(True)
    )

    assert build_called == []
    assert os.path.exists(marker_path)


@pytest.mark.unit
def test_write_and_load_stac_marker_round_trip(processor_instance, tmp_path):
    """A written marker can be read back as the same STAC item dict."""
    marker_path = str(tmp_path / "lidar_dtm_test.tif.stac.json")
    stac_item = {"id": "lidar_dtm_test", "type": "Feature"}

    processor_instance._write_stac_marker(marker_path, stac_item)
    loaded = processor_instance._load_cached_stac_item(marker_path)

    assert loaded == stac_item


@pytest.mark.unit
def test_load_cached_stac_item_missing_returns_none(processor_instance, tmp_path):
    """No marker file means no cached item — must not raise."""
    marker_path = str(tmp_path / "does_not_exist.stac.json")
    assert processor_instance._load_cached_stac_item(marker_path) is None


@pytest.mark.unit
def test_create_stac_item_writes_marker_only_on_publish_success(
    processor_instance, tmp_path
):
    """A successful publish leaves a marker behind for future cache hits."""
    marker_path = str(tmp_path / "lidar_dtm_test.tif.stac.json")

    with patch.object(processor_instance, "_post_to_stac_api", return_value=True):
        processor_instance._create_stac_item(
            item_id="lidar_dtm_test",
            geometry={"type": "Point", "coordinates": [0, 0]},
            bbox=(0, 0, 1, 1),
            product="dtm",
            asset={"href": "x"},
            marker_path=marker_path,
        )

    assert os.path.exists(marker_path)


@pytest.mark.unit
def test_create_stac_item_no_marker_on_publish_failure(processor_instance, tmp_path):
    """A failed publish must not leave a marker — otherwise the item would
    never get (re)published."""
    marker_path = str(tmp_path / "lidar_dtm_test.tif.stac.json")

    with patch.object(processor_instance, "_post_to_stac_api", return_value=False):
        processor_instance._create_stac_item(
            item_id="lidar_dtm_test",
            geometry={"type": "Point", "coordinates": [0, 0]},
            bbox=(0, 0, 1, 1),
            product="dtm",
            asset={"href": "x"},
            marker_path=marker_path,
        )

    assert not os.path.exists(marker_path)


# ---------------------------------------------------------------------------
# Product metadata helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_product_title_and_description_defined_for_aspect():
    """aspect has the same title/description coverage as the other products."""
    assert LidarFetchProcessor._get_product_title("aspect") != "ASPECT"
    assert "DTM" in LidarFetchProcessor._get_product_description("aspect")
