"""List large GeoParquet collections served without a usable .duckdb index (#282).

Run with ``python -m vector_api.check_materialized`` (``make check-materialized``).
Exit codes: 0 nothing listed, 1 collections listed, 2 invalid setting or data dir.
"""

import sys

import duckdb

from .duckdb_manager import (
    BYTES_PER_MB,
    COLLECTION_ID_PATTERN,
    DuckDBConfigError,
    DuckDBManager,
    open_materialized,
)


def _one_line(error: Exception) -> str:
    return " ".join(str(error).split())


def _has_geometry(manager: DuckDBManager, collection_id: str) -> bool:
    rows = manager.query_rows(
        f"DESCRIBE SELECT * FROM {manager.parquet_source(collection_id)}"
    )
    return any(
        row["column_name"] in DuckDBManager.GEOMETRY_COLUMN_CANDIDATES for row in rows
    )


def _index_problem(manager: DuckDBManager, collection_id: str) -> str | None:
    db_path = manager.data_dir / f"{collection_id}.duckdb"
    if not db_path.exists():
        return "missing"
    try:
        open_materialized(db_path, manager.memory_limit).close()
    except duckdb.Error as e:
        return f"unreadable: {_one_line(e)}"
    return None


def check(manager: DuckDBManager) -> int:
    """Print every large geometry collection without a usable .duckdb.

    A Parquet file that cannot be stat()-ed or described is listed as
    unchecked, so one bad file never hides the rest.

    Returns:
        1 if any collection is listed or unchecked, 0 otherwise.
    """
    threshold_bytes = manager.raw_parquet_warn_mb * BYTES_PER_MB
    collections = [
        path
        for path in sorted(manager.data_dir.glob("*.parquet"))
        if COLLECTION_ID_PATTERN.match(path.stem)
    ]
    listed = unchecked = 0
    for path in collections:
        try:
            size_bytes = path.stat().st_size
            if size_bytes <= threshold_bytes or not _has_geometry(manager, path.stem):
                continue
        except (duckdb.Error, OSError, ValueError) as e:
            unchecked += 1
            print(f"{path.stem}  unchecked: {_one_line(e)}")
            continue
        problem = _index_problem(manager, path.stem)
        if problem is None:
            continue
        listed += 1
        print(f"{path.stem}  {size_bytes / BYTES_PER_MB:.1f} MB  {problem}")
    summary = (
        f"{listed} of {len(collections)} collections are geometry collections "
        f"above {manager.raw_parquet_warn_mb} MB without a usable .duckdb"
    )
    if unchecked:
        summary += f", {unchecked} could not be checked"
    print(summary)
    return 1 if listed or unchecked else 0


def main() -> int:
    try:
        manager = DuckDBManager()
    except DuckDBConfigError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        if not manager.data_dir.is_dir():
            print(f"Data directory not found: {manager.data_dir}", file=sys.stderr)
            return 2
        return check(manager)
    finally:
        manager.close()


if __name__ == "__main__":
    sys.exit(main())
