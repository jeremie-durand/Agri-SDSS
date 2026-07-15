from pathlib import Path
from unittest.mock import Mock, patch

import duckdb
import geopandas as gpd
import pandas as pd
import pytest
from gis_pipeline.core.config import Config
from gis_pipeline.modules.db.duckdb_utils import (
    DuckDBManager,
    DuckDBSpatialExtensionError,
)


@pytest.fixture(autouse=True)
def in_memory_duckdb():
    """Fixture to provide an in-memory DuckDB instance."""
    with patch.object(Config, "DUCKDB_DATABASE", ":memory:"), patch.object(
        Config, "DUCKDB_DATA_DIR", "/tmp"
    ):
        yield


# ------------------------------------------
# Fixtures - General
# ------------------------------------------
@pytest.fixture
def duckdb_manager():
    """Provide a temporary DuckDBManager instance with in-memory DB."""
    db = DuckDBManager()
    yield db
    db.conn.close()


# ------------------------------------------
# Fixtures - GeoDataFrames
# ------------------------------------------
@pytest.fixture
def gdf_points_fixture_v2():
    """Simple GeoDataFrame with points for testing (version 2 for functions that uses two gdf)."""
    gdf = gpd.GeoDataFrame(
        {
            "gid": [10, 20, 30],
            "name": ["A", "B", "C"],
            "geometry": gpd.points_from_xy([10, 20, 30], [10, 20, 30]),
        },
        crs="EPSG:4326",
    )
    return gdf


# ------------------------------------------
# Test cases for save_df_to_parquet()
# ------------------------------------------
@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    """Ensure DUCKDB_DATA_DIR points to a temp dir for all tests in this module."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )
    yield


def test_save_df_to_parquet_success(tmp_path):
    """Test successful saving of a simple DataFrame to Parquet."""
    df = pd.DataFrame({"gid": [1, 2], "name": ["a", "b"]})
    output_name = "success_test"

    DuckDBManager.save_df_to_parquet(df=df, output_file_name=output_name)

    expected = Path(tmp_path) / f"{output_name}.parquet"
    assert expected.exists()
    # verify readable and content preserved
    df_read = pd.read_parquet(expected)
    assert list(df_read["gid"]) == [1, 2]
    assert list(df_read["name"]) == ["a", "b"]


def test_save_df_to_parquet_empty_dataframe_raises():
    """Test that saving an empty DataFrame raises a ValueError."""
    df = pd.DataFrame()
    with pytest.raises(ValueError, match="Cannot save empty DataFrame"):
        DuckDBManager.save_df_to_parquet(df=df, output_file_name="any")


def test_save_df_to_parquet_empty_filename_raises():
    """Test that saving with an empty output file name raises a ValueError."""
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(ValueError, match="Output file name must not be empty"):
        DuckDBManager.save_df_to_parquet(df=df, output_file_name=" ")


def test_save_df_to_parquet_overwrite_false_raises(tmp_path, monkeypatch):
    """Test that saving with overwrite=False return empty when file exists."""
    # Patch the directory used by the function
    monkeypatch.setattr(Config, "DUCKDB_DATA_DIR", str(tmp_path))

    df = pd.DataFrame({"x": [1]})
    output_name = "already_there"

    target = tmp_path / f"{output_name}.parquet"
    target.write_bytes(b"existing")

    DuckDBManager.save_df_to_parquet(
        df=df, output_file_name=output_name, overwrite=False
    )
    # file should be unchanged
    assert target.read_bytes() == b"existing"


def test_save_df_to_parquet_removes_existing_tmp_and_creates_parquet(
    tmp_path, monkeypatch
):
    """Test that stale tmp file is removed and parquet is created successfully."""
    df = pd.DataFrame({"a": [1, 2, 3]})
    output_name = "tmp_remove_test"

    # Patch the DUCKDB_DATA_DIR to use pytest's tmp_path
    monkeypatch.setattr(Config, "DUCKDB_DATA_DIR", str(tmp_path))

    parquet_path = tmp_path / f"{output_name}.parquet"
    tmp_file = tmp_path / f"{output_name}.tmp"

    # Create a stale tmp file
    tmp_file.write_bytes(b"stale temp")

    DuckDBManager.save_df_to_parquet(df=df, output_file_name=output_name)

    assert parquet_path.exists()  # now passes
    assert not tmp_file.exists()  # tmp removed

    df_read = pd.read_parquet(parquet_path)
    assert len(df_read) == 3


def test_save_df_to_parquet_filesystem_error_triggers_cleanup(tmp_path, monkeypatch):
    """Test that a filesystem error during save triggers cleanup of tmp file."""
    df = pd.DataFrame({"a": [1]})
    output_name = "fs_error_test"

    # force DataFrame.to_parquet to raise OSError
    def raise_oserror(self, *args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", raise_oserror)

    cleanup_mock = Mock()
    # patch the class method directly so calls to DuckDBManager._cleanup_temp_file are intercepted
    monkeypatch.setattr(DuckDBManager, "_cleanup_temp_file", cleanup_mock)

    with pytest.raises(
        RuntimeError, match="File system error saving DataFrame to Parquet"
    ):
        DuckDBManager.save_df_to_parquet(df=df, output_file_name=output_name)

    # cleanup may be called with a positional arg or a keyword arg (tmp_path)
    call_args, call_kwargs = cleanup_mock.call_args
    if call_kwargs:
        assert "tmp_path" in call_kwargs
        assert isinstance(call_kwargs["tmp_path"], Path)
    else:
        assert len(call_args) == 1
        assert isinstance(call_args[0], Path)


# ------------------------------------------
# Test cases for save_gdf_to_geoparquet()
# ------------------------------------------
def test_save_gdf_to_geoparquet_simple_success(
    gdf_points_fixture_id, tmp_path, monkeypatch
):
    """Test successful saving of a simple GeoDataFrame to GeoParquet."""
    # Mock the Config.DUCKDB_DATA_DIR to use tmp_path
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    output_file_name = "test_simple"

    DuckDBManager.save_gdf_to_geoparquet(
        gdf=gdf_points_fixture_id, output_file_name=output_file_name
    )

    # Verify file creation
    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()

    # Verify file can be read back
    gdf_read = gpd.read_parquet(expected_path)
    assert len(gdf_read) == 2
    assert list(gdf_read["gid"]) == [1, 2]
    assert list(gdf_read["name"]) == ["Feature1", "Feature2"]


def test_save_gdf_to_geoparquet_with_null_like_values(
    gdf_points_with_null_like_values_fixture, tmp_path, monkeypatch
):
    """Test saving GeoDataFrame with null-like values that need normalization."""
    # Mock the Config.DUCKDB_DATA_DIR to use tmp_path
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    output_file_name = "test_null_values"

    DuckDBManager.save_gdf_to_geoparquet(
        gdf=gdf_points_with_null_like_values_fixture, output_file_name=output_file_name
    )

    # Verify file creation
    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()


def test_save_gdf_to_geoparquet_overwrites_existing_file(
    gdf_points_fixture_id, gdf_points_fixture_v2, tmp_path, monkeypatch
):
    """Test that saving overwrites an existing file."""
    # Mock the Config.DUCKDB_DATA_DIR to use tmp_path
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    output_file_name = "test_overwrite"
    expected_path = tmp_path / f"{output_file_name}.parquet"

    # Create initial file
    DuckDBManager.save_gdf_to_geoparquet(
        gdf=gdf_points_fixture_id, output_file_name=output_file_name
    )
    assert expected_path.exists()

    # Overwrite the file
    DuckDBManager.save_gdf_to_geoparquet(
        gdf=gdf_points_fixture_v2, output_file_name=output_file_name
    )

    # Verify the file was overwritten
    assert expected_path.exists()

    # Verify content is from the new GeoDataFrame
    gdf_read = gpd.read_parquet(expected_path)
    assert len(gdf_read) == 3
    assert list(gdf_read["gid"]) == [10, 20, 30]


# ------------------------------------------
# Test cases for save_gdf_to_geoparquet() column normalization
# ------------------------------------------
def test_save_gdf_to_geoparquet_renames_id_to_gid(tmp_path, monkeypatch):
    """Test that id column is renamed to gid during export."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # Create GeoDataFrame with 'id' column
    gdf = gpd.GeoDataFrame(
        {
            "id": [100, 200],
            "name": ["LocationA", "LocationB"],
            "geometry": gpd.points_from_xy([5, 10], [5, 10]),
        },
        crs="EPSG:4326",
    )

    output_file_name = "test_id_rename"
    DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name=output_file_name)

    # Verify file was created and id was renamed to gid
    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()

    gdf_read = gpd.read_parquet(expected_path)
    assert "gid" in gdf_read.columns
    assert "id" not in gdf_read.columns
    assert list(gdf_read["gid"]) == [100, 200]


