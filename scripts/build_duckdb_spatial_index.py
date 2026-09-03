#!/usr/bin/env python3
"""Rebuild the persistent, RTree-indexed DuckDB table for one Parquet collection.

Run this manually after the pipeline regenerates a materialized collection's
source Parquet file.

Builds into a fresh "<collection>.duckdb.new" file -- never touching the
"<collection>.duckdb" file vector-api already has open, since DuckDB excludes
every other connection (even read-only ones, from other processes) while a
writer holds a file open -- then atomically renames it into place.

After the swap, this script notifies vector-api's /invalidate endpoint so it
drops its cached connection and re-opens the fresh file on the next request
-- no container restart needed. If vector-api is unreachable (e.g. not
running yet on a fresh install), the notification is skipped with a warning;
`docker compose restart vector-api` remains available as a manual fallback.

Usage (mirrors scripts/build_grhq_water_union.py's invocation pattern):

    docker compose run --rm \\
      -v "$(pwd)/scripts/build_duckdb_spatial_index.py:/tmp/build_duckdb_spatial_index.py:ro" \\
      vector-api \\
      python3 /tmp/build_duckdb_spatial_index.py --collection bdppad_v03_an_2025_s_20260504
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from vector_api.materialize import materialize_collection


def _notify_vector_api(collection_id: str, vector_api_url: str) -> None:
    """Best-effort POST to vector-api's /invalidate endpoint. Never raises."""
    url = f"{vector_api_url.rstrip('/')}/parquet/collections/{collection_id}/invalidate"
    try:
        request = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode())
        print(f"Notified vector-api: {body}", flush=True)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(
            f"WARNING: Failed to notify vector-api at {url}: {e}. "
            "Run 'docker compose restart vector-api' manually to pick up "
            "the refreshed data.",
            file=sys.stderr,
        )


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
    parser.add_argument(
        "--vector-api-url",
        default=os.environ.get("VECTOR_API_URL", "http://vector-api:8083"),
        help="Base URL of the running vector-api service, used to notify it "
        "to drop its cached connection for this collection after the swap "
        "(default: $VECTOR_API_URL or http://vector-api:8083).",
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

    _notify_vector_api(args.collection, args.vector_api_url)


if __name__ == "__main__":
    main()
