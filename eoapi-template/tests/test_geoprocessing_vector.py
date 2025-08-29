# tests/test_geoprocessing_vector.py
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pandas as pd
import pytest
import sqlalchemy
from demo.geoprocessing import GeoprocessingVector, geoprocessing_vector_data_postgis
from demo.processing_stac import StacApiClient
from shapely.geometry import Point, Polygon


# ------------------------------------------
# Test cases for validating GeoDataFrames
# ------------------------------------------
@pytest.fixture
def sample_gdf():
    """
    Sample GeoDataFrame for testing.
    """
    data = {
        "geometry": [Point(0, 0), Point(1, 1)],
        "other": [1, 2],
    }
    gdf = gpd.GeoDataFrame(data, geometry="geometry")
    gdf.crs = "EPSG:4326"
    return gdf


def test_validate_vector_data_success(sample_gdf):
    """
    Test if the GeoDataFrame is validated successfully.
    """
    sample_gdf = sample_gdf.set_crs(epsg=4326)
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=sample_gdf)
    geoprocessing_vector.validate_vector_data()
    assert isinstance(
        geoprocessing_vector, GeoprocessingVector
    ), "Validation should return the GeoprocessingVector instance"


def test_validate_vector_data_not_geodataframe():
    """
    Test if the input is not a valid GeoDataFrame.
    """
    df = pd.DataFrame({"a": [1, 2, 3]})
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=df)
    with pytest.raises(ValueError, match="Input must be a valid GeoDataFrame"):
        geoprocessing_vector.validate_vector_data()


def test_validate_vector_data_missing_geometry_column():
    """
    Test if the GeoDataFrame is missing the geometry column.
    """
    geometry = [Point(0, 0), Point(1, 1)]
    gdf = gpd.GeoDataFrame({"attr": [1, 2], "geom": geometry})
    gdf = gdf.set_geometry("geom")
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.drop(columns=["geom"])  # Remove geometry column to trigger error
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf)
    with pytest.raises(ValueError, match="Input must be a valid GeoDataFrame"):
        geoprocessing_vector.validate_vector_data()


def test_validate_vector_data_empty_geodataframe():
    """
    Test if the GeoDataFrame is empty.
    """
    gdf = gpd.GeoDataFrame({"geometry": []}, geometry="geometry")
    gdf = gdf.set_crs(epsg=4326)
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf)
    with pytest.raises(ValueError, match="GeoDataFrame is empty."):
        geoprocessing_vector.validate_vector_data()


# ------------------------------------------
# Test cases for harmonizing GeoDataFrames
# ------------------------------------------
@pytest.fixture
def sample_gdf_harmonization():
    """
    Sample GeoDataFrame for testing harmonization.
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


def test_harmonize_gdf_removes_duplicates(sample_gdf_harmonization):
    """
    Test if the harmonize_gdf method removes duplicate rows.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=sample_gdf_harmonization
    )
    # Count the lines number before and after suppression
    initial_count = len(sample_gdf_harmonization)
    geoprocessing_vector.harmonize_gdf(drop_duplicates=True)
    final_count = len(geoprocessing_vector.gdf)
    # Check duplicates were removed
    assert final_count <= initial_count
    assert geoprocessing_vector.gdf.equals(
        geoprocessing_vector.gdf.drop_duplicates()
    ), "The GeoDataFrame still have duplicates."


def test_harmonize_gdf_handles_nulls(sample_gdf_harmonization):
    """
    Test if the harmonize_gdf method handles null values.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=sample_gdf_harmonization
    )
    geoprocessing_vector.harmonize_gdf()
    null_count = geoprocessing_vector.gdf.isnull().sum().sum()
    assert null_count > 0, f"Expected some nulls, found {null_count}"


def test_harmonize_gdf_renames_columns(sample_gdf_harmonization):
    """
    Test if the harmonize_gdf method renames columns correctly.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=sample_gdf_harmonization
    )
    columns_mapping = {"Nom": "name", "Valeur": "value"}
    geoprocessing_vector.harmonize_gdf(columns_mapping=columns_mapping)
    assert all(
        [s in geoprocessing_vector.gdf.columns for s in columns_mapping.values()]
    )