def test_save_gdf_to_geoparquet_renames_station_id_to_gid(tmp_path, monkeypatch):
    """Test that station_id column is renamed to gid during export."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # Create GeoDataFrame with 'station_id' column
    gdf = gpd.GeoDataFrame(
        {
            "station_id": [5, 6, 7],
            "measurement": [12.5, 13.1, 14.2],
            "geometry": gpd.points_from_xy([1, 2, 3], [1, 2, 3]),
        },
        crs="EPSG:4326",
    )

    output_file_name = "test_station_id_rename"
    DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name=output_file_name)

    # Verify file was created and station_id was renamed to gid
    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()

    gdf_read = gpd.read_parquet(expected_path)
    assert "gid" in gdf_read.columns
    assert "station_id" not in gdf_read.columns
    assert list(gdf_read["gid"]) == [5, 6, 7]


def test_save_gdf_to_geoparquet_preserves_existing_gid(tmp_path, monkeypatch):
    """Test that existing gid column is preserved (no renaming)."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # Create GeoDataFrame with 'gid' column already
    gdf = gpd.GeoDataFrame(
        {
            "gid": [50, 51],
            "category": ["A", "B"],
            "geometry": gpd.points_from_xy([0, 1], [0, 1]),
        },
        crs="EPSG:4326",
    )

    output_file_name = "test_gid_preserved"
    DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name=output_file_name)

    # Verify file was created and gid remains unchanged
    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()

    gdf_read = gpd.read_parquet(expected_path)
    assert "gid" in gdf_read.columns
    assert list(gdf_read["gid"]) == [50, 51]


def test_save_gdf_to_geoparquet_original_gdf_unmodified(tmp_path, monkeypatch):
    """Test that original GeoDataFrame is not modified during export."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # Create GeoDataFrame with 'id' column
    gdf = gpd.GeoDataFrame(
        {
            "id": [9, 10],
            "value": [100, 200],
            "geometry": gpd.points_from_xy([2, 3], [2, 3]),
        },
        crs="EPSG:4326",
    )

    # Save original column names
    original_columns = list(gdf.columns)

    output_file_name = "test_original_unmodified"
    DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name=output_file_name)

    # Verify original GeoDataFrame is unmodified
    assert list(gdf.columns) == original_columns
    assert "id" in gdf.columns
    assert "gid" not in gdf.columns


def test_save_gdf_to_geoparquet_column_rename_logged(tmp_path, monkeypatch):
    """Test that column renaming is logged at INFO level."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "name": ["X", "Y"],
            "geometry": gpd.points_from_xy([0, 1], [0, 1]),
        },
        crs="EPSG:4326",
    )

    with patch("gis_pipeline.modules.db.duckdb_utils.logger") as mock_logger:
        DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name="test_logging")

    logged = [call.args[0] for call in mock_logger.info.call_args_list if call.args]
    assert any("Renamed column 'id' to 'gid'" in msg for msg in logged)


