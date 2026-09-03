from datetime import datetime as dt
from datetime import timezone
from unittest.mock import Mock, patch

import geopandas as gpd
import pandas as pd
import pytest
import sqlalchemy.exc
from gis_pipeline.modules.db.pg_utils import PostGISManager
from gis_pipeline.services.mapping import PostgresDataTypes, RasterStacColumns
from shapely.geometry import Point


# ------------------------------------------
# Environment Variable Tests
# ------------------------------------------
@pytest.fixture(autouse=True)
def mock_config():
    """Auto-use fixture to mock Config class."""
    config_values = {
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_pass",
        "POSTGRES_HOST": "database",
        "POSTGRES_PORT": 5432,
        "POSTGRES_DB": "postgres",
        "POSTGRES_MAX_NAME_LENGTH": 50,
    }

    with patch("gis_pipeline.modules.db.pg_utils.Config") as mock_config:
        for attr, value in config_values.items():
            setattr(mock_config, attr, value)

        yield mock_config


def create_mock_context_manager():
    """Create a proper mock context manager."""
    mock_cm = Mock()
    mock_cm.__enter__ = Mock(return_value=mock_cm)
    mock_cm.__exit__ = Mock(return_value=None)
    return mock_cm


# ------------------------------------------
# Fixtures - General
# ------------------------------------------
@pytest.fixture
def mock_engine(mock_config):
    """Provide a mock SQLAlchemy engine with proper context manager support and URL info."""
    mock_engine = Mock()

    mock_url = Mock()
    mock_url.host = mock_config.POSTGRES_HOST
    mock_url.port = mock_config.POSTGRES_PORT
    mock_url.database = mock_config.POSTGRES_DB
    mock_url.username = mock_config.POSTGRES_USER
    mock_engine.url = mock_url

    # Mock connexion PostGIS
    mock_conn = Mock()
    mock_result = Mock()
    mock_result.fetchone.return_value = (
        "postgis",
    )  # Simulate PostGIS extension present
    mock_conn.execute.return_value = mock_result

    mock_conn.__enter__ = Mock(return_value=mock_conn)
    mock_conn.__exit__ = Mock(return_value=None)

    mock_engine.connect.return_value = mock_conn
    mock_engine.begin.return_value = mock_conn

    return mock_engine


@pytest.fixture
def mock_engine_no_postgis(mock_config):
    """Provide a mock engine without PostGIS extension."""
    mock_engine = Mock()

    mock_url = Mock()
    mock_url.host = mock_config.POSTGRES_HOST
    mock_url.port = mock_config.POSTGRES_PORT
    mock_url.database = mock_config.POSTGRES_DB
    mock_url.username = mock_config.POSTGRES_USER
    mock_engine.url = mock_url

    mock_conn = Mock()
    mock_result = Mock()
    mock_result.fetchone.return_value = None  # Simulate PostGIS extension missing
    mock_conn.execute.return_value = mock_result

    mock_conn.__enter__ = Mock(return_value=mock_conn)
    mock_conn.__exit__ = Mock(return_value=None)

    mock_engine.connect.return_value = mock_conn
    return mock_engine


@pytest.fixture
def postgis_manager(mock_engine):
    """Provide a PostGISManager instance with mocked engine."""
    return PostGISManager(engine=mock_engine)


@pytest.fixture
def mock_gdf():
    """Provide a mock GeoDataFrame."""
    return gpd.GeoDataFrame({"gid": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]})


# ------------------------------------------
# Fixtures - GeoDataFrames
# ------------------------------------------


# ------------------------------------------
# Fixtures - COG metadata variations
# ------------------------------------------
@pytest.fixture
def cog_metadata_simple():
    """Simple COG metadata with all required fields."""
    return {
        "id": "test_cog",
        "datetime": "2024-06-01T00:00:00Z",
        "bbox": [-81.5, 44.4, -56.0, 55.2],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-81.5, 44.4],
                    [-56.0, 44.4],
                    [-56.0, 55.2],
                    [-81.5, 55.2],
                    [-81.5, 44.4],
                ]
            ],
        },
        "file_url": "file:///data/test.tif",
        "metadata": {"bands": 3, "width": 1024, "height": 1024, "crs": "EPSG:4326"},
    }


@pytest.fixture
def cog_metadata_missing_id():
    """COG metadata missing the 'id' field."""
    return {
        "bbox": [-1, -1, 1, 1],
        "file_url": "test.tif",
        # no 'id' field
    }


@pytest.fixture
def cog_metadata_missing_bbox():
    """COG metadata missing the 'bbox' field."""
    return {
        "id": "test_cog",
        "file_url": "test.tif",
        # no 'bbox' field
    }


@pytest.fixture
def cog_metadata_missing_file_url():
    """COG metadata missing the 'file_url' field."""
    return {
        "id": "test_cog",
        "bbox": [-1, -1, 1, 1],
        # no 'file_url' field
    }


@pytest.fixture
def cog_metadata_invalid_bbox():
    """COG metadata with invalid bbox (only 3 coordinates)."""
    return {
        "id": "test_cog",
        "bbox": [-1, -1, 1],  # invalid bbox
        "file_url": "test.tif",
    }


@pytest.fixture
def cog_metadata_empty():
    """Completely empty COG metadata."""
    return {}


@pytest.fixture
def cog_metadata_minimal():
    """Minimal valid COG metadata with only required fields."""
    return {
        "id": "test_cog",
        "bbox": [-1, -1, 1, 1],
        "file_url": "test.tif",
    }


@pytest.fixture
def cog_metadata_no_dates():
    """COG metadata without date fields (for default date testing)."""
    return {
        "id": "test_cog",
        "bbox": [-1, -1, 1, 1],
        "file_url": "test.tif",
    }


@pytest.fixture
def cog_metadata_with_datetime():
    """COG metadata with single datetime field instead of start/end dates."""
    return {
        "id": "test_cog_datetime",
        "datetime": "2024-06-15T12:00:00Z",
        "bbox": [-2, -2, 2, 2],
        "file_url": "test_datetime.tif",
        "metadata": {"bands": 4, "width": 512, "height": 512},
    }


