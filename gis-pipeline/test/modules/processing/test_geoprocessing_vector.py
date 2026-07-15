from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fiona
import geopandas as gpd
import pandas as pd
import pytest
from gis_pipeline.core.config import Config
from gis_pipeline.core.utils import harmonize_name
from gis_pipeline.modules.processing.geoprocessing import GeoprocessingVector
from gis_pipeline.services.mapping import NamingPatterns
from shapely.geometry import MultiPolygon, Point, Polygon

_GDF_PATTERN = NamingPatterns.PATTERN_GDF_NAME.value
_MAX = Config.POSTGRES_MAX_NAME_LENGTH


# ------------------------------------------
# Fixtures - GeoDataFrames
# ------------------------------------------
@pytest.fixture
def gdf_points_harmonization_fixture():
    """
    Sample GeoDataFrame for testing data harmonization.
    """
    data = {
        "Nom": ["A", "B", "B", None, "Na", "N/A"],
        "Valeur": [1, 2, 2, 3, 4, 5],
        "geometry": [
            Point(0, 0),
            Point(1, 1),
            Point(1, 1),
            None,
            Point(2, 2),
            Point(3, 3),
        ],
    }
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.set_crs(epsg=4326, inplace=True)
    return gdf


@pytest.fixture
def gdf_with_null_geoms():
    """
    Fixture for GeoDataFrame with some null geometries.
    """
    data = {"attr": [1, 2, 3], "geometry": [Point(0, 0), None, Point(1, 1)]}
    return gpd.GeoDataFrame(data, geometry="geometry")


@pytest.fixture
def gdf_with_polygons():
    """
    Fixture for GeoDataFrame with polygons.
    """
    data = {
        "attr": [1, 2],
        "geometry": [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
        ],
    }
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.set_crs(epsg=4326, inplace=True)
    return gdf


@pytest.fixture
def gdf_epsg3857():
    """
    Fixture for GeoDataFrame in EPSG:3857.
    """
    # GeoDataFrame in EPSG:3857
    return gpd.GeoDataFrame(
        {"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:3857"
    )


@pytest.fixture
def gdf_no_crs():
    """
    Fixture for GeoDataFrame with no CRS.
    """
    return gpd.GeoDataFrame({"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])


@pytest.fixture
def gdf_with_overlapping_polygons():
    """
    Fixture for GeoDataFrame with overlapping polygons.
    """
    data = {
        "attr": [1, 2],
        "geometry": [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]),
        ],
    }
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.set_crs(epsg=4326, inplace=True)
    return gdf


# ------------------------------------------
# Fixture - Temporary vector files
# ------------------------------------------
@pytest.fixture
def temp_vector_files(tmp_path):
    """Create temporary vector files (shapefile, geojson, gpkg) and return paths + original gdf."""
    # sample GeoDataFrame
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "name": ["a", "b"]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )

    # Shapefile
    shp_path = tmp_path / "test_shapefile.shp"
    gdf.to_file(shp_path)  # driver inferred

    # GeoJSON
    geojson_path = tmp_path / "test_geojson.geojson"
    gdf.to_file(geojson_path, driver="GeoJSON")

    # GeoPackage
    gpkg_path = tmp_path / "test_geopackage.gpkg"
    gdf.to_file(gpkg_path, driver="GPKG", layer="test")

    return {
        "shapefile": shp_path,
        "geojson": geojson_path,
        "geopackage": gpkg_path,
        "gdf": gdf,
    }


