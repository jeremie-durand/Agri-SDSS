# tests/test_duckdb.py
import math
import re

import duckdb
import pytest
from demo.config import Config
from demo.duckdb_utils import DuckDBManager
from flask.testing import FlaskClient
from infrastructure.duckdb.app import app as duckdb_app


# -------------------------------
# Helper function
# -------------------------------
def parse_wkt_point(wkt: str):
    """Parse a WKT POINT string into (x, y) floats.

    Args:
        wkt: Well-Known Text representation of geometry.
    """

    match = re.match(r"POINT\s*\(\s*([0-9\.\-eE]+)\s+([0-9\.\-eE]+)\s*\)", wkt)
    if match is None:
        raise ValueError(f"Invalid WKT point: {wkt}")
    return float(match.group(1)), float(match.group(2))


# -------------------------------
# Fixture Flask test client
# -------------------------------
@pytest.fixture
def client():
    """Fixture to create a Flask test client."""
    duckdb_app.config["TESTING"] = True  # Enable testing mode
    with duckdb_app.test_client() as client:
        yield client


# -------------------------------
# Fixture DuckDBManager
# -------------------------------
@pytest.fixture
def db_manager():
    """Fixture to create a DuckDBManager instance for testing."""
    test_conn = duckdb.connect(":memory:")

    manager = DuckDBManager(conn=test_conn)
    manager.init_extensions()
    yield manager
    manager.conn.close()


@pytest.fixture
def db_manager_clean(db_manager: DuckDBManager):
    """Provide a DuckDBManager and clean up tables after the test."""
    yield db_manager
    # Teardown: drop all tables created during tests
    tables = db_manager.conn.execute("SHOW TABLES").fetchall()
    for (table_name,) in tables:
        # Validate table_name to prevent SQL injection
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
            db_manager.conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        else:
            raise ValueError(f"Unsafe table name detected: {table_name}")


# -------------------------------
# API route tests
# -------------------------------
def test_home_status(client: FlaskClient):
    """Test the home route status code."""
    resp = client.get("/")
    assert resp.status_code == 200


def test_home_content(client: FlaskClient):
    """Test the home route content."""
    resp = client.get("/")
    assert b"DuckDB is ready!" in resp.data


def test_fetch_postgis_status(client: FlaskClient):
    """Test the fetch-postgis route status code."""
    resp = client.post("/fetch-postgis")
    assert resp.status_code == 200


def test_fetch_postgis_success(client: FlaskClient):
    """Test the fetch-postgis route JSON status."""
    resp = client.post("/fetch-postgis")
    data = resp.get_json()
    assert data["status"] == "success"


def test_check_data_status(client: FlaskClient):
    """Test the check-data route status code."""
    resp = client.get("/check-data")
    assert resp.status_code == 200


def test_check_data_success(client: FlaskClient):
    """Test the check-data route JSON status."""
    resp = client.get("/check-data")
    data = resp.get_json()
    assert data["status"] == "success"


def test_check_data_result_type(client: FlaskClient):
    """Test the check-data result type."""
    resp = client.get("/check-data")
    data = resp.get_json()
    assert isinstance(data["result"], list)


def test_generate_centroids_status(client: FlaskClient):
    """Test the generate-centroids route status code."""
    resp = client.post("/generate-centroids")
    assert resp.status_code == 200


def test_generate_centroids_success(client: FlaskClient):
    """Test the generate-centroids route JSON status."""
    resp = client.post("/generate-centroids")
    data = resp.get_json()
    assert data["status"] == "success"


# -------------------------------
# DuckDBManager tests
# -------------------------------
@pytest.mark.parametrize(
    "table",
    getattr(Config, "VECTOR_TABLES", []),
)
def test_get_centroids_table_exists_success(
    db_manager_clean: DuckDBManager, table: str
):
    """Test if the centroid table is created for the specified vector table.

    Args:
        db_manager_clean: The DuckDBManager instance.
        table: The name of the vector table.
    """
    if table is None:
        pytest.skip("Skipping empty table name")

    # Create a dummy table for testing
    db_manager_clean.conn.execute(
        f"CREATE OR REPLACE TABLE {table} AS "
        f"SELECT ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))') AS geom"
    )

    db_manager_clean.get_centroids(tables=[table])

    tables_in_db = db_manager_clean.check_data()
    centroid_table = f"{table}_centroids"
    assert (
        centroid_table in tables_in_db
    ), f"Centroid table '{centroid_table}' does not exist"


def test_get_centroids_multiple_polygons(db_manager_clean: DuckDBManager):
    """Test multiple polygons: ensure correct number of centroids is returned."""
    db_manager_clean.conn.execute(
        """
        CREATE OR REPLACE TABLE poly_table AS 
        SELECT ST_GeomFromText('POLYGON((0 0,0 4,4 4,4 0,0 0))') AS geom
        UNION ALL
        SELECT ST_GeomFromText('POLYGON((10 10,10 12,12 12,12 10,10 10))')
    """
    )

    result = db_manager_clean.get_centroids("poly_table")
    centroids = result["poly_table_centroids"]

    # Step 1: Check number of centroids
    expected_coords = [(2.0, 2.0), (11.0, 11.0)]
    assert len(centroids) == len(
        expected_coords
    ), f"Expected {len(expected_coords)} centroids, got {len(centroids)}"

    # Step 2: Check each centroid point by point
    for i, (wkt, (expected_x, expected_y)) in enumerate(
        zip(centroids, expected_coords)
    ):
        # Check it's a POINT
        assert wkt[0].startswith("POINT"), f"Centroid {i} is not a POINT: {wkt[0]}"

        # Parse and check coordinates
        actual_x, actual_y = parse_wkt_point(wkt[0])
        assert math.isclose(
            actual_x, expected_x, rel_tol=1e-6
        ), f"Centroid {i} X coordinate: expected {expected_x}, got {actual_x}"
        assert math.isclose(
            actual_y, expected_y, rel_tol=1e-6
        ), f"Centroid {i} Y coordinate: expected {expected_y}, got {actual_y}"


def test_get_centroids_empty_table(db_manager_clean: DuckDBManager):
    """Test getting centroids from an empty table."""
    db_manager_clean.conn.execute("CREATE OR REPLACE TABLE empty_table (geom GEOMETRY)")

    result = db_manager_clean.get_centroids("empty_table")

    assert result["empty_table_centroids"] == [], "Expected empty list for empty table"
