from datetime import datetime as dt
from datetime import timezone
from unittest.mock import Mock, patch

import geopandas as gpd
import pandas as pd
import pytest
from pipeline.mapping import PostgresDataTypes, RasterStacColumns
from pipeline.modules.db.pg_utils import PostGISManager
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

    with patch("pipeline.modules.db.pg_utils.Config") as mock_config:
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
    return gpd.GeoDataFrame({"id": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]})


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
@patch("pipeline.modules.db.pg_utils.sqlalchemy.create_engine")
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


@patch("pipeline.modules.db.pg_utils.sqlalchemy.create_engine")
def test_init_connection_failure(mock_create_engine):
    """Test PostGISManager initialization with connection failure."""
    mock_create_engine.side_effect = Exception("Connection failed")

    with pytest.raises(RuntimeError, match="Error connecting to PostGIS database"):
        PostGISManager()


def test_init_no_postgis_extension(mock_engine_no_postgis):
    """Test PostGISManager initialization when PostGIS extension is missing."""
    with pytest.raises(RuntimeError, match="Error checking PostGIS extension"):
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
    with patch("pipeline.modules.db.pg_utils.Config.POSTGRES_MAX_NAME_LENGTH", 5):
        with pytest.raises(RuntimeError, match="Error checking PostGIS variables"):
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
        "gid": {"type": "Integer", "primary_key": True, "autoincrement": True},
        "name": {"type": "Text"},
        "geometry": {"type": "Geometry", "geometry_type": "POLYGON", "srid": 4326},
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
        "pipeline.modules.db.pg_utils.SqlAlchemyTypes",
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
# Test cases for insert_gdf()
# ------------------------------------------
def test_insert_gdf_new_table_success(postgis_manager, gdf_points_fixture):
    """Test inserting GeoDataFrame into new table."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = False

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(postgis_manager, "_create_table_from_mapping") as mock_create:
            with patch.object(gdf_points_fixture, "to_postgis") as mock_to_postgis:
                mock_to_postgis.return_value = None

                postgis_manager.insert_gdf(
                    gdf=gdf_points_fixture, table_name=table_name
                )

                expected_mapping = postgis_manager._build_column_mapping_from_gdf(
                    gdf_points_fixture
                )
                mock_create.assert_called_once_with(
                    table_name=table_name, column_mapping=expected_mapping
                )
                mock_to_postgis.assert_called_once()


def test_insert_gdf_existing_table_success(postgis_manager, gdf_points_fixture):
    """Test inserting GeoDataFrame into existing table."""
    table_name = "existing_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(gdf_points_fixture, "to_postgis") as mock_to_postgis:
            mock_to_postgis.return_value = None

            postgis_manager.insert_gdf(gdf=gdf_points_fixture, table_name=table_name)

            mock_to_postgis.assert_called_once()


def test_insert_gdf_database_error(postgis_manager, gdf_points_fixture):
    """Test insert_gdf with database error."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(
            gdf_points_fixture, "to_postgis", side_effect=Exception("DB Error")
        ):
            with pytest.raises(
                RuntimeError,
                match="Error inserting GeoDataFrame into PostGIS",
            ):
                postgis_manager.insert_gdf(
                    gdf=gdf_points_fixture, table_name=table_name
                )


def test_insert_gdf_table_creation_flow(postgis_manager, gdf_points_fixture):
    """Test complete flow of table creation and data insertion."""
    table_name = "new_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = False

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(postgis_manager, "_create_table_from_mapping") as mock_create:
            with patch.object(gdf_points_fixture, "to_postgis") as mock_to_postgis:
                mock_create.return_value = None
                mock_to_postgis.return_value = None

                postgis_manager.insert_gdf(
                    gdf=gdf_points_fixture, table_name=table_name
                )

                mock_create.assert_called_once()
                mock_to_postgis.assert_called_once()


def test_insert_gdf_inspection_error(postgis_manager, gdf_points_fixture):
    """Test insert_gdf when table inspection fails."""
    table_name = "test_table"

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect",
        side_effect=Exception("Inspection failed"),
    ):
        with pytest.raises(
            RuntimeError,
            match="Error inserting GeoDataFrame into PostGIS",
        ):
            postgis_manager.insert_gdf(gdf=gdf_points_fixture, table_name=table_name)


def test_insert_gdf_create_table_error(postgis_manager, gdf_points_fixture):
    """Test insert_gdf when table creation fails."""
    table_name = "test_table"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = False

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(
            postgis_manager,
            "_create_table_from_mapping",
            side_effect=Exception("Table creation failed"),
        ):
            with pytest.raises(
                RuntimeError,
                match="Error inserting GeoDataFrame into PostGIS",
            ):
                postgis_manager.insert_gdf(
                    gdf=gdf_points_fixture, table_name=table_name
                )


def test_insert_gdf_valid_table_names(postgis_manager, gdf_points_fixture):
    """Test insert_gdf with various valid table names."""
    valid_table_names = [
        "simple_table",
        "table_with_underscores",
        "table123",
        "TableMixedCase",
    ]

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(gdf_points_fixture, "to_postgis") as mock_to_postgis:
            mock_to_postgis.return_value = None

            for table_name in valid_table_names:
                mock_to_postgis.reset_mock()

                postgis_manager.insert_gdf(
                    gdf=gdf_points_fixture, table_name=table_name
                )

                mock_to_postgis.assert_called_once()


def test_insert_gdf_empty_table_name(postgis_manager, gdf_points_fixture):
    """Test insert_gdf with empty table name."""
    with pytest.raises(
        RuntimeError,
        match="Error inserting GeoDataFrame into PostGIS",
    ):
        postgis_manager.insert_gdf(gdf=gdf_points_fixture, table_name="")


def test_insert_gdf_none_table_name(postgis_manager, gdf_points_fixture):
    """Test insert_gdf with None table name."""
    with pytest.raises(
        RuntimeError,
        match="Error inserting GeoDataFrame into PostGIS",
    ):
        postgis_manager.insert_gdf(gdf=gdf_points_fixture, table_name=None)


# ------------------------------------------
# Test cases for insert_cog_metadata()
# ------------------------------------------
def test_insert_cog_metadata_success(postgis_manager, cog_metadata_simple):
    """Test successful COG metadata insertion."""
    table_name = "test_cogs"

    mock_inspector = Mock()
    mock_inspector.has_table.return_value = True

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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

    with patch(
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
    ):
        with patch.object(postgis_manager, "_create_table_from_mapping") as mock_create:
            postgis_manager.insert_cog_metadata(
                metadata=cog_metadata_simple, table_name=table_name
            )

            mock_create.assert_called_once_with(
                table_name=table_name,
                column_mapping=RasterStacColumns,
            )


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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
        "pipeline.modules.db.pg_utils.sqlalchemy.inspect", return_value=mock_inspector
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