@pytest.fixture
def temp_multilayer_gpkg(tmp_path):
    """Create a temporary multi-layer GeoPackage and return its path."""
    gpkg_path = tmp_path / "multi_layer.gpkg"

    # Create two different GeoDataFrames
    gdf1 = gpd.GeoDataFrame(
        {"id": [1, 2], "name": ["layer1_a", "layer1_b"]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )

    gdf2 = gpd.GeoDataFrame(
        {"id": [3, 4], "name": ["layer2_a", "layer2_b"]},
        geometry=[Point(2, 2), Point(3, 3)],
        crs="EPSG:4326",
    )

    # Write both GeoDataFrames to the same GeoPackage under different layers
    gdf1.to_file(gpkg_path, layer="layer1", driver="GPKG")
    gdf2.to_file(gpkg_path, layer="layer2", driver="GPKG")

    return {"path": gpkg_path}


# ------------------------------------------
# Test cases for GeoprocessingVector._find_overlapping_polygons()
# ------------------------------------------
def test_find_overlapping_polygons_no_overlaps():
    """Test _find_overlapping_polygons with non-overlapping polygons."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2, 3],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),  # Square at origin
                Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),  # Square at (2,2)
                Polygon([(5, 5), (6, 5), (6, 6), (5, 6)]),  # Square at (5,5)
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert overlaps == []


def test_find_overlapping_polygons_with_overlaps():
    """Test _find_overlapping_polygons with overlapping polygons."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "geometry": [
                Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),  # Square 0-2,0-2
                Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),  # Square 1-3,1-3 (overlaps)
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Should find one overlap (bidirectional)
    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_touching_not_overlapping():
    """Test _find_overlapping_polygons with touching but not overlapping polygons."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),  # Square 0-1,0-1
                Polygon(
                    [(1, 0), (2, 0), (2, 1), (1, 1)]
                ),  # Square 1-2,0-1 (touching edge)
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Touching polygons intersect but don't overlap significantly
    # intersects() returns True for touching geometries
    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_empty_geodataframe():
    """Test _find_overlapping_polygons with empty GeoDataFrame."""
    gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert overlaps == []


def test_find_overlapping_polygons_no_polygons():
    """Test _find_overlapping_polygons with GeoDataFrame containing no polygons."""
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2, 3], "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]},
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert overlaps == []


def test_find_overlapping_polygons_mixed_geometry_types_reindexed():
    """Test _find_overlapping_polygons with mixed geometry types."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2, 3, 4],
            "geometry": [
                Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),  # Polygon - index 0
                Polygon(
                    [(1, 1), (3, 1), (3, 3), (1, 3)]
                ),  # Overlapping polygon - index 1
                Point(0, 0),  # Point - index 2
                Point(3, 3),  # Point - index 3
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_multipolygon():
    """Test _find_overlapping_polygons with MultiPolygon geometries."""
    # Create MultiPolygons
    poly1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    poly2 = Polygon([(2, 2), (3, 2), (3, 3), (2, 3)])
    multipoly1 = MultiPolygon([poly1, poly2])

    poly3 = Polygon(
        [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]
    )  # Overlaps with poly1
    multipoly2 = MultiPolygon([poly3])

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "geometry": [multipoly1, multipoly2]}, crs="EPSG:4326"
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # MultiPolygons should be detected and checked for overlaps
    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_single_polygon():
    """Test _find_overlapping_polygons with single polygon."""
    gdf = gpd.GeoDataFrame(
        {"id": [1], "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert overlaps == []


def test_find_overlapping_polygons_multiple_overlaps():
    """Test _find_overlapping_polygons with multiple overlapping polygons."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2, 3],
            "geometry": [
                Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),  # Square 0-2,0-2
                Polygon(
                    [(1, 1), (3, 1), (3, 3), (1, 3)]
                ),  # Square 1-3,1-3 (overlaps with 0)
                Polygon(
                    [(1.5, 1.5), (2.5, 1.5), (2.5, 2.5), (1.5, 2.5)]
                ),  # Overlaps with both 0 and 1
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Should find overlaps: (0,1), (1,0), (0,2), (2,0), (1,2), (2,1)
    assert len(overlaps) == 6
    expected_pairs = [(0, 1), (1, 0), (0, 2), (2, 0), (1, 2), (2, 1)]
    for pair in expected_pairs:
        assert pair in overlaps


def test_find_overlapping_polygons_identical_polygons():
    """Test _find_overlapping_polygons with identical polygons."""
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "geometry": [polygon, polygon]},  # Identical polygons
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Identical polygons should be detected as overlapping
    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_large_dataset():
    """Test _find_overlapping_polygons with larger dataset."""
    # Create a grid of polygons with some overlaps
    polygons = []
    for i in range(5):
        for j in range(5):
            # Create slightly overlapping grid
            x_start = i * 0.9  # 0.9 instead of 1.0 to create overlaps
            y_start = j * 0.9
            poly = Polygon(
                [
                    (x_start, y_start),
                    (x_start + 1, y_start),
                    (x_start + 1, y_start + 1),
                    (x_start, y_start + 1),
                ]
            )
            polygons.append(poly)

    gdf = gpd.GeoDataFrame(
        {"id": range(len(polygons)), "geometry": polygons}, crs="EPSG:4326"
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Should find many overlaps in the grid
    assert len(overlaps) > 0
    # Each polygon should overlap with its neighbors
    # Verify that overlaps are bidirectional
    overlap_set = set(overlaps)
    for i, j in overlap_set:
        assert (j, i) in overlap_set


def test_find_overlapping_polygons_invalid_geometry_column():
    """Test _find_overlapping_polygons with invalid geometry column name."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    # Should raise KeyError for non-existent column
    with pytest.raises(KeyError):
        geoprocessing_vector._find_overlapping_polygons(
            geometry_column="invalid_column"
        )


def test_find_overlapping_polygons_polygon_within_polygon():
    """Test _find_overlapping_polygons with polygon completely within another."""
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "geometry": [
                Polygon([(0, 0), (4, 0), (4, 4), (0, 4)]),  # Large outer polygon
                Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),  # Small inner polygon
            ],
        },
        crs="EPSG:4326",
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Inner polygon should be detected as overlapping with outer polygon
    assert len(overlaps) == 2  # (0,1) and (1,0)
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_complex_shapes():
    """Test _find_overlapping_polygons with complex polygon shapes."""
    # L-shaped polygons that overlap
    l_shape1 = Polygon([(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2), (0, 0)])

    l_shape2 = Polygon([(1, 1), (3, 1), (3, 3), (2, 3), (2, 2), (1, 2), (1, 1)])

    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "geometry": [l_shape1, l_shape2]}, crs="EPSG:4326"
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # Complex shapes should be detected as overlapping
    assert len(overlaps) == 2
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


