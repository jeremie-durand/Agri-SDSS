# tests/test_postgresql.py
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy
from sqlalchemy import text

from demo.config import Config


# ------------------------------------------
# Test cases for postgreSQL connection
# ------------------------------------------
def test_postgis_extension_enabled():
    """
    Test if the PostGIS extension is enabled in the PostgreSQL database.
    """
    engine = sqlalchemy.create_engine(
        f"postgresql+psycopg2://{Config.POSTGRES_USER}:{Config.POSTGRES_PASSWORD}@{Config.POSTGRES_HOST}:{Config.POSTGRES_PORT}/{Config.POSTGRES_DB}"
    )

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'postgis';")
        )
        assert result.fetchone() is not None, "PostGIS extension is not enabled."


def test_postgresql_database_connection_returns_successful():
    """
    Test the database connection using the provided credentials.
    """
    try:
        engine = sqlalchemy.create_engine(
            f"postgresql+psycopg2://{Config.POSTGRES_USER}:{Config.POSTGRES_PASSWORD}@{Config.POSTGRES_HOST}:{Config.POSTGRES_PORT}/{Config.POSTGRES_DB}"
        )
        with engine.connect() as connection:
            assert connection is not None, "Connection to the database failed."
    except Exception as e:
        pytest.fail(f"Database connection failed: {e}")


# ------------------------------------------
# Test cases for postgreSQL tables
# ------------------------------------------
@pytest.mark.mocked
@pytest.mark.parametrize("table", ["dummy_table_1", "dummy_table_2"])
def test_postgresql_table_exists_mocked(table):
    """
    Mocked test: Check if a specific table exists in the PostgreSQL database.
    """
    # Patch create_engine to return a mock engine
    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Simulate .scalar() returning True (table exists)
        mock_result.scalar.return_value = True
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        # Now run your logic (it will use the mocks)
        engine = sqlalchemy.create_engine("mocked_url")
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name=:table);"
                ),
                {"table": table},
            )
            exists = result.scalar()
            assert exists, f"Table '{table}' does not exist in the database."


# ------------------------------------------
# Test cases for postgreSQL queries
# ------------------------------------------
@pytest.mark.mocked
@pytest.mark.parametrize("table", ["dummy_table_1", "dummy_table_2"])
def test_postgis_spatial_query_mocked(table):
    """
    Mocked test: Check if a spatial query returns geometry data.
    """
    with patch("sqlalchemy.create_engine") as mock_create_engine:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        # Simulate .fetchone() returning a tuple with dummy WKT geometry
        mock_result.fetchone.return_value = ("POINT(1 2)",)
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        engine = sqlalchemy.create_engine("mocked_url")
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT ST_AsText(geom) FROM {table} LIMIT 1;"))
            row = result.fetchone()
            assert row[0] is not None, f"No geometry found in '{table}'."
