# demo/duckdb_utils.py
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple, Union

import duckdb
from demo.config import Config
from demo.init_postgis import connect_to_postgis, read_data_postgis
from demo.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


class DuckDBManager:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None):
        """Initialize the DuckDBManager with a persistent connection."""
        if conn is None:
            if not hasattr(Config, 'DUCKDB_DATABASE') or Config.DUCKDB_DATABASE is None:
                raise ValueError(
                    "Config.DUCKDB_DATABASE is not set. "
                    "Please check your configuration or provide a connection explicitly."
                )
            self.conn = duckdb.connect(Config.DUCKDB_DATABASE)
        else:
            self.conn = conn

    def __enter__(self):
        """Support for context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection when exiting context."""
        self.conn.close()

    def init_extensions(self) -> None:
        """Install/load spatial extension."""
        try:
            self.conn.execute("INSTALL spatial")
            logger.info("DuckDB spatial extension installed.")
        except duckdb.IOException:
            logger.info("Spatial extension already installed.")

        try:
            self.conn.execute("LOAD spatial")
            logger.info("DuckDB spatial extension loaded.")
        except Exception as e:
            raise RuntimeError(f"Error loading spatial extension: {e}") from e

    @staticmethod
    def _validate_table_name(table_name: str) -> str:
        """Validate and safely return a DuckDB table name.

        Args:
            table_name: The name of the DuckDB table to validate.

        Returns:
            A validated and safely quoted DuckDB table name.
        """
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name) is None:
            raise ValueError(f"Invalid table name: {table_name}")
        return f'"{table_name}"'  # wrap in quotes to prevent SQL injection

    @staticmethod
    def _escape_sql_string(value: str) -> str:
        """Escape single quotes in strings for safe SQL usage.

        Args:
            value: The SQL string to escape.

        Returns:
            The escaped SQL string.
        """
        return value.replace("'", "''")

    def export_table_to_parquet(self, table_name: str, output_path: Path) -> None:
        """Export a DuckDB table to Parquet format.

        Args:
            table_name: The name of the DuckDB table to export.
            output_path: The file path to save the Parquet file.
        """
        try:
            safe_table_name = self._validate_table_name(table_name=table_name)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            safe_output_path = self._escape_sql_string(value=str(output_path))

            row_count = self.conn.execute(
                f"SELECT COUNT(*) FROM {safe_table_name}"
            ).fetchone()[0]

            if row_count == 0:
                logger.warning(f"Table '{table_name}' is empty. Skipping export.")
                return

            self.conn.execute(
                f"COPY {safe_table_name} TO '{safe_output_path}' (FORMAT PARQUET);"
            )
            logger.info(
                f"Saved DuckDB table '{safe_table_name}' to Parquet: {output_path}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Error exporting table '{table_name}' to Parquet: {e}"
            ) from e

    def fetch_postgis(self, tables: Union[List[str], str]) -> None:
        """Fetch data from PostGIS tables and save them as Parquet files in DuckDB.

        Args:
            tables: List of table names or a single table name to fetch from
        """
        pg_engine = connect_to_postgis(
            user=Config.POSTGRES_USER,
            password=Config.POSTGRES_PASSWORD,
            host=Config.POSTGRES_HOST,
            port=Config.POSTGRES_PORT,
            db=Config.POSTGRES_DB,
        )
        tables = [tables] if isinstance(tables, str) else tables

        try:
            for table in tables:
                safe_table_name = self._validate_table_name(table_name=table)
                output_path = (
                    Path(Config.DUCKDB_DATA_DIR) / f"{safe_table_name}.parquet"
                )

                data = read_data_postgis(engine=pg_engine, table_name=table)
                data.to_parquet(path=output_path, index=False)

                safe_output_path = self._escape_sql_string(
                    value=str(output_path)
                )
                self.conn.execute(
                    f"CREATE OR REPLACE TABLE {safe_table_name} AS SELECT * FROM read_parquet('{safe_output_path}')"
                )
                logger.info(f"Saved and registered {safe_table_name} in DuckDB")
        except Exception as e:
            raise RuntimeError(f"Error fetching table {tables}: {e}") from e
        finally:
            pg_engine.dispose()

    def check_data(self) -> list[str]:
        """Check all data in DuckDB and return a list of all table names.

        Returns:
            A list of all table names in the DuckDB database.
        """
        try:
            result = self.conn.execute(
                "SELECT * FROM information_schema.tables WHERE table_schema = 'main';"
            ).fetchall()
            return [row[2] for row in result]
        except Exception as e:
            raise RuntimeError(f"Error checking data: {e}") from e

    def save_table_to_parquet(self, table_name: str) -> Path:
        """Save a single DuckDB table to a Parquet file for reproducibility.

        Args:
            table_name: Name of the DuckDB table to save

        Returns:
            The file path to the saved Parquet file.
        """
        output_path = Path(Config.DUCKDB_DATA_DIR) / f"{table_name}.parquet"
        self.export_table_to_parquet(table_name, output_path)
        return output_path

    def save_all_tables_to_parquet(self, variable: str) -> list[Path]:
        """Save all DuckDB tables with the given suffix to Parquet files for reproducibility.

        Args:
            variable: Suffix to identify tables to save.

        Returns:
            A list of Paths to the saved Parquet files.

        Notes:
            For example, if variable="centroids", it saves tables like "table_centroids".
        """
        tables = (
            [Config.VECTOR_TABLES]
            if isinstance(Config.VECTOR_TABLES, str)
            else Config.VECTOR_TABLES
        )
        output_paths: list[Path] = []
        for table in tables:
            table_name = f"{table}_{variable}"
            output_path = self.save_table_to_parquet(table_name)
            output_paths.append(output_path)
        return output_paths

    def get_centroids(self, tables: Union[List[str], str]) -> Dict[str, list[Tuple]]:
        """Compute centroids of polygon geometries in DuckDB tables,

        Args:
            tables: List of table names or a single table name to process.

        Returns:
            A dictionary mapping centroid table names to their centroid geometries.

        Notes:
            Create new tables named '{table}_centroids' to store them,
            and save the centroid tables to Parquet files.
        """
        if tables is None:
            raise ValueError("No tables provided")
        
        tables = [tables] if isinstance(tables, str) else tables
        centroids: Dict[str, list[Tuple]] = {}

        try:
            for table in tables:
                centroid_table = f"{table}_centroids"
                logger.info(f"Creating centroid table: {centroid_table}")
                self.conn.execute(
                    f"""
                    CREATE OR REPLACE TABLE "{centroid_table}" AS
                    SELECT ST_AsText(ST_Centroid(geom)) AS centroid_wkt
                    FROM "{table}"
                    """
                )
                result = self.conn.execute(f"SELECT * FROM {centroid_table}").fetchall()
                centroids[centroid_table] = result
                output_path = self.save_table_to_parquet(centroid_table)
                logger.info(
                    f"Computed and stored {len(result)} centroids in table: {output_path}"
                )
            return centroids
        except Exception as e:
            raise RuntimeError(
                f"Error computing centroids for tables {tables}: {e}"
            ) from e