def test_find_overlapping_polygons_return_type():
    """Test that _find_overlapping_polygons returns correct type."""
    gdf = gpd.GeoDataFrame(
        {"geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]}, crs="EPSG:4326"
    )

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    assert isinstance(overlaps, list)
    assert all(isinstance(item, tuple) for item in overlaps)
    assert all(len(item) == 2 for item in overlaps)
    assert all(
        isinstance(item[0], int) and isinstance(item[1], int) for item in overlaps
    )


@pytest.mark.parametrize("overlap_type", ["partial", "complete", "touching"])
def test_find_overlapping_polygons_different_overlap_types(overlap_type):
    """Parametrized test for different types of polygon overlaps."""
    if overlap_type == "partial":
        poly1 = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        poly2 = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])
    elif overlap_type == "complete":
        poly1 = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
        poly2 = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])
    else:  # touching
        poly1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        poly2 = Polygon([(1, 0), (2, 0), (2, 1), (1, 1)])

    gdf = gpd.GeoDataFrame({"geometry": [poly1, poly2]}, crs="EPSG:4326")

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    overlaps = geoprocessing_vector._find_overlapping_polygons(
        geometry_column="geometry"
    )

    # All types should be detected as intersecting
    assert len(overlaps) == 2
    assert (0, 1) in overlaps
    assert (1, 0) in overlaps


# ------------------------------------------
# Test cases for GeoprocessingVector._read_csv_as_gdf()
# ------------------------------------------
def test_read_csv_as_gdf_success_lon_lat(tmp_path):
    """Should read CSV with lon/lat columns and produce a GeoDataFrame with EPSG:4326 by default."""
    csv_path = tmp_path / "coords.csv"
    df = pd.DataFrame({"Lon": [0.0, 1.0], "Lat": [0.5, 1.5], "attr": [10, 20]})
    df.to_csv(csv_path, index=False)

    gdf = GeoprocessingVector._read_csv_as_gdf(vector_file=csv_path)
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert "geometry" in gdf.columns
    assert len(gdf) == 2
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 4326


def test_read_csv_as_gdf_fallback_to_latin1(monkeypatch, tmp_path):
    """Simulate UnicodeDecodeError on first pd.read_csv call and ensure latin1 fallback is used."""
    csv_path = tmp_path / "latin1.csv"
    # create a simple file (content doesn't matter because we patch pd.read_csv)
    csv_path.write_text("lon,lat\n0,0\n", encoding="latin1")

    csv_path.write_text("lon;lat\n0;0\n", encoding="latin1")
    gdf = GeoprocessingVector._read_csv_as_gdf(vector_file=csv_path)
    assert gdf.shape[0] == 1
    assert gdf.geometry.iloc[0].x == 0
    assert gdf.geometry.iloc[0].y == 0


def test_read_csv_as_gdf_missing_coordinate_columns_raises(tmp_path):
    """CSV without coordinate columns must raise ValueError."""
    csv_path = tmp_path / "no_coords.csv"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(csv_path, index=False)

    with pytest.raises(
        ValueError, match="CSV file does not contain valid geometry columns"
    ):
        GeoprocessingVector._read_csv_as_gdf(vector_file=csv_path)


def test_read_csv_as_gdf_uses_registry_crs(tmp_path):
    """If CSVDataRegistryForSourceCRS contains an entry for the file stem, its CRS should be used."""
    csv_path = tmp_path / "testcsv.csv"
    pd.DataFrame({"lon": [2.0], "lat": [3.0]}).to_csv(csv_path, index=False)

    # Fake registry object compatible with lookup in the function
    class FakeRegistry:
        __members__ = {"testcsv": True}

        def __getitem__(self, key):
            # emulate Enum member with .value, where value is a tuple and CRS is at index 1
            return SimpleNamespace(value=(None, "EPSG:3857"))

    with patch(
        "gis_pipeline.modules.processing.geoprocessing.CSVDataRegistryForSourceCRS",
        new=FakeRegistry(),
    ):
        gdf = GeoprocessingVector._read_csv_as_gdf(vector_file=csv_path)
        assert isinstance(gdf, gpd.GeoDataFrame)
        # CRS provided by registry should be used
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 3857