@pytest.fixture
def cog_metadata_with_objects():
    """COG metadata with datetime objects instead of strings."""
    return {
        "id": "test_cog_objects",
        "datetime": dt(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        "bbox": [-3, -3, 3, 3],
        "file_url": "test_objects.tif",
        "metadata": {"bands": 1, "width": 256, "height": 256},
    }


# ------------------------------------------
# Test cases for PostGISManager.__init__()
# ------------------------------------------
@patch("gis_pipeline.modules.db.pg_utils.sqlalchemy.create_engine")
def test_init_with_connection_params_success(mock_create_engine):
    """Test PostGISManager initialization with connection parameters."""
    mock_engine = Mock()
    mock_create_engine.return_value = mock_engine

    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.fetchone.return_value = ("postgis",)
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value = mock_conn

    manager = PostGISManager(
        user="test_user",
        password="test_pass",
        host="test_host",
        port=5432,
        db="test_db",
    )

    mock_create_engine.assert_called_once_with(
        "postgresql+psycopg://test_user:test_pass@test_host:5432/test_db"
    )
    assert manager.engine == mock_engine
    assert manager.connection_info == {
        "host": "test_host",
        "port": 5432,
        "database": "test_db",
        "user": "test_user",
    }


@patch("gis_pipeline.modules.db.pg_utils.sqlalchemy.create_engine")
def test_init_connection_failure(mock_create_engine):
    """Test PostGISManager initialization with connection failure."""
    mock_create_engine.side_effect = Exception("Connection failed")

    with pytest.raises(RuntimeError, match="Error connecting to PostGIS database"):
        PostGISManager()


def test_init_no_postgis_extension(mock_engine_no_postgis):
    """Test PostGISManager initialization when PostGIS extension is missing."""
    with pytest.raises(
        RuntimeError, match="PostGIS extension is not enabled in the database"
    ):
        PostGISManager(engine=mock_engine_no_postgis)


def test_init_postgis_check_connection_error():
    """Test PostGIS extension check with connection error."""
    mock_engine = Mock()
    mock_engine.connect.side_effect = Exception("Connection error")

    with pytest.raises(RuntimeError, match="Error checking PostGIS extension"):
        PostGISManager(engine=mock_engine)


def test_init_postgis_check_variables_error():
    """Test PostGIS variables check with invalid configuration."""
    mock_engine = Mock()
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.fetchone.return_value = ("postgis",)
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value = mock_conn

    # Mock Config.POSTGRES_MAX_NAME_LENGTH to an invalid value
    with patch("gis_pipeline.modules.db.pg_utils.Config.POSTGRES_MAX_NAME_LENGTH", 5):
        with pytest.raises(
            ValueError, match="POSTGRES_MAX_NAME_LENGTH must be greater than or equal"
        ):
            PostGISManager(engine=mock_engine)


# ------------------------------------------
# Test cases for context manager
# ------------------------------------------
def test_context_manager_success(mock_engine):
    """Test PostGISManager as context manager."""
    with PostGISManager(engine=mock_engine) as manager:
        assert isinstance(manager, PostGISManager)
        assert manager.engine == mock_engine

    mock_engine.dispose.assert_called_once()


def test_context_manager_with_exception(mock_engine):
    """Test PostGISManager context manager with exception."""
    with pytest.raises(ValueError):
        with PostGISManager(engine=mock_engine):
            raise ValueError("Test exception")


# ------------------------------------------
# Test cases for close()
# ------------------------------------------
def test_close_connection(postgis_manager):
    """Test closing database connection."""
    postgis_manager.close()

    postgis_manager.engine.dispose.assert_called_once()


# ------------------------------------------
# Test cases for error handling and edge cases
# ------------------------------------------
def test_multiple_managers_isolation():
    """Test that multiple PostGISManager instances are isolated."""
    mock_engines = []
    for i in range(3):
        mock_engine = Mock()
        mock_conn = create_mock_context_manager()
        mock_result = Mock()
        mock_result.fetchone.return_value = ("postgis",)
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value = mock_conn
        mock_engines.append(mock_engine)

    managers = [PostGISManager(engine=engine) for engine in mock_engines]

    assert len(managers) == 3
    for i, manager in enumerate(managers):
        assert manager.engine == mock_engines[i]


def test_postgis_extension_check_sql_query(mock_engine):
    """Test that PostGIS extension check uses correct SQL query."""
    PostGISManager(engine=mock_engine)

    mock_conn = mock_engine.connect.return_value.__enter__.return_value
    mock_conn.execute.assert_called_once()

    call_args = mock_conn.execute.call_args[0][0]
    query_str = str(call_args)
    assert "pg_extension" in query_str.lower()
    assert "postgis" in query_str.lower()


# ------------------------------------------
# Test cases for _create_table_from_mapping()
# ------------------------------------------
def test_create_table_from_mapping_success(postgis_manager):
    """Test successful table creation from mapping."""
    table_name = "test_table"

    sqlalchemy_mapping = {
        "gid": {"sa_type": "Integer", "primary_key": True, "autoincrement": True},
        "name": {"sa_type": "Text"},
        "geometry": {"sa_type": "Geometry", "geometry_type": "POLYGON", "srid": 4326},
    }

    with patch("sqlalchemy.MetaData") as mock_metadata:
        with patch("sqlalchemy.Table") as mock_table:
            mock_table_instance = Mock()
            mock_table.return_value = mock_table_instance
            mock_metadata_instance = Mock()
            mock_metadata.return_value = mock_metadata_instance

            postgis_manager._create_table_from_mapping(
                table_name=table_name, column_mapping=sqlalchemy_mapping
            )

            mock_table.assert_called_once()
            mock_metadata_instance.create_all.assert_called_once_with(
                postgis_manager.engine, tables=[mock_table_instance]
            )


def test_create_table_from_mapping_invalid_table_name(postgis_manager):
    """Test table creation with invalid table name."""
    test_mapping = {"gid": "INTEGER PRIMARY KEY"}

    with pytest.raises(ValueError, match="Invalid table name"):
        postgis_manager._create_table_from_mapping(
            table_name="123invalid_name", column_mapping=test_mapping
        )


def test_create_table_from_mapping_unknown_sql_type(postgis_manager):
    """Test table creation with unknown SQL type."""
    test_mapping = {"gid": "UNKNOWN_TYPE"}
    table_name = "test_table"

    with pytest.raises(
        RuntimeError, match=f"Error creating table '{table_name}' from mapping"
    ):
        postgis_manager._create_table_from_mapping(
            table_name=table_name, column_mapping=test_mapping
        )


def test_create_table_from_mapping_unsupported_column_type(postgis_manager):
    """Test table creation with unsupported column type in mapping."""
    test_mapping = {"custom_col": "TEXT"}
    table_name = "test_table"

    with patch(
        "gis_pipeline.modules.db.pg_utils.SqlAlchemyTypes",
        {"TEXT": {"type": "UnsupportedType"}},
    ):
        with pytest.raises(
            RuntimeError, match=f"Error creating table '{table_name}' from mapping"
        ):
            postgis_manager._create_table_from_mapping(
                table_name=table_name, column_mapping=test_mapping
            )


def test_create_table_from_mapping_database_error(postgis_manager):
    """Test table creation error handling."""
    test_mapping = {"gid": "INTEGER PRIMARY KEY"}
    table_name = "test_table"

    with patch("sqlalchemy.MetaData") as mock_metadata:
        mock_metadata_instance = Mock()
        mock_metadata.return_value = mock_metadata_instance
        mock_metadata_instance.create_all.side_effect = Exception("Database error")

        with patch("sqlalchemy.Table"):
            with pytest.raises(
                RuntimeError, match=f"Error creating table '{table_name}' from mapping"
            ):
                postgis_manager._create_table_from_mapping(
                    table_name=table_name, column_mapping=test_mapping
                )


# ------------------------------------------
# Test cases for _build_column_mapping_from_gdf()
# ------------------------------------------
def test_build_column_mapping_infers_common_types(postgis_manager):
    """Test inference of common types from GeoDataFrame columns."""
    df = pd.DataFrame(
        {
            "geometry": [Point(0, 0), Point(1, 1)],
            "dt": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"], utc=True
            ),
            "cnt": [1, 2],
            "val": [0.1, 2.5],
            "meta": [{"a": 1}, {"b": 2}],
            "name": ["a", "b"],
        }
    )
    gdf = gpd.GeoDataFrame(df, geometry="geometry")

    mapping = postgis_manager._build_column_mapping_from_gdf(gdf)

    assert mapping["geometry"] == PostgresDataTypes.GEOMETRY_4326.value
    assert mapping["dt"] == PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value
    assert mapping["cnt"] == PostgresDataTypes.TEXT.value
    assert mapping["val"] == PostgresDataTypes.TEXT.value
    assert mapping["meta"] == PostgresDataTypes.JSONB.value
    assert mapping["name"] == PostgresDataTypes.TEXT.value