def test_save_gdf_to_geoparquet_multiple_id_columns_conflicting_values(
    tmp_path, monkeypatch
):
    """Test that a ValueError is raised when two ID-alias columns map to the same
    canonical name but contain different values."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # id=[1,2] will be renamed to gid first; then station_id=[100,200] conflicts
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "station_id": [100, 200],  # different values → conflict
            "name": ["A", "B"],
            "geometry": gpd.points_from_xy([0, 1], [0, 1]),
        },
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="Column conflict"):
        DuckDBManager.save_gdf_to_geoparquet(
            gdf=gdf, output_file_name="test_multiple_ids_conflict"
        )


def test_save_gdf_to_geoparquet_multiple_id_columns_identical_values(
    tmp_path, monkeypatch
):
    """Test that a redundant alias column is silently dropped when its values are
    identical to the canonical column that was already renamed from another alias."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )

    # id=[1,2] will be renamed to gid; station_id=[1,2] is identical → dropped
    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "station_id": [1, 2],  # same values as id → redundant
            "name": ["A", "B"],
            "geometry": gpd.points_from_xy([0, 1], [0, 1]),
        },
        crs="EPSG:4326",
    )

    output_file_name = "test_multiple_ids_identical"
    with patch("gis_pipeline.modules.db.duckdb_utils.logger") as mock_logger:
        DuckDBManager.save_gdf_to_geoparquet(gdf=gdf, output_file_name=output_file_name)

    expected_path = tmp_path / f"{output_file_name}.parquet"
    assert expected_path.exists()

    gdf_read = gpd.read_parquet(expected_path)
    assert "gid" in gdf_read.columns
    assert "id" not in gdf_read.columns
    assert "station_id" not in gdf_read.columns  # dropped as redundant
    assert list(gdf_read["gid"]) == [1, 2]
    logged = [call.args[0] for call in mock_logger.info.call_args_list if call.args]
    assert any("Dropped redundant alias" in msg for msg in logged)


# ------------------------------------------
# Test cases for save_table_to_geoparquet()
# ------------------------------------------
def test_save_table_to_geoparquet_simple_success(duckdb_manager):
    """Test successful saving of a simple DuckDB table to Parquet."""
    manager = duckdb_manager

    table_name = "test_table_simple"
    manager.conn.execute(f"""
    CREATE TABLE {manager.escape_duckdb(table_name)} (
        id INTEGER, 
        name VARCHAR,
        geometry GEOMETRY
    )
    """)
    manager.conn.execute(
        f"INSERT INTO {manager.escape_duckdb(table_name)} VALUES (1, 'A', ST_Point(0,0)), (2, 'B', ST_Point(1,1))"
    )

    saved_path = manager.save_table_to_geoparquet(table_name=table_name)

    expected_path = Path(saved_path)
    assert expected_path.exists()

    gdf_read = gpd.read_parquet(saved_path)
    assert gdf_read.shape == (2, 3)
    assert list(gdf_read.columns) == ["gid", "name", "geometry"]


def test_save_table_to_geoparquet_nonexistent_table(duckdb_manager):
    """Test error handling when trying to save a nonexistent table."""
    manager = duckdb_manager

    table_name = "nonexistent_table"

    with pytest.raises(
        RuntimeError, match=f"Table '{table_name}' does not exist in database"
    ):
        manager.save_table_to_geoparquet(table_name=table_name)


def test_save_table_to_geoparquet_invalid_table_name(duckdb_manager):
    """Test error handling when table name is invalid."""
    manager = duckdb_manager

    # List of invalid table names to test
    invalid_table_names = {"invalid-table-name!", "table name with spaces"}

    for invalid_table_name in invalid_table_names:
        manager.conn.execute(
            f"CREATE TABLE {manager.escape_duckdb(invalid_table_name)} (id INTEGER)"
        )
        with pytest.raises(ValueError, match="Invalid table name"):
            manager.save_table_to_geoparquet(table_name=invalid_table_name)


def test_save_table_to_geoparquet_with_various_data_types(duckdb_manager):
    """Test saving table with various data types to Parquet."""
    manager = duckdb_manager

    table_name = "mixed_types_table"

    # Create table with various data types
    manager.conn.execute("""
        CREATE TABLE mixed_types_table (
            id INTEGER,
            name VARCHAR,
            price DOUBLE,
            created_date DATE,
            created_time TIMESTAMP
        )
    """)

    # Insert test data
    manager.conn.execute("""
        INSERT INTO mixed_types_table VALUES 
        (1, 'Product A', 19.99, '2024-01-01', '2024-01-01 10:30:00'),
        (2, 'Product B', 29.99, '2024-01-02', '2024-01-02 14:45:00')
    """)

    # Test the function
    result_path = manager.save_table_to_geoparquet(table_name=table_name)

    # Verify file was created
    assert Path(result_path).exists()

    # Verify data integrity
    result_path = Path(result_path)
    # Note: 'id' column is renamed to 'gid' during Parquet export
    verification_result = manager.conn.execute(
        f"SELECT * FROM '{str(result_path)}' ORDER BY gid"
    ).fetchall()
    assert len(verification_result) == 2

    first_row = verification_result[0]
    second_row = verification_result[1]

    # Test first row
    assert first_row[0] == 1
    assert first_row[1] == "Product A"
    assert first_row[2] == 19.99
    assert str(first_row[3]) == "2024-01-01"

    # Test second row
    assert second_row[0] == 2
    assert second_row[1] == "Product B"
    assert second_row[2] == 29.99
    assert str(second_row[3]) == "2024-01-02"