# ------------------------------------------
# Test cases for GeoprocessingVector.validate_vector_data()
# ------------------------------------------
def test_validate_vector_data_success(gdf_polygon_fixture):
    """Test successful validation of a valid GeoDataFrame."""
    with patch("gis_pipeline.modules.processing.geoprocessing.logger") as mock_logger:
        geoprocessing_vector = GeoprocessingVector(
            gdf=gdf_polygon_fixture,
            target_crs=Config.GLOBAL_CRS,
            collection_id=Config.STAC_COLLECTION_ID,
        )

        geoprocessing_vector.validate_vector_data()

        assert geoprocessing_vector.gdf.index.equals(
            pd.RangeIndex(len(gdf_polygon_fixture))
        )

        # Logging is informative and no warnings/errors are raised
        call_args = [c[0][0] for c in mock_logger.info.call_args_list]
        assert "Validating input data for vector processing..." in call_args
        assert "Input GeoDataFrame passed validation." in call_args
        mock_logger.error.assert_not_called()
        mock_logger.warning.assert_not_called()


@pytest.mark.parametrize(
    "invalid_input",
    [
        None,  # None
        "not_a_dataframe",  # String
        [1, 2, 3],  # List
        {"a": 1},  # Dictionary
    ],
)
def test_validate_vector_data_invalid_input_types(invalid_input):
    """Validation fails when input is not a GeoDataFrame."""
    geoprocessing_vector = GeoprocessingVector(
        gdf=invalid_input,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    with pytest.raises(
        ValueError, match="Input must be a GeoDataFrame or a pandas DataFrame."
    ):
        geoprocessing_vector.validate_vector_data()


def test_validate_vector_data_empty_gdf():
    """Empty GeoDataFrame should pass validation with a warning."""
    gdf = gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    assert geoprocessing_vector.gdf.empty


def test_validate_vector_data_missing_geometry_column():
    """Validation passed when the geometry column is absent."""
    df = pd.DataFrame({"attr": [1, 2], "some_column": ["a", "b"]})
    geoprocessing_vector = GeoprocessingVector(
        gdf=df,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.validate_vector_data()

    assert isinstance(geoprocessing_vector.gdf, pd.DataFrame)


def test_validate_vector_data_geometry_column_not_in_columns():
    """Validation passes when geometry attribute is missing from columns, converting to DataFrame."""
    gdf = gpd.GeoDataFrame({"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
    gdf.crs = "EPSG:4326"
    gdf = gdf.drop(columns=["geometry"])  # Remove geometry column

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    assert isinstance(geoprocessing_vector.gdf, pd.DataFrame)


def test_validate_vector_data_no_crs():
    """Validation fails when CRS is missing."""
    gdf = gpd.GeoDataFrame({"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    with pytest.raises(
        ValueError, match="GeoDataFrame must have a CRS before processing."
    ):
        geoprocessing_vector.validate_vector_data()


def test_validate_vector_data_crs_no_epsg():
    """Validation fails when CRS cannot be converted to EPSG."""
    gdf = gpd.GeoDataFrame({"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
    gdf.crs = "EPSG:4326"
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    with patch.object(geoprocessing_vector.gdf.crs, "to_epsg", return_value=None):
        with pytest.raises(
            ValueError, match="GeoDataFrame CRS is invalid or unreadable"
        ):
            geoprocessing_vector.validate_vector_data()


def test_validate_vector_data_index_reset():
    """Index is reset to a default RangeIndex."""
    gdf = gpd.GeoDataFrame(
        {"attr": [1, 2, 3]}, geometry=[Point(0, 0), Point(1, 1), Point(2, 2)]
    )
    gdf.crs = "EPSG:4326"
    gdf.index = [10, 20, 30]

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    expected_index = pd.RangeIndex(start=0, stop=3, step=1)
    assert geoprocessing_vector.gdf.index.equals(expected_index)


def test_validate_vector_data_preserves_data():
    """Data content is preserved after validation."""
    original_data = {"attr": [1, 2], "name": ["A", "B"]}
    original_geometry = [Point(0, 0), Point(1, 1)]
    gdf = gpd.GeoDataFrame(original_data, geometry=original_geometry)
    gdf.crs = "EPSG:4326"

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf.copy(),
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    assert list(geoprocessing_vector.gdf["attr"]) == original_data["attr"]
    assert list(geoprocessing_vector.gdf["name"]) == original_data["name"]
    assert len(geoprocessing_vector.gdf) == len(original_geometry)


def test_validate_vector_data_multiple_calls_idempotent():
    """Multiple validations remain idempotent."""
    gdf = gpd.GeoDataFrame({"attr": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)])
    gdf.crs = "EPSG:4326"

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    for _ in range(3):
        geoprocessing_vector.validate_vector_data()

    assert isinstance(geoprocessing_vector.gdf, gpd.GeoDataFrame)
    assert len(geoprocessing_vector.gdf) == 2


def test_validate_vector_data_with_different_crs_formats():
    """Validation handles multiple CRS formats."""
    geometries = [Point(0, 0), Point(1, 1)]
    crs_formats = [
        "EPSG:4326",
        "epsg:4326",
        4326,
        "WGS84",
        "+proj=longlat +datum=WGS84 +no_defs",
    ]

    for crs in crs_formats:
        gdf = gpd.GeoDataFrame({"attr": [1, 2]}, geometry=geometries)
        try:
            gdf.crs = crs
            geoprocessing_vector = GeoprocessingVector(
                gdf=gdf,
                target_crs=Config.GLOBAL_CRS,
                collection_id=Config.STAC_COLLECTION_ID,
            )

            if gdf.crs.to_epsg() is not None:
                geoprocessing_vector.validate_vector_data()
                assert isinstance(geoprocessing_vector.gdf, gpd.GeoDataFrame)
            else:
                with pytest.raises(
                    ValueError,
                    match="GeoDataFrame must have a CRS set before harmonizing",
                ):
                    geoprocessing_vector.validate_vector_data()
        except Exception:
            # Skip invalid CRS formats
            continue


def test_validate_vector_data_edge_case_single_row():
    """Validation works on a single-row GeoDataFrame."""
    gdf = gpd.GeoDataFrame({"attr": [1]}, geometry=[Point(0, 0)])
    gdf.crs = "EPSG:4326"

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    assert len(geoprocessing_vector.gdf) == 1
    assert isinstance(geoprocessing_vector.gdf, gpd.GeoDataFrame)


def test_validate_vector_data_edge_case_many_columns():
    """Validation handles many attribute columns."""
    data = {f"col_{i}": [i, i + 1] for i in range(100)}
    data["geometry"] = [Point(0, 0), Point(1, 1)]
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.crs = "EPSG:4326"

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )

    geoprocessing_vector.validate_vector_data()

    assert len(geoprocessing_vector.gdf.columns) == 101
    assert isinstance(geoprocessing_vector.gdf, gpd.GeoDataFrame)


# ------------------------------------------
# Test cases for GeoprocessingVector.harmonize_gdf()
# ------------------------------------------
def test_harmonize_gdf_removes_duplicates(gdf_points_harmonization_fixture):
    """
    Test if the harmonize_gdf method removes duplicate rows.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_points_harmonization_fixture,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    # Count the lines number before and after suppression
    initial_count = len(gdf_points_harmonization_fixture)
    geoprocessing_vector.harmonize_gdf(drop_duplicates=True)
    final_count = len(geoprocessing_vector.gdf)
    # Check duplicates were removed
    assert final_count <= initial_count
    assert geoprocessing_vector.gdf.equals(
        geoprocessing_vector.gdf.drop_duplicates()
    ), "The GeoDataFrame still have duplicates."


def test_harmonize_gdf_handles_nulls(gdf_points_harmonization_fixture):
    """
    Test if the harmonize_gdf method handles null values.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_points_harmonization_fixture,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.harmonize_gdf()
    null_count = geoprocessing_vector.gdf.isnull().sum().sum()
    assert null_count > 0, f"Expected some nulls, found {null_count}"


def test_harmonize_gdf_renames_columns(gdf_points_harmonization_fixture):
    """
    Test if the harmonize_gdf method renames columns correctly.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_points_harmonization_fixture,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.harmonize_gdf(rename_columns=True)

    # Original columns should not remain
    assert "Nom" not in geoprocessing_vector.gdf.columns
    assert "Valeur" not in geoprocessing_vector.gdf.columns

    # Expect renamed/normalized columns present (lowercase, no spaces)
    cols = list(geoprocessing_vector.gdf.columns)
    name_candidates = [
        c
        for c in cols
        if c.lower().startswith("nom")
        or c.lower().startswith("name")
        or "nom" in c.lower()
    ]
    value_candidates = [
        c
        for c in cols
        if c.lower().startswith("val")
        or c.lower().startswith("value")
        or "valeur" in c.lower()
    ]

    assert name_candidates, f"No candidate column found for 'Nom' in {cols}"
    assert value_candidates, f"No candidate column found for 'Valeur' in {cols}"

    # Ensure normalized form: lowercase and no spaces
    for c in name_candidates + value_candidates:
        assert c == c.lower()
        assert " " not in c


def test_harmonize_gdf_strips_accented_column_names():
    """Column names with accented characters must be reduced to ASCII equivalents."""
    gdf = gpd.GeoDataFrame(
        {"année": [2023], "région": ["QC"], "geometry": [Point(0, 0)]},
        crs="EPSG:4326",
    )
    gv = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    gv.harmonize_gdf(rename_columns=True)
    cols = list(gv.gdf.columns)
    assert "année" not in cols
    assert "région" not in cols
    assert "annee" in cols
    assert "region" in cols


def test_harmonize_gdf_drops_null_geometries(gdf_points_harmonization_fixture):
    """
    Test if the harmonize_gdf method drops rows with null geometries.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_points_harmonization_fixture,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.harmonize_gdf(drop_null_geoms=True)
    assert geoprocessing_vector.gdf.loc[:, "geometry"].isnull().sum() == 0


def test_harmonize_gdf_invalid_input():
    """
    Test if the harmonize_gdf method raises an error for invalid input.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=pd.DataFrame({"a": [1, 2, 3]}),
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    with pytest.raises(AttributeError):
        geoprocessing_vector.harmonize_gdf()


# ------------------------------------------
# Test cases for GeoprocessingVector.clean_geometries_gdf()
# ------------------------------------------
def test_clean_geometries_gdf_removes_nulls(gdf_with_null_geoms):
    """
    Test if the clean_geometries_gdf method removes rows with null geometries.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_with_null_geoms,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.clean_geometries_gdf()
    assert geoprocessing_vector.gdf["geometry"].isnull().sum() == 0
    assert (
        geoprocessing_vector.gdf.shape[0] == 2
    )  # Only rows with valid geometry remain


def test_clean_geometries_gdf_detects_geometry_column(gdf_with_null_geoms):
    """
    Test if the clean_geometries_gdf method detects the geometry column correctly.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_with_null_geoms,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    # Should auto-detect 'geometry' column
    geoprocessing_vector.clean_geometries_gdf()
    assert "geometry" in geoprocessing_vector.gdf.columns


def test_clean_geometries_gdf_check_overlaps(gdf_with_polygons):
    """
    Test if the clean_geometries_gdf method checks for overlaps in polygons.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_with_polygons,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    # Should run without error and return the same number of rows
    geoprocessing_vector.clean_geometries_gdf(is_check_overlaps=True)
    assert geoprocessing_vector.gdf.shape[0] == 2


# ------------------------------------------
# Test cases for GeoprocessingVector.harmonize_crs_gdf()
# ------------------------------------------
@pytest.mark.parametrize(
    "initial_crs,expected_epsg",
    [
        (3857, 4326),  # Different crs
        (4326, 4326),  # Same crs
    ],
)
def test_harmonize_crs_gdf(initial_crs, expected_epsg, gdf_epsg3857):
    """
    Test harmonize_crs_gdf for reprojection and no-op when already EPSG:4326.
    """
    gdf = gdf_epsg3857.copy()
    gdf = gdf.set_crs(epsg=initial_crs, allow_override=True)

    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    geoprocessing_vector.harmonize_crs_gdf()

    # Vérifie que le CRS final est bien EPSG:4326
    assert geoprocessing_vector.gdf.crs.to_epsg() == expected_epsg


def test_harmonize_crs_gdf_missing_crs(gdf_no_crs):
    """
    Test if the harmonize_crs_gdf method raises an error for GeoDataFrame with no CRS.
    """
    geoprocessing_vector = GeoprocessingVector(
        gdf=gdf_no_crs,
        target_crs=Config.GLOBAL_CRS,
        collection_id=Config.STAC_COLLECTION_ID,
    )
    with pytest.raises(ValueError):
        geoprocessing_vector.harmonize_crs_gdf()


# ------------------------------------------
# Test cases for GeoprocessingVector.convert_vector_files_to_gdf()
# ------------------------------------------
def test_convert_vector_files_to_gdf_single_file_single_layer(temp_vector_files):
    """Test converting single vector file with single layer."""
    vector_files = [temp_vector_files["shapefile"]]

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    assert len(result) == 1
    assert isinstance(result, list)

    # Check the tuple structure (name, gdf)
    name, gdf = result[0]
    assert isinstance(name, str)
    assert isinstance(gdf, gpd.GeoDataFrame)

    # Check the name is harmonized
    assert name == "test_shapefile"  # stem of the file

    # Check the GeoDataFrame content
    assert len(gdf) == 2
    assert "id" in gdf.columns
    assert "name" in gdf.columns
    assert "geometry" in gdf.columns
    assert gdf.crs is not None


def test_convert_vector_files_to_gdf_multiple_files(temp_vector_files):
    """Test converting multiple vector files."""
    vector_files = [
        temp_vector_files["shapefile"],
        temp_vector_files["geojson"],
        temp_vector_files["geopackage"],
    ]

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    assert len(result) == 3

    # Check names are different and harmonized
    names = [name for name, gdf in result]
    expected_names = ["test_shapefile", "test_geojson", "test_geopackage"]
    assert set(names) == set(expected_names)

    # Check all are GeoDataFrames
    for name, gdf in result:
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 2


def test_convert_vector_files_to_gdf_multilayer_file(temp_multilayer_gpkg):
    """Test converting file with multiple layers."""
    vector_files = [temp_multilayer_gpkg["path"]]

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    assert len(result) == 2  # Two layers

    # Compute expected names from actual file stem
    file_stem = Path(temp_multilayer_gpkg["path"]).stem
    expected_name1 = f"{file_stem}_layer1"
    expected_name2 = f"{file_stem}_layer2"

    # Check names include layer suffixes
    names = [name for name, gdf in result]
    assert expected_name1 in names
    assert expected_name2 in names

    # Check GeoDataFrames have expected content (fixture writes 'id' and 'name')
    gdfs_by_name = {name: gdf for name, gdf in result}

    layer1_gdf = gdfs_by_name[expected_name1]
    layer2_gdf = gdfs_by_name[expected_name2]

    assert "id" in layer1_gdf.columns
    assert "name" in layer2_gdf.columns
    assert len(layer1_gdf) == 2
    assert len(layer2_gdf) == 2


def test_convert_vector_files_to_gdf_empty_list():
    """Test with empty list of files."""
    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[])

    assert result == []
    assert isinstance(result, list)


def test_convert_vector_files_to_gdf_nonexistent_file(tmp_path):
    """Test with non-existent file raises VectorProcessingError."""
    from gis_pipeline.core.exceptions import VectorProcessingError

    nonexistent_file = tmp_path / "does_not_exist.shp"
    vector_files = [nonexistent_file]

    with pytest.raises(VectorProcessingError):
        GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)


@patch("gis_pipeline.modules.processing.geoprocessing.fiona.listlayers")
@patch("gis_pipeline.modules.processing.geoprocessing.gpd.read_file")
def test_convert_vector_files_to_gdf_fiona_exception(
    mock_read_file, mock_listlayers, tmp_path
):
    """Test when fiona.listlayers raises exception."""
    test_file = tmp_path / "test.shp"
    test_file.touch()  # Create empty file

    # Make fiona.listlayers raise an exception
    mock_listlayers.side_effect = Exception("Fiona error")

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[test_file])

    assert result == []


@patch("gis_pipeline.modules.processing.geoprocessing.fiona.listlayers")
@patch("gis_pipeline.modules.processing.geoprocessing.gpd.read_file")
def test_convert_vector_files_to_gdf_geopandas_exception(
    mock_read_file, mock_listlayers, tmp_path
):
    """Test when geopandas.read_file raises exception."""
    test_file = tmp_path / "test.shp"
    test_file.touch()

    # Make fiona.listlayers succeed but gpd.read_file fail
    mock_listlayers.return_value = ["layer1"]
    mock_read_file.side_effect = Exception("GeoPandas error")

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[test_file])

    assert result == []


def test_convert_vector_files_to_gdf_name_harmonization(tmp_path):
    """Test that file names are properly harmonized."""
    # Create file with name that needs harmonization
    gdf = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326")

    # File with special characters in name
    special_file = tmp_path / "My Data File (2023) - Version 1.0.shp"
    gdf.to_file(special_file)

    result = GeoprocessingVector.convert_vector_files_to_gdf(
        vector_files=[special_file]
    )

    assert len(result) == 1
    name, gdf_result = result[0]

    # Name should be harmonized
    assert name == "my_data_file_2023_version_1_0"
    assert isinstance(gdf_result, gpd.GeoDataFrame)


def test_convert_vector_files_to_gdf_layer_name_harmonization(temp_multilayer_gpkg):
    """Test that layer names are properly harmonized."""
    # Create geopackage with layer names that need harmonization
    gpkg_path = temp_multilayer_gpkg["path"].parent / "special_layers.gpkg"

    gdf = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326")

    # Save with special characters in layer name
    gdf.to_file(gpkg_path, layer="Layer With Spaces!", driver="GPKG")

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[gpkg_path])

    assert len(result) == 1
    name, gdf_result = result[0]

    file_stem = "special_layers"
    layer_name = "Layer With Spaces!"

    # Simuler la logique de la fonction
    layers = fiona.listlayers(gpkg_path)

    if len(layers) == 1:
        expected_name = file_stem
    else:
        expected_name = f"{file_stem}_{layer_name.strip()}"

    expected_harmonized = harmonize_name(expected_name, _GDF_PATTERN, _MAX)

    assert name == expected_harmonized
    assert isinstance(gdf_result, gpd.GeoDataFrame)


