"""DuckDB Manager for Vector API - Parquet/GeoParquet support.

This module provides functionality to query GeoParquet files using DuckDB's
spatial extension, enabling the Vector API to expose Parquet datasets alongside
PostGIS collections.

Adapted from gis-pipeline/src/gis_pipeline/modules/db/duckdb_utils.py
"""

import logging
import os
import re
import threading
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import duckdb

from .materialize import MATERIALIZED_TABLE_NAME

logger = logging.getLogger(__name__)

# Strict pattern for collection IDs to prevent path traversal
COLLECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


class DuckDBDescribeColumn(IntEnum):
    """Column indices for DuckDB DESCRIBE query result.

    DuckDB's DESCRIBE returns a row per column with this structure:
    (column_name, column_type, null, key, default, extra)

    Reference: https://duckdb.org/docs/sql/statements/describe.html
    """

    NAME = 0
    TYPE = 1
    NULL = 2
    KEY = 3
    DEFAULT = 4
    EXTRA = 5


class ColumnInfo(TypedDict):
    """Type definition for column information dictionary."""

    name: str
    type: str


class ParquetSchemaInfo(TypedDict):
    """Type definition for Parquet schema information dictionary.

    Returned by get_parquet_schema() to describe a Parquet file's structure.
    """

    columns: List[ColumnInfo]
    id_column: Optional[str]
    geometry_column: Optional[str]
    has_geometry: bool
    feature_count: int
    bbox: Optional[List[float]]  # [minx, miny, maxx, maxy]


class DuckDBSpatialExtensionError(duckdb.Error):
    """Raised when the DuckDB spatial extension cannot be loaded."""

    pass