def test_build_column_mapping_object_mixed_fallback(postgis_manager):
    """Test that mixed object types fallback to TEXT."""
    df = pd.DataFrame(
        {
            "geometry": [Point(0, 0), Point(1, 1)],
            "mixed": [{"a": 1}, "string_value"],
        }
    )
    gdf = gpd.GeoDataFrame(df, geometry="geometry")

    mapping = postgis_manager._build_column_mapping_from_gdf(gdf)

    assert mapping["mixed"] == PostgresDataTypes.TEXT.value


# ------------------------------------------
# Test cases for insert_table_data()
# ------------------------------------------
def test_insert_table_data_new_table_calls_create_with_converted_mapping(
    postgis_manager, gdf_points_fixture
):
    """Test that insert_table_data inserts GeoDataFrame and creates PRIMARY KEY.

    Note: Implementation now uses to_postgis() directly (which handles table creation)
    instead of manual table creation pipeline.
    """
    table_name = "test_table"

    # Mock the database connection for PRIMARY KEY creation
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0  # No existing PRIMARY KEY
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None

            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )

            # Verify _insert_geodataframe was called (uses to_postgis internally)
            mock_insert.assert_called_once()

            # Verify the GeoDataFrame passed has gid column
            gdf_arg = mock_insert.call_args[0][0]
            assert "gid" in gdf_arg.columns, "GeoDataFrame should have gid column"

            # Verify PRIMARY KEY constraint SQL was executed
            calls = [str(call[0][0]) for call in mock_conn.execute.call_args_list]
            assert any(
                "DROP CONSTRAINT IF EXISTS" in call and "test_table_pkey" in call
                for call in calls
            ), "Should drop existing PRIMARY KEY constraint (idempotent)"
            assert any(
                "ALTER COLUMN gid SET NOT NULL" in call for call in calls
            ), "Should set gid to NOT NULL"
            assert any(
                "ADD CONSTRAINT" in call
                and "test_table_pkey" in call
                and "PRIMARY KEY (gid)" in call
                for call in calls
            ), "Should add PRIMARY KEY constraint on gid column"


def test_insert_table_data_existing_table_success(postgis_manager, gdf_points_fixture):
    """Test inserting GeoDataFrame into existing table.

    Note: Implementation uses to_postgis() with if_exists parameter, no inspect needed.
    """
    table_name = "existing_table"

    # Mock the database connection for PRIMARY KEY creation
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None

            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )

            mock_insert.assert_called_once()


def test_insert_table_data_database_error(postgis_manager, gdf_points_fixture):
    """Test insert_table_data with database error.

    Note: Patch _insert_geodataframe instead of to_postgis on the fixture, because
    insert_table_data works on a copy (gdf.copy()), so a patch on the original object
    would not be seen by the copy.
    """
    table_name = "test_table"

    with patch.object(
        postgis_manager,
        "_insert_geodataframe",
        side_effect=Exception("DB Error"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Error inserting GeoDataFrame/DataFrame into PostGIS",
        ):
            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )


def test_insert_table_data_table_creation_flow(postgis_manager, gdf_points_fixture):
    """Test complete flow of table creation and data insertion.

    Note: Implementation now uses to_postgis() for table creation with automatic
    PostGIS metadata handling, then adds PRIMARY KEY constraint via ALTER TABLE.
    """
    table_name = "new_table"

    # Mock the database connection for PRIMARY KEY creation
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0  # No existing PRIMARY KEY
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None

            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )

            # Verify _insert_geodataframe was called (to_postgis handles table creation)
            mock_insert.assert_called_once()

            # Verify GeoDataFrame has gid column
            gdf_arg = mock_insert.call_args[0][0]
            assert "gid" in gdf_arg.columns, "GeoDataFrame should have gid column"

            # Verify PRIMARY KEY SQL was executed
            calls = [str(call[0][0]) for call in mock_conn.execute.call_args_list]
            assert any(
                "DROP CONSTRAINT IF EXISTS" in call for call in calls
            ), "Should drop existing PRIMARY KEY (idempotent)"
            assert any(
                "ALTER COLUMN gid SET NOT NULL" in call for call in calls
            ), "Should set gid to NOT NULL"
            assert any(
                "ADD CONSTRAINT" in call and "PRIMARY KEY (gid)" in call
                for call in calls
            ), "Should add PRIMARY KEY constraint"


def test_insert_table_data_insert_failure(postgis_manager, gdf_points_fixture):
    """Test insert_table_data when _insert_geodataframe fails.

    Note: to_postgis() handles table existence internally.
    """
    table_name = "test_table"

    with patch.object(
        postgis_manager,
        "_insert_geodataframe",
        side_effect=Exception("Insert failed"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Error inserting GeoDataFrame/DataFrame into PostGIS",
        ):
            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )


def test_insert_table_data_create_table_error(postgis_manager, gdf_points_fixture):
    """Test insert_table_data when table creation fails.

    Note: to_postgis() handles table creation internally.
    """
    table_name = "test_table"

    with patch.object(
        postgis_manager,
        "_insert_geodataframe",
        side_effect=Exception("Table creation failed"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Error inserting GeoDataFrame/DataFrame into PostGIS",
        ):
            postgis_manager.insert_table_data(
                gdf=gdf_points_fixture, table_name=table_name
            )


def test_insert_table_data_valid_table_names(postgis_manager, gdf_points_fixture):
    """Test insert_table_data with various valid table names.

    Note: Implementation uses to_postgis() directly, no inspect needed.
    """
    valid_table_names = [
        "simple_table",
        "table_with_underscores",
        "table123",
        "TableMixedCase",
    ]

    # Mock the database connection for PRIMARY KEY creation
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None

            for table_name in valid_table_names:
                mock_insert.reset_mock()

                postgis_manager.insert_table_data(
                    gdf=gdf_points_fixture, table_name=table_name
                )

                mock_insert.assert_called_once()


def test_insert_table_data_empty_table_name(postgis_manager, gdf_points_fixture):
    """Test insert_table_data with empty table name."""
    with pytest.raises(
        RuntimeError,
        match="Error inserting GeoDataFrame/DataFrame into PostGIS",
    ):
        postgis_manager.insert_table_data(gdf=gdf_points_fixture, table_name="")


def test_insert_table_data_none_table_name(postgis_manager, gdf_points_fixture):
    """Test insert_table_data with None table name."""
    with pytest.raises(
        RuntimeError,
        match="Error inserting GeoDataFrame/DataFrame into PostGIS",
    ):
        postgis_manager.insert_table_data(gdf=gdf_points_fixture, table_name=None)


def test_insert_table_data_gid_offset_shifts_gids(postgis_manager):
    """gid_offset adds to each GID before insertion — used for chunk uniqueness."""
    gdf = gpd.GeoDataFrame(
        {"gid": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]},
        crs="EPSG:4326",
    )
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None
            postgis_manager.insert_table_data(gdf=gdf, table_name="t", gid_offset=1000)

    gdf_arg = mock_insert.call_args[0][0]
    assert gdf_arg["gid"].tolist() == [1001, 1002]