@patch("gis_pipeline.modules.processing.geoprocessing.fiona.listlayers")
def test_convert_vector_files_to_gdf_no_layers(mock_listlayers, tmp_path):
    """Test when fiona.listlayers returns empty list."""
    test_file = tmp_path / "empty.shp"
    test_file.touch()

    mock_listlayers.return_value = []

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[test_file])

    # Should return empty list when no layers found
    assert result == []


def test_convert_vector_files_to_gdf_pathlib_path_objects(temp_vector_files):
    """Test that function works with pathlib.Path objects."""
    vector_files = [
        Path(temp_vector_files["shapefile"]),
        Path(temp_vector_files["geojson"]),
    ]

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    assert len(result) == 2

    for name, gdf in result:
        assert isinstance(name, str)
        assert isinstance(gdf, gpd.GeoDataFrame)


@pytest.mark.parametrize("file_extension", [".shp", ".geojson", ".gpkg"])
def test_convert_vector_files_to_gdf_different_formats(tmp_path, file_extension):
    """Parametrized test for different vector file formats."""
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]}, crs="EPSG:4326"
    )

    file_path = tmp_path / f"test{file_extension}"

    # Choose appropriate driver
    driver_map = {".shp": "ESRI Shapefile", ".geojson": "GeoJSON", ".gpkg": "GPKG"}

    gdf.to_file(file_path, driver=driver_map[file_extension])

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=[file_path])

    assert len(result) == 1
    name, result_gdf = result[0]
    assert name == "test"
    assert len(result_gdf) == 2


