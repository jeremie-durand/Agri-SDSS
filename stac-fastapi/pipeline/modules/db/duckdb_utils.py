import re
from pathlib import Path
from typing import Dict, List, Tuple, Union

import duckdb
import geopandas as gpd
import pandas as pd
from pipeline.config import Config
from pipeline.logging_setup import handle_error, setup_logging
from pipeline.mapping import AttributeNullValues, NamingPatterns

logger = setup_logging()


class DuckDBSpatialExtensionError(duckdb.Error):
    """Raised when the DuckDB spatial extension cannot be loaded."""

    pass


class DuckDBManager:
    def __init__(self, conn: duckdb.DuckDBPyConnection | None = None):
        """Initialize the DuckDBManager with a persistent connection."""
        self.conn = conn or duckdb.connect(database=Config.DUCKDB_DATABASE)
        self._init_extensions()

    def __enter__(self):
        """Support for context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection when exiting context."""
        self.conn.close()

    def _init_extensions(self) -> None:
        """Install/load spatial extension."""
        try:
            self.conn.execute("INSTALL spatial")
            logger.info("DuckDB spatial extension installed.")
        except duckdb.IOException:
            logger.info("Spatial extension already installed.")

        try:
            self.conn.execute("LOAD spatial")
            logger.info("DuckDB spatial extension loaded.")
        except duckdb.Error:
            error_msg = "Failed to load spatial extension in DuckDB"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=DuckDBSpatialExtensionError,
            )

    @staticmethod
    def _normalize_parquet_value(x: object) -> object:
        """Helper function to normalize values for Parquet compatibility.

        Args:
            x: The value to normalize. Expected common types:
               - dict: metadata-like objects (empty dict -> {"NA": None})
               - str: attribute keys looked up in AttributeNullValues mapping
               - tuple/list: sequences (lists are unhashable; function will try tuple fallback)
               - other scalar types

        Returns:
            The normalized value. If the mapping does not contain the key, returns None.
        """
        if isinstance(x, dict):
            return {"NA": None} if len(x) == 0 else x

        mapping: dict = {m.value: None for m in AttributeNullValues}

        try:
            # Try direct lookup
            return mapping.get(x, None)
        except TypeError:
            try:
                # Try tuple fallback for unhashable types (e.g., lists)
                return mapping.get(tuple(x), None)
            except Exception:
                logger.exception(f"Failed to normalize value: {x}")
                return None

    @staticmethod
    def _cleanup_temp_file(tmp_path: Path) -> None:
        """Helper function to clean up temporary file if it exists.

        Args:
            tmp_path: Path to the temporary file to clean up.
        """
        try:
            if tmp_path.exists():
                tmp_path.unlink()
                logger.info(f"Cleaned up temporary file: {tmp_path}")
        except duckdb.Error as cleanup_error:
            error_msg = f"Failed to clean up temporary file {tmp_path}: {cleanup_error}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def _check_geometry_column(self, table: str) -> None:
        """Helper function to check if the specified table has a 'geometry' column.

        Args:
            table: Name of the DuckDB table to check.
        """
        try:
            columns_result = self.conn.execute(f"DESCRIBE {table}").fetchall()
            column_names = [row[0] for row in columns_result]
            if "geometry" not in column_names:
                error_msg = f"Table '{table}' does not have a 'geometry' column"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except duckdb.Error as e:
            error_msg = (
                f"Error describing table '{table}', cannot check geometry column: {e}"
            )
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def _compute_and_save_centroid(self, table: str) -> tuple[str, list, str]:
        """Compute centroid table for a single table, save it to Parquet file.

        Args:
            table: Name of the DuckDB table to process.

        Returns:
            A tuple containing:
                - The name of the centroid table created.
                - A list of centroid geometries as WKT strings.
                - The path to the saved Parquet file.
        """
        if not re.match(NamingPatterns.PATTERN_DUCKDB_NAME.value, table):
            error_msg = f"Invalid table name: {table}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        centroid_table = f"{table}_centroids"
        logger.info(f"Creating centroid table: {centroid_table}")

        existing_tables = self.check_data()
        if table not in existing_tables:
            error_msg = f"Table '{table}' does not exist in the database."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Properly escape table names
        escaped_table = self.escape_duckdb(table)
        centroid_table_escaped = self.escape_duckdb(centroid_table)

        # Check if geometry column exists
        self._check_geometry_column(escaped_table)

        # Create centroid table
        self.conn.execute(
            f"""
            CREATE OR REPLACE TABLE {centroid_table_escaped} AS
            SELECT ST_AsText(ST_Centroid(geometry)) AS centroid_wkt
            FROM {escaped_table}
            """
        )

        # Read results and save
        result = self.conn.execute(f"SELECT * FROM {centroid_table_escaped}").fetchall()

        output_path = self.save_table_to_geoparquet(table_name=centroid_table)
        logger.info(
            f"Computed and stored {len(result)} centroids in table: {output_path}"
        )

        return centroid_table, result, output_path

    @staticmethod
    def escape_duckdb(name: str) -> str:
        """Escape a DuckDB identifier (e.g., table or column name).

        Args:
            name: The identifier to escape.

        Returns:
            The escaped identifier.
        """
        if not name:
            error_msg = "Identifier name must be provided"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        escaped = name.replace('"', '""')

        return f'"{escaped}"'

    @staticmethod
    def save_df_to_parquet(
        df: pd.DataFrame,
        output_file_name: str,
        engine: str = "pyarrow",
        overwrite: bool = True,
    ):
        """Save a DataFrame to a Parquet file.

        Args:
            df: The DataFrame to save.
            output_file_name: The name of the output Parquet file (without extension).
            engine: The Parquet engine to use.
            overwrite: Whether to overwrite existing files.
        """
        if not output_file_name or not output_file_name.strip():
            error_msg = "Output file name must not be empty"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=ValueError,
            )

        if df.empty:
            error_msg = "Cannot save empty DataFrame"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        parquet_path = Path(Config.DUCKDB_DATA_DIR) / f"{output_file_name}.parquet"
        tmp_path = parquet_path.with_suffix(".tmp")

        try:
            if parquet_path.exists() and not overwrite:
                logger.warning(
                    f"File '{parquet_path}' already exists and overwrite=False. Skipping save."
                )
                return

            df.to_parquet(tmp_path, engine=engine, index=False)

            tmp_path.replace(parquet_path)

            if not parquet_path.exists():
                error_msg = (
                    f"Parquet file '{parquet_path}' was not created after rename."
                )
                handle_error(
                    logger=logger,
                    error_msg=error_msg,
                    exc_class=RuntimeError,
                )

            file_size = parquet_path.stat().st_size
            logger.info(
                f"DataFrame saved to Parquet '{parquet_path}' successfully. "
                f"Size: {file_size:,} bytes, Rows: {len(df):,}"
            )
        except (OSError, IOError) as e:
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            error_msg = f"File system error saving DataFrame to Parquet: {e}"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=RuntimeError,
            )
        except Exception as e:
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            error_msg = f"Unexpected error saving DataFrame to Parquet: {e}"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=RuntimeError,
            )

    @staticmethod
    def save_gdf_to_geoparquet(
        gdf: gpd.GeoDataFrame,
        output_file_name: str,
        engine: str = "pyarrow",
        overwrite: bool = True,
    ):
        """Save a GeoDataFrame to a GeoParquet file.

        Args:
            gdf: The GeoDataFrame to save.
            output_file_name: The name of the output GeoParquet file (without extension).
            engine: The Parquet engine to use.
            overwrite: Whether to overwrite existing files.
        """
        if not output_file_name or not output_file_name.strip():
            error_msg = "Output file name must not be empty"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        if gdf.empty:
            error_msg = "Cannot save empty GeoDataFrame"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        parquet_path = Path(Config.DUCKDB_DATA_DIR) / f"{output_file_name}.parquet"
        tmp_path = parquet_path.with_suffix(".tmp")

        if parquet_path.exists() and overwrite is not True:
            error_msg = f"File '{parquet_path}' already exists and overwrite=False"
            handle_error(logger=logger, error_msg=error_msg, exc_class=FileExistsError)

        try:
            tmp_path.parent.mkdir(parents=True, exist_ok=True)

            if tmp_path.exists():
                logger.warning(f"Removing existing temp file: {tmp_path}")
                tmp_path.unlink()

            gdf_copy = gdf.copy()

            for col in gdf.columns:
                # Skip geometry column (keep original geometry)
                if col == gdf.geometry.name:
                    continue

                # Only handle object-dtype columns for normalization
                if gdf[col].dtype == "object":
                    # Create a normalized column and keep the original column untouched
                    norm_col = f"{col}_normalized"
                    gdf[norm_col] = gdf[col].apply(
                        DuckDBManager._normalize_parquet_value
                    )
                    logger.warning(
                        f"Created normalized column '{norm_col}' from '{col}' for Parquet compatibility."
                    )

            # Ensure output directory exists
            Path(Config.DUCKDB_DATA_DIR).mkdir(parents=True, exist_ok=True)

            # Use a temporary file and then rename to avoid partial writes
            parquet_path = Path(Config.DUCKDB_DATA_DIR) / f"{output_file_name}.parquet"
            tmp_path = parquet_path.with_suffix(".tmp")

            # Save to GeoParquet
            gdf_copy.to_parquet(tmp_path, engine=engine, index=False)

            if not tmp_path.exists():
                error_msg = f"Temporary file '{tmp_path}' was not created."
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

            tmp_path.replace(parquet_path)

            if not parquet_path.exists():
                error_msg = f"Failed to create GeoParquet file at '{parquet_path}'."
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

            file_size = parquet_path.stat().st_size
            logger.info(
                f"GeoDataFrame saved to GeoParquet '{parquet_path}' successfully. "
                f"Size: {file_size:,} bytes, Rows: {len(gdf):,}"
            )

        except (OSError, IOError) as e:
            error_msg = f"File system error saving GeoDataFrame to GeoParquet: {e}"
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except duckdb.Error as e:
            error_msg = f"Unexpected error saving GeoDataFrame to GeoParquet: {e}"
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def save_table_to_geoparquet(self, table_name: str, overwrite: bool = True) -> str:
        """Save a DuckDB table to a Parquet file.

        Args:
            table_name: Name of the DuckDB table to save.

        Returns:
            The path to the saved Parquet file.
        """
        if not re.match(NamingPatterns.PATTERN_DUCKDB_NAME.value, table_name):
            error_msg = f"Invalid table name: {table_name}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        output_path = Path(Config.DUCKDB_DATA_DIR) / f"{table_name}.parquet"
        tmp_path = output_path.with_suffix(".tmp")

        if output_path.exists() and not overwrite:
            error_msg = f"File '{output_path}' already exists and overwrite=False"
            handle_error(logger=logger, error_msg=error_msg, exc_class=FileExistsError)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if tmp_path.exists():
                logger.warning(f"Removing existing temp file: {tmp_path}")
                tmp_path.unlink()

            escaped_table_name = self.escape_duckdb(table_name)

            logger.debug(
                f"Exporting table '{table_name}' to temporary file: {tmp_path}"
            )
            self.conn.execute(
                f"COPY (SELECT * FROM {escaped_table_name}) TO '{str(tmp_path)}' (FORMAT 'parquet')"
            )

            if not tmp_path.exists():
                error_msg = f"Temporary file '{tmp_path}' was not created"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

            # Move temp file to final output path
            tmp_path.replace(output_path)

            if not output_path.exists():
                error_msg = f"Failed to create Parquet file at '{output_path}'"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

            file_size = output_path.stat().st_size
            logger.info(
                f"Table '{table_name}' saved to Parquet at: {output_path} (Size: {file_size:,} bytes)"
            )
            return str(output_path)

        except duckdb.CatalogException:
            error_msg = f"Table '{table_name}' does not exist in database"
            self._cleanup_temp_file(tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except duckdb.Error as e:
            error_msg = f"DuckDB error saving table '{table_name}' to Parquet: {e}"
            self._cleanup_temp_file(tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except (OSError, IOError) as e:
            error_msg = f"File system error saving table '{table_name}' to Parquet: {e}"
            self._cleanup_temp_file(tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except Exception:
            error_msg = f"Unexpected error saving table '{table_name}' to Parquet"
            self._cleanup_temp_file(tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def check_data(self) -> list[str]:
        """Check all data in DuckDB and return a list of all table names.

        Returns:
            A list of all table names in the DuckDB database.
        """
        try:
            result = self.conn.execute("SHOW TABLES;").fetchall()
            table_names = [row[0] for row in result]
            logger.debug(f"Found {len(table_names)} tables in database")
            return table_names
        except duckdb.ConnectionException as e:
            error_msg = f"Database connection error while checking data: {e}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except duckdb.Error as e:
            error_msg = f"DuckDB error while checking data: {e}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except Exception:
            error_msg = "Unexpected error while checking data"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

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
            error_msg = "No tables provided for centroid computation"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        tables = [tables] if isinstance(tables, str) else tables
        centroids: Dict[str, list[Tuple]] = {}

        try:
            for table in tables:
                centroid_table, centroid_data, output_path = (
                    self._compute_and_save_centroid(table=table)
                )
                centroids[centroid_table] = centroid_data
                logger.info(f"Centroids for table '{table}' saved to '{output_path}'")

            return centroids

        except ValueError:
            error_msg = f"ValueError computing centroids for tables {tables}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        except duckdb.BinderException as e:
            # Intercepte l'absence de spatial extension ou de fonction ST_Centroid
            if "ST_Centroid" in str(e) or "function matches the given name" in str(e):
                error_msg = f"Failed to load spatial extension in DuckDB: {e}"
                handle_error(
                    logger=logger,
                    error_msg=error_msg,
                    exc_class=DuckDBSpatialExtensionError,
                )
            else:
                error_msg = (
                    f"SQL binding error computing centroids for tables {tables}: {e}"
                )
                handle_error(logger=logger, error_msg=error_msg, exc_class=duckdb.Error)

        except duckdb.ConnectionException as e:
            error_msg = f"Database connection error computing centroids for tables {tables}: {e}"
            handle_error(
                logger=logger, error_msg=error_msg, exc_class=duckdb.ConnectionException
            )

        except duckdb.Error as e:
            error_msg = f"DuckDB error computing centroids for tables {tables}: {e}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=duckdb.Error)

        except Exception:
            error_msg = f"Unexpected error computing centroids for tables {tables}"
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