def test_insert_table_data_gid_offset_zero_no_shift(postgis_manager):
    """gid_offset=0 must leave GIDs unchanged."""
    gdf = gpd.GeoDataFrame(
        {"gid": [5, 10], "geometry": [Point(0, 0), Point(1, 1)]},
        crs="EPSG:4326",
    )
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None
            postgis_manager.insert_table_data(gdf=gdf, table_name="t", gid_offset=0)

    gdf_arg = mock_insert.call_args[0][0]
    assert gdf_arg["gid"].tolist() == [5, 10]


def test_insert_table_data_default_gid_offset_no_shift(postgis_manager):
    """Default gid_offset (0) must leave GIDs unchanged."""
    gdf = gpd.GeoDataFrame(
        {"gid": [100, 200], "geometry": [Point(0, 0), Point(1, 1)]},
        crs="EPSG:4326",
    )
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            mock_insert.return_value = None
            postgis_manager.insert_table_data(gdf=gdf, table_name="t")

    gdf_arg = mock_insert.call_args[0][0]
    assert gdf_arg["gid"].tolist() == [100, 200]


# ------------------------------------------
# Test cases for insert_cog_metadata()
# ------------------------------------------
def test_insert_cog_metadata_success(postgis_manager, cog_metadata_simple):
    """Test successful COG metadata insertion."""
    table_name = "test_cogs"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_simple, table_name=table_name
        )
        postgis_manager.engine.begin.assert_called_once()


def test_insert_cog_metadata_new_table(postgis_manager, cog_metadata_simple):
    """Test COG metadata insertion with new table creation."""
    table_name = "new_cogs"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = False

    expected_sqlalchemy = {"id": {"type": "Text"}}  # controlled return for conversion

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        with patch.object(
            postgis_manager,
            "_convert_pg_mapping_to_sqlalchemy",
            return_value=expected_sqlalchemy,
        ) as mock_convert:
            with patch.object(
                postgis_manager, "_create_table_from_mapping"
            ) as mock_create:
                postgis_manager.insert_cog_metadata(
                    metadata=cog_metadata_simple, table_name=table_name
                )

                mock_convert.assert_called_once_with(
                    {col.name.lower(): col.value for col in RasterStacColumns}
                )
                mock_create.assert_called_once_with(
                    table_name=table_name,
                    column_mapping=expected_sqlalchemy,
                    schema="public",
                )
                mock_inspector.has_table.assert_called_once_with(
                    table_name, schema="public"
                )


def test_insert_cog_metadata_new_table_real_column_mapping(
    postgis_manager, cog_metadata_simple
):
    """
    Test that new-table creation converts RasterStacColumns into a real dict
    before handing it to the (unmocked) Postgres->SQLAlchemy converter, instead
    of passing the raw Enum class through (which crashes on `.items()`).
    """
    table_name = "new_cogs"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = False

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        with patch.object(
            postgis_manager, "_create_table_from_mapping"
        ) as mock_create:
            postgis_manager.insert_cog_metadata(
                metadata=cog_metadata_simple, table_name=table_name
            )

    mock_create.assert_called_once()
    _, kwargs = mock_create.call_args
    assert kwargs["table_name"] == table_name
    assert kwargs["schema"] == "public"
    assert set(kwargs["column_mapping"]) == {
        "gid",
        "datetime",
        "bbox",
        "geometry",
        "file_url",
        "metadata",
    }


def test_ensure_cog_table_checks_existence_in_public_schema(
    postgis_manager, cog_metadata_simple
):
    """
    Test that the existence check for the cogs table is schema-qualified to
    'public'. An unqualified has_table() would resolve against this database's
    current_schema() — which is 'pgstac' when pgSTAC's search_path is active —
    and incorrectly report the table missing forever, since the app role can
    never create anything there.
    """
    table_name = "cogs"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True  # table already exists in public

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        with patch.object(postgis_manager, "_create_table_from_mapping") as mock_create:
            postgis_manager.insert_cog_metadata(
                metadata=cog_metadata_simple, table_name=table_name
            )

    mock_inspector.has_table.assert_called_once_with(table_name, schema="public")
    mock_create.assert_not_called()


def test_insert_cog_metadata_validation_error_is_not_rewritten(postgis_manager):
    """A missing required field surfaces as its own ValueError, not a generic wrap.

    The other missing-field tests below fail earlier, inside _ensure_cog_table on
    the mocked engine, so they never reach validation. Stubbing it out is what
    exercises _validate_cog_metadata.
    """
    with patch.object(postgis_manager, "_ensure_cog_table", return_value=None):
        with pytest.raises(ValueError, match="Missing required field 'bbox'"):
            postgis_manager.insert_cog_metadata(
                metadata={"id": 1, "file_url": "http://example.com/a.tif"},
                table_name="cogs",
            )


def test_insert_table_data_rejects_non_dataframe(postgis_manager):
    """A non-DataFrame input raises ValueError rather than a generic RuntimeError."""
    with pytest.raises(ValueError, match="Input must be a GeoDataFrame or DataFrame"):
        postgis_manager.insert_table_data(gdf="not a dataframe", table_name="t")


def test_insert_cog_metadata_missing_id(postgis_manager, cog_metadata_missing_id):
    """Test COG metadata insertion with missing id field."""
    table_name = "test_table"

    with pytest.raises(RuntimeError, match="Error inserting COG metadata into PostGIS"):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_missing_id, table_name=table_name
        )


def test_insert_cog_metadata_missing_bbox(postgis_manager, cog_metadata_missing_bbox):
    """Test COG metadata insertion with missing bbox field."""
    with pytest.raises(RuntimeError, match="Error inserting COG metadata into PostGIS"):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_missing_bbox, table_name="test_table"
        )


def test_insert_cog_metadata_missing_file_url(
    postgis_manager, cog_metadata_missing_file_url
):
    """Test COG metadata insertion with missing file_url field."""
    with pytest.raises(RuntimeError, match="Error inserting COG metadata into PostGIS"):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_missing_file_url, table_name="test_table"
        )


def test_insert_cog_metadata_invalid_bbox(postgis_manager, cog_metadata_invalid_bbox):
    """Test COG metadata insertion with invalid bbox."""
    with pytest.raises(RuntimeError, match="Error inserting COG metadata into PostGIS"):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_invalid_bbox, table_name="test_table"
        )