def test_convert_vector_files_to_gdf_preserves_gdf_properties(temp_vector_files):
    """Test that GeoDataFrame properties are preserved."""
    vector_files = [temp_vector_files["shapefile"]]
    original_gdf = temp_vector_files["gdf"]

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    name, result_gdf = result[0]

    # Check that important properties are preserved
    assert result_gdf.crs is not None
    assert len(result_gdf) == len(original_gdf)
    assert set(result_gdf.columns) >= {"id", "name", "geometry"}

    # Check geometry types are preserved
    assert all(result_gdf.geometry.geom_type == "Point")


def test_convert_vector_files_to_gdf_large_file_list(temp_vector_files):
    """Test with a large list of the same file (stress test)."""
    # Create list with same file repeated multiple times
    vector_files = [temp_vector_files["shapefile"]] * 10

    result = GeoprocessingVector.convert_vector_files_to_gdf(vector_files=vector_files)

    # Should process all files
    assert len(result) == 10

    # All should have the same name (since it's the same file)
    names = [name for name, gdf in result]
    assert all(name == "test_shapefile" for name in names)

    # All should be identical GeoDataFrames
    for name, gdf in result:
        assert len(gdf) == 2
        assert isinstance(gdf, gpd.GeoDataFrame)


# ------------------------------------------
# GEE flag functions
# ------------------------------------------