def test_harmonize_gdf_casts_types(sample_gdf_harmonization):
    """
    Test if the harmonize_gdf method casts column types correctly.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=sample_gdf_harmonization
    )
    geoprocessing_vector.harmonize_gdf(
        columns_mapping={"Nom": "name", "Valeur": "value"},
        expected_types={"name": str, "value": int}
    )
    assert geoprocessing_vector.gdf["name"].dropna().map(type).eq(str).all(), \
        "Column 'name' does not contain only str values"
    assert pd.api.types.is_integer_dtype(geoprocessing_vector.gdf["value"]), \
        "Column 'value' is not of integer dtype"


def test_harmonize_gdf_drops_null_geometries(sample_gdf_harmonization):
    """
    Test if the harmonize_gdf method drops rows with null geometries.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=sample_gdf_harmonization
    )
    geoprocessing_vector.harmonize_gdf(drop_null_geoms=True)
    assert geoprocessing_vector.gdf.loc[:, "geometry"].isnull().sum() == 0  


def test_harmonize_gdf_invalid_input():
    """
    Test if the harmonize_gdf method raises an error for invalid input.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=pd.DataFrame({"a": [1, 2, 3]}))
    with pytest.raises(AttributeError):
        geoprocessing_vector.harmonize_gdf()


# ------------------------------------------
# Test cases for GeoDataFrame geometry cleaning
# ------------------------------------------
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


def test_clean_geometries_gdf_removes_nulls(gdf_with_null_geoms):
    """
    Test if the clean_geometries_gdf method removes rows with null geometries.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf_with_null_geoms)
    geoprocessing_vector.clean_geometries_gdf()
    assert geoprocessing_vector.gdf["geom"].isnull().sum() == 0
    assert (
        geoprocessing_vector.gdf.shape[0] == 2
    )  # Only rows with valid geometry remain


def test_clean_geometries_gdf_detects_geometry_column(gdf_with_null_geoms):
    """
    Test if the clean_geometries_gdf method detects the geometry column correctly.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf_with_null_geoms)
    # Should auto-detect 'geometry' column
    geoprocessing_vector.clean_geometries_gdf()
    assert "geom" in geoprocessing_vector.gdf.columns


def test_clean_geometries_gdf_check_overlaps(gdf_with_polygons):
    """
    Test if the clean_geometries_gdf method checks for overlaps in polygons.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf_with_polygons)
    # Should run without error and return the same number of rows
    geoprocessing_vector.clean_geometries_gdf(is_check_overlaps=True)
    assert geoprocessing_vector.gdf.shape[0] == 2


# ------------------------------------------
# Test cases for harmonizing CRS in GeoDataFrames
# ------------------------------------------
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

    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf)
    geoprocessing_vector.harmonize_crs_gdf()
    
    # Vérifie que le CRS final est bien EPSG:4326
    assert geoprocessing_vector.gdf.crs.to_epsg() == expected_epsg