def test_insert_cog_metadata_empty_metadata(postgis_manager, cog_metadata_empty):
    """Test COG metadata insertion with completely empty metadata."""
    with pytest.raises(RuntimeError, match="Error inserting COG metadata into PostGIS"):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_empty, table_name="test_table"
        )


def test_insert_cog_metadata_default_dates(postgis_manager, cog_metadata_no_dates):
    """Test COG metadata insertion with default date handling."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_no_dates, table_name=table_name
        )
        postgis_manager.engine.begin.assert_called_once()


def test_insert_cog_metadata_minimal_valid(postgis_manager, cog_metadata_minimal):
    """Test COG metadata insertion with minimal valid metadata."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_minimal, table_name=table_name
        )
        postgis_manager.engine.begin.assert_called_once()


def test_insert_cog_metadata_with_datetime_object(
    postgis_manager, cog_metadata_with_objects
):
    """Test COG metadata insertion with datetime objects."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_with_objects, table_name=table_name
        )
        postgis_manager.engine.begin.assert_called_once()


def test_insert_cog_metadata_with_single_datetime(
    postgis_manager, cog_metadata_with_datetime
):
    """Test COG metadata insertion with single datetime field."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        postgis_manager.insert_cog_metadata(
            metadata=cog_metadata_with_datetime, table_name=table_name
        )
        postgis_manager.engine.begin.assert_called_once()