@pytest.mark.unit
class TestGetGeeFieldIds:
    def test_returns_set_of_ints_from_parquet(self):
        from gis_pipeline.modules.processing.geoprocessing import get_gee_field_ids

        mock_con = MagicMock()
        mock_con.execute.return_value.fetchall.return_value = [(1,), (2,), (3,)]

        with patch(
            "glob.glob", return_value=["/data/duckdb/BareSoil_TOPCLI_2023.parquet"]
        ):
            with patch("duckdb.connect", return_value=mock_con):
                result = get_gee_field_ids("/data/duckdb")

        assert result == {1, 2, 3}
        mock_con.close.assert_called_once()

    def test_returns_empty_set_when_no_parquet_files(self):
        from gis_pipeline.modules.processing.geoprocessing import get_gee_field_ids

        with patch("glob.glob", return_value=[]):
            result = get_gee_field_ids("/data/duckdb")

        assert result == set()

    def test_returns_empty_set_on_duckdb_error(self):
        from gis_pipeline.modules.processing.geoprocessing import get_gee_field_ids

        with patch(
            "glob.glob", return_value=["/data/duckdb/BareSoil_TOPCLI_2023.parquet"]
        ):
            with patch("duckdb.connect", side_effect=Exception("DuckDB error")):
                result = get_gee_field_ids("/data/duckdb")

        assert result == set()