def test_save_table_to_geoparquet_with_null_values(duckdb_manager):
    """Test saving table with NULL values to Parquet."""
    manager = duckdb_manager

    table_name = "null_values_table"

    # Create table with potential NULL values
    manager.conn.execute("""
        CREATE TABLE null_values_table (
            id INTEGER,
            name VARCHAR,
            optional_value DOUBLE
        )
    """)

    # Insert data with NULLs
    manager.conn.execute("""
        INSERT INTO null_values_table VALUES 
        (1, 'Alice', 10.5),
        (2, NULL, 20.3),
        (3, 'Charlie', NULL)
    """)

    # Test the function
    result_path = manager.save_table_to_geoparquet(table_name=table_name)

    # Verify file was created
    assert Path(result_path).exists()

    # Verify NULL handling
    verification_result = manager.conn.execute(
        f"SELECT COUNT(*) FROM '{str(result_path)}' WHERE name IS NULL"
    ).fetchone()
    assert verification_result[0] == 1  # One NULL name


def test_save_table_to_geoparquet_large_table(duckdb_manager):
    """Test saving a large table to Parquet."""
    manager = duckdb_manager

    table_name = "large_table"

    # Create table with many rows
    manager.conn.execute("""
        CREATE TABLE large_table (
            id INTEGER,
            value VARCHAR
        )
    """)

    # Insert many rows (using DuckDB's generate_series)
    manager.conn.execute("""
        INSERT INTO large_table 
        SELECT i, 'value_' || i 
        FROM generate_series(1, 1000) AS t(i)
    """)

    # Test the function
    result_path = manager.save_table_to_geoparquet(table_name=table_name)

    # Verify file was created
    assert Path(result_path).exists()

    # Verify all data was saved
    verification_result = manager.conn.execute(
        f"SELECT COUNT(*) FROM '{result_path}'"
    ).fetchone()
    assert verification_result[0] == 1000


def test_save_table_to_geoparquet_overwrites_existing_file(duckdb_manager):
    """Test that saving overwrites an existing Parquet file."""
    table_name = "overwrite_table"

    # Create first table
    duckdb_manager.conn.execute("""
        CREATE TABLE overwrite_table (
            id INTEGER,
            value VARCHAR
        )
    """)

    # Insert initial data
    duckdb_manager.conn.execute("INSERT INTO overwrite_table VALUES (1, 'original')")

    # First save
    result_path1 = duckdb_manager.save_table_to_geoparquet(table_name=table_name)
    assert Path(result_path1).exists()

    # Verify initial content
    initial_result = duckdb_manager.conn.execute(
        f"SELECT value FROM '{str(result_path1)}'"
    ).fetchone()
    assert initial_result[0] == "original"

    # Modify table data
    duckdb_manager.conn.execute(
        "UPDATE overwrite_table SET value = 'updated' WHERE id = 1"
    )
    duckdb_manager.conn.execute("INSERT INTO overwrite_table VALUES (2, 'new')")

    # Second save (should overwrite)
    result_path2 = duckdb_manager.save_table_to_geoparquet(table_name=table_name)
    assert result_path1 == result_path2  # Same path

    # Verify updated content
    updated_results = duckdb_manager.conn.execute(
        f"SELECT COUNT(*) FROM '{result_path2}'"
    ).fetchone()
    assert updated_results[0] == 2  # Now has 2 rows


def test_save_table_to_geoparquet_return_value_type(duckdb_manager):
    """Test that save_table_to_geoparquet returns correct type."""
    table_name = "return_test"

    # Create test table
    duckdb_manager.conn.execute("CREATE TABLE return_test (id INTEGER)")
    duckdb_manager.conn.execute("INSERT INTO return_test VALUES (1)")

    # Test the function
    result_path = duckdb_manager.save_table_to_geoparquet(table_name=table_name)

    # Verify return type
    assert isinstance(result_path, str)
    assert result_path.endswith(".parquet")
    assert "return_test" in result_path


def test_save_table_to_geoparquet_with_geometry_data(duckdb_manager):
    """Test saving table with geometry data to Parquet."""
    table_name = "geom_table"

    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create table with geometry
    duckdb_manager.conn.execute("""
        CREATE TABLE geom_table (
            id INTEGER,
            name VARCHAR,
            geometry GEOMETRY
        )
    """)

    # Insert geometry data
    duckdb_manager.conn.execute("""
        INSERT INTO geom_table VALUES 
        (1, 'Point A', ST_GeomFromText('POINT(1 1)')),
        (2, 'Point B', ST_GeomFromText('POINT(2 2)'))
    """)

    # Test the function
    result_path = duckdb_manager.save_table_to_geoparquet(table_name=table_name)

    # Verify file was created
    assert Path(result_path).exists()

    # Verify geometry data was saved
    verification_result = duckdb_manager.conn.execute(
        f"SELECT COUNT(*) FROM '{result_path}'"
    ).fetchone()
    assert verification_result[0] == 2


def test_save_table_to_geoparquet_concurrent_access(duckdb_manager):
    """Test saving table when file might be in use (simulates concurrent access)."""
    table_name = "concurrent_table"

    # Create test table
    duckdb_manager.conn.execute("CREATE TABLE concurrent_table (id INTEGER)")
    duckdb_manager.conn.execute("INSERT INTO concurrent_table VALUES (1)")

    # First save
    result_path1 = duckdb_manager.save_table_to_geoparquet(table_name=table_name)
    assert Path(result_path1).exists()

    # Second save should still work
    result_path2 = duckdb_manager.save_table_to_geoparquet(table_name=table_name)
    assert Path(result_path2).exists()
    assert result_path1 == result_path2


