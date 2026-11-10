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
import time
from collections import OrderedDict
from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, TypeVar

import anyio
import duckdb

from .materialize import MATERIALIZED_TABLE_NAME

logger = logging.getLogger(__name__)

# Strict pattern for collection IDs to prevent path traversal
COLLECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")

DEFAULT_MEMORY_LIMIT: str = "819MB"
DEFAULT_MAX_OPEN_DUCKDB: int = 2
DEFAULT_MAX_DUCKDB_QUERIES: int = 1

MaterializedEntry = tuple[duckdb.DuckDBPyConnection, threading.Lock]
T = TypeVar("T")


class DuckDBConfigError(RuntimeError):
    """Raised when a DuckDB manager setting is invalid.

    Deliberately not a ValueError: the router maps ValueError from manager
    calls to 400 "Invalid collection ID".
    """


def _positive_int_setting(name: str, value: int | None, default: int) -> int:
    """Return value, else the env var name, else default, as a positive int.

    Raises:
        DuckDBConfigError: If the resolved value is not a positive integer.
    """
    raw = value if value is not None else os.getenv(name)
    if raw is None or raw == "":
        return default
    error = DuckDBConfigError(f"{name} must be a positive integer, got {raw!r}")
    try:
        resolved = int(raw)
    except (TypeError, ValueError):
        raise error from None
    if resolved < 1:
        raise error
    return resolved


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

    def __init__(
        self,
        data_dir: Optional[str] = None,
        memory_limit: str | None = None,
        max_open: int | None = None,
        max_queries: int | None = None,
    ) -> None:
        """Initialize the DuckDBManager with an in-memory connection.

        Args:
            data_dir: Directory containing Parquet files. Defaults to DUCKDB_DATA_DIR env var.
            memory_limit: DuckDB memory_limit applied to every connection this
                manager opens (each one is a separate DuckDB instance).
                Defaults to the DUCKDB_MEMORY_LIMIT env var, then
                DEFAULT_MEMORY_LIMIT.
            max_open: Most materialized connections kept open at once.
                Defaults to VECTOR_API_MAX_OPEN_DUCKDB, then
                DEFAULT_MAX_OPEN_DUCKDB.
            max_queries: Most queries running on materialized connections at
                once. Defaults to VECTOR_API_MAX_DUCKDB_QUERIES, then
                DEFAULT_MAX_DUCKDB_QUERIES.

        Raises:
            DuckDBConfigError: If max_open or max_queries (or their env var)
                is not a positive integer.
        """
        self.data_dir = Path(data_dir or os.getenv("DUCKDB_DATA_DIR", "/data/duckdb"))
        self.memory_limit: str = (
            memory_limit or os.getenv("DUCKDB_MEMORY_LIMIT") or DEFAULT_MEMORY_LIMIT
        )
        self.max_open: int = _positive_int_setting(
            "VECTOR_API_MAX_OPEN_DUCKDB", max_open, DEFAULT_MAX_OPEN_DUCKDB
        )
        self.max_queries: int = _positive_int_setting(
            "VECTOR_API_MAX_DUCKDB_QUERIES", max_queries, DEFAULT_MAX_DUCKDB_QUERIES
        )
        self.conn = duckdb.connect(
            database=":memory:", config={"memory_limit": self.memory_limit}
        )
        # DuckDB in-memory connections are not thread-safe; a single shared
        # connection requires serialised access.
        self._lock = threading.Lock()
        # Schema cache: collection_id -> ParquetSchemaInfo.
        # Parquet files are immutable so entries never need invalidation.
        # Filled at start-up by warm_schema_cache() and on any later miss;
        # protected by self._lock.
        self._schema_cache: Dict[str, ParquetSchemaInfo] = {}
        # Lazily-opened read-only connections to materialized, RTree-indexed
        # collections (see materialize.py), in least-recently-used order and
        # capped at max_open: each one is a separate DuckDB instance with its
        # own block cache, so an unbounded cache OOM-kills the process (#288).
        # Each entry pairs a connection with its own lock.
        self._materialized_conns: OrderedDict[str, MaterializedEntry] = OrderedDict()
        # Collection IDs whose .duckdb file exists but failed to open or
        # failed the validity probe during this process's lifetime -- avoids
        # retrying (and re-logging) on every request for a persistently
        # broken file. Cleared per-collection by invalidate_materialized()
        # after an external rebuild.
        self._failed_materialized: set[str] = set()
        # Guards _materialized_conns and _failed_materialized. Separate from
        # self._lock, which is held for whole queries on the in-memory
        # connection and would make every cache lookup wait behind them.
        self._cache_lock = threading.Lock()
        self._query_slots = threading.BoundedSemaphore(self.max_queries)
        self._warned_position_collisions: set[str] = set()
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
        with self._cache_lock:
            entries = list(self._materialized_conns.values())
            self._materialized_conns.clear()
            self._failed_materialized.clear()
        for conn, conn_lock in entries:
            with conn_lock:
                conn.close()

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

    def parquet_source(self, collection_id: str) -> str:
        """Return a ``read_parquet(...)`` SQL expression for a collection.

        Raises:
            FileNotFoundError: If the collection does not exist.
            ValueError: If collection_id contains invalid characters.
        """
        path = self._get_validated_parquet_path(collection_id)
        return f"read_parquet('{self._escape_sql_string(str(path))}')"

    def query_rows(
        self, query: str, params: Optional[list] = None
    ) -> List[Dict[str, Any]]:
        """Run a read query on the shared connection and return rows as dicts."""
        rows, columns = self._fetchall(query, params)
        return [dict(zip(columns, row)) for row in rows]

    def _get_materialized_connection(
        self, collection_id: str
    ) -> MaterializedEntry | None:
        """Return the (connection, lock) for a materialized collection, if available.

        A collection is materialized purely by having a valid
        <collection_id>.duckdb file in data_dir -- there is no allowlist.
        Returns None when the file doesn't exist, previously failed to open,
        or fails now; callers must fall back to querying the Parquet file
        directly in that case.

        Opening one more than max_open closes the least recently used ones.
        Run queries through _run_materialized(), never on the returned pair
        directly: it may be closed by an eviction at any time.

        Args:
            collection_id: The collection identifier.

        Returns:
            (connection, lock) tuple, or None.
        """
        with self._cache_lock:
            entry = self._materialized_conns.get(collection_id)
            if entry is not None:
                self._materialized_conns.move_to_end(collection_id)
                return entry

            if collection_id in self._failed_materialized:
                return None

            db_path = self.data_dir / f"{collection_id}.duckdb"
            if not db_path.exists():
                return None

            try:
                conn = duckdb.connect(
                    database=str(db_path),
                    read_only=True,
                    config={"memory_limit": self.memory_limit},
                )
                conn.execute("INSTALL spatial")
                conn.execute("LOAD spatial")
                conn.execute(f"SELECT 1 FROM {MATERIALIZED_TABLE_NAME} LIMIT 1")
            except duckdb.Error as e:
                logger.warning(
                    "Failed to open materialized connection for %s: %s",
                    collection_id,
                    e,
                )
                if "conn" in locals():
                    conn.close()
                self._failed_materialized.add(collection_id)
                return None

            entry = (conn, threading.Lock())
            self._materialized_conns[collection_id] = entry
            evicted: list[tuple[str, MaterializedEntry]] = []
            while len(self._materialized_conns) > self.max_open:
                evicted.append(self._materialized_conns.popitem(last=False))

        logger.info("Opened materialized DuckDB connection for %s.", collection_id)
        for evicted_id, (evicted_conn, evicted_lock) in evicted:
            # Closed outside _cache_lock: waiting here for the evicted
            # connection's running query would otherwise block every cache
            # lookup behind it.
            with evicted_lock:
                evicted_conn.close()
            logger.info("Evicted materialized DuckDB connection for %s.", evicted_id)
        return entry

    def _run_materialized(
        self, collection_id: str, work: Callable[[duckdb.DuckDBPyConnection], T]
    ) -> T | None:
        """Run work on a collection's materialized connection, if it has one.

        Holds a query slot, then the connection's lock, for the whole of
        work. An entry is always removed from the cache before it is closed,
        and closed only under its lock, so finding the same entry still
        cached while holding the lock means the connection is open. A
        connection evicted or invalidated between lookup and lock is reopened
        once; if it is closed again, the caller falls back to read_parquet,
        which returns the same rows, more slowly.

        Args:
            collection_id: The collection identifier.
            work: Runs the queries; must not return None.

        Returns:
            work's result, or None when the collection has no usable
            materialized connection (callers then query read_parquet).
        """
        for _ in range(2):
            entry = self._get_materialized_connection(collection_id)
            if entry is None:
                return None
            conn, conn_lock = entry
            with self._query_slots, conn_lock:
                with self._cache_lock:
                    still_cached = self._materialized_conns.get(collection_id) is entry
                if not still_cached:
                    continue
                return work(conn)
        logger.warning(
            "Materialized connection for %s was closed twice before a query "
            "could use it; falling back to read_parquet",
            collection_id,
        )
        return None

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
        with self._cache_lock:
            self._failed_materialized.discard(collection_id)
            entry = self._materialized_conns.pop(collection_id, None)

        if entry is None:
            return False

        conn, conn_lock = entry
        with conn_lock:
            conn.close()
        logger.info("Invalidated materialized connection for %s.", collection_id)
        return True

    def get_parquet_schema(self, collection_id: str) -> ParquetSchemaInfo:
        """Get schema information for a Parquet file.

        Results are cached per collection_id for the lifetime of the process,
        except a schema whose bbox scan failed: it is returned with bbox None
        and computed again on the next call.

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

        schema, bbox_failed = self._compute_parquet_schema(collection_id)
        if bbox_failed:
            return schema

        # Cache under the lock so concurrent first-time callers for the same
        # collection_id don't both write (harmless, but avoids redundant work).
        with self._lock:
            self._schema_cache[collection_id] = schema

        return schema

    def _compute_parquet_schema(
        self, collection_id: str
    ) -> tuple[ParquetSchemaInfo, bool]:
        """Compute schema by introspecting the Parquet file.

        Called by get_parquet_schema on cache miss.

        Returns:
            The schema, and whether its bbox query raised (bbox is then None).
        """
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

        bbox_failed = False
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
                bbox_failed = True
                logger.warning(
                    "Could not compute bbox for %s, will retry: %s", collection_id, e
                )

        return schema_info, bbox_failed

    def _can_page_by_position(
        self, schema: ParquetSchemaInfo, position_column: str, collection_id: str
    ) -> bool:
        """Return False when a source column would shadow the row-position column.

        Warns once per collection and position column, not on every page.
        """
        column_names = {column["name"].lower() for column in schema["columns"]}
        if position_column not in column_names:
            return True
        warning_key = f"{collection_id}:{position_column}"
        with self._lock:
            first_time = warning_key not in self._warned_position_collisions
            self._warned_position_collisions.add(warning_key)
        if first_time:
            logger.warning(
                "Collection %s has a column named %s; paging with the "
                "single-statement query, which sorts full rows",
                collection_id,
                position_column,
            )
        return False

    @staticmethod
    def _position_paged_select_sql(
        *,
        from_sql: str,
        position_column: str,
        exclude_position: bool,
        escaped_id_col: str,
        escaped_geom_col: str | None,
        where_sql: str,
        limit: int,
        offset: int,
    ) -> str:
        """Build a page query that sorts only (id, row position), then joins full rows.

        A single ``SELECT * ... ORDER BY id LIMIT n OFFSET k`` makes DuckDB keep
        the top ``k + n`` full rows, geometry included, which exhausts memory
        on deep offsets of large collections (#279). Sorting the narrow
        (id, position) pair keeps memory proportional to the key width, and
        the position tie-break gives duplicate ids a fixed order, so every page
        holds exactly ``limit`` rows and pages never overlap.
        """
        exclude_sql = f" EXCLUDE ({position_column})" if exclude_position else ""
        geojson_sql = (
            f", ST_AsGeoJSON(t.{escaped_geom_col}) AS __geojson__"
            if escaped_geom_col
            else ""
        )
        return f"""
            WITH page AS (
                SELECT {position_column} AS __pos__, {escaped_id_col} AS __id__
                FROM {from_sql}
                {where_sql}
                ORDER BY {escaped_id_col}, {position_column}
                LIMIT {limit} OFFSET {offset}
            )
            SELECT t.*{exclude_sql}{geojson_sql}
            FROM {from_sql} t
            JOIN page p ON t.{position_column} = p.__pos__
            ORDER BY p.__id__, p.__pos__
        """

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
        order_sql = f"ORDER BY {self.escape_identifier(id_column)}" if id_column else ""

        def build(materialized: bool) -> tuple[str, str]:
            from_sql = (
                self.escape_identifier(MATERIALIZED_TABLE_NAME)
                if materialized
                else f"read_parquet('{escaped_path}')"
            )
            count_query = f"SELECT COUNT(*) FROM {from_sql} {where_sql}"
            position_column = "rowid" if materialized else "file_row_number"
            page_by_position = id_column is not None and self._can_page_by_position(
                schema, position_column, collection_id
            )
            if page_by_position:
                select_sql = self._position_paged_select_sql(
                    from_sql=(
                        from_sql
                        if materialized
                        else f"read_parquet('{escaped_path}', file_row_number = true)"
                    ),
                    position_column=position_column,
                    exclude_position=not materialized,
                    escaped_id_col=self.escape_identifier(id_column),
                    escaped_geom_col=escaped_geom_col if has_geometry else None,
                    where_sql=where_sql,
                    limit=limit,
                    offset=offset,
                )
            elif has_geometry:
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
            return count_query, select_sql

        materialized_queries = (
            build(materialized=True)
            if (self.data_dir / f"{collection_id}.duckdb").exists()
            else None
        )

        def run_page(
            conn: duckdb.DuckDBPyConnection,
        ) -> tuple[int, list[tuple], list[str]]:
            assert materialized_queries is not None
            count_query, select_sql = materialized_queries
            matched = self._fetchone_unlocked(conn, count_query)[0]
            rows, row_columns = self._fetchall_unlocked(conn, select_sql)
            return matched, rows, row_columns

        page = (
            self._run_materialized(collection_id, run_page)
            if materialized_queries is not None
            else None
        )
        if page is None:
            count_query, select_sql = build(materialized=False)
            number_matched = self._fetchone(count_query)[0]
            result, columns = self._fetchall(select_sql)
        else:
            number_matched, result, columns = page

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

        if id_column:
            # Parameterized to prevent SQL injection
            where_sql = f"WHERE {self.escape_identifier(id_column)} = $1"
            offset_sql = ""
            params: list | None = [item_id]
        else:
            # Fall back to row number (1-indexed)
            try:
                row_num = int(item_id)
            except ValueError:
                return None
            where_sql = ""
            offset_sql = f"OFFSET {row_num - 1}"
            params = None
        geojson_sql = (
            f", ST_AsGeoJSON({escaped_geom_col}) as __geojson__" if has_geometry else ""
        )

        def build(materialized: bool) -> str:
            from_sql = (
                self.escape_identifier(MATERIALIZED_TABLE_NAME)
                if materialized
                else f"read_parquet('{escaped_path}')"
            )
            return f"""
                SELECT *{geojson_sql}
                FROM {from_sql}
                {where_sql}
                LIMIT 1 {offset_sql}
            """

        materialized_query = build(materialized=True)
        try:
            found = self._run_materialized(
                collection_id,
                lambda conn: self._fetchall_unlocked(conn, materialized_query, params),
            )
            rows, columns = (
                found
                if found is not None
                else self._fetchall(build(materialized=False), params)
            )
        except duckdb.Error as e:
            logger.warning(
                "Error querying item %s from %s: %s", item_id, collection_id, e
            )
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


# ---------------------------------------------------------------------------
# Request gate
# ---------------------------------------------------------------------------

_REQUEST_GATE = anyio.CapacityLimiter(1)


async def run_duckdb_request(func: Callable[..., T], *args: Any) -> T:
    """Run a request's DuckDB work and response building in a worker thread.

    Every request-time DuckDB call goes through here, so it never blocks the
    event loop (#280). The gate admits one request at a time across the
    in-memory and the materialized connections, keeping the one-heavy-query
    memory envelope measured for #279 and #288. A request waiting for the gate
    holds no worker thread.

    Args:
        func: Synchronous callable doing the DuckDB work.
        *args: Positional arguments passed to func.

    Returns:
        func's result. Exceptions raised by func propagate unchanged.
    """
    return await anyio.to_thread.run_sync(func, *args, limiter=_REQUEST_GATE)


async def warm_schema_cache() -> None:
    """Compute every Parquet collection's schema once, right after start-up.

    Each collection takes the request gate on its own, so a request arriving
    meanwhile waits for one schema scan, not for the whole warm-up (#281).
    Failures are logged and never raised: a broken collection is skipped, and
    a manager that cannot start leaves the /parquet routes answering 503.
    """
    started = time.monotonic()
    try:
        manager = await run_duckdb_request(get_shared_manager)
        parquet_files = await run_duckdb_request(manager.list_parquet_files)
    except Exception as e:
        logger.warning("Parquet schema warm-up skipped: %s", e)
        return

    failed = 0
    for parquet_file in parquet_files:
        collection_id = parquet_file["id"]
        try:
            await run_duckdb_request(manager.get_parquet_schema, collection_id)
        except Exception as e:
            failed += 1
            logger.warning("Parquet schema warm-up failed for %s: %s", collection_id, e)

    logger.info(
        "Parquet schema warm-up: %d of %d collections scanned in %.1f s",
        len(parquet_files) - failed,
        len(parquet_files),
        time.monotonic() - started,
    )
