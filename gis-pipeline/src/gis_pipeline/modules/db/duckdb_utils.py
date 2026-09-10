import re
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import structlog
from gis_pipeline.core.config import Config
from gis_pipeline.core.logging_setup import handle_error
from gis_pipeline.services.mapping import (
    ColumnMappings,
    NamingPatterns,
)

logger = structlog.get_logger()


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

    @staticmethod
    def _load_spatial_extension(conn: duckdb.DuckDBPyConnection) -> None:
        """Install and load the spatial extension on the given connection.

        Raises:
            DuckDBSpatialExtensionError: If loading the extension fails.
        """
        try:
            conn.execute("INSTALL spatial")
        except duckdb.IOException:
            logger.debug("Spatial extension already installed.")

        try:
            conn.execute("LOAD spatial")
        except duckdb.Error:
            error_msg = "Failed to load spatial extension in DuckDB"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=DuckDBSpatialExtensionError,
            )

    def _init_extensions(self) -> None:
        """Install/load spatial extension."""
        DuckDBManager._load_spatial_extension(self.conn)

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
        except RuntimeError:
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            raise
        except Exception as e:
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            error_msg = f"Unexpected error saving DataFrame to Parquet: {e}"
            handle_error(
                logger=logger,
                error_msg=error_msg,
                exc_class=RuntimeError,
            )

    @staticmethod
    def _resolve_column_alias_gdf(
        gdf_copy: gpd.GeoDataFrame, col: str
    ) -> gpd.GeoDataFrame:
        """Apply column alias resolution for one non-geometry column of a GeoDataFrame.

        Args:
            gdf_copy: Working copy of the GeoDataFrame (modified in place).
            col: Column name to check against ColumnMappings.

        Returns:
            The (possibly modified) GeoDataFrame copy.

        Raises:
            ValueError: If the alias and canonical columns contain conflicting values.
        """
        mapping = ColumnMappings.find(col.lower().strip())
        if not (mapping and mapping.value.canonical != col):
            return gdf_copy

        canonical_name = mapping.value.canonical
        # Only rename if canonical name doesn't already exist (avoid duplicates)
        if canonical_name not in gdf_copy.columns:
            gdf_copy.rename(columns={col: canonical_name}, inplace=True)
            logger.info(
                f"Renamed column '{col}' to '{canonical_name}' during Parquet export"
            )
        else:
            # Both alias and canonical exist — compare values to decide
            alias_vals = gdf_copy[col].reset_index(drop=True)
            canonical_vals = gdf_copy[canonical_name].reset_index(drop=True)
            if alias_vals.equals(canonical_vals):
                gdf_copy.drop(columns=[col], inplace=True)
                logger.info(
                    f"Dropped redundant alias column '{col}' — identical to canonical '{canonical_name}'"
                )
            else:
                error_msg = (
                    f"Column conflict: alias '{col}' and canonical '{canonical_name}' "
                    f"contain different values. Cannot determine authoritative source."
                )
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        return gdf_copy

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

            # Apply column normalization to rename ID column aliases to canonical names
            for col in gdf_copy.columns:
                # Skip geometry column
                if col == gdf_copy.geometry.name:
                    continue
                gdf_copy = DuckDBManager._resolve_column_alias_gdf(gdf_copy, col)

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
                f"Size: {file_size:,} bytes, Rows: {len(gdf):,}",
                table=output_file_name,
            )

        except (OSError, IOError) as e:
            error_msg = f"File system error saving GeoDataFrame to GeoParquet: {e}"
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        except duckdb.Error as e:
            error_msg = f"Unexpected error saving GeoDataFrame to GeoParquet: {e}"
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    @staticmethod
    def finalize_chunked_geoparquet(table: str) -> None:
        """Combine a table's per-chunk staged Parquet files into one final file.

        Reads every part*.parquet file staged under
        Config.DUCKDB_DATA_DIR/.chunks/<table>/ (written once per chunk by
        save_gdf_to_geoparquet, via _process_spatial_table's chunk_index
        handling) and combines them into a single <table>.parquet using the
        same tmp-file-then-atomic-rename idiom as every other export in this
        class, then removes the staging directory.

        Args:
            table: Table name whose staged chunks should be combined.

        Raises:
            RuntimeError: If no staged chunk files are found, or the combine
                query fails.
        """
        staging_dir = Path(Config.DUCKDB_DATA_DIR) / ".chunks" / table
        chunk_files = sorted(staging_dir.glob("*.parquet"))
        if not chunk_files:
            error_msg = (
                f"No staged chunk files found for table '{table}' in {staging_dir}"
            )
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

        parquet_path = Path(Config.DUCKDB_DATA_DIR) / f"{table}.parquet"
        tmp_path = parquet_path.with_suffix(".tmp")
        chunk_glob = str(staging_dir / "*.parquet")

        conn = duckdb.connect()
        try:
            DuckDBManager._load_spatial_extension(conn)
            conn.execute(
                f"COPY (SELECT * FROM read_parquet('{chunk_glob}')) "
                f"TO '{tmp_path}' (FORMAT 'parquet')"
            )
        except duckdb.Error as e:
            error_msg = f"Failed to combine chunked GeoParquet for table '{table}': {e}"
            DuckDBManager._cleanup_temp_file(tmp_path=tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
        finally:
            conn.close()

        tmp_path.replace(parquet_path)

        for chunk_file in chunk_files:
            chunk_file.unlink()
        staging_dir.rmdir()

        logger.info(
            "chunked_geoparquet_finalized",
            table=table,
            output_path=str(parquet_path),
            chunk_count=len(chunk_files),
        )

    def _build_select_with_aliases(
        self, column_names: list[str], table_name: str
    ) -> list[str]:
        """Build a SELECT column list with alias-to-canonical renaming for DuckDB export.

        Args:
            column_names: Ordered column names from the DuckDB table.
            table_name: Unescaped table name (used in queries and log messages).

        Returns:
            List of SELECT column expressions, each either a bare escaped name or
            ``escaped_alias AS escaped_canonical``.

        Raises:
            ValueError: If an alias and canonical column contain conflicting values.
        """
        escaped_table = self.escape_duckdb(table_name)
        # Build SELECT clause with column renaming.
        # assigned_canonicals tracks canonical names already committed to the SELECT
        # so that a second alias mapping to the same canonical is treated as a conflict.
        select_columns: list[str] = []
        assigned_canonicals: dict[str, str] = (
            {}
        )  # canonical -> original col already in SELECT
        for col in column_names:
            norm = col.lower().strip()
            mapping = ColumnMappings.find(norm)
            if mapping and mapping.value.canonical != col:
                canonical_name = mapping.value.canonical
                # Determine the column to compare against: either an explicit canonical
                # column in the table, or a previously-assigned alias.
                existing_col = (
                    canonical_name
                    if canonical_name in column_names
                    else assigned_canonicals.get(canonical_name)
                )
                if existing_col is not None:
                    # A column already occupies this canonical slot — compare values
                    count_diff = self.conn.execute(
                        f"SELECT COUNT(*) FROM {escaped_table} "
                        f"WHERE {self.escape_duckdb(col)} IS DISTINCT FROM {self.escape_duckdb(existing_col)}"
                    ).fetchone()[0]
                    if count_diff == 0:
                        # Alias is redundant — skip it
                        logger.info(
                            f"Dropped redundant alias column '{col}' in table '{table_name}' "
                            f"— identical to canonical '{canonical_name}'"
                        )
                    else:
                        error_msg = (
                            f"Column conflict in table '{table_name}': alias '{col}' and "
                            f"canonical '{canonical_name}' (held by '{existing_col}') "
                            f"contain {count_diff} differing row(s). Cannot determine authoritative source."
                        )
                        handle_error(
                            logger=logger, error_msg=error_msg, exc_class=ValueError
                        )
                else:
                    select_columns.append(
                        f"{self.escape_duckdb(col)} AS {self.escape_duckdb(canonical_name)}"
                    )
                    assigned_canonicals[canonical_name] = col
                    logger.info(
                        f"Renaming column '{col}' to '{canonical_name}' during table export from '{table_name}'"
                    )
            else:
                select_columns.append(self.escape_duckdb(col))
        return select_columns

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

            # Get column list and build SELECT with column renaming for ID aliases
            columns_result = self.conn.execute(
                f"DESCRIBE {escaped_table_name}"
            ).fetchall()
            column_names = [row[0] for row in columns_result]

            select_clause = ", ".join(
                self._build_select_with_aliases(column_names, table_name)
            )

            logger.debug(
                f"Exporting table '{table_name}' to temporary file: {tmp_path}"
            )
            self.conn.execute(
                f"COPY (SELECT {select_clause} FROM {escaped_table_name}) TO '{str(tmp_path)}' (FORMAT 'parquet')"
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

        except ValueError:
            self._cleanup_temp_file(tmp_path)
            raise
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
        except RuntimeError:
            self._cleanup_temp_file(tmp_path)
            raise
        except Exception:
            error_msg = f"Unexpected error saving table '{table_name}' to Parquet"
            self._cleanup_temp_file(tmp_path)
            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)