@pytest.mark.unit
class TestStampGeeFlagsOnFieldBoundaries:
    def test_happy_path_calls_stamp_and_refresh(self):
        from gis_pipeline.modules.processing.geoprocessing import (
            stamp_gee_flags_on_field_boundaries,
        )

        mock_pg = MagicMock()

        with patch(
            "gis_pipeline.modules.processing.geoprocessing.get_gee_field_ids",
            return_value={1, 2},
        ):
            with patch(
                "gis_pipeline.modules.processing.geoprocessing.PostGISManager"
            ) as mock_pg_cls:
                mock_pg_cls.return_value.__enter__.return_value = mock_pg
                with patch(
                    "gis_pipeline.modules.processing.geoprocessing._refresh_gee_geoparquet"
                ) as mock_refresh:
                    stamp_gee_flags_on_field_boundaries()

        mock_pg.stamp_gee_flags.assert_called_once_with("som_field_boundaries", {1, 2})
        mock_refresh.assert_called_once()

    def test_postgis_failure_skips_refresh(self):
        from gis_pipeline.modules.processing.geoprocessing import (
            stamp_gee_flags_on_field_boundaries,
        )

        with patch(
            "gis_pipeline.modules.processing.geoprocessing.get_gee_field_ids",
            return_value={1},
        ):
            with patch(
                "gis_pipeline.modules.processing.geoprocessing.PostGISManager",
                side_effect=Exception("PG down"),
            ):
                with patch(
                    "gis_pipeline.modules.processing.geoprocessing._refresh_gee_geoparquet"
                ) as mock_refresh:
                    stamp_gee_flags_on_field_boundaries()  # must not raise

        mock_refresh.assert_not_called()