def test_save_table_to_geoparquet_table_with_complex_sql_query(duckdb_manager):
    """Test that the function uses SELECT * correctly for complex table structures."""
    table_name = "base_table"

    # Create table with computed columns via view-like structure
    duckdb_manager.conn.execute("""
        CREATE TABLE base_table (
            id INTEGER,
            quantity INTEGER,
            price DOUBLE
        )
    """)

    # Insert test data
    duckdb_manager.conn.execute("""
        INSERT INTO base_table VALUES 
        (1, 5, 10.0),
        (2, 3, 15.0)
    """)

    # Test the function
    result_path = duckdb_manager.save_table_to_geoparquet(table_name=table_name)

    # Verify all columns were saved
    columns_result = duckdb_manager.conn.execute(
        f"DESCRIBE SELECT * FROM '{result_path}'"
    ).fetchall()
    column_names = [row[0] for row in columns_result]

    assert "gid" in column_names
    assert "quantity" in column_names
    assert "price" in column_names


def test_save_table_to_geoparquet_raises_when_alias_and_canonical_differ(
    duckdb_manager,
):
    """Test that a ValueError is raised when both alias and canonical columns exist
    with different values — the pipeline cannot determine the authoritative source."""
    table_name = "table_with_id_and_gid_conflicting"

    duckdb_manager.conn.execute("""
        CREATE TABLE table_with_id_and_gid_conflicting (
            id INTEGER,
            gid INTEGER,
            name VARCHAR
        )
    """)
    duckdb_manager.conn.execute("""
        INSERT INTO table_with_id_and_gid_conflicting VALUES
        (1, 10, 'alpha'),
        (2, 20, 'beta')
    """)

    with pytest.raises(ValueError, match="Column conflict"):
        duckdb_manager.save_table_to_geoparquet(table_name=table_name)


def test_save_table_to_geoparquet_drops_alias_when_identical_to_canonical(
    duckdb_manager,
):
    """Test that a redundant alias column is dropped (not duplicated) when its values
    are identical to the canonical column already present in the table."""
    table_name = "table_with_id_and_gid_identical"

    duckdb_manager.conn.execute("""
        CREATE TABLE table_with_id_and_gid_identical (
            id INTEGER,
            gid INTEGER,
            name VARCHAR
        )
    """)
    duckdb_manager.conn.execute("""
        INSERT INTO table_with_id_and_gid_identical VALUES
        (10, 10, 'alpha'),
        (20, 20, 'beta')
    """)

    with patch("gis_pipeline.modules.db.duckdb_utils.logger") as mock_logger:
        result_path = duckdb_manager.save_table_to_geoparquet(table_name=table_name)

    assert Path(result_path).exists()

    columns_result = duckdb_manager.conn.execute(
        f"DESCRIBE SELECT * FROM '{result_path}'"
    ).fetchall()
    column_names = [row[0] for row in columns_result]

    assert column_names.count("gid") == 1, "Expected exactly one 'gid' column"
    assert "id" not in column_names, "Redundant alias 'id' should have been dropped"

    rows = duckdb_manager.conn.execute(
        f"SELECT gid FROM '{result_path}' ORDER BY gid"
    ).fetchall()
    assert [r[0] for r in rows] == [10, 20]

    logged = [call.args[0] for call in mock_logger.info.call_args_list if call.args]
    assert any("Dropped redundant alias" in msg and "id" in msg for msg in logged)


def test_save_table_to_geoparquet_two_aliases_no_explicit_gid_identical(
    duckdb_manager,
):
    """Test: two alias columns (id, station_id) with identical values and no explicit gid.
    First alias is renamed to gid, second is dropped as redundant.
    """
    table_name = "table_two_aliases_identical"

    duckdb_manager.conn.execute("""
        CREATE TABLE table_two_aliases_identical (
            id INTEGER,
            station_id INTEGER,
            name VARCHAR
        )
    """)
    duckdb_manager.conn.execute("""
        INSERT INTO table_two_aliases_identical VALUES
        (1, 1, 'alpha'),
        (2, 2, 'beta')
    """)

    with patch("gis_pipeline.modules.db.duckdb_utils.logger") as mock_logger:
        result_path = duckdb_manager.save_table_to_geoparquet(table_name=table_name)

    assert Path(result_path).exists()

    column_names = [
        row[0]
        for row in duckdb_manager.conn.execute(
            f"DESCRIBE SELECT * FROM '{result_path}'"
        ).fetchall()
    ]

    assert column_names.count("gid") == 1, "Expected exactly one 'gid' column"
    assert "id" not in column_names
    assert "station_id" not in column_names

    rows = duckdb_manager.conn.execute(
        f"SELECT gid FROM '{result_path}' ORDER BY gid"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]

    logged = [call.args[0] for call in mock_logger.info.call_args_list if call.args]
    assert any("Dropped redundant alias" in msg for msg in logged)


def test_save_table_to_geoparquet_two_aliases_no_explicit_gid_conflicting(
    duckdb_manager,
):
    """Test: two alias columns (id, station_id) with different values and no explicit gid.
    First alias is renamed to gid, second triggers a ValueError.
    """
    table_name = "table_two_aliases_conflicting"

    duckdb_manager.conn.execute("""
        CREATE TABLE table_two_aliases_conflicting (
            id INTEGER,
            station_id INTEGER,
            name VARCHAR
        )
    """)
    duckdb_manager.conn.execute("""
        INSERT INTO table_two_aliases_conflicting VALUES
        (1, 10, 'alpha'),
        (2, 20, 'beta')
    """)

    with pytest.raises(ValueError, match="Column conflict"):
        duckdb_manager.save_table_to_geoparquet(table_name=table_name)


# ------------------------------------------
# Test cases for check_data()
# ------------------------------------------
def test_check_data_empty_database(duckdb_manager):
    """Test check_data returns empty list when no tables exist."""
    tables = duckdb_manager.check_data()
    assert tables == []


def test_check_data_single_table(duckdb_manager):
    """Test check_data returns correct table name when one table exists."""
    duckdb_manager.conn.execute("CREATE TABLE test_table (id INTEGER)")
    tables = duckdb_manager.check_data()

    assert isinstance(tables, list)
    assert "test_table" in tables
    assert len(tables) >= 1


