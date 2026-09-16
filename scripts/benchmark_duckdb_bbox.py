#!/usr/bin/env python3
"""Benchmark a bbox spatial filter: raw read_parquet() vs. the materialized,
RTree-indexed DuckDB table.

Validates the win described in GitHub issue #104: numberMatched must be
identical between the two paths (indexing must not change results, only
speed), and reports mean/median/stdev over n warm-cache trials for each.

Example:
    docker compose run --rm \\
        -v "$(pwd)/scripts/benchmark_duckdb_bbox.py:/tmp/benchmark_duckdb_bbox.py:ro" \\
        vector-api \\
        python3 /tmp/benchmark_duckdb_bbox.py \\
        --collection bdppad_v03_an_2025_s_20260504 \\
        --bbox -74.0 45.0 -72.5 45.7 \\
        --trials 10
"""

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

import duckdb


def _load_spatial(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("INSTALL spatial")
    conn.execute("LOAD spatial")


def _bbox_count_query(table_or_scan: str, bbox: tuple) -> str:
    minx, miny, maxx, maxy = bbox
    return (
        f"SELECT COUNT(*) FROM {table_or_scan} "
        f"WHERE ST_Intersects(geometry, "
        f"ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}))"
    )


def _time_trials(conn: duckdb.DuckDBPyConnection, query: str, trials: int):
    counts = []
    durations_ms = []
    for _ in range(trials):
        start = time.perf_counter()
        counts.append(conn.execute(query).fetchone()[0])
        durations_ms.append((time.perf_counter() - start) * 1000)
    return counts, durations_ms


def _report(label: str, counts: list, durations_ms: list) -> int:
    assert len(set(counts)) == 1, f"{label}: numberMatched varied: {counts}"
    print(f"{label}: numberMatched={counts[0]}")
    print(
        f"{label}: mean={statistics.mean(durations_ms):.1f}ms "
        f"median={statistics.median(durations_ms):.1f}ms "
        f"stdev={statistics.stdev(durations_ms):.1f}ms"
    )
    return counts[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument(
        "--data-dir", default=os.environ.get("DUCKDB_DATA_DIR", "/data/duckdb")
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        required=True,
        metavar=("MINX", "MINY", "MAXX", "MAXY"),
    )
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    parquet_path = data_dir / f"{args.collection}.parquet"
    duckdb_path = data_dir / f"{args.collection}.duckdb"

    if not parquet_path.exists():
        print(f"ERROR: Parquet file not found: {parquet_path}", file=sys.stderr)
        sys.exit(1)

    raw_conn = duckdb.connect(database=":memory:")
    _load_spatial(raw_conn)
    escaped_path = str(parquet_path).replace("'", "''")
    raw_query = _bbox_count_query(f"read_parquet('{escaped_path}')", tuple(args.bbox))
    raw_conn.execute(raw_query).fetchone()  # discarded warm-up, not timed
    raw_counts, raw_durations = _time_trials(raw_conn, raw_query, args.trials)
    raw_conn.close()
    raw_matched = _report("read_parquet (no index)", raw_counts, raw_durations)

    if not duckdb_path.exists():
        print(
            f"\n{duckdb_path} does not exist yet -- run "
            f"scripts/build_duckdb_spatial_index.py --collection "
            f"{args.collection} first.",
            file=sys.stderr,
        )
        sys.exit(1)

    idx_conn = duckdb.connect(database=str(duckdb_path), read_only=True)
    _load_spatial(idx_conn)
    idx_query = _bbox_count_query("items", tuple(args.bbox))
    idx_conn.execute(idx_query).fetchone()  # discarded warm-up, not timed
    idx_counts, idx_durations = _time_trials(idx_conn, idx_query, args.trials)
    idx_conn.close()
    idx_matched = _report("materialized (RTree index)", idx_counts, idx_durations)

    print()
    if raw_matched != idx_matched:
        print(
            f"MISMATCH: read_parquet numberMatched={raw_matched} != "
            f"materialized numberMatched={idx_matched}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"numberMatched consistent across both paths: {raw_matched}")
    speedup = statistics.mean(raw_durations) / statistics.mean(idx_durations)
    print(f"speedup: {speedup:.2f}x")


if __name__ == "__main__":
    main()
