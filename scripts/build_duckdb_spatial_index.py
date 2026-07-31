#!/usr/bin/env python3
"""Rebuild the persistent, RTree-indexed DuckDB table for one Parquet collection.

Run this manually after the pipeline regenerates a materialized collection's
source Parquet file (see PARQUET_MATERIALIZED_COLLECTIONS in .env.example).

Builds into a fresh "<collection>.duckdb.new" file -- never touching the
"<collection>.duckdb" file vector-api already has open, since DuckDB excludes
every other connection (even read-only ones, from other processes) while a
writer holds a file open -- then atomically renames it into place.

vector-api's own connection to the old file is unaffected by the rename
until it reopens the path, so the running service must be restarted
afterwards to pick up the refreshed data and index:

    docker compose restart vector-api

Usage (mirrors scripts/build_grhq_water_union.py's invocation pattern):

    docker compose run --rm \\
      -v "$(pwd)/scripts/build_duckdb_spatial_index.py:/tmp/build_duckdb_spatial_index.py:ro" \\
      vector-api \\
      python3 /tmp/build_duckdb_spatial_index.py --collection bdppad_v03_an_2025_s_20260504
"""

import argparse
import os
import sys
from pathlib import Path

from vector_api.materialize import materialize_collection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection",
        required=True,
        help="Collection ID, i.e. the Parquet filename without its extension "
        "(e.g. bdppad_v03_an_2025_s_20260504).",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("DUCKDB_DATA_DIR", "/data/duckdb"),
        help="Directory containing the source Parquet files "
        "(default: $DUCKDB_DATA_DIR).",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    parquet_path = data_dir / f"{args.collection}.parquet"
    if not parquet_path.exists():
        print(f"ERROR: Parquet file not found: {parquet_path}", file=sys.stderr)
        sys.exit(1)

    final_path = data_dir / f"{args.collection}.duckdb"
    new_path = data_dir / f"{args.collection}.duckdb.new"
    new_wal_path = data_dir / f"{args.collection}.duckdb.new.wal"
    if new_path.exists():
        new_path.unlink()
    new_wal_path.unlink(missing_ok=True)

    print(f"Materializing {parquet_path} -> {new_path} ...", flush=True)
    try:
        row_count = materialize_collection(parquet_path, new_path)
    except Exception as e:
        print(f"ERROR: Failed to materialize {args.collection}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Materialized {row_count:,} rows and built the RTree index.", flush=True)

    new_path.rename(final_path)
    print(f"Swapped into place: {final_path}", flush=True)

    print("\nNext step (run manually):", flush=True)
    print("  docker compose restart vector-api", flush=True)


if __name__ == "__main__":
    main()