def test_check_data_multiple_tables(duckdb_manager):
    """Test check_data returns all table names when multiple tables exist."""
    duckdb_manager.conn.execute("CREATE TABLE users (id INTEGER)")
    duckdb_manager.conn.execute("CREATE TABLE products (name VARCHAR)")
    duckdb_manager.conn.execute("CREATE TABLE orders (value DOUBLE)")

    tables = duckdb_manager.check_data()
    assert len(tables) == 3
    assert "users" in tables
    assert "products" in tables
    assert "orders" in tables


def test_check_data_table_with_special_characters(duckdb_manager):
    """Test check_data handles table names with special characters."""
    # Note: DuckDB allows quoted identifiers with special characters
    duckdb_manager.conn.execute('CREATE TABLE "test_table_123" (id INTEGER)')
    duckdb_manager.conn.execute('CREATE TABLE "my-table" (id INTEGER)')

    tables = duckdb_manager.check_data()
    assert "test_table_123" in tables
    assert "my-table" in tables


def test_check_data_after_table_drop(duckdb_manager):
    """Test check_data reflects dropped tables correctly."""
    # Create tables
    duckdb_manager.conn.execute("CREATE TABLE temp_table1 (id INTEGER)")
    duckdb_manager.conn.execute("CREATE TABLE temp_table2 (id INTEGER)")

    tables_before = duckdb_manager.check_data()
    assert "temp_table1" in tables_before
    assert "temp_table2" in tables_before

    # Drop one table
    duckdb_manager.conn.execute("DROP TABLE temp_table1")

    tables_after = duckdb_manager.check_data()
    assert "temp_table1" not in tables_after
    assert "temp_table2" in tables_after


def test_check_data_case_sensitivity(duckdb_manager):
    """Test check_data handles case sensitivity correctly."""
    # Note : DuckDB is case-insensitive for unquoted identifiers but preserves case
    duckdb_manager.conn.execute("CREATE TABLE TestTable (id INTEGER)")
    duckdb_manager.conn.execute('CREATE TABLE "CaseSensitiveTable" (id INTEGER)')

    tables = duckdb_manager.check_data()

    # Check that table names are returned with their original case
    assert any(table.lower() == "testtable" for table in tables)
    assert "CaseSensitiveTable" in tables


def test_check_data_with_various_table_types(duckdb_manager):
    """Test check_data with different types of tables (regular, temporary)."""
    # Create regular table
    duckdb_manager.conn.execute("CREATE TABLE regular_table (id INTEGER)")

    # Create temporary table
    duckdb_manager.conn.execute("CREATE TEMP TABLE temp_table (id INTEGER)")

    tables = duckdb_manager.check_data()

    # Only main schema tables should be returned (not temp tables)
    assert "regular_table" in tables


def test_check_data_returns_list_type(duckdb_manager):
    """Test check_data always returns a list."""
    # Empty database
    tables_empty = duckdb_manager.check_data()
    assert isinstance(tables_empty, list)

    # With tables
    duckdb_manager.conn.execute("CREATE TABLE test_table (id INTEGER)")
    tables_with_data = duckdb_manager.check_data()
    assert isinstance(tables_with_data, list)
    assert all(isinstance(table_name, str) for table_name in tables_with_data)


def test_check_data_table_order_consistency(duckdb_manager):
    """Test check_data returns tables in consistent order."""
    # Create tables in specific order
    table_names = ["zebra_table", "alpha_table", "beta_table"]
    for table_name in table_names:
        duckdb_manager.conn.execute(f"CREATE TABLE {table_name} (id INTEGER)")

    # Call check_data multiple times
    tables1 = duckdb_manager.check_data()
    tables2 = duckdb_manager.check_data()

    # Results should be consistent
    assert tables1 == tables2
    assert len(tables1) == 3
    assert all(table in tables1 for table in table_names)


def test_check_data_error_handling_closed_connection():
    """Test check_data raises RuntimeError when connection is closed."""
    # Create a connection and close it
    conn = duckdb.connect(":memory:")
    manager = DuckDBManager(conn=conn)
    conn.close()

    with pytest.raises(
        RuntimeError, match="Database connection error while checking data"
    ):
        manager.check_data()


def test_check_data_error_handling_invalid_connection():
    """Test check_data raises RuntimeError when the connection is closed."""
    conn = duckdb.connect(":memory:")
    manager = DuckDBManager(conn=conn)
    conn.close()

    with pytest.raises(
        RuntimeError, match="Database connection error while checking data"
    ):
        manager.check_data()


def test_check_data_large_number_of_tables(duckdb_manager):
    """Test check_data performance with many tables."""
    # Create many tables
    num_tables = 50
    for i in range(num_tables):
        duckdb_manager.conn.execute(f"CREATE TABLE table_{i:03d} (id INTEGER)")

    tables = duckdb_manager.check_data()
    assert len(tables) == num_tables

    # Verify all tables are present
    expected_tables = [f"table_{i:03d}" for i in range(num_tables)]
    for expected_table in expected_tables:
        assert expected_table in tables


def test_check_data_with_data_vs_empty_tables(duckdb_manager):
    """Test check_data returns tables regardless of whether they contain data."""
    # Create empty table
    duckdb_manager.conn.execute("CREATE TABLE empty_table (id INTEGER, name VARCHAR)")

    # Create table with data
    duckdb_manager.conn.execute("CREATE TABLE filled_table (id INTEGER, name VARCHAR)")
    duckdb_manager.conn.execute(
        "INSERT INTO filled_table VALUES (1, 'test'), (2, 'data')"
    )

    tables = duckdb_manager.check_data()

    # Both tables should be returned regardless of content
    assert "empty_table" in tables
    assert "filled_table" in tables
    assert len(tables) == 2