def test_insert_cog_metadata_database_error(postgis_manager, cog_metadata_minimal):
    """Test COG metadata insertion with database error."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    mock_conn = create_mock_context_manager()
    mock_conn.execute.side_effect = Exception("DB Error")

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
            with pytest.raises(
                RuntimeError,
                match="Error inserting COG metadata into PostGIS",
            ):
                postgis_manager.insert_cog_metadata(
                    metadata=cog_metadata_minimal, table_name=table_name
                )


def test_insert_cog_metadata_various_bbox_formats(postgis_manager):
    """Test COG metadata insertion with various valid bbox formats."""
    bbox_test_cases = [
        {"id": "test1", "bbox": [-1.0, -1.0, 1.0, 1.0], "file_url": "test1.tif"},
        {"id": "test2", "bbox": (-2, -2, 2, 2), "file_url": "test2.tif"},
        {
            "id": "test3",
            "bbox": [-180, -90, 180, 90],
            "file_url": "test3.tif",
        },  # World extent
    ]
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        for metadata in bbox_test_cases:
            postgis_manager.insert_cog_metadata(
                metadata=metadata, table_name=table_name
            )

        assert postgis_manager.engine.begin.call_count == len(bbox_test_cases)


def test_insert_cog_metadata_edge_case_values(postgis_manager):
    """Test COG metadata insertion with edge case values."""
    edge_cases = [
        {"id": "test_cog-2024.v1", "bbox": [0, 0, 1, 1], "file_url": "special.tif"},
        {
            "id": "tiny_bbox",
            "bbox": [0.0001, 0.0001, 0.0002, 0.0002],
            "file_url": "tiny.tif",
        },
        {
            "id": "http_cog",
            "bbox": [-1, -1, 1, 1],
            "file_url": "https://example.com/file.tif",
        },
    ]
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        return_value=mock_inspector,
    ):
        for metadata in edge_cases:
            postgis_manager.insert_cog_metadata(
                metadata=metadata, table_name=table_name
            )

        assert postgis_manager.engine.begin.call_count == len(edge_cases)


# ------------------------------------------
# Test cases for read_data()
# ------------------------------------------
def test_read_data_success(postgis_manager, mock_gdf):
    """Test successful data reading."""
    table_name = "test_table"

    with patch("sqlalchemy.MetaData"):
        with patch("sqlalchemy.Table"):
            with patch("sqlalchemy.select"):
                with patch("geopandas.read_postgis", return_value=mock_gdf):
                    result = postgis_manager.read_data(table_name=table_name)

                    assert isinstance(result, gpd.GeoDataFrame)
                    assert len(result) == 2


def test_read_data_nonexistent_table(postgis_manager):
    """Test reading data from nonexistent table."""
    table_name = "nonexistent_table"

    with patch("sqlalchemy.MetaData"):
        with patch("sqlalchemy.Table"):
            with patch("sqlalchemy.select"):
                with patch(
                    "geopandas.read_postgis", side_effect=Exception("Table not found")
                ):
                    with pytest.raises(
                        RuntimeError,
                        match="Error reading data from PostGIS",
                    ):
                        postgis_manager.read_data(table_name=table_name)


def test_read_data_with_limit(postgis_manager, mock_gdf):
    """Test reading data with limit."""
    table_name = "test_table"

    with patch("sqlalchemy.MetaData"):
        with patch("sqlalchemy.Table"):
            with patch("sqlalchemy.select"):
                with patch("geopandas.read_postgis", return_value=mock_gdf.head(1)):
                    result = postgis_manager.read_data(table_name=table_name)

                    assert isinstance(result, gpd.GeoDataFrame)
                    assert len(result) == 1


# ------------------------------------------
# Test cases for GID column handling
# ------------------------------------------
@pytest.fixture
def gdf_with_custom_ids():
    """GeoDataFrame with custom ID values."""
    data = {
        "id": [100, 200, 300, 400, 500],
        "name": ["Point A", "Point B", "Point C", "Point D", "Point E"],
        "value": [10, 20, 30, 40, 50],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2), Point(3, 3), Point(4, 4)],
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


@pytest.fixture
def gdf_with_gid_column():
    """GeoDataFrame with existing gid column."""
    data = {
        "gid": [100, 200, 300, 400, 500],
        "name": ["Point A", "Point B", "Point C", "Point D", "Point E"],
        "geometry": [Point(i, i) for i in range(5)],
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


@pytest.fixture
def gdf_without_gid():
    """GeoDataFrame without any ID column."""
    data = {
        "name": ["Point A", "Point B", "Point C"],
        "value": [10, 20, 30],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


def test_validate_gid_column_valid(postgis_manager, gdf_with_gid_column):
    """Test validation passes with valid gid column."""
    # Should not raise any exception
    postgis_manager._validate_gid_column(gdf_with_gid_column)


def test_validate_gid_column_no_gid(postgis_manager, gdf_without_gid):
    """Test validation fails when no gid column exists."""
    with pytest.raises(ValueError, match="GID column is missing"):
        postgis_manager._validate_gid_column(gdf_without_gid)


def test_validate_gid_column_with_duplicates(postgis_manager, gdf_with_gid_column):
    """Test validation fails with duplicate gid values."""
    gdf_duplicates = gdf_with_gid_column.copy()
    gdf_duplicates.loc[2, "gid"] = 100  # Create duplicate

    with pytest.raises(ValueError, match="duplicate values"):
        postgis_manager._validate_gid_column(gdf_duplicates)


def test_validate_gid_column_with_nulls(postgis_manager, gdf_with_gid_column):
    """Test validation fails with null gid values."""
    gdf_nulls = gdf_with_gid_column.copy()
    gdf_nulls.loc[1, "gid"] = None

    with pytest.raises(ValueError, match="null value"):
        postgis_manager._validate_gid_column(gdf_nulls)


def test_validate_gid_column_with_negative_values(postgis_manager, gdf_with_gid_column):
    """Test validation fails with negative gid values."""
    gdf_negative = gdf_with_gid_column.copy()
    gdf_negative.loc[0, "gid"] = -1

    with pytest.raises(ValueError, match="negative values"):
        postgis_manager._validate_gid_column(gdf_negative)


def test_validate_gid_column_with_non_integer(postgis_manager):
    """Test validation fails with non-integer gid values."""
    data = {"gid": ["a", "b", "c"], "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]}
    gdf_invalid = gpd.GeoDataFrame(data, crs="EPSG:4326")

    with pytest.raises(ValueError, match="cannot be converted to integers"):
        postgis_manager._validate_gid_column(gdf_invalid)


def test_ensure_gid_column_preserves_existing(postgis_manager, gdf_with_gid_column):
    """Test that existing gid column is preserved."""
    result = postgis_manager._ensure_gid_column(gdf_with_gid_column.copy())

    assert "gid" in result.columns
    assert result["gid"].tolist() == [100, 200, 300, 400, 500]


def test_ensure_gid_column_generates_sequential(postgis_manager, gdf_without_gid):
    """Test that sequential gid is generated when no gid exists."""
    result = postgis_manager._ensure_gid_column(gdf_without_gid.copy())

    assert "gid" in result.columns
    assert result["gid"].tolist() == [1, 2, 3]


def test_ensure_gid_column_uses_index(postgis_manager):
    """Test that DataFrame index is used as gid when appropriate."""
    data = {"name": ["Point A", "Point B"], "geometry": [Point(0, 0), Point(1, 1)]}
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")

    result = postgis_manager._ensure_gid_column(gdf)

    assert "gid" in result.columns
    assert result["gid"].tolist() == [1, 2]  # Index + 1


def test_ensure_gid_column_converts_invalid_to_sequential(postgis_manager):
    """Test that invalid gid values are replaced with sequential integers."""
    data = {
        "gid": ["invalid", None, "bad"],
        "name": ["Point A", "Point B", "Point C"],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
    }
    gdf_invalid = gpd.GeoDataFrame(data, crs="EPSG:4326")

    result = postgis_manager._ensure_gid_column(gdf_invalid)

    assert "gid" in result.columns
    assert result["gid"].tolist() == [1, 2, 3]


def test_ensure_gid_column_converts_float_to_int(postgis_manager):
    """Test that float gid values are converted to integers."""
    data = {
        "gid": [1.0, 2.0, 3.0],
        "name": ["Point A", "Point B", "Point C"],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
    }
    gdf_float = gpd.GeoDataFrame(data, crs="EPSG:4326")

    result = postgis_manager._ensure_gid_column(gdf_float)

    assert "gid" in result.columns
    assert result["gid"].tolist() == [1, 2, 3]
    assert pd.api.types.is_integer_dtype(result["gid"])


def test_build_column_mapping_with_existing_gid(postgis_manager, gdf_with_gid_column):
    """Test that column mapping detects existing gid data."""
    mapping = postgis_manager._build_column_mapping_from_gdf(gdf_with_gid_column)

    assert "gid" in mapping
    # Should use default VectorPostGISColumns.GID configuration
    # (The autoincrement disabling happens in _create_sqlalchemy_column based on presence of data)
    assert mapping["gid"] == PostgresDataTypes.INTEGER_PRIMARY_KEY.value


def test_build_column_mapping_without_gid(postgis_manager, gdf_without_gid):
    """Test that column mapping uses default gid configuration when no gid exists."""
    mapping = postgis_manager._build_column_mapping_from_gdf(gdf_without_gid)

    assert "gid" in mapping
    # Should use default VectorPostGISColumns configuration


def test_insert_geodataframe_preserves_gid(postgis_manager, gdf_with_gid_column):
    """Test that _insert_geodataframe preserves gid values."""
    table_name = "test_gid_preservation"

    with patch("geopandas.GeoDataFrame.to_postgis") as mock_to_postgis:
        # _insert_geodataframe expects gdf to already have valid gid
        postgis_manager._insert_geodataframe(gdf_with_gid_column, table_name, "replace")

        # Verify to_postgis was called with index=False
        mock_to_postgis.assert_called_once()
        call_kwargs = mock_to_postgis.call_args[1]
        assert call_kwargs["index"] is False


def test_insert_table_data_with_custom_gid(postgis_manager, gdf_with_gid_column):
    """Test that insert_table_data preserves custom gid values."""
    table_name = "test_custom_gid"

    with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
        with patch.object(postgis_manager, "_add_primary_key_constraint") as mock_pk:
            postgis_manager.insert_table_data(gdf_with_gid_column, table_name)

            # Verify insertion was called
            assert mock_insert.called

            # Verify the GeoDataFrame passed has gid column with custom values
            gdf_arg = mock_insert.call_args[0][0]
            assert "gid" in gdf_arg.columns
            assert gdf_arg["gid"].tolist() == [100, 200, 300, 400, 500]

            # Verify PRIMARY KEY constraint creation was attempted
            assert mock_pk.called


def test_primary_key_creation_on_insert(postgis_manager):
    """Test that PRIMARY KEY constraint is created automatically on gid column."""
    # Create a simple test GeoDataFrame
    data = {
        "name": ["Feature 1", "Feature 2", "Feature 3"],
        "value": [10, 20, 30],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
    }
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    table_name = "test_pk_constraint"

    # Mock the connection and execution
    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0  # No existing PRIMARY KEY
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe") as mock_insert:
            postgis_manager.insert_table_data(
                gdf, table_name, override_method="replace"
            )

            # Verify _insert_geodataframe was called
            assert mock_insert.called

            # Verify PRIMARY KEY SQL statements were executed
            calls = [str(call[0][0]) for call in mock_conn.execute.call_args_list]

            # Should have: DROP CONSTRAINT, SET NOT NULL, ADD PRIMARY KEY
            assert any(
                "DROP CONSTRAINT" in call and "test_pk_constraint_pkey" in call
                for call in calls
            ), "Should drop existing PRIMARY KEY constraint"
            assert any(
                "ALTER COLUMN gid SET NOT NULL" in call for call in calls
            ), "Should set gid to NOT NULL"
            assert any(
                "ADD CONSTRAINT" in call
                and "test_pk_constraint_pkey" in call
                and "PRIMARY KEY (gid)" in call
                for call in calls
            ), "Should add PRIMARY KEY constraint on gid"


def test_primary_key_uses_correct_constraint_name(postgis_manager):
    """Test that PRIMARY KEY constraint uses correct naming pattern."""
    data = {"geometry": [Point(0, 0), Point(1, 1)]}
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    table_name = "my_test_table"

    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe"):
            postgis_manager.insert_table_data(gdf, table_name)

            calls = [str(call[0][0]) for call in mock_conn.execute.call_args_list]

            # Verify constraint name follows pattern: {table_name}_pkey
            expected_constraint = "my_test_table_pkey"
            assert any(
                expected_constraint in call for call in calls
            ), f"PRIMARY KEY constraint should be named '{expected_constraint}'"


def test_primary_key_handles_schema_qualified_table(postgis_manager):
    """Test that PRIMARY KEY creation works with schema-qualified table names."""
    data = {"geometry": [Point(0, 0)]}
    gdf = gpd.GeoDataFrame(data, crs="EPSG:4326")
    table_name = "public.schema_test_table"

    mock_conn = create_mock_context_manager()
    mock_result = Mock()
    mock_result.scalar.return_value = 0
    mock_conn.execute.return_value = mock_result

    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        with patch.object(postgis_manager, "_insert_geodataframe"):
            postgis_manager.insert_table_data(gdf, table_name)

            calls = [str(call[0][0]) for call in mock_conn.execute.call_args_list]

            # Should use qualified table name in SQL
            assert any(
                '"public"."schema_test_table"' in call for call in calls
            ), "Should use qualified table name in SQL statements"

            # Should use correct constraint name (table only, no schema)
            expected_constraint = "schema_test_table_pkey"
            assert any(
                expected_constraint in call for call in calls
            ), f"PRIMARY KEY constraint should be named '{expected_constraint}'"


@pytest.mark.unit
class TestRepairNullGidsEdgeCases:
    def test_all_nulls_generates_sequential_from_one(self) -> None:
        """When all GIDs are NaN, sequential IDs starting from 1 are assigned."""
        from gis_pipeline.modules.db.pg_utils import GIDValidator

        series = pd.Series([float("nan"), float("nan"), float("nan")])
        result = GIDValidator._repair_null_gids(series)
        assert len(result) == 3
        assert result.nunique() == 3
        assert set(result.tolist()) == {1, 2, 3}

    def test_partial_nulls_avoids_existing_ids(self) -> None:
        """Generated IDs must not conflict with pre-existing valid IDs."""
        from gis_pipeline.modules.db.pg_utils import GIDValidator

        series = pd.Series([1.0, float("nan"), 3.0])
        result = GIDValidator._repair_null_gids(series)
        assert result.nunique() == 3
        assert 1 in result.tolist()
        assert 3 in result.tolist()
        # New ID must not be 1 or 3
        new_id = [v for v in result.tolist() if v not in (1, 3)][0]
        assert new_id not in (1, 3)


@pytest.mark.unit
class TestBuildColumnMappingEdgeCases:
    def test_column_above_70pct_dicts_inferred_as_jsonb(self) -> None:
        from gis_pipeline.modules.db.pg_utils import TypeMapper

        values = [{"k": "v"}] * 8 + ["plain string"] * 2
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)] * 10, "data": values}, crs="EPSG:4326"
        )
        mapping = TypeMapper._build_column_mapping_from_gdf(gdf)
        from gis_pipeline.services.mapping import PostgresDataTypes

        assert mapping.get("data") == PostgresDataTypes.JSONB.value

    def test_column_below_70pct_dicts_inferred_as_text(self) -> None:
        from gis_pipeline.modules.db.pg_utils import TypeMapper

        values = [{"k": "v"}] * 5 + ["plain string"] * 5
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)] * 10, "data": values}, crs="EPSG:4326"
        )
        mapping = TypeMapper._build_column_mapping_from_gdf(gdf)
        from gis_pipeline.services.mapping import PostgresDataTypes

        assert mapping.get("data") == PostgresDataTypes.TEXT.value

    def test_datetime_column_inferred_as_timestamp_with_tz(self) -> None:
        from gis_pipeline.modules.db.pg_utils import TypeMapper

        times = pd.to_datetime(["2024-01-01", "2024-01-02"])
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0), Point(1, 1)], "ts": times}, crs="EPSG:4326"
        )
        mapping = TypeMapper._build_column_mapping_from_gdf(gdf)
        from gis_pipeline.services.mapping import PostgresDataTypes

        assert mapping.get("ts") == PostgresDataTypes.TIMESTAMP_WITH_TIMEZONE.value


@pytest.mark.unit
class TestNormalizeCogMetadataEdgeCases:
    def test_plain_dict_returned_as_dict(self) -> None:
        from gis_pipeline.modules.db.pg_utils import DataInserter

        meta = {
            "id": "item1",
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "file_url": "/path/to/file",
        }
        result = DataInserter._normalize_cog_metadata(meta)
        assert isinstance(result, dict)
        assert result["id"] == "item1"

    def test_bbox_tuple_converted_to_list_of_floats(self) -> None:
        from gis_pipeline.modules.db.pg_utils import DataInserter

        meta = {"id": "item1", "bbox": (1, 2, 3, 4), "file_url": "/path"}
        result = DataInserter._normalize_cog_metadata(meta)
        assert isinstance(result["bbox"], list)
        assert result["bbox"] == [1.0, 2.0, 3.0, 4.0]

    def test_non_primitive_id_coerced_to_string(self) -> None:
        from gis_pipeline.modules.db.pg_utils import DataInserter

        meta = {"id": 42, "bbox": [0.0, 0.0, 1.0, 1.0], "file_url": "/path"}
        result = DataInserter._normalize_cog_metadata(meta)
        # id=42 (int) is already primitive; no coercion needed
        assert result["id"] in (42, "42")


# ------------------------------------------
# Test cases for apply_foreign_keys()
# ------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
def test_apply_foreign_keys_executes_unique_and_fk_sql(postgis_manager):
    """apply_foreign_keys runs UNIQUE then FK NOT VALID SQL for each definition."""
    fk_defs = [
        {
            "from_table": "couverture_pps",
            "from_col": "code_polygone",
            "to_table": "couverture_pedologique",
            "to_col": "code_polygone",
        }
    ]
    mock_conn = create_mock_context_manager()
    with patch.object(postgis_manager.engine, "begin", return_value=mock_conn):
        postgis_manager.apply_foreign_keys(fk_defs)

    calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
    assert any(
        "UNIQUE" in c and "code_polygone" in c for c in calls
    ), "Expected a UNIQUE constraint SQL call"
    assert any(
        "FOREIGN KEY" in c and "NOT VALID" in c for c in calls
    ), "Expected a FK NOT VALID SQL call"


@pytest.mark.unit
@pytest.mark.mocked
def test_apply_foreign_keys_skips_duplicate_unique_constraint(postgis_manager):
    """Duplicate UNIQUE constraint (pgcode 42710) is silently skipped, FK is still attempted."""
    import sqlalchemy.exc

    fk_defs = [
        {
            "from_table": "child",
            "from_col": "code",
            "to_table": "parent",
            "to_col": "code",
        }
    ]

    dup_error = sqlalchemy.exc.ProgrammingError("stmt", {}, Exception())
    dup_error.orig = type("Orig", (), {"pgcode": "42710"})()

    call_count = 0

    def begin_side_effect():
        nonlocal call_count
        call_count += 1
        mock_conn = create_mock_context_manager()
        if call_count == 1:
            mock_conn.execute.side_effect = dup_error
        return mock_conn

    with patch.object(postgis_manager.engine, "begin", side_effect=begin_side_effect):
        postgis_manager.apply_foreign_keys(fk_defs)

    # Two begin() calls: one for UNIQUE (raises dup), one for FK
    assert call_count == 2


@pytest.mark.unit
@pytest.mark.mocked
def test_apply_foreign_keys_skips_fk_on_unique_failure(postgis_manager):
    """Non-42710 error on UNIQUE step causes FK to be skipped for that definition."""
    import sqlalchemy.exc

    fk_defs = [
        {
            "from_table": "child",
            "from_col": "ref_col",
            "to_table": "parent",
            "to_col": "ref_col",
        }
    ]

    hard_error = sqlalchemy.exc.ProgrammingError("stmt", {}, Exception())
    hard_error.orig = type("Orig", (), {"pgcode": "42P01"})()  # undefined table

    mock_conn = create_mock_context_manager()
    mock_conn.execute.side_effect = hard_error

    with patch.object(
        postgis_manager.engine, "begin", return_value=mock_conn
    ) as mock_begin:
        postgis_manager.apply_foreign_keys(fk_defs)
        # Only one begin() call: UNIQUE fails with hard error → FK is skipped
        assert mock_begin.call_count == 1


@pytest.mark.unit
@pytest.mark.mocked
def test_apply_foreign_keys_empty_list_is_noop(postgis_manager):
    """Empty fk_defs list results in no database calls."""
    postgis_manager.apply_foreign_keys([])

    postgis_manager.engine.begin.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_apply_foreign_keys_multiple_definitions(postgis_manager):
    """Each FK definition produces its own UNIQUE + FK SQL pair."""
    fk_defs = [
        {
            "from_table": "t1",
            "from_col": "col_a",
            "to_table": "ref1",
            "to_col": "col_a",
        },
        {
            "from_table": "t2",
            "from_col": "col_b",
            "to_table": "ref2",
            "to_col": "col_b",
        },
    ]
    all_calls: list[str] = []

    def begin_side_effect():
        mock_conn = create_mock_context_manager()
        mock_conn.execute.side_effect = lambda sql: all_calls.append(str(sql))
        return mock_conn

    with patch.object(
        postgis_manager.engine, "begin", side_effect=begin_side_effect
    ) as mock_begin:
        postgis_manager.apply_foreign_keys(fk_defs)
        # 2 definitions × 2 SQL statements each = 4 total engine.begin() calls
        assert mock_begin.call_count == 4

    unique_calls = [c for c in all_calls if "UNIQUE" in c]
    fk_calls = [c for c in all_calls if "FOREIGN KEY" in c]
    assert len(unique_calls) == 2
    assert len(fk_calls) == 2


# ------------------------------------------
# Test cases for _drop_incoming_fk_constraints and UniqueViolation handling
# ------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
def test_drop_incoming_fk_constraints_called_on_replace(postgis_manager):
    """_drop_incoming_fk_constraints is invoked when override_method='replace', not 'append'."""
    import geopandas as gpd
    from gis_pipeline.modules.db.pg_utils import DataInserter
    from shapely.geometry import Point

    inserter = DataInserter(postgis_manager.engine)
    gdf = gpd.GeoDataFrame({"gid": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")

    with patch.object(inserter, "_drop_incoming_fk_constraints") as mock_drop:
        mock_conn = create_mock_context_manager()
        with patch.object(inserter.engine, "begin", return_value=mock_conn):
            with patch("geopandas.GeoDataFrame.to_postgis"):
                inserter._insert_geodataframe(gdf, "some_table", "replace")
                mock_drop.assert_called_once_with("some_table")

    with patch.object(inserter, "_drop_incoming_fk_constraints") as mock_drop:
        mock_conn = create_mock_context_manager()
        with patch.object(inserter.engine, "begin", return_value=mock_conn):
            with patch("geopandas.GeoDataFrame.to_postgis"):
                inserter._insert_geodataframe(gdf, "some_table", "append")
                mock_drop.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_add_fk_constraints_skips_unique_violation(postgis_manager):
    """UniqueViolation (pgcode 23505) on the UNIQUE step is logged and skipped, not raised."""
    import sqlalchemy.exc

    fk_defs = [
        {
            "from_table": "child",
            "from_col": "ref_col",
            "to_table": "parent",
            "to_col": "ref_col",
        }
    ]

    integrity_error = sqlalchemy.exc.IntegrityError("stmt", {}, Exception())
    integrity_error.orig = type("Orig", (), {"pgcode": "23505"})()

    call_count = 0

    def begin_side_effect():
        nonlocal call_count
        call_count += 1
        mock_conn = create_mock_context_manager()
        if call_count == 1:
            mock_conn.execute.side_effect = integrity_error
        return mock_conn

    with patch.object(postgis_manager.engine, "begin", side_effect=begin_side_effect):
        # Must not raise; only one begin() call (the UNIQUE step that fails)
        postgis_manager.apply_foreign_keys(fk_defs)
    assert call_count == 1


# ------------------------------------------
# PostGISManager.stamp_gee_flags
# ------------------------------------------


@pytest.mark.unit
class TestStampGeeFlags:
    def test_three_sql_statements_when_ids_provided(self, postgis_manager, mock_engine):
        """ADD COLUMN + reset FALSE + set TRUE = 3 execute() calls."""
        mock_conn = mock_engine.begin.return_value
        mock_conn.execute.reset_mock()
        postgis_manager.stamp_gee_flags("som_field_boundaries", {1, 42})
        assert mock_conn.execute.call_count == 3

    def test_two_sql_statements_when_ids_empty(self, postgis_manager, mock_engine):
        """ADD COLUMN + reset FALSE only (no TRUE update) when set is empty."""
        mock_conn = mock_engine.begin.return_value
        mock_conn.execute.reset_mock()
        postgis_manager.stamp_gee_flags("som_field_boundaries", set())
        assert mock_conn.execute.call_count == 2

    def test_db_error_raises_runtime_error(self, postgis_manager, mock_engine):
        """A PostGIS error must surface as RuntimeError so the pipeline notices."""
        mock_engine.begin.side_effect = sqlalchemy.exc.SQLAlchemyError("DB gone")
        with pytest.raises(RuntimeError, match="Failed to stamp GEE flags"):
            postgis_manager.stamp_gee_flags("som_field_boundaries", {1})


# ------------------------------------------
# PostGISManager.has_table
# ------------------------------------------


@pytest.mark.unit
class TestHasTable:
    def test_returns_true_when_table_exists(self, postgis_manager):
        """has_table must reflect the SQLAlchemy inspector result."""
        with patch(
            "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect"
        ) as mock_inspect:
            mock_inspect.return_value.has_table.return_value = True
            assert postgis_manager.has_table("som_field_boundaries") is True

    def test_returns_false_when_table_missing(self, postgis_manager):
        """A missing table must return False without raising."""
        with patch(
            "gis_pipeline.modules.db.pg_utils.sqlalchemy.inspect"
        ) as mock_inspect:
            mock_inspect.return_value.has_table.return_value = False
            assert postgis_manager.has_table("som_field_boundaries") is False