class DuckDBManager:
    """Manager for DuckDB operations on Parquet/GeoParquet files."""

    # Common ID column names to auto-detect (in priority order)
    ID_COLUMN_CANDIDATES = ["gid", "id", "fid", "ogc_fid", "objectid"]

    # Common geometry column names to auto-detect (in priority order)
    GEOMETRY_COLUMN_CANDIDATES = [
        "geometry",
        "geom",
        "the_geom",
        "shape",
        "wkb_geometry",
    ]

    def __init__(self, data_dir: Optional[str] = None):
        """Initialize the DuckDBManager with an in-memory connection.

        Args:
            data_dir: Directory containing Parquet files. Defaults to DUCKDB_DATA_DIR env var.
        """
        self.data_dir = Path(data_dir or os.getenv("DUCKDB_DATA_DIR", "/data/duckdb"))
        self.conn = duckdb.connect(database=":memory:")
        # DuckDB in-memory connections are not thread-safe; a single shared
        # connection requires serialised access.
        self._lock = threading.Lock()
        # Schema cache: collection_id -> ParquetSchemaInfo.
        # Parquet files are immutable so entries never need invalidation.
        # Populated lazily on first access; protected by self._lock.
        self._schema_cache: Dict[str, ParquetSchemaInfo] = {}
        # Lazily-opened read-only connections to materialized, RTree-indexed
        # collections (see materialize.py). A collection becomes materialized
        # purely by having a <collection_id>.duckdb file in data_dir -- there
        # is no allowlist. Keyed by collection_id; each entry pairs a
        # connection with its own lock since it is a distinct DuckDB
        # connection object from self.conn.
        self._materialized_conns: Dict[
            str, Tuple[duckdb.DuckDBPyConnection, threading.Lock]
        ] = {}
        # Collection IDs whose .duckdb file exists but failed to open or
        # failed the validity probe during this process's lifetime -- avoids
        # retrying (and re-logging) on every request for a persistently
        # broken file. Cleared per-collection by invalidate_materialized()
        # after an external rebuild.
        self._failed_materialized: set = set()
        self._init_extensions()

    def __enter__(self):
        """Support for context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """No-op: the shared singleton connection must not be closed by callers.

        Call close() explicitly only during application shutdown.
        """

    def close(self) -> None:
        """Explicitly close the DuckDB connection(s). Use only on shutdown."""
        self.conn.close()
        for conn, _ in self._materialized_conns.values():
            conn.close()
        self._materialized_conns.clear()
        self._failed_materialized.clear()

    def _init_extensions(self) -> None:
        """Install and load spatial extension."""
        try:
            self.conn.execute("INSTALL spatial")
            logger.info("DuckDB spatial extension installed.")
        except duckdb.IOException:
            logger.debug("Spatial extension already installed.")

        try:
            self.conn.execute("LOAD spatial")
            logger.info("DuckDB spatial extension loaded.")
        except duckdb.Error as e:
            logger.error(f"Failed to load spatial extension in DuckDB: {e}")
            raise DuckDBSpatialExtensionError(
                "Failed to load spatial extension in DuckDB"
            ) from e

    @staticmethod
    def escape_identifier(name: str) -> str:
        """Escape a DuckDB identifier (e.g., table or column name).

        Args:
            name: The identifier to escape.

        Returns:
            The escaped identifier.
        """
        if not name:
            raise ValueError("Identifier name must be provided")
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    @staticmethod
    def _escape_sql_string(value: str) -> str:
        """Escape a string value for safe embedding in a SQL string literal.

        Single quotes are doubled (SQL standard), so a path like
        ``/data/it's data/file.parquet`` becomes
        ``/data/it''s data/file.parquet`` and can be placed inside
        surrounding single quotes without breaking the query.

        Args:
            value: The raw string to escape (e.g. a file-system path).

        Returns:
            The escaped string, safe to embed between single quotes in SQL.
        """
        return value.replace("'", "''")

    @staticmethod
    def _fetchone_unlocked(
        conn: duckdb.DuckDBPyConnection, query: str, params: Optional[list] = None
    ) -> Optional[tuple]:
        """Execute a query and return the first row. Caller must hold the connection's lock."""
        cursor = conn.execute(query, params) if params else conn.execute(query)
        return cursor.fetchone()

    @staticmethod
    def _fetchall_unlocked(
        conn: duckdb.DuckDBPyConnection, query: str, params: Optional[list] = None
    ) -> Tuple[List[tuple], List[str]]:
        """Execute a query and return (rows, column_names). Caller must hold the connection's lock."""
        conn.execute(query, params) if params else conn.execute(query)
        rows = conn.fetchall()
        column_names = (
            [desc[0] for desc in conn.description] if conn.description else []
        )
        return rows, column_names

    def _fetchone(
        self,
        query: str,
        params: Optional[list] = None,
        conn: Optional[duckdb.DuckDBPyConnection] = None,
        lock: Optional[threading.Lock] = None,
    ) -> Optional[tuple]:
        """Execute a query and return the first row with the connection lock held.

        Args:
            query: SQL query to execute.
            params: Optional parameter list for parameterized queries.
            conn: Connection to use. Defaults to the shared in-memory connection.
            lock: Lock guarding conn. Defaults to the shared connection's lock.

        Returns:
            First row as a tuple, or None if no rows.
        """
        conn = conn or self.conn
        lock = lock or self._lock
        with lock:
            return self._fetchone_unlocked(conn, query, params)

    def _fetchall(
        self,
        query: str,
        params: Optional[list] = None,
        conn: Optional[duckdb.DuckDBPyConnection] = None,
        lock: Optional[threading.Lock] = None,
    ) -> Tuple[List[tuple], List[str]]:
        """Execute a query and return (rows, column_names) with the connection lock held.

        conn.description reflects the *last* executed query on conn and must
        therefore be read while the lock is still held.

        Args:
            query: SQL query to execute.
            params: Optional parameter list for parameterized queries.
            conn: Connection to use. Defaults to the shared in-memory connection.
            lock: Lock guarding conn. Defaults to the shared connection's lock.

        Returns:
            Tuple of (rows, column_names).
        """
        conn = conn or self.conn
        lock = lock or self._lock
        with lock:
            return self._fetchall_unlocked(conn, query, params)

    @staticmethod
    def _extract_geometry_from_row(
        row_dict: Dict[str, Any], has_geometry: bool, geometry_column: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract and parse geometry from a row dictionary.

        Args:
            row_dict: Row dictionary (will be modified in-place).
            has_geometry: Whether the row should contain geometry.
            geometry_column: Name of the geometry column to remove from properties.

        Returns:
            Parsed GeoJSON geometry dict, or None if no geometry.
        """
        geometry = None
        if has_geometry and "__geojson__" in row_dict:
            import json

            geojson_str = row_dict.pop("__geojson__")
            if geojson_str:
                geometry = json.loads(geojson_str)
            # Remove original geometry column from properties
            row_dict.pop(geometry_column, None)
        return geometry

    def list_parquet_files(self) -> List[Dict[str, Any]]:
        """List all Parquet files in the data directory.

        Returns:
            List of dictionaries containing collection info:
            - id: Collection identifier (filename without extension)
            - path: Full path to the Parquet file
            - title: Human-readable title
        """
        collections = []
        if not self.data_dir.exists():
            logger.warning(f"Data directory does not exist: {self.data_dir}")
            return collections

        for parquet_file in sorted(self.data_dir.glob("*.parquet")):
            collection_id = parquet_file.stem
            collections.append(
                {
                    "id": collection_id,
                    "path": str(parquet_file),
                    "title": collection_id.replace("_", " ").title(),
                }
            )

        logger.info(f"Found {len(collections)} Parquet files in {self.data_dir}")
        return collections

    def get_parquet_path(self, collection_id: str) -> Optional[Path]:
        """Get the full path to a Parquet file by collection ID.

        Args:
            collection_id: The collection identifier (filename without extension).

        Returns:
            Path to the Parquet file, or None if not found.

        Raises:
            ValueError: If collection_id contains invalid characters.
        """
        # Validate collection_id against strict pattern to prevent path traversal
        if not collection_id or not COLLECTION_ID_PATTERN.match(collection_id):
            logger.warning(f"Invalid collection_id rejected: {collection_id!r}")
            raise ValueError(
                "Invalid collection ID. Only alphanumeric characters, "
                "underscores, and hyphens are allowed."
            )

        parquet_path = self.data_dir / f"{collection_id}.parquet"

        # Defense in depth: resolve and verify path is within data_dir
        try:
            resolved_path = parquet_path.resolve()
            if not str(resolved_path).startswith(str(self.data_dir.resolve()) + os.sep):
                logger.warning(
                    f"Path traversal attempt detected: {collection_id!r} -> {resolved_path}"
                )
                return None
        except (OSError, ValueError) as e:
            logger.warning(f"Error resolving path for {collection_id}: {e}")
            return None

        if resolved_path.exists():
            return resolved_path
        return None

    def _get_validated_parquet_path(self, collection_id: str) -> Path:
        """Get and validate Parquet path, raising exception if not found.

        Args:
            collection_id: The collection identifier.

        Returns:
            Path to the Parquet file.

        Raises:
            FileNotFoundError: If collection does not exist.
            ValueError: If collection_id is invalid.
        """
        parquet_path = self.get_parquet_path(collection_id)
        if not parquet_path:
            raise FileNotFoundError(f"Collection not found: {collection_id}")
        return parquet_path

    def _get_materialized_connection(
        self, collection_id: str
    ) -> Optional[Tuple[duckdb.DuckDBPyConnection, threading.Lock]]:
        """Return the (connection, lock) for a materialized collection, if available.

        A collection is materialized purely by having a valid
        <collection_id>.duckdb file in data_dir -- there is no allowlist.
        Returns None when the file doesn't exist, previously failed to open,
        or fails now; callers must fall back to querying the Parquet file
        directly in that case.

        Args:
            collection_id: The collection identifier.

        Returns:
            (connection, lock) tuple, or None.
        """
        if collection_id in self._materialized_conns:
            return self._materialized_conns[collection_id]

        if collection_id in self._failed_materialized:
            return None

        with self._lock:
            if collection_id in self._materialized_conns:
                return self._materialized_conns[collection_id]

            if collection_id in self._failed_materialized:
                return None

            db_path = self.data_dir / f"{collection_id}.duckdb"
            if not db_path.exists():
                return None

            try:
                conn = duckdb.connect(database=str(db_path), read_only=True)
                conn.execute("INSTALL spatial")
                conn.execute("LOAD spatial")
                conn.execute(f"SELECT 1 FROM {MATERIALIZED_TABLE_NAME} LIMIT 1")
            except duckdb.Error as e:
                logger.warning(
                    f"Failed to open materialized connection for {collection_id}: {e}"
                )
                if "conn" in locals():
                    conn.close()
                self._failed_materialized.add(collection_id)
                return None

            entry = (conn, threading.Lock())
            self._materialized_conns[collection_id] = entry
            logger.info(f"Opened materialized DuckDB connection for {collection_id}.")
            return entry

    def invalidate_materialized(self, collection_id: str) -> bool:
        """Drop any cached materialized connection/failure state for a collection.

        Called after an external rebuild (the manual CLI script or
        gis-pipeline's automatic trigger) swaps in a fresh .duckdb file, so
        the next request re-opens it instead of continuing to serve a stale
        cached connection. Safe to call even if nothing was cached yet.

        Args:
            collection_id: The collection identifier.

        Returns:
            True if a cached connection was found and closed, False otherwise.
        """
        with self._lock:
            self._failed_materialized.discard(collection_id)
            entry = self._materialized_conns.pop(collection_id, None)

        if entry is None:
            return False

        conn, conn_lock = entry
        with conn_lock:
            conn.close()
        logger.info(f"Invalidated materialized connection for {collection_id}.")
        return True

    def get_parquet_schema(self, collection_id: str) -> ParquetSchemaInfo:
        """Get schema information for a Parquet file.

        Results are cached per collection_id. Parquet files are immutable so
        the cache is valid for the lifetime of the process.

        Args:
            collection_id: The collection identifier.

        Returns:
            Dictionary containing:
            - columns: List of column info (name, type)
            - id_column: Detected ID column name
            - geometry_column: Detected geometry column name
            - has_geometry: Whether file has geometry column
            - feature_count: Total number of features
            - bbox: Bounding box [minx, miny, maxx, maxy] if spatial
        """
        # Fast path: return cached schema without acquiring the lock.
        # Dict reads are thread-safe in CPython due to the GIL, and the
        # worst case is a redundant recomputation on the very first request.
        if collection_id in self._schema_cache:
            return self._schema_cache[collection_id]

        schema = self._compute_parquet_schema(collection_id)

        # Cache under the lock so concurrent first-time callers for the same
        # collection_id don't both write (harmless, but avoids redundant work).
        with self._lock:
            self._schema_cache[collection_id] = schema

        return schema

    def _compute_parquet_schema(self, collection_id: str) -> ParquetSchemaInfo:
        """Compute schema by introspecting the Parquet file. Called by get_parquet_schema on cache miss."""
        parquet_path = self._get_validated_parquet_path(collection_id)
        path_str = str(parquet_path)

        # Get column info
        escaped_path = self._escape_sql_string(path_str)
        describe_query = f"DESCRIBE SELECT * FROM read_parquet('{escaped_path}')"
        columns_result, _ = self._fetchall(describe_query)
        columns: List[ColumnInfo] = [
            {
                "name": row[DuckDBDescribeColumn.NAME],
                "type": row[DuckDBDescribeColumn.TYPE],
            }
            for row in columns_result
        ]
        column_names = [col["name"] for col in columns]

        # Detect ID column (use first match based on priority order)
        id_column = None
        matching_id_candidates = [
            c for c in self.ID_COLUMN_CANDIDATES if c in column_names
        ]

        if matching_id_candidates:
            id_column = matching_id_candidates[0]
            if len(matching_id_candidates) > 1:
                logger.info(
                    f"Multiple ID column candidates found in {collection_id}: "
                    f"{matching_id_candidates}. Using '{id_column}' (highest priority)."
                )

        # Detect geometry column (use first match based on priority order)
        geometry_column = None
        matching_geom_candidates = [
            c for c in self.GEOMETRY_COLUMN_CANDIDATES if c in column_names
        ]

        if matching_geom_candidates:
            geometry_column = matching_geom_candidates[0]
            if len(matching_geom_candidates) > 1:
                logger.info(
                    f"Multiple geometry column candidates found in {collection_id}: "
                    f"{matching_geom_candidates}. Using '{geometry_column}' (highest priority)."
                )

        has_geometry = geometry_column is not None

        # Get feature count
        count_query = f"SELECT COUNT(*) FROM read_parquet('{escaped_path}')"
        feature_count = self._fetchone(count_query)[0]

        schema_info: ParquetSchemaInfo = {
            "columns": columns,
            "id_column": id_column,
            "geometry_column": geometry_column,
            "has_geometry": has_geometry,
            "feature_count": feature_count,
            "bbox": None,
        }

        # Compute bounding box if spatial
        if has_geometry:
            try:
                escaped_geom_col = self.escape_identifier(geometry_column)
                bbox_query = f"""
                    SELECT 
                        MIN(ST_XMin({escaped_geom_col})),
                        MIN(ST_YMin({escaped_geom_col})),
                        MAX(ST_XMax({escaped_geom_col})),
                        MAX(ST_YMax({escaped_geom_col}))
                    FROM read_parquet('{escaped_path}')
                    WHERE {escaped_geom_col} IS NOT NULL
                """
                bbox_result = self._fetchone(bbox_query)
                if bbox_result and all(v is not None for v in bbox_result):
                    schema_info["bbox"] = list(bbox_result)
            except duckdb.Error as e:
                logger.warning(f"Could not compute bbox for {collection_id}: {e}")

        return schema_info

    def query_items(
        self,
        collection_id: str,
        limit: int = 10,
        offset: int = 0,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> Dict[str, Any]:
        """Query items from a Parquet file.

        Args:
            collection_id: The collection identifier.
            limit: Maximum number of items to return.
            offset: Number of items to skip.
            bbox: Optional bounding box filter [minx, miny, maxx, maxy].

        Returns:
            Dictionary containing:
            - features: List of feature dictionaries
            - numberMatched: Total count matching filter
            - numberReturned: Number returned in this response
        """
        parquet_path = self._get_validated_parquet_path(collection_id)
        path_str = str(parquet_path)
        escaped_path = self._escape_sql_string(path_str)
        schema = self.get_parquet_schema(collection_id)
        has_geometry = schema["has_geometry"]
        geometry_column = schema["geometry_column"]
        escaped_geom_col = (
            self.escape_identifier(geometry_column) if geometry_column else None
        )
        id_column = schema["id_column"]

        materialized = self._get_materialized_connection(collection_id)
        if materialized:
            conn, lock = materialized
            from_sql = self.escape_identifier(MATERIALIZED_TABLE_NAME)
        else:
            conn, lock = None, None
            from_sql = f"read_parquet('{escaped_path}')"

        # Build WHERE clause
        where_clauses = []
        if bbox and has_geometry:
            if len(bbox) != 4:
                raise ValueError(
                    f"bbox must have exactly 4 values, got {len(bbox)}: {bbox}"
                )
            minx, miny, maxx, maxy = bbox
            where_clauses.append(
                f"ST_Intersects({escaped_geom_col}, "
                f"ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}))"
            )

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Build ORDER BY for stable pagination
        if id_column:
            order_sql = f"ORDER BY {self.escape_identifier(id_column)}"
        else:
            order_sql = ""

        count_query = f"SELECT COUNT(*) FROM {from_sql} {where_sql}"

        # Build SELECT with geometry conversion
        if has_geometry:
            select_sql = f"""
                SELECT *, ST_AsGeoJSON({escaped_geom_col}) as __geojson__
                FROM {from_sql}
                {where_sql}
                {order_sql}
                LIMIT {limit} OFFSET {offset}
            """
        else:
            select_sql = f"""
                SELECT *
                FROM {from_sql}
                {where_sql}
                {order_sql}
                LIMIT {limit} OFFSET {offset}
            """

        if materialized:
            # Hold the lock for the entire count+select sequence so a
            # concurrent invalidate_materialized() can't close conn between
            # the two calls (see invalidate_materialized's docstring for the
            # race this avoids). Only needed for materialized connections --
            # invalidate_materialized never touches self.conn, so the
            # fallback path below is safe with independent lock acquisitions,
            # same as before this fix.
            with lock:
                number_matched = self._fetchone_unlocked(conn, count_query)[0]
                result, columns = self._fetchall_unlocked(conn, select_sql)
        else:
            number_matched = self._fetchone(count_query)[0]
            result, columns = self._fetchall(select_sql)

        # Convert to GeoJSON features
        features = []
        for i, row in enumerate(result):
            row_dict = dict(zip(columns, row))

            # Extract geometry
            geometry = self._extract_geometry_from_row(
                row_dict, has_geometry, geometry_column
            )

            # Determine feature ID
            if id_column and id_column in row_dict:
                feature_id = row_dict[id_column]
            else:
                feature_id = offset + i + 1

            feature = {
                "type": "Feature",
                "id": feature_id,
                "geometry": geometry,
                "properties": row_dict,
            }
            features.append(feature)

        return {
            "features": features,
            "numberMatched": number_matched,
            "numberReturned": len(features),
        }

    def get_item_by_id(
        self, collection_id: str, item_id: Any
    ) -> Optional[Dict[str, Any]]:
        """Get a single item by ID from a Parquet file.

        Args:
            collection_id: The collection identifier.
            item_id: The item ID to retrieve.

        Returns:
            Feature dictionary, or None if not found.
        """
        if item_id is None:
            return None

        parquet_path = self._get_validated_parquet_path(collection_id)
        path_str = str(parquet_path)
        escaped_path = self._escape_sql_string(path_str)
        schema = self.get_parquet_schema(collection_id)
        has_geometry = schema["has_geometry"]
        geometry_column = schema["geometry_column"]
        escaped_geom_col = (
            self.escape_identifier(geometry_column) if geometry_column else None
        )
        id_column = schema["id_column"]

        materialized = self._get_materialized_connection(collection_id)
        if materialized:
            conn, lock = materialized
            from_sql = self.escape_identifier(MATERIALIZED_TABLE_NAME)
        else:
            conn, lock = None, None
            from_sql = f"read_parquet('{escaped_path}')"

        if not id_column:
            # Fall back to row number (1-indexed)
            try:
                row_num = int(item_id)
                if has_geometry:
                    query = f"""
                        SELECT *, ST_AsGeoJSON({escaped_geom_col}) as __geojson__
                        FROM {from_sql}
                        LIMIT 1 OFFSET {row_num - 1}
                    """
                else:
                    query = f"""
                        SELECT *
                        FROM {from_sql}
                        LIMIT 1 OFFSET {row_num - 1}
                    """
                params = None
            except ValueError:
                return None
        else:
            # Use ID column with parameterized query to prevent SQL injection
            escaped_id_col = self.escape_identifier(id_column)
            if has_geometry:
                query = f"""
                    SELECT *, ST_AsGeoJSON({escaped_geom_col}) as __geojson__
                    FROM {from_sql}
                    WHERE {escaped_id_col} = $1
                    LIMIT 1
                """
            else:
                query = f"""
                    SELECT *
                    FROM {from_sql}
                    WHERE {escaped_id_col} = $1
                    LIMIT 1
                """
            params = [item_id]

        try:
            rows, columns = self._fetchall(query, params, conn=conn, lock=lock)
        except duckdb.Error as e:
            logger.warning(f"Error querying item {item_id} from {collection_id}: {e}")
            return None

        if not rows:
            return None

        row_dict = dict(zip(columns, rows[0]))

        # Extract geometry
        geometry = self._extract_geometry_from_row(
            row_dict, has_geometry, geometry_column
        )

        return {
            "type": "Feature",
            "id": item_id,
            "geometry": geometry,
            "properties": row_dict,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_shared_manager: Optional[DuckDBManager] = None
_manager_init_lock = threading.Lock()


def get_shared_manager() -> DuckDBManager:
    """Return the module-level DuckDBManager singleton (lazy, thread-safe init).

    Notes :
        Uses double-checked locking so that after the first initialisation the
        hot path (already initialised) never acquires the lock.

    Raises:
        DuckDBSpatialExtensionError: If the spatial extension cannot be loaded.
    """
    global _shared_manager
    if _shared_manager is None:
        with _manager_init_lock:
            if _shared_manager is None:
                _shared_manager = DuckDBManager()
                logger.info("DuckDB shared manager singleton created.")
    return _shared_manager