# ------------------------------------------
# Test cases for get_centroids()
# ------------------------------------------
def test_get_centroids_none_input(duckdb_manager):
    """Test get_centroids raises ValueError when tables is None."""
    with pytest.raises(ValueError, match="No tables provided"):
        duckdb_manager.get_centroids(tables=None)


def test_get_centroids_single_table_string(duckdb_manager, monkeypatch):
    """Test get_centroids with single table name as string."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create a test table with polygon geometries
    duckdb_manager.conn.execute("""
        CREATE TABLE test_polygons (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert test polygon data (using WKT)
    duckdb_manager.conn.execute("""
        INSERT INTO test_polygons VALUES 
        (1, ST_GeomFromText('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))')),
        (2, ST_GeomFromText('POLYGON((3 3, 5 3, 5 5, 3 5, 3 3))'))
    """)

    # Verify data insertion
    count_result = duckdb_manager.conn.execute(
        "SELECT COUNT(*) FROM test_polygons"
    ).fetchone()
    assert count_result[0] == 2

    # Mock save_table_to_geoparquet to avoid file operations
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name="test_polygons_centroids": f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="test_polygons")

    # Verify results
    assert isinstance(result, dict)
    assert "test_polygons_centroids" in result
    assert len(result["test_polygons_centroids"]) == 2

    # Check that centroid table was created
    tables = duckdb_manager.check_data()
    assert "test_polygons_centroids" in tables

    # Verify centroid geometries are points
    centroids = result["test_polygons_centroids"]
    for centroid in centroids:
        wkt = centroid[0]
        assert isinstance(wkt, str)
        assert "POINT" in wkt.upper()


