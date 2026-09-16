"""Build a persistent, RTree-indexed DuckDB table from a GeoParquet file.

Adapted from vector-api/src/materialize.py -- see that module's docstring
for why the CAST below is required. This gis-pipeline copy is invoked
automatically after gis-pipeline writes a collection's GeoParquet file (see
materialize_trigger.py), and manually by scripts/build_duckdb_spatial_index.py
on the vector-api side. Duplicated rather than imported because gis-pipeline
and vector-api are separately-built Docker images with no shared-package
mechanism between them -- the same pattern already used for this module's
sibling, duckdb_utils.py, whose vector-api counterpart already notes it was
"Adapted from" this codebase.
"""

from pathlib import Path

import duckdb
import structlog

logger = structlog.get_logger()

MATERIALIZED_TABLE_NAME = "items"


def materialize_collection(
    parquet_path: Path, db_path: Path, geometry_column: str = "geometry"
) -> int:
    """Materialize a GeoParquet file into an RTree-indexed on-disk DuckDB table.

    Connects to db_path with read/write access and (re)builds
    MATERIALIZED_TABLE_NAME from scratch, so it is safe to call repeatedly on
    the same path. Callers refreshing an already-served file must build into
    a fresh path and swap it into place afterwards: DuckDB excludes every
    other connection, even read-only ones from other processes, while this
    write connection is open.

    Args:
        parquet_path: Source GeoParquet file to materialize.
        db_path: Destination .duckdb file (created if missing).
        geometry_column: Name of the geometry column to index.

    Returns:
        Number of rows materialized.
    """
    escaped_parquet = str(parquet_path).replace("'", "''")
    escaped_geom_name = geometry_column.replace('"', '""')
    escaped_geom = f'"{escaped_geom_name}"'

    conn = duckdb.connect(database=str(db_path))
    try:
        conn.execute("INSTALL spatial")
        conn.execute("LOAD spatial")
        conn.execute(f"DROP TABLE IF EXISTS {MATERIALIZED_TABLE_NAME}")
        conn.execute(
            f"""
            CREATE TABLE {MATERIALIZED_TABLE_NAME} AS
            SELECT * EXCLUDE ({escaped_geom}),
                   CAST({escaped_geom} AS GEOMETRY) AS {escaped_geom}
            FROM read_parquet('{escaped_parquet}')
            """
        )
        conn.execute(
            f"CREATE INDEX idx_{MATERIALIZED_TABLE_NAME}_geom "
            f"ON {MATERIALIZED_TABLE_NAME} USING RTREE({escaped_geom})"
        )
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM {MATERIALIZED_TABLE_NAME}"
        ).fetchone()[0]
        logger.info(
            "materialized_collection",
            parquet_path=str(parquet_path),
            db_path=str(db_path),
            table=MATERIALIZED_TABLE_NAME,
            geometry_column=geometry_column,
            row_count=row_count,
        )
        return row_count
    finally:
        conn.close()