def test_harmonize_crs_gdf_missing_crs(gdf_no_crs):
    """
    Test if the harmonize_crs_gdf method raises an error for GeoDataFrame with no CRS.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf_no_crs)
    with pytest.raises(ValueError):
        geoprocessing_vector.harmonize_crs_gdf()


# ------------------------------------------
# Test cases for cleaning geometries in GeoDataFrames
# ------------------------------------------
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


def test_find_overlapping_polygons_success(gdf_with_overlapping_polygons):
    """
    Test if the find_overlapping_polygons method detects overlapping polygons.
    """
    geoprocessing_vector = GeoprocessingVector(
        config=None, gdf=gdf_with_overlapping_polygons
    )
    overlaps = geoprocessing_vector.find_overlapping_polygons(
        geometry_column="geometry"
    )
    assert len(overlaps) == 2, "Expected two overlapping polygons"


def test_find_overlapping_polygons_no_overlaps(gdf_with_polygons):
    """
    Test if the find_overlapping_polygons method returns empty for non-overlapping polygons.
    """
    geoprocessing_vector = GeoprocessingVector(config=None, gdf=gdf_with_polygons)
    overlaps = geoprocessing_vector.find_overlapping_polygons(
        geometry_column="geometry"
    )
    assert len(overlaps) == 0, "Expected no overlapping polygons"


# ------------------------------------------
# Test cases for vector data processing in PostGIS
# ------------------------------------------
@pytest.mark.mocked
@pytest.mark.parametrize(
    "gdf_list",
    [
        [
            (
                "test_table",
                gpd.GeoDataFrame(
                    {
                        "geom": [Point(0, 0), Point(1, 1)],
                        "gid": [1, 2],
                        "start_date": [
                            pd.Timestamp("2023-01-01T00:00:00Z"),
                            pd.Timestamp("2023-01-01T00:00:00Z"),
                        ],
                        "end_date": [
                            pd.Timestamp("2023-01-02T00:00:00Z"),
                            pd.Timestamp("2023-01-02T00:00:00Z"),
                        ],
                    },
                    geometry="geom",
                    crs="EPSG:4326",
                ),
            )
        ],
        [
            (
                "test_table",
                gpd.GeoDataFrame(
                    {
                        "geom": [Point(2, 2), Point(3, 3)],
                        "gid": [3, 4],
                        "start_date": [
                            pd.Timestamp("2023-01-01T00:00:00Z"),
                            pd.Timestamp("2023-01-01T00:00:00Z"),
                        ],
                        "end_date": [
                            pd.Timestamp("2023-01-02T00:00:00Z"),
                            pd.Timestamp("2023-01-02T00:00:00Z"),
                        ],
                    },
                    geometry="geom",
                    crs="EPSG:4326",
                ),
            )
        ],
    ],
)
def test_geoprocessing_vector_data_postgis_success(gdf_list):
    """
    Test if the geoprocessing_vector_data_postgis function processes vector data correctly.
    """
    assert "geom" in gdf_list[0][1].columns
    assert gdf_list[0][1].geometry.name == "geom"

    with patch("requests.get") as mock_get, patch("requests.post") as mock_post, patch(
        "sqlalchemy.create_engine"
    ) as mock_create_engine, patch(
        "geopandas.GeoDataFrame.to_postgis"
    ) as mock_to_postgis, patch(
        "sqlalchemy.text"
    ) as mock_text, patch(
        "sqlalchemy.inspect"
    ) as mock_sa_inspect, patch(
        "geopandas.read_postgis", return_value=gdf_list[0][1]
    ) as mock_read_postgis, patch(
        "demo.processing_stac.build_stac_items_from_table",
        return_value=[{"id": "item1"}],
    ), patch(
        "demo.processing_stac.validate_stac"
    ), patch.object(
        StacApiClient,
        "create_and_validate_collection",
        return_value={"id": "collection1"},
    ), patch.object(
        StacApiClient, "post_collection"
    ), patch.object(
        StacApiClient, "post_items"
    ):
        # Setup mocks
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.keys.return_value = ["geom", "gid"]
        mock_result.scalar.return_value = 2
        mock_result.fetchall.return_value = [(Point(0, 0), 1), (Point(1, 1), 2)]
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        # Inspector mock
        mock_insp = MagicMock()
        mock_insp.get_columns.return_value = [{"name": "geom"}, {"name": "gid"}]
        mock_sa_inspect.return_value = mock_insp

        # Run pipeline
        engine = sqlalchemy.create_engine("mocked_url")
        geoprocessing_vector_data_postgis(engine, gdf_list)

        # Assert table was queried
        mock_conn.execute.assert_called_with(
            mock_text("SELECT COUNT(*) FROM test_table")
        )
        assert mock_conn.execute.return_value.scalar() == 2