def test_get_centroids_multiple_tables_list(duckdb_manager, monkeypatch):
    """Test get_centroids with multiple table names as list."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create multiple test tables
    for i, table_name in enumerate(["table1", "table2"]):
        duckdb_manager.conn.execute(f"""
            CREATE TABLE {table_name} (
                id INTEGER,
                geometry GEOMETRY
            )
        """)

        # Insert different polygons for each table
        offset = i * 10
        duckdb_manager.conn.execute(f"""
            INSERT INTO {table_name} VALUES 
            (1, ST_GeomFromText('POLYGON(({offset} {offset}, {offset+2} {offset}, {offset+2} {offset+2}, {offset} {offset+2}, {offset} {offset}))')),
            (2, ST_GeomFromText('POLYGON(({offset+3} {offset+3}, {offset+5} {offset+3}, {offset+5} {offset+5}, {offset+3} {offset+5}, {offset+3} {offset+3}))'))
        """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables=["table1", "table2"])

    # Verify results
    assert isinstance(result, dict)
    assert "table1_centroids" in result
    assert "table2_centroids" in result
    assert len(result["table1_centroids"]) == 2
    assert len(result["table2_centroids"]) == 2

    # Check that both centroid tables were created
    tables = duckdb_manager.check_data()
    assert "table1_centroids" in tables
    assert "table2_centroids" in tables


def test_get_centroids_empty_table(duckdb_manager, monkeypatch):
    """Test get_centroids with empty table."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create empty table
    duckdb_manager.conn.execute("""
        CREATE TABLE empty_table (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="empty_table")

    # Verify results
    assert isinstance(result, dict)
    assert "empty_table_centroids" in result
    assert len(result["empty_table_centroids"]) == 0

    # Check that centroid table was created (even if empty)
    tables = duckdb_manager.check_data()
    assert "empty_table_centroids" in tables


def test_get_centroids_point_geometries(duckdb_manager, monkeypatch):
    """Test get_centroids with point geometries (centroid of point is the point itself)."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create table with point geometries
    duckdb_manager.conn.execute("""
        CREATE TABLE test_points (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert test point data
    duckdb_manager.conn.execute("""
        INSERT INTO test_points VALUES 
        (1, ST_GeomFromText('POINT(1 1)')),
        (2, ST_GeomFromText('POINT(5 5)'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="test_points")

    # Verify results
    assert isinstance(result, dict)
    assert "test_points_centroids" in result
    assert len(result["test_points_centroids"]) == 2


def test_get_centroids_line_geometries(duckdb_manager, monkeypatch):
    """Test get_centroids with line geometries."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create table with line geometries
    duckdb_manager.conn.execute("""
        CREATE TABLE test_lines (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert test line data
    duckdb_manager.conn.execute("""
        INSERT INTO test_lines VALUES 
        (1, ST_GeomFromText('LINESTRING(0 0, 2 2)')),
        (2, ST_GeomFromText('LINESTRING(1 1, 3 3, 5 5)'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="test_lines")

    # Verify results
    assert isinstance(result, dict)
    assert "test_lines_centroids" in result
    assert len(result["test_lines_centroids"]) == 2


def test_get_centroids_polygon_geometries(duckdb_manager, monkeypatch):
    """Test get_centroids with polygon geometries."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create table with polygon geometries
    duckdb_manager.conn.execute("""
        CREATE TABLE test_polygons (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert test polygon data
    duckdb_manager.conn.execute("""
        INSERT INTO test_polygons VALUES 
        (1, ST_GeomFromText('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))')),
        (2, ST_GeomFromText('POLYGON((3 3, 5 3, 5 5, 3 5, 3 3))'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="test_polygons")

    # Verify results
    assert isinstance(result, dict)
    assert "test_polygons_centroids" in result
    assert len(result["test_polygons_centroids"]) == 2


def test_get_centroids_mixed_geometry_types(duckdb_manager, monkeypatch):
    """Test get_centroids with mixed geometry types."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create table with mixed geometry types
    duckdb_manager.conn.execute("""
        CREATE TABLE mixed_geoms (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert mixed geometry data
    duckdb_manager.conn.execute("""
        INSERT INTO mixed_geoms VALUES 
        (1, ST_GeomFromText('POINT(1 1)')),
        (2, ST_GeomFromText('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))')),
        (3, ST_GeomFromText('LINESTRING(0 0, 1 1, 2 2)'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="mixed_geoms")

    # Verify results
    assert isinstance(result, dict)
    assert "mixed_geoms_centroids" in result
    assert len(result["mixed_geoms_centroids"]) == 3


def test_get_centroids_replaces_existing_centroid_table(duckdb_manager, monkeypatch):
    """Test get_centroids replaces existing centroid table (CREATE OR REPLACE)."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create original table
    duckdb_manager.conn.execute("""
        CREATE TABLE original_table (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert initial data
    duckdb_manager.conn.execute("""
        INSERT INTO original_table VALUES 
        (1, ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # First call
    result1 = duckdb_manager.get_centroids(tables="original_table")
    assert len(result1["original_table_centroids"]) == 1

    # Add more data
    duckdb_manager.conn.execute("""
        INSERT INTO original_table VALUES 
        (2, ST_GeomFromText('POLYGON((2 2, 3 2, 3 3, 2 3, 2 2))'))
    """)

    # Second call should replace the centroid table
    result2 = duckdb_manager.get_centroids(tables="original_table")
    assert len(result2["original_table_centroids"]) == 2


def test_get_centroids_return_value_structure(duckdb_manager, monkeypatch):
    """Test get_centroids returns correct data structure."""
    # Initialize spatial extension
    duckdb_manager._init_extensions()

    # Create test table
    duckdb_manager.conn.execute("""
        CREATE TABLE struct_test (
            id INTEGER,
            geometry GEOMETRY
        )
    """)

    # Insert test data
    duckdb_manager.conn.execute("""
        INSERT INTO struct_test VALUES 
        (1, ST_GeomFromText('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))'))
    """)

    # Mock save_table_to_geoparquet
    monkeypatch.setattr(
        duckdb_manager,
        "save_table_to_geoparquet",
        lambda table_name: f"/mock/path/{table_name}.parquet",
    )

    # Test the function
    result = duckdb_manager.get_centroids(tables="struct_test")

    # Verify structure
    assert isinstance(result, dict)
    assert "struct_test_centroids" in result
    assert isinstance(result["struct_test_centroids"], list)
    assert isinstance(result["struct_test_centroids"][0], tuple)

    # Check that the tuple contains WKT string
    centroid_wkt = result["struct_test_centroids"][0][0]
    assert isinstance(centroid_wkt, str)
    assert "POINT" in centroid_wkt


def test_get_centroids_without_spatial_extension(duckdb_manager):
    """Test get_centroids raises duckdb.Error when spatial extension is not loaded."""
    # Don't initialize spatial extension
    # Create a regular table
    duckdb_manager.conn.execute("""
        CREATE TABLE test_table (
            id INTEGER,
            geometry VARCHAR  -- Not a geometry type
        )
    """)

    with pytest.raises(
        DuckDBSpatialExtensionError, match="Failed to load spatial extension in DuckDB"
    ):
        duckdb_manager.get_centroids("test_table")


def test_get_centroids_empty_list_input(duckdb_manager):
    """Test get_centroids with empty list."""
    # Empty list should be processed but return empty result
    result = duckdb_manager.get_centroids(tables=[])

    assert isinstance(result, dict)
    assert len(result) == 0


# ------------------------------------------
# _normalize_parquet_value edge cases
# ------------------------------------------


@pytest.mark.unit
def test_normalize_parquet_value_list_unknown_to_mapping_returns_none():
    """A list not in the null-value mapping uses the tuple fallback and returns None.

    Documents that the except clause is intentional for TypeError only —
    unhashable types (list) are converted to tuple for the dict lookup.
    """
    result = DuckDBManager._normalize_parquet_value([1, 2, 3])
    assert result is None


@pytest.mark.unit
def test_normalize_parquet_value_nested_list_returns_none():
    """A nested list (unhashable even as a tuple) falls through to None with a log."""
    # [[1,2],[3,4]] → outer TypeError → tuple(x) = ([1,2],[3,4]) → inner TypeError (lists unhashable)
    result = DuckDBManager._normalize_parquet_value([[1, 2], [3, 4]])
    assert result is None


@pytest.mark.unit
def test_normalize_parquet_value_dict_returned_as_is_when_non_empty():
    """Non-empty dicts are returned unchanged (they are not null-value candidates)."""
    d = {"key": "value"}
    result = DuckDBManager._normalize_parquet_value(d)
    assert result == d


@pytest.mark.unit
def test_normalize_parquet_value_empty_dict_returns_na_none():
    """Empty dict signals missing metadata — mapped to {'NA': None}."""
    result = DuckDBManager._normalize_parquet_value({})
    assert result == {"NA": None}


@pytest.mark.unit
def test_normalize_parquet_value_numpy_float32_returns_none():
    """numpy.float32 scalar is hashable but not in the null-value mapping → returns None."""
    import numpy as np

    result = DuckDBManager._normalize_parquet_value(np.float32(3.14))
    assert result is None


@pytest.mark.unit
def test_normalize_parquet_value_numpy_int64_returns_none():
    """numpy.int64 scalar is hashable but not in the null-value mapping → returns None."""
    import numpy as np

    result = DuckDBManager._normalize_parquet_value(np.int64(42))
    assert result is None


@pytest.mark.unit
def test_save_gdf_to_geoparquet_empty_gdf_raises_value_error(tmp_path, monkeypatch):
    """Passing an empty GeoDataFrame to save_gdf_to_geoparquet must raise ValueError."""
    monkeypatch.setattr(
        "gis_pipeline.modules.db.duckdb_utils.Config.DUCKDB_DATA_DIR", str(tmp_path)
    )
    empty_gdf = gpd.GeoDataFrame()

    with pytest.raises(ValueError):
        DuckDBManager.save_gdf_to_geoparquet(
            gdf=empty_gdf, output_file_name="empty_test"
        )
